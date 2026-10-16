"""The local-file access policy (#796): one check for every local read and write a
tool makes on the server's own filesystem.

`LOCAL_FILE_ACCESS=full|roots|off` picks the mode, defaulting to `full` under stdio
and `off` under any network transport, since a network-facing server's caller isn't
necessarily its operator. `roots` limits paths to the directories in
`LOCAL_FILE_ROOTS`. The server's own credential, config, cache and log files are
refused in every mode. Design: docs/design/local-file-access-policy.md.
"""

import contextvars
import enum
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import auth, cache

logger = logging.getLogger(__name__)


class LocalFileAccess(str, enum.Enum):
    """`str, Enum` rather than StrEnum, which needs Python 3.11."""

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
    ]
    for name in ("GOOGLE_APPLICATION_CREDENTIALS", "LOG_FILE", "ACCESS_LOG_FILE"):
        if value := env.get(name):
            paths.append(value)
    return [os.path.realpath(p) for p in paths if p]


def resolve_policy(env, argv: list[str]) -> Policy:
    """The policy for this environment and command line. Raises SystemExit with a
    one-line message for an invalid setting, so a misconfigured server never serves."""
    transport = cli_transport(argv)
    raw_mode = (env.get("LOCAL_FILE_ACCESS") or "").strip().lower()
    explicit = bool(raw_mode)
    if not explicit:
        mode = LocalFileAccess.FULL if transport == "stdio" else LocalFileAccess.OFF
    else:
        try:
            mode = LocalFileAccess(raw_mode)
        except ValueError:
            raise SystemExit(
                f"mcp-gee-sweet: LOCAL_FILE_ACCESS={raw_mode!r} isn't valid "
                "(use full, roots, or off)"
            ) from None

    raw_roots = [r for r in (env.get("LOCAL_FILE_ROOTS") or "").split(os.pathsep) if r.strip()]
    roots: list[tuple[str, str]] = []
    if mode is LocalFileAccess.ROOTS:
        if not raw_roots:
            raise SystemExit(
                "mcp-gee-sweet: LOCAL_FILE_ACCESS=roots needs LOCAL_FILE_ROOTS, a "
                f"{os.pathsep!r}-separated list of directories"
            )
        for root in raw_roots:
            root = root.strip()
            if not os.path.isdir(root):
                raise SystemExit(
                    f"mcp-gee-sweet: LOCAL_FILE_ROOTS entry {root!r} isn't an existing directory"
                )
            roots.append((root, os.path.realpath(root)))
    elif raw_roots:
        logger.warning(
            "LOCAL_FILE_ROOTS is set but ignored: it applies only when LOCAL_FILE_ACCESS=roots"
        )
    return Policy(mode, explicit, transport, tuple(roots), tuple(_deny_list_paths(env)))


POLICY = resolve_policy(os.environ, sys.argv)

# Set by server._timed for the duration of a tool call: whether the call arrived over
# an HTTP transport (its request context carries a Starlette Request).
request_over_http: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "mcp_gee_sweet_request_over_http", default=False
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
    if POLICY.explicit:
        return "local file access is disabled on this server (LOCAL_FILE_ACCESS=off)"
    return (
        "local file access is disabled on this server: LOCAL_FILE_ACCESS is unset, "
        f"which means off for the {POLICY.transport} transport"
    )


def _is_denied(real: str) -> bool:
    """Whether `real` (a realpath) is one of the deny-listed files. File identity for
    an existing target, so a case variant on a case-insensitive filesystem or a
    hardlink is caught; a normalized path compare otherwise (the write case)."""
    try:
        st = os.stat(real)
    except OSError:
        st = None
    folded = os.path.normcase(real).casefold()
    for entry in POLICY.deny_list:
        if os.path.normcase(entry).casefold() == folded:
            return True
        if st is not None:
            try:
                if os.path.samestat(st, os.stat(entry)):
                    return True
            except OSError:
                continue
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
    real = os.path.realpath(path)
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
    the refusal is the same whether or not the path exists. Returns the resolved path
    to do the I/O on."""
    return _check(path, "read")


def check_write(path: str | os.PathLike) -> Path:
    """`check_read`'s counterpart for a path a tool writes or creates."""
    return _check(path, "written")
