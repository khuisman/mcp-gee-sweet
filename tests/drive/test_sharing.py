"""Tests for tools/drive/sharing.py (share_spreadsheet, share_file, list_permissions, etc.)."""

import inspect
import json
from typing import Literal, get_args
from unittest.mock import AsyncMock, MagicMock

import pytest
from googleapiclient.errors import HttpError

from mcp_gee_sweet.tools.drive import sharing as sharing_module


def _make_tool_registry():
    captured = {}

    def tool(annotations=None, local_only=False, **_):
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


def _http_error_with_raw_content(status: int, content: bytes) -> HttpError:
    resp = MagicMock()
    resp.status = status
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

    async def test_http_error_with_non_dict_json_content_does_not_crash(self):
        """QA review, PR #758, finding #3: json.loads(e.content) can return valid
        JSON that isn't a dict (e.g. `null` or a JSON array) — the old
        `except json.JSONDecodeError` didn't catch the AttributeError that
        `.get()` then raises on that non-dict value, so the exception escaped
        _share_one entirely and completed[0]/report_progress were skipped for
        that item."""
        drive = MagicMock()
        drive.permissions.return_value.create.return_value.execute.side_effect = (
            _http_error_with_raw_content(500, b"null")
        )
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["share_spreadsheet"](
            spreadsheet_id="ss1",
            recipients=[{"email_address": "user@example.com", "role": "reader"}],
            ctx=ctx,
        )
        assert len(result["failures"]) == 1
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

    async def test_malformed_non_dict_entry_stays_attributable(self):
        """A non-dict recipient raises from .get() before any validation return —
        the failure must still echo the raw entry, not collapse to an anonymous
        email_address=None result indistinguishable from other bad entries."""
        drive = self._drive_svc()
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["share_spreadsheet"](
            spreadsheet_id="ss1",
            recipients=[
                {"email_address": "good@example.com", "role": "reader"},
                "not-a-dict",
                ["also", "not", "a", "dict"],
            ],
            ctx=ctx,
        )
        assert len(result["successes"]) == 1
        assert len(result["failures"]) == 2
        entries = [f["entry"] for f in result["failures"]]
        assert "not-a-dict" in entries
        assert ["also", "not", "a", "dict"] in entries

    async def test_create_call_sets_supports_all_drives(self):
        """The permissions().create() call must pass supportsAllDrives=True, or
        sharing fails with 'File not found' on any Shared Drive item — every other
        permission-mutating call in this module already sets it (issue #687)."""
        drive = self._drive_svc()
        ctx = _make_ctx(drive_service=drive)
        await _sharing_tools["share_spreadsheet"](
            spreadsheet_id="ss1",
            recipients=[{"email_address": "alice@example.com", "role": "writer"}],
            ctx=ctx,
        )
        _, kwargs = drive.permissions.return_value.create.call_args
        assert kwargs["supportsAllDrives"] is True

    async def test_reports_progress_per_recipient(self):
        """#355: extends #316/#319's per-item ctx.report_progress pattern to
        share_spreadsheet's concurrent shares."""
        drive = self._drive_svc()
        ctx = _make_ctx(drive_service=drive)
        ctx.report_progress = AsyncMock()
        await _sharing_tools["share_spreadsheet"](
            spreadsheet_id="ss1",
            recipients=[
                {"email_address": "alice@example.com", "role": "writer"},
                {"email_address": "bob@example.com", "role": "reader"},
            ],
            ctx=ctx,
        )
        assert ctx.report_progress.await_count == 2
        completed_values = sorted(c.args[0] for c in ctx.report_progress.await_args_list)
        assert completed_values == [1, 2]
        for c in ctx.report_progress.await_args_list:
            assert c.args[1] == 2  # total recipients
            assert ": success" in c.args[2]

    async def test_report_progress_failure_does_not_demote_a_successful_share(self):
        """PR #351's review established this guard for download_folder/sync_folder:
        a broken notification channel must not turn an already-successful item into
        a failure. #355 extends the same pattern here."""
        drive = self._drive_svc(perm_id="perm-xyz")
        ctx = _make_ctx(drive_service=drive)
        ctx.report_progress = AsyncMock(side_effect=RuntimeError("connection dropped"))
        result = await _sharing_tools["share_spreadsheet"](
            spreadsheet_id="ss1",
            recipients=[{"email_address": "alice@example.com", "role": "writer"}],
            ctx=ctx,
        )
        assert len(result["successes"]) == 1
        assert result["successes"][0]["permissionId"] == "perm-xyz"


class TestShareSpreadsheetDeprecation:
    """#665: share_spreadsheet stays callable for one release, its description
    opening with the share_file call that replaces it."""

    def test_deprecated_with_share_file_as_replacement(self):
        from mcp_gee_sweet.deprecation import tool_deprecation

        func = _sharing_tools["share_spreadsheet"]
        deprecation = tool_deprecation(func)
        assert deprecation is not None
        assert deprecation.removed_in == "the next feature release"
        assert func.__doc__.startswith("Deprecated: use `share_file`")

    def test_note_names_the_role_default_that_differs(self):
        # share_file defaults a missing `role` to reader, so following the note for
        # a recipient that omits it must not quietly share read-only what this tool
        # would have shared as writer.
        note = _sharing_tools["share_spreadsheet"].__doc__.split("\n\n", 1)[0]
        assert "'type': 'user'" in note
        assert "`'role': 'writer'` explicitly" in note

    @pytest.mark.parametrize("tool_name", ["share_file", "list_permissions"])
    def test_survivors_not_deprecated(self, tool_name):
        from mcp_gee_sweet.deprecation import tool_deprecation

        assert tool_deprecation(_sharing_tools[tool_name]) is None

    @pytest.mark.parametrize("send_notification", [True, False])
    async def test_share_file_as_the_note_says_sends_the_same_request(self, send_notification):
        """The note's share_file call creates the same permission, with the same
        notification setting, as the share_spreadsheet call it replaces."""
        calls = {}
        for tool_name, kwargs in (
            (
                "share_spreadsheet",
                {
                    "spreadsheet_id": "ss1",
                    "recipients": [{"email_address": "a@example.com", "role": "commenter"}],
                },
            ),
            (
                "share_file",
                {
                    "file_id": "ss1",
                    "permissions": [
                        {"type": "user", "email_address": "a@example.com", "role": "commenter"}
                    ],
                },
            ),
        ):
            drive = MagicMock()
            drive.permissions.return_value.create.return_value.execute.return_value = {"id": "p1"}
            ctx = _make_ctx(drive_service=drive)
            ctx.report_progress = AsyncMock()
            result = await _sharing_tools[tool_name](
                **kwargs, send_notification=send_notification, ctx=ctx
            )
            assert result["failures"] == []
            calls[tool_name] = drive.permissions.return_value.create.call_args.kwargs
        assert calls["share_file"] == calls["share_spreadsheet"]


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


class TestTransferOwnership:
    """transfer_ownership calls permissions().create() with transferOwnership=True."""

    async def test_success_returns_confirmation_with_permission_id(self):
        """Result must contain fileId, new_owner, and the permissionId from the API."""
        drive = MagicMock()
        drive.permissions.return_value.create.return_value.execute.return_value = {"id": "perm-42"}
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["transfer_ownership"](
            file_id="file-1", new_owner_email="new-owner@example.com", ctx=ctx
        )
        assert result == {
            "fileId": "file-1",
            "new_owner": "new-owner@example.com",
            "permissionId": "perm-42",
        }

    async def test_request_body_sets_owner_role_and_transfer_flag(self):
        """The permissions().create() call must set role='owner', transferOwnership=True,
        and the type/emailAddress body Drive requires for an ownership transfer."""
        drive = MagicMock()
        drive.permissions.return_value.create.return_value.execute.return_value = {"id": "p"}
        ctx = _make_ctx(drive_service=drive)
        await _sharing_tools["transfer_ownership"](
            file_id="file-1", new_owner_email="new-owner@example.com", ctx=ctx
        )
        _, kwargs = drive.permissions.return_value.create.call_args
        assert kwargs["fileId"] == "file-1"
        assert kwargs["transferOwnership"] is True
        assert kwargs["body"] == {
            "type": "user",
            "role": "owner",
            "emailAddress": "new-owner@example.com",
        }

    async def test_send_notification_false_rejected_without_api_call(self):
        """#1055: Drive 403s every ownership transfer whose notification is
        disabled ("sendNotificationEmail … must not be disabled for ownership
        transfers") before it even resolves the file, so the tool must refuse the
        value locally instead of sending a request that can never succeed.

        This test previously asserted the opposite — that False was forwarded to
        sendNotificationEmail — which pinned the request Drive rejects."""
        drive = MagicMock()
        drive.permissions.return_value.create.return_value.execute.return_value = {"id": "p"}
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["transfer_ownership"](
            file_id="file-1",
            new_owner_email="new-owner@example.com",
            send_notification=False,
            ctx=ctx,
        )
        assert "error" in result
        assert "send_notification=False" in result["error"]
        drive.permissions.return_value.create.assert_not_called()

    async def test_send_notification_true_is_forwarded(self):
        drive = MagicMock()
        drive.permissions.return_value.create.return_value.execute.return_value = {"id": "p"}
        ctx = _make_ctx(drive_service=drive)
        await _sharing_tools["transfer_ownership"](
            file_id="file-1",
            new_owner_email="new-owner@example.com",
            send_notification=True,
            ctx=ctx,
        )
        _, kwargs = drive.permissions.return_value.create.call_args
        assert kwargs["sendNotificationEmail"] is True

    async def test_default_still_notifies(self):
        """Omitting the parameter keeps the transfer working unchanged: the only
        value Drive accepts is the one the default already sends."""
        drive = MagicMock()
        drive.permissions.return_value.create.return_value.execute.return_value = {"id": "p"}
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["transfer_ownership"](
            file_id="file-1", new_owner_email="new-owner@example.com", ctx=ctx
        )
        assert result == {
            "fileId": "file-1",
            "new_owner": "new-owner@example.com",
            "permissionId": "p",
        }
        _, kwargs = drive.permissions.return_value.create.call_args
        assert kwargs["sendNotificationEmail"] is True

    async def test_guard_refuses_truthy_non_true_value(self):
        """#1181: the guard tests `is not True`, so a truthy value that isn't True
        (a caller that skipped schema validation) is refused, never forwarded.
        test_default_still_notifies covers the request's literal kwarg."""
        drive = MagicMock()
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["transfer_ownership"](
            file_id="file-1",
            new_owner_email="new-owner@example.com",
            send_notification=1,
            ctx=ctx,
        )
        assert "error" in result
        drive.permissions.return_value.create.assert_not_called()

    async def test_refusal_names_what_drive_requires(self):
        """#1181: Drive requires that the notification not be disabled; the
        message says so rather than naming the API parameter as required."""
        ctx = _make_ctx(drive_service=MagicMock())
        result = await _sharing_tools["transfer_ownership"](
            file_id="file-1",
            new_owner_email="new-owner@example.com",
            send_notification=False,
            ctx=ctx,
        )
        assert "notification email is disabled" in result["error"]
        assert "requires sendNotificationEmail" not in result["error"]

    def test_schema_allows_only_true(self):
        """#1181: the parameter's schema admits only True, so an agent can't pick
        False from the tool listing, and True or an omitted value still validates."""
        param = inspect.signature(_sharing_tools["transfer_ownership"]).parameters[
            "send_notification"
        ]
        assert param.annotation == Literal[True]
        assert get_args(param.annotation) == (True,)
        assert param.default is True

    async def test_shared_drive_item_returns_clear_error(self):
        """#1181: Drive 403s an owner transfer on a shared drive item with
        ownerOnTeamDriveItemNotSupported ("Owner role is invalid for shared drive
        items.", TC-D233/TC-D234). The tool says why and what to do instead."""
        drive = MagicMock()
        resp = MagicMock()
        resp.status = 403
        content = json.dumps(
            {
                "error": {
                    "code": 403,
                    "message": "Owner role is invalid for shared drive items.",
                    "errors": [
                        {
                            "reason": "ownerOnTeamDriveItemNotSupported",
                            "message": "Owner role is invalid for shared drive items.",
                        }
                    ],
                }
            }
        ).encode()
        drive.permissions.return_value.create.return_value.execute.side_effect = HttpError(
            resp=resp, content=content
        )
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["transfer_ownership"](
            file_id="file-1", new_owner_email="new-owner@example.com", ctx=ctx
        )
        assert set(result) == {"error"}
        assert "file-1" in result["error"]
        assert "shared drive" in result["error"]
        assert "Nothing was changed" in result["error"]
        assert "My Drive" in result["error"]

    async def test_consumer_accounts_return_clear_error(self):
        """#1181: between two gmail.com accounts Drive 403s with
        consentRequiredForOwnershipTransfer (checked live). The tool says the new
        owner has to accept and where the request is sent from."""
        drive = MagicMock()
        resp = MagicMock()
        resp.status = 403
        content = json.dumps(
            {
                "error": {
                    "code": 403,
                    "message": "Consent is required to transfer ownership of a file to another user.",
                    "errors": [{"reason": "consentRequiredForOwnershipTransfer"}],
                }
            }
        ).encode()
        drive.permissions.return_value.create.return_value.execute.side_effect = HttpError(
            resp=resp, content=content
        )
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["transfer_ownership"](
            file_id="file-1", new_owner_email="new-owner@gmail.com", ctx=ctx
        )
        assert set(result) == {"error"}
        assert "file-1" in result["error"]
        assert "new-owner@gmail.com" in result["error"]
        assert "Nothing was changed" in result["error"]
        assert "Share dialog" in result["error"]
        assert "doesn't send" in result["error"]
        # Worded from the reason alone: only gmail.com -> gmail.com was seen live,
        # and the rewrite applies to every account pair Drive sends it for.
        assert "personal" not in result["error"]

    async def test_other_http_errors_still_raise(self):
        """Only the shared drive and consumer-consent reasons are rewritten; any
        other Drive error (a 404, a different 403, the cross-organization 400,
        whose own message is already clear) propagates unchanged, as before.
        The cross-organization 400 has been seen live with two reasons (#1181):
        ownershipChangeAcrossDomainNotPermitted (gmail.com owner to a Workspace
        account) and invalidSharingRequest (Workspace owner to an address with no
        Google account, PR #1600 QA round 1)."""

        def cross_org(reason: str) -> HttpError:
            resp = MagicMock()
            resp.status = 400
            message = (
                "Sorry, ownership can only be transferred to another user in the "
                "same organization as the current owner."
            )
            return HttpError(
                resp=resp,
                content=json.dumps(
                    {"error": {"message": message, "errors": [{"reason": reason}]}}
                ).encode(),
            )

        for err in (
            _http_error(404, "File not found: file-1."),
            _http_error(403, "Forbidden"),
            cross_org("ownershipChangeAcrossDomainNotPermitted"),
            cross_org("invalidSharingRequest"),
        ):
            drive = MagicMock()
            drive.permissions.return_value.create.return_value.execute.side_effect = err
            ctx = _make_ctx(drive_service=drive)
            with pytest.raises(HttpError):
                await _sharing_tools["transfer_ownership"](
                    file_id="file-1", new_owner_email="new-owner@example.com", ctx=ctx
                )


class TestShareFile:
    """share_file handles the richer type/domain/anyone permission model."""

    def _drive_svc(self, perm_id="perm-xyz"):
        mock = MagicMock()
        mock.permissions.return_value.create.return_value.execute.return_value = {"id": perm_id}
        return mock

    async def test_http_error_with_non_dict_json_content_does_not_crash(self):
        """QA review, PR #758, finding #3: json.loads(e.content) can return valid
        JSON that isn't a dict (e.g. a JSON array) — the old
        `except json.JSONDecodeError` didn't catch the AttributeError that
        `.get()` then raises on that non-dict value, so the exception escaped
        _share_one entirely and completed[0]/report_progress were skipped for
        that item."""
        drive = MagicMock()
        drive.permissions.return_value.create.return_value.execute.side_effect = (
            _http_error_with_raw_content(500, b"[1, 2, 3]")
        )
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["share_file"](
            file_id="file-1",
            permissions=[{"type": "anyone", "role": "reader"}],
            ctx=ctx,
        )
        assert len(result["failures"]) == 1
        assert "Failed to share" in result["failures"][0]["error"]

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

    async def test_malformed_non_dict_entry_stays_attributable(self):
        """A non-dict permission entry raises from .get() before any validation
        return — the failure must still echo the raw entry, not collapse to an
        anonymous entry=None result indistinguishable from other bad entries."""
        drive = self._drive_svc()
        ctx = _make_ctx(drive_service=drive)
        result = await _sharing_tools["share_file"](
            file_id="file-1",
            permissions=[
                {"type": "anyone", "role": "reader"},
                "not-a-dict",
            ],
            ctx=ctx,
        )
        assert len(result["successes"]) == 1
        assert len(result["failures"]) == 1
        assert result["failures"][0]["entry"] == "not-a-dict"

    async def test_reports_progress_per_permission(self):
        """#355: extends #316/#319's per-item ctx.report_progress pattern to
        share_file's concurrent shares."""
        drive = self._drive_svc()
        ctx = _make_ctx(drive_service=drive)
        ctx.report_progress = AsyncMock()
        await _sharing_tools["share_file"](
            file_id="file-1",
            permissions=[
                {"type": "anyone", "role": "reader"},
                {"type": "domain", "domain": "example.com", "role": "reader"},
            ],
            ctx=ctx,
        )
        assert ctx.report_progress.await_count == 2
        completed_values = sorted(c.args[0] for c in ctx.report_progress.await_args_list)
        assert completed_values == [1, 2]
        for c in ctx.report_progress.await_args_list:
            assert c.args[1] == 2  # total permissions
            assert ": success" in c.args[2]

    async def test_report_progress_failure_does_not_demote_a_successful_share(self):
        """PR #351's review established this guard for download_folder/sync_folder:
        a broken notification channel must not turn an already-successful item into
        a failure. #355 extends the same pattern here."""
        drive = self._drive_svc(perm_id="perm-abc")
        ctx = _make_ctx(drive_service=drive)
        ctx.report_progress = AsyncMock(side_effect=RuntimeError("connection dropped"))
        result = await _sharing_tools["share_file"](
            file_id="file-1",
            permissions=[{"type": "anyone", "role": "reader"}],
            ctx=ctx,
        )
        assert len(result["successes"]) == 1
        assert result["successes"][0]["permissionId"] == "perm-abc"

    async def test_progress_names_each_entry_by_address_or_domain(self):
        """#665: share_file replaces share_spreadsheet, which named each recipient in
        its progress message, so entries of one type stay distinguishable. An entry
        with neither (`anyone`), and a malformed one, are named by their type."""
        drive = self._drive_svc()
        ctx = _make_ctx(drive_service=drive)
        ctx.report_progress = AsyncMock()
        await _sharing_tools["share_file"](
            file_id="file-1",
            permissions=[
                {"type": "user", "email_address": "alice@example.com", "role": "writer"},
                {"type": "user", "email_address": "bob@example.com", "role": "reader"},
                {"type": "domain", "domain": "example.com", "role": "reader"},
                {"type": "anyone", "role": "reader"},
                "not-a-dict",
            ],
            ctx=ctx,
        )
        messages = sorted(c.args[2] for c in ctx.report_progress.await_args_list)
        assert messages == [
            "None: failure",
            "alice@example.com: success",
            "anyone: success",
            "bob@example.com: success",
            "example.com: success",
        ]

    def test_role_documented_as_optional_reader(self):
        # The CHANGELOG's migration advice relies on a missing role meaning reader.
        doc = " ".join(_sharing_tools["share_file"].__doc__.split())
        assert "'role' is optional and defaults to 'reader'" in doc
        assert "must have 'type' and 'role'" not in doc
