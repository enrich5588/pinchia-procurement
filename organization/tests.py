import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from config.env import env_bool, load_env
from organization.models import Department, UserProfile


class EnvironmentTests(SimpleTestCase):
    def test_literal_env_preserves_process_values(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ, {"EXISTING": "process"}):
            path = Path(folder) / ".env"
            path.write_text('# comment\nEXISTING=file\nNEW_VALUE="a=b # literal"\n', encoding="utf-8")
            load_env(path)
            self.assertEqual(os.environ["EXISTING"], "process")
            self.assertEqual(os.environ["NEW_VALUE"], "a=b # literal")

    def test_malformed_environment_fails_explicitly(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            for value in ["no separator", 'KEY="unclosed']:
                path.write_text(value, encoding="utf-8")
                with self.assertRaises(ImproperlyConfigured):
                    load_env(path)

    def test_invalid_boolean_fails_instead_of_enabling_feature(self):
        with patch.dict(os.environ, {"FEATURE_OPEN_TO_ALL": "typo"}):
            with self.assertRaises(ImproperlyConfigured):
                env_bool("FEATURE_OPEN_TO_ALL")


class StandaloneProjectTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.department = Department.objects.create(name="資訊部")
        cls.user = get_user_model().objects.create_user("standalone-staff")
        UserProfile.objects.create(user=cls.user, department=cls.department)
        cls.admin = get_user_model().objects.create_superuser("standalone-admin", password="test")

    def test_old_imports_and_database_identity_are_preserved(self):
        from platform_stub.models import Department as LegacyDepartment
        self.assertIs(LegacyDepartment, Department)
        self.assertIs(apps.get_model("platform_stub", "Department"), Department)
        self.assertEqual(Department._meta.db_table, "platform_stub_department")
        self.assertEqual(UserProfile._meta.db_table, "platform_stub_userprofile")

    def test_all_main_pages_keep_their_templates_and_static_assets(self):
        self.client.force_login(self.admin)
        pages = [
            ("home", "procurement/home.html"),
            ("supplies", "procurement/supply_list.html"),
            ("equipment_procurement", "procurement/equipment_list.html"),
            ("asset_list", "assets/asset_list.html"),
            ("registration_list", "assets/registration_list.html"),
            ("collaboration_task_list", "collaboration_hub/task_list.html"),
            ("approval_list", "approval_hub/approval_list.html"),
            ("database_monitor", "assets/database_monitor.html"),
        ]
        for name, template in pages:
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, template)
        from django.contrib.staticfiles import finders
        for asset in ["assets/asset-modal.js", "procurement/supply-modal.js",
                      "procurement/equipment-modal.js", "collaboration_hub/task-workflow.js",
                      "approval_hub/approval.js"]:
            self.assertIsNotNone(finders.find(asset), asset)

    def test_login_uses_project_owned_template(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Path(response.templates[0].origin.name).parent.name, "templates")
        self.assertNotContains(response, "stub")

    @override_settings(FEATURE_OPEN_TO_ALL=False)
    def test_feature_setting_blocks_staff_but_allows_admin(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("supplies")).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("supplies")).status_code, 200)

    @override_settings(FEATURE_OPEN_TO_ALL=True)
    def test_feature_setting_allows_staff(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("supplies")).status_code, 200)


class ProductionSettingsTests(SimpleTestCase):
    def test_production_checks_and_rejects_unsafe_configuration(self):
        root = Path(__file__).resolve().parent.parent
        for secret, hosts, valid in [
            ("test-only-" + "x" * 60, "procurement.example.com", True),
            ("short", "procurement.example.com", False),
            ("test-only-" + "x" * 60, "*", False),
        ]:
            with self.subTest(valid=valid, hosts=hosts):
                env = os.environ.copy()
                env.update(DJANGO_SETTINGS_MODULE="config.settings.production",
                           DJANGO_SECRET_KEY=secret, DJANGO_ALLOWED_HOSTS=hosts)
                result = subprocess.run(
                    [sys.executable, str(root / "manage.py"), "check", "--deploy", "--fail-level", "WARNING"],
                    cwd=root, env=env, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode == 0, valid, result.stderr)


class DemoApprovalSetupTests(TestCase):
    def test_demo_initialization_supports_every_approval_amount(self):
        from django.core.management import call_command
        from io import StringIO
        from approval_hub.services import create_approval_request
        from project_options.approvals import APPROVAL_ROUTE_RULES
        call_command("seed_demo", stdout=StringIO())
        applicant = get_user_model().objects.get(username="staff1")
        for amount_range, usernames in APPROVAL_ROUTE_RULES.items():
            with self.subTest(amount_range=amount_range):
                approval = create_approval_request(
                    applicant=applicant, department=applicant.profile.department,
                    subject="初始化驗證", content="測試", amount_range=amount_range,
                )
                self.assertEqual(list(approval.steps.order_by("sequence").values_list(
                    "approver__username", flat=True)), list(usernames))

    def test_demo_initialization_preserves_existing_approver_credentials(self):
        from django.core.management import call_command
        from io import StringIO
        user = get_user_model().objects.create_user("wang", password="existing", is_active=False)
        call_command("seed_demo", stdout=StringIO())
        user.refresh_from_db()
        self.assertTrue(user.check_password("existing"))
        self.assertFalse(user.is_active)
        self.assertFalse(user.is_superuser)


class LogoutFlowTests(TestCase):
    def test_logout_returns_to_project_login_and_clears_session(self):
        user = get_user_model().objects.create_user("logout-test")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("login"))
        self.assertNotIn("_auth_user_id", self.client.session)
