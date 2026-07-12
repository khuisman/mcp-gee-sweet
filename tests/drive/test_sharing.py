"""Tests for tools/drive/sharing.py (share_spreadsheet, share_file, list_permissions, etc.)."""

import json
from unittest.mock import MagicMock

from googleapiclient.errors import HttpError

from mcp_gee_sweet.tools.drive import sharing as sharing_module


def _make_tool_registry():
    captured = {}

    def tool(annotations=None):
        def decorator(func):
            captured[func.__name__] = func
            return func

        return decorator

    return tool, captured


def _make_ctx(**services):
    ctx = MagicMock()
    lc = ctx.request_context.lifespan_context
    for k, v in services.items():
        setattr(lc, k, v)
    return ctx


_sharing_tool, _sharing_tools = _make_tool_registry()
sharing_module.register(_sharing_tool)


def _http_error(status: int, message: str = "error") -> HttpError:
    resp = MagicMock()
    resp.status = status
    content = json.dumps({"error": {"message": message}}).encode()
    return HttpError(resp=resp, content=content)


class TestShareSpreadsheet:
    """share_spreadsheet validates roles and emails client-side before any API call."""

    def _drive_svc(self, perm_id="perm-123"):
        mock = MagicMock()
        mock.permissions.return_value.create.return_value.execute.return_value = {"id": perm_id}
        return mock

    async def test_invalid_role_routes_to_failures_without_api_call(self):
        """Unrecognized role is rejected client-side; permissions().create() must not fire."""
        drive = self._drive_svc()
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["share_spreadsheet"](
            spreadsheet_id="ss1",
            recipients=[{"email_address": "bob@example.com", "role": "owner"}],
            ctx=ctx,
        )
        assert len(result["failures"]) == 1
        assert len(result["successes"]) == 0
        assert "owner" in result["failures"][0]["error"]
        drive.permissions.return_value.create.assert_not_called()

    async def test_missing_email_address_routes_to_failures(self):
        """A recipient dict with no 'email_address' key ends up in failures with email_address=None."""
        drive = self._drive_svc()
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["share_spreadsheet"](
            spreadsheet_id="ss1",
            recipients=[{"role": "reader"}],
            ctx=ctx,
        )
        assert len(result["failures"]) == 1
        assert result["failures"][0]["email_address"] is None
        drive.permissions.return_value.create.assert_not_called()

    async def test_success_returns_permission_id_from_api(self):
        """Successful share must include the permissionId returned by the Drive API."""
        drive = self._drive_svc(perm_id="perm-abc")
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["share_spreadsheet"](
            spreadsheet_id="ss1",
            recipients=[{"email_address": "alice@example.com", "role": "writer"}],
            ctx=ctx,
        )
        assert len(result["successes"]) == 1
        assert result["successes"][0]["permissionId"] == "perm-abc"
        assert result["successes"][0]["role"] == "writer"

    async def test_api_http_error_is_caught_and_routed_to_failures(self):
        """An HttpError from Drive must be caught; the recipient appears in failures."""
        drive = MagicMock()
        drive.permissions.return_value.create.return_value.execute.side_effect = _http_error(
            403, "The caller does not have permission"
        )
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["share_spreadsheet"](
            spreadsheet_id="ss1",
            recipients=[{"email_address": "user@example.com", "role": "reader"}],
            ctx=ctx,
        )
        assert len(result["failures"]) == 1
        assert len(result["successes"]) == 0
        assert "Failed to share" in result["failures"][0]["error"]

    async def test_mixed_batch_produces_independent_successes_and_failures(self):
        """Valid recipient succeeds and bad-role recipient fails independently."""
        drive = self._drive_svc()
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["share_spreadsheet"](
            spreadsheet_id="ss1",
            recipients=[
                {"email_address": "good@example.com", "role": "reader"},
                {"email_address": "bad@example.com", "role": "superuser"},
            ],
            ctx=ctx,
        )
        assert len(result["successes"]) == 1
        assert len(result["failures"]) == 1
        assert result["successes"][0]["email_address"] == "good@example.com"
        assert result["failures"][0]["email_address"] == "bad@example.com"


class TestListPermissions:
    """list_permissions maps Drive API camelCase field names to snake_case output."""

    async def test_maps_camel_case_api_fields_to_snake_case_output(self):
        """emailAddress → email_address and displayName → display_name in output."""
        drive = MagicMock()
        drive.permissions.return_value.list.return_value.execute.return_value = {
            "permissions": [
                {
                    "id": "perm-1",
                    "type": "user",
                    "role": "writer",
                    "emailAddress": "alice@example.com",
                    "displayName": "Alice Example",
                    "deleted": False,
                }
            ]
        }
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["list_permissions"](file_id="file-1", ctx=ctx)
        assert len(result) == 1
        perm = result[0]
        assert perm["email_address"] == "alice@example.com"
        assert perm["display_name"] == "Alice Example"
        assert perm["id"] == "perm-1"
        assert perm["role"] == "writer"

    async def test_empty_permissions_returns_empty_list(self):
        """A file with no permissions must produce an empty list, not an error."""
        drive = MagicMock()
        drive.permissions.return_value.list.return_value.execute.return_value = {"permissions": []}
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["list_permissions"](file_id="file-2", ctx=ctx)
        assert result == []


class TestUpdatePermission:
    """update_permission validates role client-side before touching the API."""

    async def test_invalid_role_returns_error_dict_without_api_call(self):
        """An unrecognized role returns {"error": ...} and must not call permissions().update()."""
        drive = MagicMock()
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["update_permission"](
            file_id="file-1",
            permission_id="perm-1",
            role="superadmin",
            ctx=ctx,
        )
        assert "error" in result
        assert "superadmin" in result["error"]
        drive.permissions.return_value.update.assert_not_called()

    async def test_success_returns_permission_id_and_new_role(self):
        """Successful update returns the permissionId and new role from the API response."""
        drive = MagicMock()
        drive.permissions.return_value.update.return_value.execute.return_value = {
            "id": "perm-1",
            "role": "reader",
        }
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["update_permission"](
            file_id="file-1",
            permission_id="perm-1",
            role="reader",
            ctx=ctx,
        )
        assert result == {"permissionId": "perm-1", "role": "reader"}


class TestRemovePermission:
    """remove_permission calls delete and returns a structured confirmation dict."""

    async def test_returns_confirmation_with_correct_fields(self):
        """Result must contain fileId, permissionId, and action='removed'."""
        drive = MagicMock()
        drive.permissions.return_value.delete.return_value.execute.return_value = None
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["remove_permission"](
            file_id="file-1", permission_id="perm-99", ctx=ctx
        )
        assert result == {"fileId": "file-1", "permissionId": "perm-99", "action": "removed"}
        drive.permissions.return_value.delete.assert_called_once()


class TestShareFile:
    """share_file handles the richer type/domain/anyone permission model."""

    def _drive_svc(self, perm_id="perm-xyz"):
        mock = MagicMock()
        mock.permissions.return_value.create.return_value.execute.return_value = {"id": perm_id}
        return mock

    async def test_anyone_type_suppresses_notification_even_when_caller_passes_true(self):
        """type='anyone' must pass sendNotificationEmail=False regardless of send_notification."""
        drive = self._drive_svc()
        ctx = _make_ctx(drive_service=drive)
        await _sharing_tools["share_file"](
            file_id="file-1",
            permissions=[{"type": "anyone", "role": "reader"}],
            send_notification=True,
            ctx=ctx,
        )
        create_call = drive.permissions.return_value.create.call_args
        assert create_call.kwargs["sendNotificationEmail"] is False

    async def test_domain_type_without_domain_field_routes_to_failures(self):
        """A domain entry missing the 'domain' key must appear in failures without an API call."""
        drive = self._drive_svc()
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["share_file"](
            file_id="file-1",
            permissions=[{"type": "domain", "role": "reader"}],
            ctx=ctx,
        )
        assert len(result["failures"]) == 1
        assert "'domain' required" in result["failures"][0]["error"]
        drive.permissions.return_value.create.assert_not_called()

    async def test_user_type_without_email_address_routes_to_failures(self):
        """type='user' with no email_address must appear in failures without an API call."""
        drive = self._drive_svc()
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["share_file"](
            file_id="file-1",
            permissions=[{"type": "user", "role": "reader"}],
            ctx=ctx,
        )
        assert len(result["failures"]) == 1
        assert "email_address" in result["failures"][0]["error"]

    async def test_invalid_permission_type_routes_to_failures(self):
        """An unrecognized type must be caught client-side without calling the API."""
        drive = self._drive_svc()
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["share_file"](
            file_id="file-1",
            permissions=[{"type": "org", "role": "reader"}],
            ctx=ctx,
        )
        assert len(result["failures"]) == 1
        assert "org" in result["failures"][0]["error"]

    async def test_domain_permission_includes_domain_in_api_body(self):
        """The domain value must be forwarded in the body sent to the Drive API."""
        drive = self._drive_svc()
        ctx = _make_ctx(drive_service=drive)
        await _sharing_tools["share_file"](
            file_id="file-1",
            permissions=[{"type": "domain", "domain": "example.com", "role": "reader"}],
            ctx=ctx,
        )
        create_call = drive.permissions.return_value.create.call_args
        assert create_call.kwargs["body"]["domain"] == "example.com"
