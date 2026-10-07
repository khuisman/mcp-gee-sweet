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

from typing import Any, NoReturn

from google.auth.exceptions import RefreshError
from mcp import UrlElicitationRequiredError
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ElicitRequestURLParams

from . import auth
from .auth import SpreadsheetContext


class ReauthorizationRequired(ToolError):
    """A ToolError asking the user to re-authorize; logged as a 401."""


def _lifespan(ctx: Any) -> SpreadsheetContext | None:
    context = getattr(getattr(ctx, "request_context", None), "lifespan_context", None)
    return context if isinstance(context, SpreadsheetContext) else None


def _session(ctx: Any) -> Any:
    return getattr(getattr(ctx, "request_context", None), "session", None)


def _supports_url_elicitation(ctx: Any) -> bool:
    caps = getattr(_session(ctx), "client_capabilities", None)
    return getattr(getattr(caps, "elicitation", None), "url", None) is not None


def refresh_error_text(error: RefreshError) -> str:
    # RefreshError(message, response_dict) stringifies as the tuple's repr.
    if error.args and isinstance(error.args[0], str):
        return error.args[0]
    return str(error) or type(error).__name__


def _cli_alternative() -> str:
    # Unlike reauthorize_instructions(), no restart: the next call reloads TOKEN_PATH.
    return (
        "Or run `mcp-gee-sweet auth` in a terminal (`uvx mcp-gee-sweet auth` for a PyPI "
        f"install) with the same TOKEN_PATH ({auth.TOKEN_PATH!r}), CREDENTIALS_PATH "
        f"({auth.CREDENTIALS_PATH!r}) and ENABLED_TOOLS as this server, then retry the "
        "call: the server picks up the new token without a restart."
    )


async def _adopt_saved_token(context: SpreadsheetContext) -> bool:
    """Adopt the token at TOKEN_PATH if it's usable and isn't the one that failed."""
    creds = await auth.load_saved_token()
    if creds is None:
        return False
    failed = context.credentials
    if failed is not None and getattr(creds, "refresh_token", None) == getattr(
        failed, "refresh_token", None
    ):
        # The same grant the connection already has: it can't be the fix.
        return False
    auth.publish_oauth_credentials(creds)
    auth.adopt_published_credentials(context)
    return True


async def _offer_consent(ctx: Any, reason: str, unavailable_message: str | None = None) -> NoReturn:
    """Raise with the consent URL for the user: a URL-mode elicitation when the client
    supports one, else a ToolError carrying the URL. If the consent can't start, raise
    `unavailable_message` (default: `reason` plus the CLI instructions) and why."""
    try:
        attempt = await auth.start_user_consent()
    except Exception as e:
        fallback = unavailable_message or f"{reason} {auth.reauthorize_instructions()}"
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
            f"call in a few seconds to get its link. {_cli_alternative()}"
        )
    timeout = auth._CONSENT_TIMEOUT_SECONDS
    if _supports_url_elicitation(ctx):
        attempt.notify_on_completion(_session(ctx))
        raise UrlElicitationRequiredError(
            [
                ElicitRequestURLParams(
                    message=(
                        f"{reason} Open this Google sign-in page to re-authorize "
                        f"mcp-gee-sweet (the link works for {timeout}s), then retry."
                    ),
                    url=url,
                    elicitation_id=attempt.elicitation_id,
                )
            ],
            f"{reason} Google re-authorization required: approve access at {url} "
            f"within {timeout}s, then retry the call.",
        )
    raise ReauthorizationRequired(
        f"{reason} To re-authorize, open this link in a browser and approve access "
        f"within {timeout}s, then retry the call: {url} {_cli_alternative()}"
    )


async def before_call(ctx: Any) -> None:
    """Before a tool body runs. Adopts a token another call already got. On a connection
    degraded because OAuth needed consent, adopts a saved token or raises with a consent
    offer. Does nothing for any other context (service account, ADC, a test's mock)."""
    context = _lifespan(ctx)
    if context is None or not context.oauth_reauthorizable:
        return
    auth.adopt_published_credentials(context)
    if context.unauthorized_message is None:
        return
    if await _adopt_saved_token(context):
        return
    # Not the degraded message itself: it ends in the CLI-and-restart instructions,
    # which the offer replaces. It's still the answer when no offer can be made.
    await _offer_consent(
        ctx,
        f"No usable OAuth token at {auth.TOKEN_PATH!r}.",
        unavailable_message=context.unauthorized_message,
    )


async def after_refresh_failure(ctx: Any, error: RefreshError) -> None:
    """After a call whose token refresh Google rejected. Raises, telling the caller to
    retry with a token adopted meanwhile or offering consent, on an OAuth connection.
    Returns without raising for any other context, which keeps the old handling."""
    context = _lifespan(ctx)
    if context is None or not context.oauth_reauthorizable or context.auth_method != "oauth":
        return
    reason = f"Google rejected the OAuth token refresh: {refresh_error_text(error).rstrip('.')}."
    if auth.adopt_published_credentials(context) or await _adopt_saved_token(context):
        raise ReauthorizationRequired(
            f"{reason} The server has since loaded a newer OAuth token; retry the call."
        )
    await _offer_consent(ctx, reason)
