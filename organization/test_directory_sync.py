from datetime import timedelta
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from .department_sync import DepartmentSyncError, fetch_directory, sync_departments
from .models import Department, DepartmentSyncState, MicrosoftIdentity, PermissionRule, UserProfile
from .permission_forms import PermissionTargetForm

TENANT = "11111111-1111-4111-8111-111111111111"
OBJECT = UUID("22222222-2222-4222-8222-222222222222")


def employee(**changes):
    return {"id": str(OBJECT), "displayName": "測試同仁", "department": "資訊部",
            "userPrincipalName": "staff@company.example", "mail": "staff@company.example",
            "userType": "Member", "accountEnabled": True, **changes}


def page(users, **extra):
    return Mock(status_code=200, json=Mock(return_value={"value": users, **extra}))


@override_settings(M365_TENANT_ID=TENANT, M365_DEPARTMENT_SYNC_ENABLED=True,
                   M365_DEPARTMENT_SYNC_SECONDS=21600)
class DirectorySyncTests(TestCase):
    def setUp(self):
        self.client_mock = patch("organization.department_sync.build_client").start()
        self.client_mock.return_value.acquire_token_for_client.return_value = {"access_token": "secret-token"}
        self.http = patch("organization.department_sync.requests.get").start()
        self.http.return_value = page([employee()])
        self.addCleanup(patch.stopall)

    def test_paging_deduplicates_departments_ignores_guests_and_blank_departments(self):
        next_link = "https://graph.microsoft.com/v1.0/users?$skiptoken=opaque"
        self.http.side_effect = [page([employee(), employee(id=str(uuid4()), department=" 資訊部 ")],
                                     **{"@odata.nextLink": next_link}),
                                 page([employee(id=str(uuid4()), department=None),
                                       employee(id=str(uuid4()), userType="Guest", department="外部")])]
        names, users = fetch_directory()
        self.assertEqual(names, {"資訊部"})
        self.assertEqual(len(users), 3)
        self.assertEqual(self.http.call_count, 2)
        self.assertEqual(self.http.call_args.args[0], next_link)
        self.assertFalse(self.http.call_args.kwargs["allow_redirects"])

    def test_sync_creates_employee_before_first_login_and_preserves_local_records(self):
        old = Department.objects.create(name="歷史部門")
        result = sync_departments()
        identity = MicrosoftIdentity.objects.get(object_id=OBJECT)
        self.assertEqual(result["employees"], 1)
        self.assertFalse(identity.user.has_usable_password())
        self.assertFalse(identity.user.is_superuser)
        self.assertEqual(identity.user.profile.department.name, "資訊部")
        self.assertTrue(Department.objects.filter(pk=old.pk).exists())
        form = PermissionTargetForm(scope="user")
        self.assertIn(identity.user, form.fields["target"].queryset)

    def test_identity_and_personal_rules_survive_name_email_and_department_changes(self):
        sync_departments()
        identity = MicrosoftIdentity.objects.get(object_id=OBJECT)
        rule = PermissionRule.objects.create(user=identity.user, permission="assets.manage", effect="allow")
        self.http.return_value = page([employee(userPrincipalName="changed@company.example",
                                              displayName="新名稱", mail="new@company.example", department="新部門")])
        sync_departments(force=True)
        identity.refresh_from_db()
        self.assertEqual(identity.user_id, rule.user_id)
        user = get_user_model().objects.get(pk=rule.user_id)
        self.assertEqual(user.first_name, "新名稱")
        self.assertEqual(user.profile.department.name, "新部門")
        self.assertTrue(PermissionRule.objects.filter(pk=rule.pk).exists())
        self.assertIn("changed@company.example", PermissionTargetForm(scope="user").fields["target"].label_from_instance(user))

    def test_no_automatic_link_by_email_or_username(self):
        local = get_user_model().objects.create_user("staff@company.example", email="staff@company.example")
        sync_departments()
        synced = MicrosoftIdentity.objects.get(object_id=OBJECT).user
        self.assertNotEqual(local.pk, synced.pk)
        self.assertTrue(synced.username.startswith("m365_"))

    def test_disabled_employee_loses_access_and_local_suspension_is_preserved(self):
        self.http.return_value = page([employee(accountEnabled=False)])
        sync_departments()
        user = MicrosoftIdentity.objects.get(object_id=OBJECT).user
        self.assertFalse(user.is_active)
        self.http.return_value = page([employee(accountEnabled=True)])
        sync_departments(force=True)
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_cleared_department_removes_former_department_privileges(self):
        sync_departments()
        user_id = MicrosoftIdentity.objects.get(object_id=OBJECT).user_id
        self.http.return_value = page([employee(department=None)])
        sync_departments(force=True)
        self.assertFalse(UserProfile.objects.filter(user_id=user_id).exists())

    def test_failed_second_page_never_imports_partial_directory_and_retries(self):
        self.http.side_effect = [page([employee()], **{"@odata.nextLink": "https://graph.microsoft.com/v1.0/users?next=2"}),
                                 Mock(status_code=403)]
        with self.assertRaisesMessage(DepartmentSyncError, "User.Read.All"):
            sync_departments()
        self.assertFalse(MicrosoftIdentity.objects.exists())
        self.assertFalse(Department.objects.exists())
        state = DepartmentSyncState.objects.get(pk=1)
        self.assertIsNone(state.last_success)
        self.assertIsNone(state.lease_until)
        self.assertGreater(state.next_attempt, timezone.now() + timedelta(minutes=14))
        self.assertNotIn("secret-token", state.last_error)

    def test_due_time_and_lease_prevent_duplicate_calls(self):
        sync_departments()
        self.assertIsNone(sync_departments())
        self.assertEqual(self.http.call_count, 1)
        DepartmentSyncState.objects.filter(pk=1).update(lease_until=timezone.now() + timedelta(minutes=1))
        self.assertIsNone(sync_departments(force=True))
        self.assertEqual(self.http.call_count, 1)

    def test_expired_lease_can_recover_after_worker_crash(self):
        DepartmentSyncState.objects.create(pk=1, lease_until=timezone.now() - timedelta(seconds=1))
        self.assertIsNotNone(sync_departments())

    def test_malicious_or_repeated_nextlink_is_rejected_without_forwarding_token(self):
        for link in ["https://evil.example/users", "http://graph.microsoft.com/v1.0/users",
                     "https://graph.microsoft.com/v1.0/users?$select=department,userType&$top=999"]:
            self.http.side_effect = None
            self.http.reset_mock()
            self.http.return_value = page([employee()], **{"@odata.nextLink": link})
            with self.assertRaises(DepartmentSyncError):
                fetch_directory()
            self.assertLessEqual(self.http.call_count, 2)

    def test_malformed_records_and_missing_status_do_not_modify_database(self):
        for data in [employee(id="bad"), employee(accountEnabled=None), employee(department=123)]:
            self.http.return_value = page([data])
            with self.assertRaises(DepartmentSyncError):
                sync_departments(force=True)
            self.assertFalse(MicrosoftIdentity.objects.exists())

    @override_settings(M365_DEPARTMENT_SYNC_ENABLED=False)
    def test_disabled_sync_never_requests_token(self):
        self.assertIsNone(sync_departments())
        self.client_mock.assert_not_called()

    def test_token_failure_has_safe_actionable_message(self):
        self.client_mock.return_value.acquire_token_for_client.return_value = {"error_description": "private-data"}
        with self.assertRaises(DepartmentSyncError) as result:
            sync_departments()
        self.assertNotIn("private-data", str(result.exception))
        self.http.assert_not_called()
