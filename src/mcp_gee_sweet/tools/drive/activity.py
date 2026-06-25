import logging
from typing import Any

from googleapiclient.errors import HttpError
from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

logger = logging.getLogger(__name__)

# Maps Drive Activity API primaryActionDetail keys to human-readable action types.
_ACTION_TYPES = {
    "edit": "edit",
    "create": "create",
    "move": "move",
    "rename": "rename",
    "delete": "delete",
    "restore": "restore",
    "permissionChange": "permission_change",
    "comment": "comment",
    "settingsChange": "settings_change",
    "dlpChange": "dlp_change",
    "reference": "reference",
    "systemEvent": "system_event",
}


def _parse_actor(actor: dict) -> dict:
    if "user" in actor:
        user = actor["user"]
        if "knownUser" in user:
            known = user["knownUser"]
            return {
                "type": "user",
                "person_name": known.get("personName"),
                "is_current_user": known.get("isCurrentUser", False),
            }
        return {"type": "unknown_user"}
    if "system" in actor:
        return {"type": "system", "event": actor["system"].get("type")}
    if "administrator" in actor:
        return {"type": "administrator"}
    if "anonymous" in actor:
        return {"type": "anonymous"}
    return {"type": "unknown"}


def _parse_action(primary: dict) -> str:
    for key, label in _ACTION_TYPES.items():
        if key in primary:
            return label
    return "unknown"


def register(tool):
    @tool(annotations=ToolAnnotations(title="List File Activity", readOnlyHint=True))
    def list_file_activity(
        file_id: str,
        page_size: int = 50,
        page_token: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Return the activity timeline for a Google Drive file.

        Uses the Drive Activity API (driveactivity/v2) to fetch a chronological list
        of edits, permission changes, comments, and other events for the given file.

        Each activity entry reports:
        - timestamp: ISO 8601 UTC time of the activity
        - action: type of action (edit, create, move, rename, delete, restore,
                  permission_change, comment, settings_change, system_event, …)
        - actors: list of who performed the action; each actor has a type field
                  ("user", "system", "administrator", "anonymous") plus a person_name
                  for known users (a People API resource name, not an email address)

        Args:
            file_id: Google Drive file ID to query.
            page_size: Maximum number of activities to return (1–100, default 50).
            page_token: Continuation token from a previous response for pagination.

        Returns:
            Dictionary with:
            - file_id: echoed back for reference
            - activities: list of activity entries (timestamp, action, actors)
            - next_page_token: present when more results are available

        Note:
            The Drive Activity API requires the drive.activity.readonly OAuth scope.
            Service accounts must be granted file access to see its activity.
            person_name values (e.g. "people/123456") are opaque identifiers; the
            People API is required to resolve them to display names or email addresses.
        """
        lc = ctx.request_context.lifespan_context
        activity_service = lc.activity_service

        body: dict[str, Any] = {
            "itemName": f"items/{file_id}",
            "pageSize": max(1, min(page_size, 100)),
        }
        if page_token:
            body["pageToken"] = page_token

        try:
            response = activity_service.activity().query(body=body).execute()
        except HttpError as e:
            logger.debug("Drive Activity API error for file %s: %s", file_id, e)
            return {"error": str(e)}

        activities = []
        for item in response.get("activities", []):
            primary = item.get("primaryActionDetail", {})
            action = _parse_action(primary)
            actors = [_parse_actor(a) for a in item.get("actors", [])]
            timestamp = item.get("timestamp") or item.get("timeRange", {}).get("endTime")
            activities.append({"timestamp": timestamp, "action": action, "actors": actors})

        result: dict[str, Any] = {"file_id": file_id, "activities": activities}
        if npt := response.get("nextPageToken"):
            result["next_page_token"] = npt

        logger.debug("list_file_activity: %d activities for file %s", len(activities), file_id)
        return result
