"""Re-authorizing OAuth from the failing tool call (#873).

When a call hits a connection that started without Google access because OAuth needed
consent (#811), or a token refresh Google rejects mid-session, the server offers the
consent to the user instead of staying broken until `mcp-gee-sweet auth` and a restart:

1. If another call already re-authorized, or a newer token is on disk (someone ran
   `mcp-gee-sweet auth`), the connection adopts it in place.
2. Otherwise it starts (or joins) the process's single consent listener and hands the
   URL to the client: as a URL-mode elicitation when the client supports one, else in
   the ToolError text. It never opens a browser itself. The user approves, the
   callback saves the token, and the retried call adopts it.

Design and trade-offs: docs/design/oauth-reauthorize-from-tool-call.md.
"""

import json
import os
from typing import Any, NoReturn

from google.auth.exceptions import GoogleAuthError, RefreshError
from mcp import UrlElicitationRequiredError
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ElicitRequestURLParams

from . import auth
from .auth import SpreadsheetContext


class ReauthorizationRequired(ToolError):
    """A ToolError asking the user to re-authorize; logged as a 401."""


def lifespan_context(ctx: Any) -> Any:
    """This call's own lifespan context (per connection under SSE, #811), or None."""
    return getattr(getattr(ctx, "request_context", None), "lifespan_context", None)


def _context(ctx: Any) -> SpreadsheetContext | None:
    context = lifespan_context(ctx)
    return context if isinstance(context, SpreadsheetContext) else None


def _session(ctx: Any) -> Any:
    return getattr(getattr(ctx, "request_context", None), "session", None)


def _supports_url_elicitation(ctx: Any) -> bool:
    caps = getattr(_session(ctx), "client_capabilities", None)
    return getattr(getattr(caps, "elicitation", None), "url", None) is not None


def exception_text(exc: BaseException) -> str:
    """An exception's message for the client. google-auth raises e.g.
    RefreshError(message, response_dict), whose str() is the tuple's repr."""
    if isinstance(exc, GoogleAuthError) and exc.args and isinstance(exc.args[0], str):
        return exc.args[0]
    return str(exc) or type(exc).__name__


def _cli_alternative() -> str:
    return auth.reauthorize_instructions(restart=False, lead="Or run")


# TOKEN_PATH's (mtime_ns, size), or None for a missing file, as of the last reload that
# found nothing usable to adopt. Process-wide, like TOKEN_PATH: until the file changes,
# reloading it again would only repeat the same failing refresh round-trip.
_unchanged_token_marker = object()
_rejected_token_stat: Any = _unchanged_token_marker


def _token_stat() -> tuple[int, int] | None:
    try:
        st = os.stat(auth.TOKEN_PATH)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


async def _adopt_saved_token(context: SpreadsheetContext) -> bool:
    """Adopt the token at TOKEN_PATH if it's usable and isn't the one that failed.
    Skipped while the file is unchanged since the last reload that found nothing."""
    global _rejected_token_stat
    stat = _token_stat()
    if stat == _rejected_token_stat:
        return False
    creds = await auth.load_saved_token()
    failed = context.credentials
    same_grant = (
        creds is not None
        and failed is not None
        and getattr(creds, "refresh_token", None) == getattr(failed, "refresh_token", None)
    )
    if creds is None or same_grant:
        # A same-grant token is the one the connection already has: it can't be the fix.
        _rejected_token_stat = stat
        return False
    _rejected_token_stat = _unchanged_token_marker
    auth.publish_oauth_credentials(creds)
    auth.adopt_published_credentials(context)
    return True


async def _offer_consent(
    ctx: Any, reason: str, unavailable_message: str | None = None, outcome: str = ""
) -> NoReturn:
    """Raise with the consent URL for the user: a URL-mode elicitation when the client
    supports one, else a ToolError carrying the URL. If the consent can't start, raise
    `unavailable_message` (default: `reason` plus the CLI instructions) and why.
    `outcome` (what the tool itself reported) goes in the text the model sees."""
    try:
        attempt = await auth.start_user_consent()
    except Exception as e:
        fallback = (
            unavailable_message
            or f"{reason} {auth.reauthorize_instructions(restart=False)}{outcome}"
        )
        raise ReauthorizationRequired(
            f"{fallback} (The server couldn't offer re-authorization itself: "
            f"{type(e).__name__}: {e}.)"
        ) from e
    url = attempt.auth_url
    if url is None:
        # The lifespan's own consent for another SSE connection, a moment before its
        # listener is bound. Its URL is about to be on stderr.
        raise ReauthorizationRequired(
            f"{reason} A browser consent for this server has just started; retry the "
            f"call in a few seconds to get its link. {_cli_alternative()}{outcome}"
        )
    remaining = attempt.remaining_seconds()
    if _supports_url_elicitation(ctx):
        attempt.notify_on_completion(_session(ctx))
        raise UrlElicitationRequiredError(
            [
                ElicitRequestURLParams(
                    message=(
                        f"{reason} Open this Google sign-in page to re-authorize "
                        f"mcp-gee-sweet (the link works for {remaining}s), then retry."
                    ),
                    url=url,
                    elicitation_id=attempt.elicitation_id,
                )
            ],
            f"{reason} Google re-authorization required: approve access at {url} "
            f"within {remaining}s, then retry the call.{outcome}",
        )
    raise ReauthorizationRequired(
        f"{reason} To re-authorize, open this link in a browser and approve access "
        f"within {remaining}s, then retry the call: {url} {_cli_alternative()}{outcome}"
    )


async def before_call(ctx: Any) -> None:
    """Before a tool body runs. Adopts a token another call already got. On a connection
    degraded because OAuth needed consent, adopts a saved token or raises with a consent
    offer. Does nothing for any other context (service account, ADC, a test's mock)."""
    context = _context(ctx)
    if context is None or not context.oauth_reauthorizable:
        return
    auth.adopt_published_credentials(context)
    if context.unauthorized_message is None:
        return
    if await _adopt_saved_token(context):
        return
    # Not the degraded message itself: it ends in the CLI instructions, which the offer
    # repeats. It's still the answer when no offer can be made.
    await _offer_consent(
        ctx,
        f"No usable OAuth token at {auth.TOKEN_PATH!r}.",
        unavailable_message=context.unauthorized_message,
    )


# Long enough for a tool's own error or a partial result's summary, short enough not
# to bury the offer.
_OUTCOME_MAX_CHARS = 1500


def describe_outcome(result: Any = None, error: BaseException | None = None) -> str:
    """What the tool reported before its result was replaced by the offer, for the
    model: a multi-request tool may have done part of its work before the refresh
    failed, and isn't re-run (PR #925 QA round 1)."""
    if error is not None:
        if isinstance(error, RefreshError):
            return ""  # the reason already says it
        text = exception_text(error)
    else:
        try:
            text = json.dumps(result, default=str)
        except (TypeError, ValueError):
            text = repr(result)
    if len(text) > _OUTCOME_MAX_CHARS:
        text = text[:_OUTCOME_MAX_CHARS] + "…"
    return (
        " The call may have partly completed before the token was rejected; the tool "
        f"reported: {text}"
    )


async def after_refresh_failure(ctx: Any, error: RefreshError, outcome: str = "") -> None:
    """After a call whose token refresh Google rejected. Raises, telling the caller to
    retry with a token adopted meanwhile or offering consent, on an OAuth connection.
    Returns without raising for any other context, which keeps the old handling."""
    context = _context(ctx)
    if context is None or not context.oauth_reauthorizable or context.auth_method != "oauth":
        return
    reason = f"Google rejected the OAuth token refresh: {exception_text(error).rstrip('.')}."
    if auth.adopt_published_credentials(context) or await _adopt_saved_token(context):
        raise ReauthorizationRequired(
            f"{reason} The server has since loaded a newer OAuth token; retry the call.{outcome}"
        )
    await _offer_consent(ctx, reason, outcome=outcome)
