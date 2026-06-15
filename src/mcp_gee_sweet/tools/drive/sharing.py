import json
import logging
from typing import Any

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

logger = logging.getLogger(__name__)


def register(tool):
    @tool(annotations=ToolAnnotations(title="Share Spreadsheet", destructiveHint=True))
    def share_spreadsheet(
        spreadsheet_id: str,
        recipients: list[dict[str, str]],
        send_notification: bool = True,
        ctx: Context = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Share a Google Spreadsheet with multiple users via email, assigning specific roles.

        Args:
            spreadsheet_id: The ID of the spreadsheet to share.
            recipients: A list of dictionaries, each containing 'email_address' and 'role'.
                        The role should be one of: 'reader', 'commenter', 'writer'.
                        Example: [
                            {'email_address': 'user1@example.com', 'role': 'writer'},
                            {'email_address': 'user2@example.com', 'role': 'reader'}
                        ]
            send_notification: Whether to send a notification email to the users. Defaults to True.

        Returns:
            A dictionary containing lists of 'successes' and 'failures'.
            Each item in the lists includes the email address and the outcome.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service
        successes = []
        failures = []

        for recipient in recipients:
            email_address = recipient.get("email_address")
            role = recipient.get("role", "writer")

            if not email_address:
                failures.append(
                    {"email_address": None, "error": "Missing email_address in recipient entry."}
                )
                continue

            if role not in ["reader", "commenter", "writer"]:
                failures.append(
                    {
                        "email_address": email_address,
                        "error": f"Invalid role '{role}'. Must be 'reader', 'commenter', or 'writer'.",
                    }
                )
                continue

            try:
                result = (
                    drive_service.permissions()
                    .create(
                        fileId=spreadsheet_id,
                        body={"type": "user", "role": role, "emailAddress": email_address},
                        sendNotificationEmail=send_notification,
                        fields="id",
                    )
                    .execute()
                )
                successes.append(
                    {"email_address": email_address, "role": role, "permissionId": result.get("id")}
                )
            except Exception as e:
                error_details = str(e)
                if hasattr(e, "content"):
                    try:
                        error_content = json.loads(e.content)
                        error_details = error_content.get("error", {}).get("message", error_details)
                    except json.JSONDecodeError:
                        pass
                failures.append(
                    {"email_address": email_address, "error": f"Failed to share: {error_details}"}
                )

        return {"successes": successes, "failures": failures}

    @tool(annotations=ToolAnnotations(title="List File Permissions", readOnlyHint=True))
    def list_permissions(file_id: str, ctx: Context = None) -> list[dict[str, Any]]:
        """
        List all permissions on a file or folder in Google Drive.

        Args:
            file_id: The Google Drive file or folder ID.

        Returns:
            List of permissions, each with id, type, role, email_address (for user/group),
            domain (for domain permissions), display_name, expiration_time, and deleted flag.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        result = (
            drive_service.permissions()
            .list(
                fileId=file_id,
                fields="permissions(id,type,role,emailAddress,displayName,domain,expirationTime,deleted)",
                supportsAllDrives=True,
            )
            .execute()
        )

        return [
            {
                "id": p["id"],
                "type": p.get("type"),
                "role": p.get("role"),
                "email_address": p.get("emailAddress"),
                "display_name": p.get("displayName"),
                "domain": p.get("domain"),
                "expiration_time": p.get("expirationTime"),
                "deleted": p.get("deleted", False),
            }
            for p in result.get("permissions", [])
        ]

    @tool(annotations=ToolAnnotations(title="Update Permission", destructiveHint=True))
    def update_permission(
        file_id: str,
        permission_id: str,
        role: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Change the role on an existing permission for a file or folder.

        Args:
            file_id: The Google Drive file or folder ID.
            permission_id: The permission ID to update (from list_permissions).
            role: New role. One of: 'reader', 'commenter', 'writer'.

        Returns:
            Updated permissionId and role.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        _VALID_ROLES = ("reader", "commenter", "writer")
        if role not in _VALID_ROLES:
            return {"error": f"Invalid role '{role}'. Must be one of: {', '.join(_VALID_ROLES)}"}

        result = (
            drive_service.permissions()
            .update(
                fileId=file_id,
                permissionId=permission_id,
                body={"role": role},
                supportsAllDrives=True,
                fields="id,role",
            )
            .execute()
        )

        logger.debug("Updated permission %s on %s → %s", permission_id, file_id, role)
        return {"permissionId": result.get("id"), "role": result.get("role")}

    @tool(annotations=ToolAnnotations(title="Remove Permission", destructiveHint=True))
    def remove_permission(file_id: str, permission_id: str, ctx: Context = None) -> dict[str, Any]:
        """
        Revoke a permission on a file or folder.

        Args:
            file_id: The Google Drive file or folder ID.
            permission_id: The permission ID to remove (from list_permissions).

        Returns:
            Confirmation with fileId, permissionId, and action taken.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        drive_service.permissions().delete(
            fileId=file_id,
            permissionId=permission_id,
            supportsAllDrives=True,
        ).execute()

        logger.debug("Removed permission %s from %s", permission_id, file_id)
        return {"fileId": file_id, "permissionId": permission_id, "action": "removed"}

    @tool(annotations=ToolAnnotations(title="Share File", destructiveHint=True))
    def share_file(
        file_id: str,
        permissions: list[dict[str, str]],
        send_notification: bool = True,
        ctx: Context = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Share any file or folder with one or more principals.

        Args:
            file_id: The Google Drive file or folder ID.
            permissions: List of permission entries. Each must have 'type' and 'role'.
                         Additional fields depend on type:
                           type='user' or 'group' — requires 'email_address'
                           type='domain'          — requires 'domain'
                           type='anyone'          — no extra fields

                         type values: 'user', 'group', 'domain', 'anyone'
                         role values: 'reader', 'commenter', 'writer'

                         Example:
                         [
                             {'type': 'user', 'email_address': 'alice@example.com', 'role': 'writer'},
                             {'type': 'domain', 'domain': 'example.com', 'role': 'reader'},
                             {'type': 'anyone', 'role': 'reader'},
                         ]
            send_notification: Send notification email to user/group recipients (default True).

        Returns:
            Dictionary with 'successes' and 'failures' lists.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        _VALID_TYPES = ("user", "group", "domain", "anyone")
        _VALID_ROLES = ("reader", "commenter", "writer")

        successes = []
        failures = []

        for perm in permissions:
            perm_type = perm.get("type")
            role = perm.get("role", "reader")
            email_address = perm.get("email_address")
            domain = perm.get("domain")

            if perm_type not in _VALID_TYPES:
                failures.append(
                    {
                        "entry": perm,
                        "error": f"Invalid type '{perm_type}'. Must be one of: {', '.join(_VALID_TYPES)}",
                    }
                )
                continue

            if role not in _VALID_ROLES:
                failures.append(
                    {
                        "entry": perm,
                        "error": f"Invalid role '{role}'. Must be one of: {', '.join(_VALID_ROLES)}",
                    }
                )
                continue

            if perm_type in ("user", "group") and not email_address:
                failures.append(
                    {"entry": perm, "error": f"'email_address' required for type='{perm_type}'"}
                )
                continue

            if perm_type == "domain" and not domain:
                failures.append({"entry": perm, "error": "'domain' required for type='domain'"})
                continue

            body: dict[str, str] = {"type": perm_type, "role": role}
            if perm_type in ("user", "group"):
                body["emailAddress"] = email_address
            elif perm_type == "domain":
                body["domain"] = domain

            try:
                result = (
                    drive_service.permissions()
                    .create(
                        fileId=file_id,
                        body=body,
                        sendNotificationEmail=send_notification and perm_type in ("user", "group"),
                        supportsAllDrives=True,
                        fields="id",
                    )
                    .execute()
                )
                entry: dict[str, Any] = {
                    "type": perm_type,
                    "role": role,
                    "permissionId": result.get("id"),
                }
                if email_address:
                    entry["email_address"] = email_address
                if domain:
                    entry["domain"] = domain
                successes.append(entry)
            except Exception as e:
                error_details = str(e)
                if hasattr(e, "content"):
                    try:
                        error_content = json.loads(e.content)
                        error_details = error_content.get("error", {}).get("message", error_details)
                    except json.JSONDecodeError:
                        pass
                failures.append({"entry": perm, "error": f"Failed to share: {error_details}"})

        return {"successes": successes, "failures": failures}
