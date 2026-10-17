"""Tests for local_files.py, the local-file access policy (#796)."""

import dataclasses
import logging
import os

import pytest

from mcp_gee_sweet import auth, cache, local_files
from mcp_gee_sweet.local_files import LocalFileAccess, LocalFileAccessError

from .fakes import use_local_file_policy


@pytest.fixture(autouse=True)
def _isolated_deny_list(monkeypatch, tmp_path):
    """Point the server's own files somewhere this test controls, so the deny-list
    never depends on the developer's real token or cache paths."""
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    monkeypatch.setattr(auth, "TOKEN_PATH", str(secrets / "token.json"))
    monkeypatch.setattr(auth, "CREDENTIALS_PATH", str(secrets / "credentials.json"))
    monkeypatch.setattr(auth, "SERVICE_ACCOUNT_PATH", str(secrets / "service_account.json"))
    monkeypatch.setattr(cache, "CACHE_DB_PATH", str(secrets / "cache.db"))
    monkeypatch.setattr(local_files, "_tripwire_warned", False)
    return secrets


class TestModeResolution:
    @pytest.mark.parametrize(
        ("argv", "expected"),
        [
            (["mcp-gee-sweet"], LocalFileAccess.FULL),
            (["mcp-gee-sweet", "--transport", "stdio"], LocalFileAccess.FULL),
            (["mcp-gee-sweet", "--transport", "sse"], LocalFileAccess.OFF),
            (["mcp-gee-sweet", "--transport", "streamable-http"], LocalFileAccess.OFF),
            (["mcp-gee-sweet", "--transport", "sse", "--reload"], LocalFileAccess.OFF),
        ],
    )
    def test_default_follows_transport(self, argv, expected):
        policy = local_files.resolve_policy({}, argv)
        assert policy.mode is expected
        assert policy.explicit is False

    @pytest.mark.parametrize("transport", ["stdio", "sse", "streamable-http"])
    @pytest.mark.parametrize("value", ["full", "OFF", " Full "])
    def test_explicit_setting_wins_for_every_transport(self, transport, value):
        policy = local_files.resolve_policy(
            {"LOCAL_FILE_ACCESS": value}, ["mcp-gee-sweet", "--transport", transport]
        )
        assert policy.mode is LocalFileAccess(value.strip().lower())
        assert policy.explicit is True

    def test_explicit_roots(self, tmp_path):
        policy = local_files.resolve_policy(
            {"LOCAL_FILE_ACCESS": "roots", "LOCAL_FILE_ROOTS": str(tmp_path)}, ["x"]
        )
        assert policy.mode is LocalFileAccess.ROOTS
        assert policy.roots == ((str(tmp_path), os.path.realpath(tmp_path)),)

    def test_cli_transport_matches_main_parse(self):
        assert local_files.cli_transport(["x"]) == "stdio"
        assert local_files.cli_transport(["x", "--transport", "sse"]) == "sse"
        # A dangling flag keeps the default, as main()'s loop always did.
        assert local_files.cli_transport(["x", "--transport"]) == "stdio"


class TestConfigValidation:
    """An invalid setting never raises at import (QA round 1, finding 4): it resolves
    to `off` with the reason in `error`, and only serving exits on it."""

    def _invalid(self, monkeypatch, env, match):
        policy = local_files.resolve_policy(env, ["x"])
        assert policy.mode is LocalFileAccess.OFF
        assert policy.roots == ()
        assert match in policy.error
        monkeypatch.setattr(local_files, "POLICY", policy)
        assert local_files.registers_local_only_tools() is False
        with pytest.raises(SystemExit) as exc:
            local_files.exit_if_invalid()
        assert str(exc.value) == f"mcp-gee-sweet: {policy.error}"
        return policy

    def test_unknown_mode(self, monkeypatch, tmp_path):
        self._invalid(
            monkeypatch,
            {"LOCAL_FILE_ACCESS": "everything"},
            "LOCAL_FILE_ACCESS='everything' isn't valid (use full, roots, or off)",
        )
        with pytest.raises(LocalFileAccessError) as exc:
            local_files.check_read(tmp_path / "a.txt")
        assert str(exc.value) == (
            "local file access is disabled on this server: LOCAL_FILE_ACCESS='everything' "
            "isn't valid (use full, roots, or off)"
        )

    @pytest.mark.parametrize("roots", [None, "", os.pathsep])
    def test_roots_mode_without_roots(self, monkeypatch, roots):
        env = {"LOCAL_FILE_ACCESS": "roots"}
        if roots is not None:
            env["LOCAL_FILE_ROOTS"] = roots
        self._invalid(monkeypatch, env, "needs LOCAL_FILE_ROOTS")

    def test_missing_root(self, monkeypatch, tmp_path):
        missing = tmp_path / "nope"
        self._invalid(
            monkeypatch,
            {"LOCAL_FILE_ACCESS": "roots", "LOCAL_FILE_ROOTS": str(missing)},
            f"LOCAL_FILE_ROOTS entry {str(missing)!r} isn't an existing directory",
        )

    def test_file_root(self, monkeypatch, tmp_path):
        f = tmp_path / "f.txt"
        f.write_text("x")
        self._invalid(
            monkeypatch,
            {"LOCAL_FILE_ACCESS": "roots", "LOCAL_FILE_ROOTS": str(f)},
            "isn't an existing directory",
        )

    def test_valid_policy_doesnt_exit(self, monkeypatch):
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="full")
        assert local_files.POLICY.error is None
        local_files.exit_if_invalid()

    def test_roots_split_on_pathsep(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir()
        b.mkdir()
        policy = local_files.resolve_policy(
            {"LOCAL_FILE_ACCESS": "roots", "LOCAL_FILE_ROOTS": f" {a} {os.pathsep}{b}"}, ["x"]
        )
        assert [spelling for spelling, _ in policy.roots] == [str(a), str(b)]

    def test_roots_set_outside_roots_mode_warns_only(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger="mcp_gee_sweet.local_files"):
            policy = local_files.resolve_policy(
                {"LOCAL_FILE_ACCESS": "full", "LOCAL_FILE_ROOTS": str(tmp_path)}, ["x"]
            )
        assert policy.mode is LocalFileAccess.FULL
        assert policy.roots == ()
        assert policy.error is None
        assert "LOCAL_FILE_ROOTS is set but ignored" in caplog.text


class TestMalformedPath:
    """QA round 1, finding 1: a NUL byte made os.path.realpath raise a plain
    ValueError, which per-item sites didn't catch."""

    def test_nul_byte_is_a_policy_refusal(self, monkeypatch):
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="full")
        with pytest.raises(LocalFileAccessError, match="isn't a usable local path"):
            local_files.check_read("/tmp/a\x00b.txt")


class TestManyChecks:
    """QA round 1, finding 6: a walk stats the deny-list once, not per entry."""

    def test_deny_list_statted_once_for_the_block(self, monkeypatch, tmp_path):
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="full")
        entries = set(local_files.POLICY.deny_list)
        stat_calls = []
        real_stat = os.stat

        def counting_stat(path, *args, **kwargs):
            if os.fspath(path) in entries:
                stat_calls.append(path)
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(local_files.os, "stat", counting_stat)
        with local_files.many_checks():
            for i in range(50):
                local_files.check_read(tmp_path / f"f{i}.txt")
        assert len(stat_calls) == len(entries)

    def test_parent_cache_never_hides_a_symlink(self, monkeypatch, tmp_path):
        root = tmp_path / "root"
        (root / "sub").mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("x")
        (root / "link.txt").symlink_to(outside / "secret.txt")
        (root / "escape").symlink_to(outside, target_is_directory=True)
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="roots", LOCAL_FILE_ROOTS=str(root))
        with local_files.many_checks():
            assert local_files.check_read(root / "a.txt") == root.resolve() / "a.txt"
            for refused in (root / "link.txt", root / "escape" / "secret.txt"):
                with pytest.raises(LocalFileAccessError, match="outside"):
                    local_files.check_read(refused)
            with pytest.raises(LocalFileAccessError, match="isn't a usable local path"):
                local_files.check_read(root / "a\x00b")
            assert local_files.check_read(root / "sub" / ".." / "a.txt") == (
                root.resolve() / "a.txt"
            )

    def test_symlink_dotdot_resolves_as_the_kernel_does(self, monkeypatch, tmp_path):
        # PR #1039 QA round 2: `link/..` is the parent of link's target, not the
        # directory holding link. abspath's lexical collapse let a deny-listed file
        # through inside many_checks().
        denied = tmp_path / "denied"
        (denied / "sub").mkdir(parents=True)
        log = denied / "log.txt"
        log.write_text("log")
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        (scratch / "link").symlink_to(denied / "sub", target_is_directory=True)
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="full", LOG_FILE=str(log))
        with local_files.many_checks():
            with pytest.raises(LocalFileAccessError, match="own credential"):
                local_files.check_write(f"{scratch}/link/../log.txt")
            # The not-yet-existing case resolves the same way.
            assert local_files.check_write(f"{scratch}/link/../new.txt") == (
                denied.resolve() / "new.txt"
            )

    @pytest.mark.parametrize(
        "spelling",
        [
            "{s}/link/../x.txt",
            "{s}/link/./x.txt",
            "{s}//link/x.txt",
            "{s}/link/../../scratch/x.txt",
            "{s}/real/../link/x.txt",
            "{s}/x.txt",
            "{s}/link/",
            "{s}/link/..",
        ],
    )
    def test_cached_realpath_matches_os_realpath(self, monkeypatch, tmp_path, spelling):
        scratch = tmp_path / "scratch"
        (scratch / "real").mkdir(parents=True)
        target = tmp_path / "elsewhere" / "deep"
        target.mkdir(parents=True)
        (scratch / "link").symlink_to(target, target_is_directory=True)
        path = spelling.format(s=scratch)
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="full")
        with local_files.many_checks():
            # Twice: the second call is served from the parent cache.
            for _ in range(2):
                assert local_files._realpath(path) == os.path.realpath(path)

    def test_snapshot_still_refuses_a_deny_listed_path(self, monkeypatch, _isolated_deny_list):
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="full")
        with local_files.many_checks():
            # Created after the snapshot: still matched by its path.
            (_isolated_deny_list / "token.json").write_text("{}")
            with pytest.raises(LocalFileAccessError, match="own credential"):
                local_files.check_read(_isolated_deny_list / "token.json")


class TestOffMode:
    def test_explicit_off_refuses_and_names_the_setting(self, monkeypatch, tmp_path):
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="off")
        with pytest.raises(LocalFileAccessError) as exc:
            local_files.check_read(tmp_path / "a.txt")
        assert str(exc.value) == (
            "local file access is disabled on this server (LOCAL_FILE_ACCESS=off)"
        )

    def test_defaulted_off_says_why(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            local_files, "POLICY", local_files.resolve_policy({}, ["x", "--transport", "sse"])
        )
        with pytest.raises(LocalFileAccessError) as exc:
            local_files.check_write(tmp_path / "a.txt")
        assert str(exc.value) == (
            "local file access is disabled on this server: LOCAL_FILE_ACCESS is unset, "
            "which means off for the sse transport"
        )

    def test_local_only_tools_dont_register(self, monkeypatch):
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="off")
        assert local_files.registers_local_only_tools() is False
        assert local_files.local_paths_usable() is False


class TestRootsMode:
    @pytest.fixture
    def root(self, monkeypatch, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="roots", LOCAL_FILE_ROOTS=str(root))
        return root

    def test_inside_root_allowed_and_resolved(self, root):
        (root / "a.txt").write_text("x")
        assert local_files.check_read(root / "a.txt") == root.resolve() / "a.txt"
        # A new file to be written needs no existing target.
        assert local_files.check_write(root / "new" / "b.txt") == root.resolve() / "new" / "b.txt"
        assert local_files.check_read(root) == root.resolve()

    def test_outside_root_refused_with_allowed_list(self, root, tmp_path):
        with pytest.raises(LocalFileAccessError) as exc:
            local_files.check_read(tmp_path / "other.txt")
        assert str(exc.value) == (
            f"{tmp_path / 'other.txt'} is outside this server's LOCAL_FILE_ROOTS. "
            f"Allowed directories: {root}"
        )

    def test_refusal_is_the_same_whether_or_not_the_path_exists(self, root, tmp_path):
        existing = tmp_path / "exists.txt"
        existing.write_text("secret")
        messages = []
        for path in (existing, tmp_path / "missing.txt"):
            with pytest.raises(LocalFileAccessError) as exc:
                local_files.check_read(path)
            messages.append(str(exc.value).replace(path.name, "<name>"))
        assert messages[0] == messages[1]

    def test_dotdot_traversal_refused(self, root, tmp_path):
        (tmp_path / "outside.txt").write_text("x")
        with pytest.raises(LocalFileAccessError, match="outside this server's LOCAL_FILE_ROOTS"):
            local_files.check_read(f"{root}/../outside.txt")

    def test_sibling_with_root_as_prefix_refused(self, root, tmp_path):
        # "/x/root-other" starts with "/x/root" as a string but isn't inside it.
        sibling = tmp_path / "root-other"
        sibling.mkdir()
        with pytest.raises(LocalFileAccessError):
            local_files.check_read(sibling / "a.txt")

    def test_symlink_inside_root_pointing_outside_refused(self, root, tmp_path):
        target = tmp_path / "outside.txt"
        target.write_text("secret")
        (root / "link.txt").symlink_to(target)
        with pytest.raises(LocalFileAccessError, match="outside this server's LOCAL_FILE_ROOTS"):
            local_files.check_read(root / "link.txt")

    def test_symlinked_dir_inside_root_pointing_outside_refused(self, root, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (root / "escape").symlink_to(outside, target_is_directory=True)
        with pytest.raises(LocalFileAccessError):
            local_files.check_write(root / "escape" / "new.txt")

    def test_symlink_outside_pointing_inside_allowed(self, root, tmp_path):
        (root / "a.txt").write_text("x")
        (tmp_path / "link.txt").symlink_to(root / "a.txt")
        assert local_files.check_read(tmp_path / "link.txt") == root.resolve() / "a.txt"

    def test_relative_path_resolves_against_cwd(self, root, monkeypatch):
        monkeypatch.chdir(root)
        assert local_files.check_read("a.txt") == root.resolve() / "a.txt"


class TestDenyList:
    """The server's own files are refused in every mode, full included."""

    @pytest.fixture(autouse=True)
    def _full(self, monkeypatch):
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="full")

    def _refused(self, path):
        with pytest.raises(LocalFileAccessError, match="one of this server's own"):
            local_files.check_read(path)

    @pytest.mark.parametrize("attr", ["TOKEN_PATH", "CREDENTIALS_PATH", "SERVICE_ACCOUNT_PATH"])
    def test_credential_files(self, attr):
        path = getattr(auth, attr)
        open(path, "w").close()
        self._refused(path)

    def test_missing_token_refused_as_a_write_target(self, _isolated_deny_list):
        # A download must not plant a token the server would then load.
        token = _isolated_deny_list / "token.json"
        assert not token.exists()
        with pytest.raises(LocalFileAccessError, match="can't be written by a tool"):
            local_files.check_write(token)

    def test_hardlink_to_token_refused(self, _isolated_deny_list, tmp_path):
        token = _isolated_deny_list / "token.json"
        token.write_text("{}")
        link = tmp_path / "innocent.json"
        os.link(token, link)
        self._refused(link)

    def test_symlink_to_token_refused(self, _isolated_deny_list, tmp_path):
        token = _isolated_deny_list / "token.json"
        token.write_text("{}")
        (tmp_path / "link.json").symlink_to(token)
        self._refused(tmp_path / "link.json")

    def test_case_variant_refused_on_case_insensitive_fs(self, _isolated_deny_list):
        token = _isolated_deny_list / "token.json"
        token.write_text("{}")
        variant = _isolated_deny_list / "TOKEN.json"
        if not variant.exists():
            pytest.skip("filesystem is case-sensitive")
        self._refused(variant)

    def test_case_variant_of_missing_token_refused(self, _isolated_deny_list):
        with pytest.raises(LocalFileAccessError):
            local_files.check_write(_isolated_deny_list / "Token.JSON")

    def test_existing_distinct_case_variant_allowed_on_case_sensitive_fs(self, _isolated_deny_list):
        # QA round 1, finding 5: a distinct Token.json beside token.json isn't the token.
        (_isolated_deny_list / "token.json").write_text("{}")
        other = _isolated_deny_list / "Token.json"
        if other.exists():
            pytest.skip("filesystem is case-insensitive: Token.json is the token")
        other.write_text("mine")
        assert local_files.check_read(other) == other.resolve()

    def test_existing_target_isnt_casefold_matched(self, monkeypatch, tmp_path):
        # The same rule emulated on any filesystem: the entry doesn't exist (a
        # case-sensitive filesystem's distinct name), the target does.
        target = tmp_path / "Token.json"
        target.write_text("mine")
        entry = os.path.join(os.path.realpath(tmp_path), "token.json")
        policy = dataclasses.replace(local_files.POLICY, deny_list=(entry,))
        monkeypatch.setattr(local_files, "POLICY", policy)
        real_stat = os.stat

        def stat(path, *args, **kwargs):
            if os.fspath(path) == entry:
                raise FileNotFoundError(path)
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(local_files.os, "stat", stat)
        assert local_files.check_read(target) == target.resolve()
        # A target that doesn't exist yet is still matched case-insensitively.
        target.unlink()
        with pytest.raises(LocalFileAccessError):
            local_files.check_write(tmp_path / "TOKEN.json")

    def test_dotenv(self):
        self._refused(os.path.join(os.path.dirname(local_files.__file__), ".env"))

    @pytest.mark.parametrize("suffix", ["", "-wal", "-shm"])
    def test_cache_db_and_sidecars(self, _isolated_deny_list, suffix):
        self._refused(str(_isolated_deny_list / "cache.db") + suffix)

    def test_google_application_credentials(self, monkeypatch, tmp_path):
        key = tmp_path / "adc-key.json"
        use_local_file_policy(
            monkeypatch, LOCAL_FILE_ACCESS="full", GOOGLE_APPLICATION_CREDENTIALS=str(key)
        )
        self._refused(key)

    def test_cloudsdk_config_overrides_adc_default(self, monkeypatch, tmp_path):
        gcloud = tmp_path / "gcloud"
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="full", CLOUDSDK_CONFIG=str(gcloud))
        self._refused(gcloud / "application_default_credentials.json")

    def test_default_adc_path(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="full")
        self._refused(tmp_path / ".config" / "gcloud" / "application_default_credentials.json")

    @pytest.mark.parametrize("name", ["LOG_FILE", "ACCESS_LOG_FILE"])
    def test_log_files_when_set(self, monkeypatch, tmp_path, name):
        log = tmp_path / "server.log"
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="full", **{name: str(log)})
        self._refused(log)

    def test_unset_log_file_adds_no_entry(self):
        with_log = local_files.resolve_policy({"LOG_FILE": "/var/log/x.log"}, ["x"])
        without = local_files.resolve_policy({}, ["x"])
        assert len(with_log.deny_list) == len(without.deny_list) + 1

    def test_ordinary_file_allowed(self, tmp_path):
        (tmp_path / "notes.txt").write_text("x")
        assert local_files.check_read(tmp_path / "notes.txt") == (tmp_path / "notes.txt").resolve()

    def test_deny_list_applies_in_roots_mode_inside_a_root(self, monkeypatch, _isolated_deny_list):
        use_local_file_policy(
            monkeypatch, LOCAL_FILE_ACCESS="roots", LOCAL_FILE_ROOTS=str(_isolated_deny_list)
        )
        self._refused(_isolated_deny_list / "token.json")


class TestHttpTripwire:
    def _over_http(self, monkeypatch):
        token = local_files.request_over_http.set(True)
        monkeypatch.setattr(local_files, "_tripwire_warned", False)
        return token

    def test_defaulted_full_over_http_refuses(self, monkeypatch, tmp_path, caplog):
        monkeypatch.setattr(local_files, "POLICY", local_files.resolve_policy({}, ["uvicorn"]))
        token = self._over_http(monkeypatch)
        try:
            with caplog.at_level(logging.WARNING, logger="mcp_gee_sweet.local_files"):
                for _ in range(2):
                    with pytest.raises(LocalFileAccessError) as exc:
                        local_files.check_read(tmp_path / "a.txt")
            assert local_files.local_paths_usable() is False
        finally:
            local_files.request_over_http.reset(token)
        assert str(exc.value) == (
            "local file access is disabled for HTTP requests unless LOCAL_FILE_ACCESS "
            "is set explicitly"
        )
        # Logged once, not per refusal.
        assert caplog.text.count("Refusing local file access for an HTTP request") == 1

    def test_explicit_full_over_http_allowed(self, monkeypatch, tmp_path):
        use_local_file_policy(monkeypatch, LOCAL_FILE_ACCESS="full")
        token = self._over_http(monkeypatch)
        try:
            assert local_files.check_read(tmp_path / "a.txt") == (tmp_path / "a.txt").resolve()
        finally:
            local_files.request_over_http.reset(token)

    def test_defaulted_full_over_stdio_allowed(self, monkeypatch, tmp_path):
        monkeypatch.setattr(local_files, "POLICY", local_files.resolve_policy({}, ["x"]))
        assert local_files.check_read(tmp_path / "a.txt") == (tmp_path / "a.txt").resolve()
