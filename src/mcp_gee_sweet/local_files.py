"""The local-file access policy (#796): one check for every local read and write a
tool makes on the server's own filesystem.

`LOCAL_FILE_ACCESS=full|roots|off` picks the mode, defaulting to `full` under stdio
and `off` under any network transport, since a network-facing server's caller isn't
necessarily its operator. `roots` limits paths to the directories in
`LOCAL_FILE_ROOTS`. The server's own credential, config, cache and log files are
refused in every mode. Design: docs/design/local-file-access-policy.md.
"""

import contextlib
import contextvars
import enum
import logging
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from . import auth, cache

logger = logging.getLogger(__name__)


class LocalFileAccess(enum.StrEnum):
    FULL = "full"
    ROOTS = "roots"
    OFF = "off"


class LocalFileAccessError(ValueError):
    """A path this server's policy refuses. A ValueError, so `_timed` passes its text
    to the client unchanged; sites reporting `{"error": ...}` use `str(e)`."""


def cli_transport(argv: list[str]) -> str:
    """The `--transport` value in `argv`, or "stdio". Shared by `server.main()` and the
    policy, so the two can't disagree. uvicorn's `--reload` worker is a spawn child,
    which inherits the parent's argv, so it resolves the same way."""
    transport = "stdio"
    for i, arg in enumerate(argv):
        if arg == "--transport" and i + 1 < len(argv):
            transport = argv[i + 1]
    return transport


@dataclass(frozen=True)
class Policy:
    mode: LocalFileAccess
    # Whether LOCAL_FILE_ACCESS was set, rather than defaulted from the transport.
    explicit: bool
    transport: str
    # (configured spelling, realpath) per LOCAL_FILE_ROOTS entry; empty unless roots.
    roots: tuple[tuple[str, str], ...] = ()
    # realpaths of the files refused in every mode (_deny_list_paths).
    deny_list: tuple[str, ...] = field(default=(), repr=False)
    # Why the setting is invalid; the mode is then off (resolve_policy).
    error: str | None = None
    # realpaths of directories refused, with everything under them (_deny_list_dirs).
    deny_dirs: tuple[str, ...] = field(default=(), repr=False)


def _adc_default_path(env) -> str:
    """gcloud's default ADC file, the fallback when GOOGLE_APPLICATION_CREDENTIALS is
    unset (google.auth._cloud_sdk's lookup)."""
    if config_dir := env.get("CLOUDSDK_CONFIG"):
        return os.path.join(config_dir, "application_default_credentials.json")
    if os.name == "nt":
        base = env.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
        return os.path.join(base, "gcloud", "application_default_credentials.json")
    return os.path.join(
        os.path.expanduser("~"), ".config", "gcloud", "application_default_credentials.json"
    )


def _deny_list_paths(env) -> list[str]:
    """The server's own files, as configured: credentials, `.env`, ADC key files,
    the cache DB with its WAL sidecars, and log files. Included whether or not the
    file exists yet, so a download can't plant a token the server then loads."""
    paths = [
        auth.CREDENTIALS_PATH,
        auth.TOKEN_PATH,
        auth.SERVICE_ACCOUNT_PATH,
        str(Path(__file__).parent / ".env"),
        _adc_default_path(env),
        cache.CACHE_DB_PATH,
        cache.CACHE_DB_PATH + "-wal",
        cache.CACHE_DB_PATH + "-shm",
        # The pre-0.9.3 shared default, kept on disk (never deleted) and still holding
        # whatever it cached for every identity that used it (GHSA-8jqx-w7j8-6xwm).
        cache._LEGACY_DB_PATH,
        cache._LEGACY_DB_PATH + "-wal",
        cache._LEGACY_DB_PATH + "-shm",
    ]
    for name in ("GOOGLE_APPLICATION_CREDENTIALS", "LOG_FILE", "ACCESS_LOG_FILE"):
        if value := env.get(name):
            paths.append(value)
    return [os.path.realpath(p) for p in paths if p]


def _deny_list_dirs(env) -> list[str]:
    """Directories refused whole: the default cache directory, which only this
    server writes (GHSA-8jqx-w7j8-6xwm). An explicit CACHE_DB_PATH may sit in a
    shared directory, so only its files are denied (_deny_list_paths)."""
    if cache.default_db_path(env) != cache.CACHE_DB_PATH:
        return []
    return [os.path.realpath(os.path.dirname(cache.CACHE_DB_PATH))]


def _config_error(mode: LocalFileAccess, raw_roots: list[str]) -> str | None:
    """Why the roots configuration is invalid, or None."""
    if mode is not LocalFileAccess.ROOTS:
        return None
    if not raw_roots:
        return (
            "LOCAL_FILE_ACCESS=roots needs LOCAL_FILE_ROOTS, a "
            f"{os.pathsep!r}-separated list of directories"
        )
    for root in raw_roots:
        if not os.path.isdir(root):
            return f"LOCAL_FILE_ROOTS entry {root!r} isn't an existing directory"
    return None


def resolve_policy(env, argv: list[str]) -> Policy:
    """The policy for this environment and command line.

    Never raises: an invalid setting resolves to `off`, the fail-safe for
    registration, with the reason in `error`. Only serving refuses to start on it
    (`exit_if_invalid`, from `server.main()`), so `mcp-gee-sweet auth` and the doc
    generator still run on a misconfigured setting, e.g. a root not mounted yet."""
    transport = cli_transport(argv)
    raw_mode = (env.get("LOCAL_FILE_ACCESS") or "").strip().lower()
    explicit = bool(raw_mode)
    deny_list = tuple(_deny_list_paths(env))
    deny_dirs = tuple(_deny_list_dirs(env))
    raw_roots = [
        r.strip() for r in (env.get("LOCAL_FILE_ROOTS") or "").split(os.pathsep) if r.strip()
    ]
    if not explicit:
        mode = LocalFileAccess.FULL if transport == "stdio" else LocalFileAccess.OFF
    else:
        try:
            mode = LocalFileAccess(raw_mode)
        except ValueError:
            error = f"LOCAL_FILE_ACCESS={raw_mode!r} isn't valid (use full, roots, or off)"
            return Policy(LocalFileAccess.OFF, True, transport, (), deny_list, error, deny_dirs)
    if error := _config_error(mode, raw_roots):
        return Policy(LocalFileAccess.OFF, True, transport, (), deny_list, error, deny_dirs)

    roots: tuple[tuple[str, str], ...] = ()
    if mode is LocalFileAccess.ROOTS:
        roots = tuple((root, os.path.realpath(root)) for root in raw_roots)
    elif raw_roots:
        logger.warning(
            "LOCAL_FILE_ROOTS is set but ignored: it applies only when LOCAL_FILE_ACCESS=roots"
        )
    return Policy(mode, explicit, transport, roots, deny_list, deny_dirs=deny_dirs)


POLICY = resolve_policy(os.environ, sys.argv)
if POLICY.error:
    # Reported here too, for a launch that never reaches main(), such as uvicorn
    # serving mcp_gee_sweet.server:app directly; that one serves with access off.
    logger.error("Local file access is off: %s", POLICY.error)


def exit_if_invalid() -> None:
    """Stop the server before it serves on an invalid setting, with a one-line message."""
    if POLICY.error:
        raise SystemExit(f"mcp-gee-sweet: {POLICY.error}")


# Set by server._timed for the duration of a tool call: whether the call arrived over
# an HTTP transport (its request context carries a Starlette Request).
request_over_http: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "mcp_gee_sweet_request_over_http", default=False
)
# The deny-list entries' stats, snapshotted for a run of checks (many_checks).
_deny_snapshot: contextvars.ContextVar[tuple | None] = contextvars.ContextVar(
    "mcp_gee_sweet_deny_snapshot", default=None
)
# Resolved parent directories, cached for a run of checks (many_checks).
_dir_cache: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "mcp_gee_sweet_dir_cache", default=None
)
_tripwire_warned = False


def registers_local_only_tools() -> bool:
    """Whether tools that can only work on local files register at all."""
    return POLICY.mode is not LocalFileAccess.OFF


def _tripped() -> bool:
    """A defaulted `full` reached by an HTTP request: the server was served some way
    argv didn't show (e.g. `uvicorn mcp_gee_sweet.server:app`), so the stdio default
    doesn't apply. An explicit LOCAL_FILE_ACCESS=full is the operator's choice."""
    return POLICY.mode is LocalFileAccess.FULL and not POLICY.explicit and request_over_http.get()


def local_paths_usable() -> bool:
    """Whether a `local_path` destination can work on this call at all, for hints
    like the response-size cap's that would otherwise suggest one."""
    return POLICY.mode is not LocalFileAccess.OFF and not _tripped()


def _off_message() -> str:
    if POLICY.error:
        return f"local file access is disabled on this server: {POLICY.error}"
    if POLICY.explicit:
        return "local file access is disabled on this server (LOCAL_FILE_ACCESS=off)"
    return (
        "local file access is disabled on this server: LOCAL_FILE_ACCESS is unset, "
        f"which means off for the {POLICY.transport} transport"
    )


def _deny_stats() -> tuple[tuple[str, os.stat_result | None], ...]:
    stats = []
    for entry in POLICY.deny_list:
        try:
            stats.append((entry, os.stat(entry)))
        except OSError:
            stats.append((entry, None))
    return tuple(stats)


@contextlib.contextmanager
def many_checks() -> Iterator[None]:
    """Stat the deny-list entries once, and resolve each parent directory once, for
    every check inside this block rather than per checked path: a folder walk checks
    every entry, on the loop. A deny-listed file created mid-block is still caught
    by its path, though not through a hardlink to it."""
    token = _deny_snapshot.set(_deny_stats())
    dirs = _dir_cache.set({})
    try:
        yield
    finally:
        _dir_cache.reset(dirs)
        _deny_snapshot.reset(token)


def _realpath(path: str) -> str:
    """os.path.realpath, reusing a parent directory many_checks already resolved
    when the last component isn't a symlink: one lstat instead of one per component.
    A NUL byte raises ValueError either way.

    Never normalizes lexically: `link/..` is the parent of link's *target*, as the
    kernel resolves it, so the parent is resolved by realpath from its raw spelling
    (PR #1039 QA round 2: `os.path.abspath` collapsed `link/..` first, and a write
    landed in a deny-listed directory the check never saw). A relative path skips
    the cache, since its meaning moves with the working directory."""
    cache = _dir_cache.get()
    if cache is None or "\x00" in path or not os.path.isabs(path):
        return os.path.realpath(path)
    parent, name = os.path.split(path)
    if name in ("", ".", "..") or os.path.islink(path):
        return os.path.realpath(path)
    if (real_parent := cache.get(parent)) is None:
        real_parent = cache[parent] = os.path.realpath(parent)
    return os.path.join(real_parent, name)


def _is_denied(real: str) -> bool:
    """Whether `real` (a realpath) is one of the deny-listed files.

    An existing target is matched by its exact path or by file identity, which
    catches a case variant on a case-insensitive filesystem and a hardlink, but not
    a distinct `Token.json` beside `token.json` on a case-sensitive one. A target
    that doesn't exist yet (a write) is also matched case-insensitively, so a new
    `TOKEN.JSON` can't be planted on macOS where it would be the token."""
    try:
        st = os.stat(real)
    except OSError:
        st = None
    normalized = os.path.normcase(real)
    folded = normalized.casefold()
    # A denied directory covers itself and everything under it, matched
    # case-insensitively for the same reason as a new file below.
    for directory in POLICY.deny_dirs:
        if Path(folded).is_relative_to(os.path.normcase(directory).casefold()):
            return True
    for entry, entry_st in _deny_snapshot.get() or _deny_stats():
        entry_normalized = os.path.normcase(entry)
        if entry_normalized == normalized:
            return True
        if st is None:
            if entry_normalized.casefold() == folded:
                return True
        elif entry_st is not None and os.path.samestat(st, entry_st):
            return True
    return False


def _check(path: str | os.PathLike, verb: str) -> Path:
    global _tripwire_warned
    if _tripped():
        if not _tripwire_warned:
            _tripwire_warned = True
            logger.warning(
                "Refusing local file access for an HTTP request: LOCAL_FILE_ACCESS is "
                "unset and the server wasn't started with --transport, so its stdio "
                "default doesn't apply. Set LOCAL_FILE_ACCESS explicitly."
            )
        raise LocalFileAccessError(
            "local file access is disabled for HTTP requests unless LOCAL_FILE_ACCESS "
            "is set explicitly"
        )
    if POLICY.mode is LocalFileAccess.OFF:
        raise LocalFileAccessError(_off_message())
    shown = os.fspath(path)
    try:
        real = _realpath(shown)
    except ValueError as e:
        # A NUL byte: no file can have this name. A LocalFileAccessError, so a
        # per-item site fails that one item rather than the whole call.
        raise LocalFileAccessError(f"{shown!r} isn't a usable local path: {e}") from None
    if POLICY.mode is LocalFileAccess.ROOTS and not any(
        Path(real).is_relative_to(root_real) for _, root_real in POLICY.roots
    ):
        allowed = ", ".join(spelling for spelling, _ in POLICY.roots)
        raise LocalFileAccessError(
            f"{shown} is outside this server's LOCAL_FILE_ROOTS. Allowed directories: {allowed}"
        )
    if _is_denied(real):
        raise LocalFileAccessError(
            f"{shown} is one of this server's own credential, config, cache, or log "
            f"files and can't be {verb} by a tool"
        )
    return Path(real)


def check_read(path: str | os.PathLike) -> Path:
    """Refuse `path` unless this server's policy allows reading it, before any stat:
    the refusal is the same whether or not the path exists. Returns the resolved
    path; using it narrows, but doesn't close, the window before the I/O."""
    return _check(path, "read")


def check_write(path: str | os.PathLike) -> Path:
    """`check_read`'s counterpart for a path a tool writes or creates."""
    return _check(path, "written")


def check_read_write(path: str | os.PathLike) -> Path:
    """`check_read`'s counterpart for a path a tool may read or write, when which one
    isn't known yet (e.g. a file on both sides of a bidirectional sync)."""
    return _check(path, "read or written")
