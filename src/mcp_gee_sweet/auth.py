import asyncio
import base64
import json
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
import wsgiref.simple_server
import wsgiref.util
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any

import google.auth
from google.auth import compute_engine, external_account, impersonated_credentials
from google.auth.exceptions import TransportError
from google.auth.transport.requests import Request
from google.oauth2 import gdch_credentials, service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow, WSGITimeoutError
from mcp.server.mcpserver import MCPServer

from .cache import (
    CalendarCache,
    DocContentCache,
    DriveFolderCache,
    SheetDataCache,
    SheetStructureCache,
)
from .http_transport import (  # noqa: F401 — re-exported for tool imports
    execute_in_thread,
    thread_http,
)

logger = logging.getLogger(__name__)

BASE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.activity.readonly",
]
# gmail.modify alone covers everything tools/gmail.py does (read, compose, send,
# draft, label, trash — every Gmail operation except permanent deletion, which no
# tool uses), so the narrower gmail.readonly/gmail.send scopes #786 also requested
# were redundant (#790).
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
# Every scope any tool can need — what a default install (no ENABLED_TOOLS filter)
# requests, and what `mcp-gee-sweet auth` authorizes by default.
SCOPES = BASE_SCOPES + GMAIL_SCOPES

# Whether any Gmail tool is registered. server.py sets this once registration is done
# (set_gmail_enabled), before the lifespan runs; defaults to True to match the
# default of every tool being registered.
_gmail_enabled = True


def set_gmail_enabled(enabled: bool) -> None:
    global _gmail_enabled
    _gmail_enabled = enabled


# Set by _oauth_creds when the saved token is missing only Gmail scopes: the server
# still starts (Sheets/Drive/Calendar/Activity are unaffected) and every Gmail tool
# returns this message as its error instead of calling the API. A startup failure
# would be invisible to a stdio client, which drops stderr and just reports
# "Connection closed" (#790, PR #807 QA round 1).
_gmail_unauthorized_message: str | None = None


def get_gmail_unauthorized_message() -> str | None:
    return _gmail_unauthorized_message


# Whether _oauth_creds may run the interactive consent flow when there's no usable
# token. server.main() turns it off for stdio (#811): there the flow blocked startup
# with no timeout, and google-auth-oauthlib print()s its "Please visit this URL"
# prompt to stdout, which is the JSON-RPC channel, so the user never saw it.
_interactive_consent = True
_STDIO_NO_CONSENT_REASON = "this server can't ask for consent itself over the stdio transport"
# Why consent is off, for the error message. The lifespan also turns it off after a
# failed attempt: under SSE the lifespan runs once per connection, and an unattended
# server shouldn't print a fresh prompt and hold each new connection for the timeout.
_interactive_consent_off_reason = _STDIO_NO_CONSENT_REASON


# Whether an auth failure in the lifespan raises (stdio: the server exits, as #790
# chose) or starts that connection without Google access (every other transport).
# server.main() turns it on for stdio. Under SSE a raising lifespan can leave the
# server unable to shut down (python-sdk#3616), and the server keeps running anyway.
_raise_auth_failures = False


def set_raise_auth_failures(enabled: bool) -> None:
    global _raise_auth_failures
    _raise_auth_failures = enabled


def set_interactive_consent(allowed: bool, reason: str = _STDIO_NO_CONSENT_REASON) -> None:
    global _interactive_consent, _interactive_consent_off_reason
    _interactive_consent = allowed
    _interactive_consent_off_reason = reason


def _consent_timeout_seconds() -> int:
    raw = os.environ.get("OAUTH_CONSENT_TIMEOUT_SECONDS", "300")
    try:
        return max(1, int(raw))
    except ValueError:
        # Value deliberately not echoed: CodeQL flags logging an OAUTH_* env var as
        # clear-text logging of sensitive data (PR #828).
        logger.warning("Ignoring non-integer OAUTH_CONSENT_TIMEOUT_SECONDS; using 300")
        return 300


# How long the interactive flow waits for the browser callback before giving up.
_CONSENT_TIMEOUT_SECONDS = _consent_timeout_seconds()


def required_scopes() -> list[str]:
    """The scopes the registered tools actually need: Gmail's are requested only
    when a Gmail tool is registered, so an ENABLED_TOOLS filter that leaves Gmail
    out never asks for mailbox access (#790)."""
    return SCOPES if _gmail_enabled else BASE_SCOPES


class OAuthConsentRequiredError(RuntimeError):
    """There's no usable OAuth token, and the interactive consent flow can't run here
    (stdio transport) or didn't complete (#811)."""


class _ConsentDeferred(Exception):
    """_oauth_creds(defer_consent=True) found no usable token and consent is allowed:
    the caller runs the consent itself, off the event loop (#833)."""

    def __init__(self, scopes: list[str]):
        super().__init__("OAuth consent needed")
        self.scopes = scopes


class _ConsentStopped(Exception):
    """The consent wait was stopped because nothing is waiting for it any more."""


class MissingOAuthScopesError(RuntimeError):
    """The saved OAuth token wasn't authorized for scopes the registered tools need.

    Raised instead of falling back to the interactive consent flow, which would
    open a browser unprompted (or hang a headless/stdio deployment) right after an
    upgrade that added a scope (#790). Deliberately not swallowed by the auth
    waterfall either: a token file on disk means OAuth is the intended method, so
    silently switching to a service account would hide the problem."""


CREDENTIALS_CONFIG = os.environ.get("CREDENTIALS_CONFIG")
TOKEN_PATH = os.environ.get("TOKEN_PATH", "token.json")
CREDENTIALS_PATH = os.environ.get("CREDENTIALS_PATH", "credentials.json")
SERVICE_ACCOUNT_PATH = os.environ.get("SERVICE_ACCOUNT_PATH", "service_account.json")
# Whether SERVICE_ACCOUNT_PATH was set on purpose, as opposed to the default: a
# missing key file then counts as a misconfiguration worth reporting (#811).
SERVICE_ACCOUNT_PATH_EXPLICIT = "SERVICE_ACCOUNT_PATH" in os.environ
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "")
# When unset, auth falls through: OAuth → service_account → ADC.
# Explicit values pin to one method with no fallback: "oauth" | "service_account" | "adc"
AUTH_METHOD = os.environ.get("AUTH_METHOD")


@dataclass
class SpreadsheetContext:
    sheets_service: Any
    drive_service: Any
    docs_service: Any
    calendar_service: Any
    activity_service: Any
    gmail_service: Any
    folder_id: str | None = None
    auth_method: str = "unknown"  # "service_account" | "oauth" | "adc"
    # True whenever the resolved credential has no personal Drive identity —
    # always true for auth_method == "service_account", but also true for
    # auth_method == "adc" when google.auth.default() itself resolved to a
    # service-account-backed credential (see _is_service_account_credential).
    is_service_account_identity: bool = False
    # Set when this connection started without Google access because OAuth needs
    # consent it couldn't get (#811): every service is None, and server.py's tool
    # wrapper raises this message instead of running any tool. Per context, not
    # process-wide: under SSE each connection runs its own lifespan.
    unauthorized_message: str | None = None
    cache: SheetStructureCache = field(default_factory=SheetStructureCache)
    sheet_data_cache: SheetDataCache = field(default_factory=SheetDataCache)
    drive_folder_cache: DriveFolderCache = field(default_factory=DriveFolderCache)
    doc_cache: DocContentCache = field(default_factory=DocContentCache)
    calendar_cache: CalendarCache = field(default_factory=CalendarCache)


def _is_service_account_credential(creds: Any) -> bool:
    """Whether `creds` is backed by a service-account identity (no personal Drive
    storage quota, no personal Drive identity) rather than a real user's own.

    True for the credentials `_service_account_creds()` returns, and — the case
    issue #506 is about — also true for an ADC-resolved credential
    (`google.auth.default()`) when ADC itself resolved to one of the
    non-user-identity credential classes `google.auth._default.py`'s own dispatch
    table can produce (confirmed against the installed `google-auth` package,
    PR #613 QA round 1 — the original version of this check only covered the
    first two and silently misclassified the rest the same way plain `"adc"` did
    before this fix existed):

    - `service_account.Credentials` — `GOOGLE_APPLICATION_CREDENTIALS` pointed at
      a key file, the same class the explicit `service_account` path uses.
    - `compute_engine.Credentials` — a GCE/Cloud Run/GKE attached metadata identity.
    - `external_account.Credentials` — Workload Identity Federation (AWS, a
      pluggable external process, or a file/URL-sourced identity pool; `aws`,
      `pluggable`, and `identity_pool` credentials all subclass this one base).
    - `impersonated_credentials.Credentials` — an impersonated service account,
      common in CI.
    - `gdch_credentials.ServiceAccountCredentials` — a GDCH service account.

    Deliberately excludes `external_account_authorized_user.Credentials`
    (Workforce Identity Federation): per its own module docstring it "usually
    access[es] resources on behalf of a user (resource owner)" — a real human
    authenticated through an external IdP, not a service identity — so it's
    treated the same as `google.oauth2.credentials.Credentials`, the class an ADC
    session backed by a real user (`gcloud auth application-default login`) or
    `_oauth_creds()`'s own OAuth flow resolves to.
    """
    return isinstance(
        creds,
        service_account.Credentials
        | compute_engine.Credentials
        | external_account.Credentials
        | impersonated_credentials.Credentials
        | gdch_credentials.ServiceAccountCredentials,
    )


def _missing_scopes_message(missing: list[str]) -> str:
    gmail_hint = (
        " The Gmail tools are what need them: to run without Gmail instead, leave "
        "the Gmail tools out of ENABLED_TOOLS / --include-tools."
        if any(s in GMAIL_SCOPES for s in missing)
        else ""
    )
    return (
        f"The OAuth token at {TOKEN_PATH!r} wasn't authorized for scope(s) the "
        f"enabled tools require: {', '.join(missing)}. {reauthorize_instructions()}"
        f"{gmail_hint}"
    )


def reauthorize_instructions() -> str:
    """How to (re-)authorize: `mcp-gee-sweet auth`, run with the same settings as this
    server so it writes the token the server reads and requests the scopes its tools
    need."""
    return (
        "To authorize, run `mcp-gee-sweet auth` in a terminal (`uvx mcp-gee-sweet auth` "
        f"for a PyPI install) with the same TOKEN_PATH ({TOKEN_PATH!r}), CREDENTIALS_PATH "
        f"({CREDENTIALS_PATH!r}) and ENABLED_TOOLS as this server, then restart the server "
        "or reconnect to it."
    )


def _missing_scopes_error(missing: list[str]) -> MissingOAuthScopesError:
    # Logged as well as raised: the traceback only reaches stderr, which stdio hosts
    # drop, so LOG_FILE (with DEBUG_LEVEL set) is where an operator can find why
    # startup failed.
    message = _missing_scopes_message(missing)
    logger.error("OAuth startup failed: %s", message)
    return MissingOAuthScopesError(message)


def _degrade_gmail(missing: list[str]) -> None:
    global _gmail_unauthorized_message
    _gmail_unauthorized_message = _missing_scopes_message(missing)
    logger.warning("Gmail tools disabled: %s", _gmail_unauthorized_message)


def _oauth_creds(*, defer_consent: bool = False) -> Credentials:
    """Obtain OAuth credentials, refreshing or running the interactive flow as needed.

    With `defer_consent`, raises _ConsentDeferred instead of running the interactive
    flow here; the lifespan uses that to run it off the event loop (#833).

    The interactive flow only runs when there's no usable token at all. A token
    authorized for fewer scopes than the enabled tools need raises
    MissingOAuthScopesError instead (#790) — unless every missing scope is a Gmail
    one, in which case the server starts without Gmail and each Gmail tool reports
    the re-authorize instructions as its own error (see _gmail_unauthorized_message).
    The check reads the scopes saved in the token file itself, so the token is loaded
    with *those* scopes rather than required_scopes(): passing the required ones would
    both make has_scopes() trivially true and send ungranted scopes on refresh (Google
    answers that with `invalid_scope`, confirmed live)."""
    global _gmail_unauthorized_message
    _gmail_unauthorized_message = None
    scopes = required_scopes()
    creds = None
    info = None
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH) as f:
            info = json.load(f)
        if info.get("scopes"):
            creds = Credentials.from_authorized_user_info(info)
            missing = [s for s in scopes if not creds.has_scopes([s])]
            if missing and all(s in GMAIL_SCOPES for s in missing):
                _degrade_gmail(missing)
            elif missing:
                raise _missing_scopes_error(missing)
        else:
            # No saved scope record to check against — keep the pre-#790 behavior.
            creds = Credentials.from_authorized_user_info(info, scopes)

    if creds and creds.expired and creds.refresh_token:
        try:
            logger.debug("Refreshing expired OAuth token...")
            creds.refresh(Request())
            _write_token(creds)
            logger.debug("Token refreshed successfully")
            return creds
        except TransportError as e:
            # Google unreachable (e.g. the network isn't up yet at login) says nothing
            # about the token itself. Keep it: google-auth refreshes an expired token
            # before its first API call, so this recovers without re-authorizing (#811).
            logger.warning(
                "Couldn't reach Google to refresh the OAuth token (%s); keeping it, "
                "it will refresh on first use",
                e,
            )
            return creds
        except Exception as e:
            # The saved scope record can overstate what was actually granted (e.g. a
            # hand-built token.json). Same clear failure as above, not a surprise
            # browser consent — and the same Gmail-only split: if the refresh
            # succeeds once the Gmail scopes are dropped, only Gmail was ungranted.
            if "invalid_scope" in str(e):
                creds = _refresh_without_gmail(info, list(creds.scopes or scopes))
                if creds is None:
                    raise _missing_scopes_error(scopes) from e
                return creds
            logger.warning("Token refresh failed: %s — the token needs re-authorizing", e)
            creds = None

    if not creds or not creds.valid:
        _check_client_secrets()
        if not _interactive_consent:
            raise _consent_off_error()
        if defer_consent:
            raise _ConsentDeferred(scopes)
        creds = _run_server_consent(scopes, threading.Event())

    return creds


def _consent_off_error() -> OAuthConsentRequiredError:
    return OAuthConsentRequiredError(
        f"No usable OAuth token at {TOKEN_PATH!r}, and "
        f"{_interactive_consent_off_reason}. {reauthorize_instructions()}"
    )


async def _oauth_creds_async() -> Credentials:
    """_oauth_creds for the lifespan. Nothing here runs on the event loop (#833): the
    token load and refresh run on a daemon thread, and so does the consent wait, so
    other connections keep being served and SIGTERM still stops the server. Before,
    a consent wait (or a hanging token endpoint) blocked the loop."""
    successes = _consent_successes
    try:
        return await _load_token()
    except _ConsentDeferred as deferred:
        if _consent_successes == successes:
            return await _await_server_consent(deferred.scopes)
    # A consent succeeded while this load ran on its thread, so the load may have read
    # TOKEN_PATH just before the token was written. Read it again rather than start a
    # second consent (PR #867 QA round 4).
    try:
        return await _load_token()
    except _ConsentDeferred as deferred:
        return await _await_server_consent(deferred.scopes)


async def _load_token() -> Credentials:
    loading = _run_in_daemon_thread(
        asyncio.get_running_loop(), lambda: _oauth_creds(defer_consent=True), name="oauth-token"
    )
    return await _await_unless_shutdown(
        loading,
        f"No usable OAuth token yet: the server shut down while loading the token at "
        f"{TOKEN_PATH!r}.",
    )


def _run_server_consent(scopes: list[str], stop: threading.Event) -> Credentials:
    """The server's consent flow: prompt on stderr, bounded by OAUTH_CONSENT_TIMEOUT_SECONDS
    (#811), stoppable through `stop`. Every failure becomes OAuthConsentRequiredError."""
    try:
        creds = _serve_consent(_new_flow(scopes), _CONSENT_TIMEOUT_SECONDS, stop)
        _write_token(creds)
    except _ConsentStopped:
        raise
    except WSGITimeoutError as e:
        raise OAuthConsentRequiredError(
            f"No usable OAuth token at {TOKEN_PATH!r}, and the browser consent wasn't "
            f"completed within {_CONSENT_TIMEOUT_SECONDS}s. {reauthorize_instructions()}"
        ) from e
    except Exception as e:
        # Denied consent, a scope unticked on the granular-consent screen, a stray
        # request consuming the one callback, an unwritable TOKEN_PATH: all leave
        # the server exactly where a timeout does.
        raise OAuthConsentRequiredError(
            f"No usable OAuth token at {TOKEN_PATH!r}, and the browser consent "
            f"failed ({type(e).__name__}: {e}). {reauthorize_instructions()}"
        ) from e
    logger.debug("OAuth flow completed successfully")
    return creds


_CONSENT_PROMPT = "Please visit this URL to authorize this application: {url}"
_CONSENT_SUCCESS_PAGE = "The authentication flow has completed. You may close this window."
# How often the callback server's wait checks the deadline and the stop flag.
_CONSENT_POLL_SECONDS = 0.5


class _CallbackApp:
    """Records the first request to the callback server. A stray request ends the wait
    too, as it does with google-auth-oauthlib's own server (its state won't match)."""

    def __init__(self):
        self.request_uri: str | None = None

    def __call__(self, environ, start_response):
        start_response("200 OK", [("Content-type", "text/plain; charset=utf-8")])
        self.request_uri = wsgiref.util.request_uri(environ)
        return [_CONSENT_SUCCESS_PAGE.encode()]


class _CallbackHandler(wsgiref.simple_server.WSGIRequestHandler):
    # A connection that sends nothing (a browser preconnect, a port scanner) would
    # otherwise block handle_request() in readline() until the client hung up, and
    # the deadline and stop checks between requests would never run (PR #867 QA).
    timeout = 5

    def log_message(self, format, *args):
        # Not logged at all: the request line carries the authorization code.
        pass


class _CallbackServer(wsgiref.simple_server.WSGIServer):
    # As in google-auth-oauthlib: on Windows, SO_REUSEADDR alone would let another
    # process bind the same port and receive the authorization code.
    allow_reuse_address = False

    def server_bind(self):
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def handle_error(self, request, client_address):
        # socketserver's default prints a traceback to stderr. A silent connection
        # timing out is expected, and nothing here is worth a traceback.
        logger.debug("Consent callback: dropped a connection", exc_info=True)


def _serve_consent(
    flow: InstalledAppFlow, timeout_seconds: float, stop: threading.Event
) -> Credentials:
    """InstalledAppFlow.run_local_server, but stoppable from another thread, and with
    its prompt written to stderr instead of print()ed to stdout. The library's wait is
    one blocking handle_request() for the whole timeout, and its prompt could only be
    moved with redirect_stdout, which swaps sys.stdout for every thread (#833)."""
    app = _CallbackApp()
    server = wsgiref.simple_server.make_server(
        "localhost", 0, app, server_class=_CallbackServer, handler_class=_CallbackHandler
    )
    try:
        flow.redirect_uri = f"http://localhost:{server.server_port}/"
        auth_url, _ = flow.authorization_url()
        try:
            webbrowser.get().open(auth_url, new=1, autoraise=True)
        except webbrowser.Error:
            logger.debug("No browser to open for the consent; the URL is on stderr")
        print(_CONSENT_PROMPT.format(url=auth_url), file=sys.stderr, flush=True)
        server.timeout = _CONSENT_POLL_SECONDS
        deadline = time.monotonic() + timeout_seconds
        while app.request_uri is None:
            if stop.is_set():
                raise _ConsentStopped()
            if time.monotonic() >= deadline:
                raise WSGITimeoutError("Timed out waiting for response from authorization server")
            server.handle_request()
        # oauthlib rejects an http:// redirect; the library makes the same swap for
        # its localhost callback.
        flow.fetch_token(authorization_response=app.request_uri.replace("http", "https", 1))
    finally:
        server.server_close()
    return flow.credentials


def _run_in_daemon_thread(
    loop: asyncio.AbstractEventLoop,
    fn: Callable[[], Any],
    name: str,
    on_settle: Callable[[BaseException | None], None] | None = None,
) -> asyncio.Future:
    """Run `fn` on a daemon thread and return a future for its result. A daemon
    thread, not asyncio.to_thread: interpreter shutdown joins the default executor's
    threads, so a call still waiting there would just move the hang to shutdown.
    `on_settle` runs on the loop just before the future settles."""
    future = loop.create_future()
    # Retrieve the outcome even if every awaiter gave up, so an exception settling
    # later isn't logged as never retrieved.
    future.add_done_callback(lambda f: f.cancelled() or f.exception())

    def settle(result: Any, error: BaseException | None) -> None:
        if on_settle is not None:
            on_settle(error)
        if future.done():
            return
        if error is None:
            future.set_result(result)
        else:
            future.set_exception(error)

    def run() -> None:
        try:
            result, error = fn(), None
        except BaseException as e:
            result, error = None, e
        # RuntimeError: the loop already closed, because the server shut down.
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(settle, result, error)

    threading.Thread(target=run, name=name, daemon=True).start()
    return future


async def _await_unless_shutdown(future: asyncio.Future, shutdown_message: str) -> Any:
    """Await `future`, but give up with OAuthConsentRequiredError(`shutdown_message`)
    once the server starts shutting down. Uvicorn waits for open connections before
    exiting, and this one can't finish until its lifespan does, so without this,
    SIGTERM waits for whatever the thread is waiting on. The future itself isn't
    cancelled (a shared consent may have other waiters)."""
    waiter = asyncio.shield(future)
    try:
        while True:
            done, _ = await asyncio.wait({waiter}, timeout=_CONSENT_POLL_SECONDS)
            if done:
                return waiter.result()
            if _server_shutting_down():
                raise OAuthConsentRequiredError(shutdown_message)
    finally:
        waiter.cancel()  # no-op once done; otherwise detaches this waiter


class _ConsentAttempt:
    """One consent flow running on a daemon thread, awaited by every connection
    that needs it."""

    def __init__(self, loop: asyncio.AbstractEventLoop, scopes: list[str]):
        self.stop = threading.Event()
        self.waiters = 0
        self.future = _run_in_daemon_thread(
            loop,
            lambda: _run_server_consent(scopes, self.stop),
            name="oauth-consent",
            on_settle=self._on_settle,
        )

    @staticmethod
    def _on_settle(error: BaseException | None) -> None:
        # A failed attempt turns off consent here, on the loop, before any waiter
        # sees the failure: not later in the lifespan, which a waterfall fallback
        # skips, and which a connection opening in between would race (PR #867 QA).
        # A stopped attempt (every waiter gave up) isn't a failure.
        # A success is counted here too, so a connection whose token load raced it
        # reads the saved token instead of starting another consent.
        global _consent_successes
        if error is None:
            _consent_successes += 1
        elif not isinstance(error, _ConsentStopped):
            _disable_consent_after_failure()


# How many consent attempts have succeeded in this process. Read and bumped on the loop.
_consent_successes = 0

# Process-wide on purpose: one consent wait (one prompt, one callback port) is shared
# by every connection that arrives while it runs, rather than one per connection.
_consent_attempt: _ConsentAttempt | None = None


def _server_shutting_down() -> bool:
    """Whether uvicorn got SIGTERM/SIGINT. sse_starlette's AppStatus flag is set from
    uvicorn's exit handler; it's how SSE streams learn to close, and the only shutdown
    signal code inside a connection's lifespan can see."""
    try:
        from sse_starlette.sse import AppStatus
    except ImportError:
        return False
    return bool(AppStatus.should_exit)


async def _await_server_consent(scopes: list[str]) -> Credentials:
    global _consent_attempt
    loop = asyncio.get_running_loop()
    attempt = _consent_attempt
    if (
        attempt is None
        or attempt.future.done()
        or attempt.stop.is_set()
        or attempt.future.get_loop() is not loop
    ):
        # Checked again here, on the loop: the token load that decided consent was
        # needed ran on a thread, and an attempt may have failed (turning consent
        # off) since. Without this, that caller would start a second consent.
        if not _interactive_consent:
            raise _consent_off_error()
        attempt = _consent_attempt = _ConsentAttempt(loop, scopes)
    attempt.waiters += 1
    try:
        return await _await_unless_shutdown(
            attempt.future,
            f"No usable OAuth token at {TOKEN_PATH!r}, and the server shut down "
            f"before the browser consent completed. {reauthorize_instructions()}",
        )
    finally:
        attempt.waiters -= 1
        if attempt.waiters == 0 and not attempt.future.done():
            # Every connection waiting on it gave up (shutdown, or cancelled):
            # stop the wait now so its callback port closes, instead of at the timeout.
            attempt.stop.set()


def _check_client_secrets() -> None:
    if not os.path.exists(CREDENTIALS_PATH):
        raise RuntimeError(
            f"{CREDENTIALS_PATH!r} not found. Set CREDENTIALS_PATH or provide credentials.json."
        )


def _check_token_writable() -> None:
    """Fail before the consent, not after: a token that can't be saved once the user
    has consented is a lost refresh token."""
    parent = os.path.dirname(os.path.abspath(TOKEN_PATH))
    if not os.path.isdir(parent):
        raise RuntimeError(
            f"The directory for TOKEN_PATH ({TOKEN_PATH!r}) doesn't exist. Create it first."
        )
    target = TOKEN_PATH if os.path.exists(TOKEN_PATH) else parent
    if not os.access(target, os.W_OK):
        raise RuntimeError(f"TOKEN_PATH ({TOKEN_PATH!r}) isn't writable.")


def write_token_json(token_json: str) -> None:
    """Save a token to TOKEN_PATH, readable by its owner only: it holds a refresh
    token for Drive (and, with Gmail enabled, the mailbox)."""
    fd = os.open(TOKEN_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        # O_CREAT's mode only applies to a new file; tighten an existing one too.
        if hasattr(os, "fchmod"):
            os.fchmod(f.fileno(), 0o600)
        f.write(token_json)


def _write_token(creds: Any) -> None:
    write_token_json(creds.to_json())


def _new_flow(scopes: list[str]) -> InstalledAppFlow:
    _check_client_secrets()
    _check_token_writable()
    return InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, scopes)


def run_consent_flow(scopes: list[str], **run_kwargs: Any) -> Credentials:
    """Run the browser consent flow for `scopes` and save the token to TOKEN_PATH.
    `run_kwargs` go to InstalledAppFlow.run_local_server. For a terminal (`mcp-gee-sweet
    auth`), where the library's stdout prompt belongs; the server's own consent is
    _run_server_consent."""
    flow = _new_flow(scopes)
    creds = flow.run_local_server(port=0, **run_kwargs)
    _write_token(creds)
    logger.debug("OAuth flow completed successfully")
    return creds


def run_auth_command(open_browser: bool = True) -> int:
    """`mcp-gee-sweet auth`: (re-)authorize from a terminal, overwriting any existing
    token, so a stdio or PyPI install has a way to recover (#811). Requests the scopes
    the registered tools need, the same set the server checks the token against."""
    scopes = required_scopes()
    print(f"Credentials : {CREDENTIALS_PATH}")
    print(f"Token target: {TOKEN_PATH}")
    print(f"Scopes      : {', '.join(scopes)}")
    print()
    try:
        run_consent_flow(scopes, open_browser=open_browser)
    except Exception as e:
        # Denied consent, an unticked scope, a malformed or web-type client JSON: a
        # terminal user needs the reason, not a traceback.
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(f"\nSaved the token to {TOKEN_PATH}. Restart the server to pick it up.")
    return 0


def _refresh_without_gmail(info: dict | None, attempted: list[str]) -> Credentials | None:
    """Retry an `invalid_scope` refresh with the Gmail scopes dropped. Returns the
    refreshed credentials (with Gmail marked unauthorized) if that succeeds, or None
    if the attempted scopes had no Gmail ones to drop or the retry still fails — a
    base scope is what's ungranted then, so the caller raises."""
    gmail = [s for s in attempted if s in GMAIL_SCOPES]
    base = [s for s in attempted if s not in GMAIL_SCOPES]
    if info is None or not gmail or not base:
        return None
    creds = Credentials.from_authorized_user_info(info, base)
    try:
        creds.refresh(Request())
    except Exception as e:
        logger.debug("Refresh without Gmail scopes also failed: %s", e)
        return None
    # Deliberately not written back to TOKEN_PATH: the saved token keeps its own
    # scope record, so re-authorizing later is `mcp-gee-sweet auth` and a restart.
    _degrade_gmail(gmail)
    return creds


def _degrade_unauthorized(message: str) -> str:
    # Logged as well: stdio hosts drop stderr, so LOG_FILE is where an operator sees it.
    logger.warning("Starting without Google access: %s", message)
    if _interactive_consent:
        # Normally already off: a failed attempt turns it off as it settles. Kept for
        # a degrade that didn't come from a settled attempt (e.g. a shutdown).
        _disable_consent_after_failure()
    return message


def _disable_consent_after_failure() -> None:
    # The lifespan runs per connection, so a retry would make each new connection
    # wait for the timeout again; later connections just re-read TOKEN_PATH instead.
    set_interactive_consent(
        False,
        reason="an earlier browser consent in this server process didn't complete "
        "(it isn't retried, so new connections don't each wait for it again)",
    )


def _unusable_fallbacks_note(adc_error: Exception) -> str:
    """What the waterfall's fallbacks hit, when they were configured on purpose: a
    degraded start shouldn't hide a broken service-account or ADC setup behind "run
    mcp-gee-sweet auth" (#811). Unconfigured fallbacks aren't worth mentioning."""
    notes = []
    if SERVICE_ACCOUNT_PATH_EXPLICIT and not os.path.exists(SERVICE_ACCOUNT_PATH):
        notes.append(
            f"no service account key file at SERVICE_ACCOUNT_PATH ({SERVICE_ACCOUNT_PATH!r})"
        )
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        notes.append(f"ADC failed ({adc_error})")
    if not notes:
        return ""
    return f" The fallbacks weren't usable either: {'; '.join(notes)}."


def _service_account_creds() -> service_account.Credentials:
    """Load service account credentials from env or file."""
    if CREDENTIALS_CONFIG:
        return service_account.Credentials.from_service_account_info(
            json.loads(base64.b64decode(CREDENTIALS_CONFIG)), scopes=required_scopes()
        )
    if SERVICE_ACCOUNT_PATH and os.path.exists(SERVICE_ACCOUNT_PATH):
        return service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_PATH, scopes=required_scopes()
        )
    return None


# mcp v2's MCPServer dropped FastMCP's get_context() with no replacement for static
# (non-templated) resources — Context injection there raises ValueError outright, and
# there's no other way to reach the running server's per-process state (confirmed live
# against mcp==2.0.0, issue #175). SpreadsheetContext is created once per process by
# this lifespan (not per-request), so mirroring it here is the correct-shaped fix, not
# a workaround: server.py's get_auth_status() (a static resource) reads it via
# get_lifespan_context() instead of going through Context at all.
_lifespan_context: SpreadsheetContext | None = None


def get_lifespan_context() -> SpreadsheetContext:
    if _lifespan_context is None:
        raise RuntimeError("Server lifespan has not started yet")
    return _lifespan_context


def _degraded_context(message: str | None) -> SpreadsheetContext:
    # No services to build. server.py's tool wrapper raises context.unauthorized_message
    # before any tool body can reach them.
    return SpreadsheetContext(
        sheets_service=None,
        drive_service=None,
        docs_service=None,
        calendar_service=None,
        activity_service=None,
        gmail_service=None,
        folder_id=DRIVE_FOLDER_ID if DRIVE_FOLDER_ID else None,
        auth_method="none",
        unauthorized_message=message,
    )


def _auth_failure_message(error: Exception) -> str:
    message = str(error)
    if error.__cause__ is not None:
        message = f"{message} ({type(error.__cause__).__name__}: {error.__cause__})"
    return message


@asynccontextmanager
async def spreadsheet_lifespan(server: MCPServer) -> AsyncIterator[SpreadsheetContext]:
    global _lifespan_context
    try:
        context = await _build_context()
    except Exception as e:
        # Over SSE, raising here leaves a POST that raced in parked forever in mcp's
        # transport (its per-session stream is never closed when the lifespan fails),
        # and SIGTERM then waits on it (python-sdk#3616, PR #867 QA round 2). The server
        # keeps running either way, so start this connection without Google access and
        # give the client the reason on every tool call instead.
        if _raise_auth_failures:
            raise
        message = _auth_failure_message(e)
        logger.error("Starting without Google access: %s", message)
        logger.debug("Auth failure detail", exc_info=True)
        context = _degraded_context(message)
    _lifespan_context = context
    try:
        yield context
    finally:
        _lifespan_context = None


async def _build_context() -> SpreadsheetContext:
    from googleapiclient.discovery import build

    logger.debug("AUTH_METHOD=%s", AUTH_METHOD or "auto (waterfall)")
    resolved = "unknown"
    unauthorized = None

    # --- Strict override modes (AUTH_METHOD set explicitly) ---

    if AUTH_METHOD == "oauth":
        try:
            creds = await _oauth_creds_async()
            resolved = "oauth"
        except OAuthConsentRequiredError as e:
            creds = None
            unauthorized = _degrade_unauthorized(str(e))

    elif AUTH_METHOD == "service_account":
        creds = _service_account_creds()
        if not creds:
            raise RuntimeError(
                "AUTH_METHOD=service_account but no credentials found. "
                "Set CREDENTIALS_CONFIG or SERVICE_ACCOUNT_PATH."
            )
        resolved = "service_account"

    elif AUTH_METHOD == "adc":
        try:
            creds, project = google.auth.default(scopes=required_scopes())
            logger.debug("ADC resolved project: %s", project)
            resolved = "adc"
        except Exception as e:
            raise RuntimeError("AUTH_METHOD=adc but ADC failed.") from e

    # --- Waterfall (AUTH_METHOD not set) ---

    else:
        creds = None
        consent_required = None

        # 1. OAuth
        try:
            creds = await _oauth_creds_async()
            resolved = "oauth"
            logger.debug("Waterfall: using OAuth")
        except MissingOAuthScopesError:
            raise
        except OAuthConsentRequiredError as e:
            consent_required = e
            logger.debug("Waterfall: OAuth needs consent (%s), trying service account", e)
        except Exception as e:
            logger.debug("Waterfall: OAuth unavailable (%s), trying service account", e)

        # 2. Service account
        if not creds:
            creds = _service_account_creds()
            if creds:
                resolved = "service_account"
                logger.debug("Waterfall: using service account")
                logger.debug("Drive folder ID: %s", DRIVE_FOLDER_ID or "not specified")

        # 3. ADC
        if not creds:
            try:
                creds, project = google.auth.default(scopes=required_scopes())
                resolved = "adc"
                logger.debug("Waterfall: using ADC for project: %s", project)
            except Exception as e:
                # OAuth client secrets on disk mean OAuth was the intended method, so
                # start without Google access and report how to authorize, rather than
                # failing startup where a stdio client can't show why.
                if consent_required is None:
                    raise RuntimeError(
                        "All authentication methods failed. Please configure credentials."
                    ) from e
                logger.debug("Waterfall: ADC unavailable (%s)", e)
                unauthorized = _degrade_unauthorized(
                    f"{consent_required}{_unusable_fallbacks_note(e)}"
                )

    if creds is None:
        return _degraded_context(unauthorized)

    logger.debug("Auth resolved: %s", resolved)
    is_service_account_identity = _is_service_account_credential(creds)
    if resolved == "adc" and is_service_account_identity:
        logger.debug("ADC resolved to a service-account-backed credential")

    # cache_discovery=False: file cache requires oauth2client<4.0; all auth paths here use google-auth
    sheets_service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
    docs_service = build("docs", "v1", credentials=creds, cache_discovery=False)
    calendar_service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    activity_service = build("driveactivity", "v2", credentials=creds, cache_discovery=False)
    gmail_service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    return SpreadsheetContext(
        sheets_service=sheets_service,
        drive_service=drive_service,
        docs_service=docs_service,
        calendar_service=calendar_service,
        activity_service=activity_service,
        gmail_service=gmail_service,
        folder_id=DRIVE_FOLDER_ID if DRIVE_FOLDER_ID else None,
        auth_method=resolved,
        is_service_account_identity=is_service_account_identity,
        cache=SheetStructureCache(),
    )
