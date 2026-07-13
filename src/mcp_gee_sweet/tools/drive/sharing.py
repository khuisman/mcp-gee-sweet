import asyncio
import json
import logging
from typing import Any

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

from ...auth import execute_in_thread

logger = logging.getLogger(__name__)


def register(tool):
    @tool(annotations=ToolAnnotations(title="Share Spreadsheet", destructiveHint=True))
    async def share_spreadsheet(
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

        async def _share_one(recipient: dict[str, str]) -> dict[str, Any]:
            # The whole body (including the recipient.get() calls) runs inside this
            # try/except — a malformed entry (e.g. not a dict) raises from those very
            # first attribute accesses, before reaching any of the validation-failure
            # returns below. Catching it here too, with `entry` echoing the raw input,
            # keeps that failure attributable instead of collapsing to an anonymous
            # email_address=None result indistinguishable from any other bad entry.
            email_address = None
            try:
                email_address = recipient.get("email_address")
                role = recipient.get("role", "writer")

                if not email_address:
                    return {
                        "_kind": "failure",
                        "email_address": None,
                        "entry": recipient,
                        "error": "Missing email_address in recipient entry.",
                    }

                if role not in ["reader", "commenter", "writer"]:
                    return {
                        "_kind": "failure",
                        "email_address": email_address,
                        "entry": recipient,
                        "error": f"Invalid role '{role}'. Must be 'reader', 'commenter', or 'writer'.",
                    }

                result = await execute_in_thread(
                    drive_service.permissions()
                    .create(
                        fileId=spreadsheet_id,
                        body={"type": "user", "role": role, "emailAddress": email_address},
                        sendNotificationEmail=send_notification,
                        fields="id",
                    )
                    .execute,
                    drive_service,
                )
                return {
                    "_kind": "success",
                    "email_address": email_address,
                    "role": role,
                    "permissionId": result.get("id"),
                }
            except Exception as e:
                error_details = str(e)
                if hasattr(e, "content"):
                    try:
                        error_content = json.loads(e.content)
                        error_details = error_content.get("error", {}).get("message", error_details)
                    except json.JSONDecodeError:
                        pass
                return {
                    "_kind": "failure",
                    "email_address": email_address,
                    "entry": recipient,
                    "error": f"Failed to share: {error_details}",
                }

        # return_exceptions=True: _share_one already catches its own errors, but this
        # also lets every in-flight share finish before surfacing an unexpected
        # exception, instead of orphaning in-flight tasks. Relative order within
        # successes/failures now reflects completion order, not input order — each
        # entry still carries its own email_address so identity isn't lost.
        raw = await asyncio.gather(*(_share_one(r) for r in recipients), return_exceptions=True)
        successes = []
        failures = []
        for r in raw:
            if isinstance(r, BaseException):
                failures.append({"email_address": None, "entry": None, "error": str(r)})
                continue
            kind = r.pop("_kind")
            (successes if kind == "success" else failures).append(r)

        return {"successes": successes, "failures": failures}

    @tool(annotations=ToolAnnotations(title="List File Permissions", readOnlyHint=True))
    async def list_permissions(file_id: str, ctx: Context = None) -> list[dict[str, Any]]:
        """
        List all permissions on a file or folder in Google Drive.

        Args:
            file_id: The Google Drive file or folder ID.

        Returns:
            List of permissions, each with id, type, role, email_address (for user/group),
            domain (for domain permissions), display_name, expiration_time, and deleted flag.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        result = await execute_in_thread(
            drive_service.permissions()
            .list(
                fileId=file_id,
                fields="permissions(id,type,role,emailAddress,displayName,domain,expirationTime,deleted)",
                supportsAllDrives=True,
            )
            .execute,
            drive_service,
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
    async def update_permission(
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

        result = await execute_in_thread(
            drive_service.permissions()
            .update(
                fileId=file_id,
                permissionId=permission_id,
                body={"role": role},
                supportsAllDrives=True,
                fields="id,role",
            )
            .execute,
            drive_service,
        )

        logger.debug("Updated permission %s on %s → %s", permission_id, file_id, role)
        return {"permissionId": result.get("id"), "role": result.get("role")}

    @tool(annotations=ToolAnnotations(title="Remove Permission", destructiveHint=True))
    async def remove_permission(
        file_id: str, permission_id: str, ctx: Context = None
    ) -> dict[str, Any]:
        """
        Revoke a permission on a file or folder.

        Args:
            file_id: The Google Drive file or folder ID.
            permission_id: The permission ID to remove (from list_permissions).

        Returns:
            Confirmation with fileId, permissionId, and action taken.
        """
        drive_service = ctx.request_context.lifespan_context.drive_service

        await execute_in_thread(
            drive_service.permissions()
            .delete(
                fileId=file_id,
                permissionId=permission_id,
                supportsAllDrives=True,
            )
            .execute,
            drive_service,
        )

        logger.debug("Removed permission %s from %s", permission_id, file_id)
        return {"fileId": file_id, "permissionId": permission_id, "action": "removed"}

    @tool(annotations=ToolAnnotations(title="Share File", destructiveHint=True))
    async def share_file(
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

        async def _share_one(perm: dict[str, str]) -> dict[str, Any]:
            # Whole body runs inside this try/except — a malformed entry (e.g. not a
            # dict) raises from the perm.get() calls below, before any validation-
            # failure return is reached. Catching it here too keeps `entry` echoing
            # the raw input so the failure stays attributable to a specific item.
            try:
                perm_type = perm.get("type")
                role = perm.get("role", "reader")
                email_address = perm.get("email_address")
                domain = perm.get("domain")

                if perm_type not in _VALID_TYPES:
                    return {
                        "_kind": "failure",
                        "entry": perm,
                        "error": (
                            f"Invalid type '{perm_type}'. Must be one of: {', '.join(_VALID_TYPES)}"
                        ),
                    }

                if role not in _VALID_ROLES:
                    return {
                        "_kind": "failure",
                        "entry": perm,
                        "error": f"Invalid role '{role}'. Must be one of: {', '.join(_VALID_ROLES)}",
                    }

                if perm_type in ("user", "group") and not email_address:
                    return {
                        "_kind": "failure",
                        "entry": perm,
                        "error": f"'email_address' required for type='{perm_type}'",
                    }

                if perm_type == "domain" and not domain:
                    return {
                        "_kind": "failure",
                        "entry": perm,
                        "error": "'domain' required for type='domain'",
                    }

                body: dict[str, str] = {"type": perm_type, "role": role}
                if perm_type in ("user", "group"):
                    body["emailAddress"] = email_address
                elif perm_type == "domain":
                    body["domain"] = domain

                result = await execute_in_thread(
                    drive_service.permissions()
                    .create(
                        fileId=file_id,
                        body=body,
                        sendNotificationEmail=send_notification and perm_type in ("user", "group"),
                        supportsAllDrives=True,
                        fields="id",
                    )
                    .execute,
                    drive_service,
                )
                entry: dict[str, Any] = {
                    "_kind": "success",
                    "type": perm_type,
                    "role": role,
                    "permissionId": result.get("id"),
                }
                if email_address:
                    entry["email_address"] = email_address
                if domain:
                    entry["domain"] = domain
                return entry
            except Exception as e:
                error_details = str(e)
                if hasattr(e, "content"):
                    try:
                        error_content = json.loads(e.content)
                        error_details = error_content.get("error", {}).get("message", error_details)
                    except json.JSONDecodeError:
                        pass
                return {
                    "_kind": "failure",
                    "entry": perm,
                    "error": f"Failed to share: {error_details}",
                }

        # Same return_exceptions=True + tagged-result pattern as share_spreadsheet.
        raw = await asyncio.gather(*(_share_one(p) for p in permissions), return_exceptions=True)
        successes = []
        failures = []
        for r in raw:
            if isinstance(r, BaseException):
                failures.append({"entry": None, "error": str(r)})
                continue
            kind = r.pop("_kind")
            (successes if kind == "success" else failures).append(r)

        return {"successes": successes, "failures": failures}
