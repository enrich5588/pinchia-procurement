from datetime import date
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client
from organization.testing import OpenPanelsTestCase
from django.urls import reverse
from django.utils import timezone

from assets.permissions import can_manage_assets, can_manage_registrations, can_monitor_database
from procurement.models import EquipmentApplication, OfficeSupplyApplication
from procurement.permissions import can_manage_office_supply_applications, can_manage_equipment_applications
from .models import Department, PermissionAudit, PermissionRule, UserProfile
from .permission_catalog import DEFAULTS, MANAGEMENT_DEPARTMENT_NAME
from .permission_service import explicit_rules, revision_for, save_permissions
from .permissions import has_permission


class PermissionTests(OpenPanelsTestCase):
    def setUp(self):
        User = get_user_model()
        self.department = Department.objects.create(name="資訊部")
        self.management = Department.objects.create(name=MANAGEMENT_DEPARTMENT_NAME)
        self.user = User.objects.create_user("permission-staff")
        self.other = User.objects.create_user("permission-other")
        self.manager = User.objects.create_user("permission-manager")
        self.admin = User.objects.create_superuser("permission-admin")
        for user, department in [(self.user, self.department), (self.other, self.department),
                                 (self.manager, self.management)]:
            UserProfile.objects.create(user=user, department=department)

    def rule(self, code, effect, *, user=None, department=None):
        return PermissionRule.objects.update_or_create(
            user=user, department=department, permission=code, defaults={"effect": effect},
        )[0]

    def values(self, **changes):
        return {**{code: "inherit" for code in DEFAULTS}, **changes}

    def save(self, scope, target, values, actor=None, revision=None):
        return save_permissions(
            actor=actor or self.admin, target_type=scope, target=target, values=values,
            revision=revision if revision is not None else revision_for(explicit_rules(scope, target)),
        )

    def url(self, scope="department", target=None):
        return reverse("permission_management") + "?" + urlencode({
            "scope": scope, "target": (target or self.department).pk,
        })

    def test_official_department_receives_default_management_grants(self):
        for check in [can_manage_assets, can_manage_registrations, can_manage_office_supply_applications,
                      can_manage_equipment_applications]:
            self.assertTrue(check(self.manager))
            self.assertFalse(check(self.user))
        self.assertFalse(has_permission(self.manager, "approvals.view_all"))
        self.assertFalse(can_monitor_database(self.manager))
        self.assertTrue(can_monitor_database(self.admin))

    def test_directory_lists_targets_without_target_dropdown(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("permission_management"))
        self.assertEqual({entry["id"] for entry in response.context["target_list"]},
                         set(Department.objects.values_list("pk", flat=True)))
        self.assertNotContains(response, '<select name="target"')
        self.assertContains(response, 'type="search"')
        response = self.client.get(reverse("permission_management"), {"scope": "user"})
        self.assertEqual(len(response.context["target_list"]), get_user_model().objects.count())
        self.assertNotContains(response, '<select name="target"')

    def test_directory_search_matches_department_name(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("permission_management"), {"q": "資訊"})
        self.assertEqual([entry["id"] for entry in response.context["target_list"]], [self.department.pk])
        self.assertEqual(response.context["total_targets"], Department.objects.count())

    def test_department_pagination_has_twenty_unique_items_per_page(self):
        Department.objects.bulk_create([Department(name=f"分頁部門 {i:02d}") for i in range(43)])
        self.client.force_login(self.admin)
        pages = [self.client.get(reverse("permission_management"), {"page": page}) for page in [1, 2, 3]]
        self.assertEqual([len(r.context["target_list"]) for r in pages], [20, 20, 5])
        ids = [item["id"] for r in pages for item in r.context["target_list"]]
        self.assertEqual(len(set(ids)), 45)
        self.assertEqual(set(ids), set(Department.objects.values_list("pk", flat=True)))
        self.assertFalse(pages[0].context["previous_page_url"])
        self.assertFalse(pages[-1].context["next_page_url"])

    def test_employee_pagination_preserves_filters_selection_and_save_position(self):
        User = get_user_model()
        for index in range(25):
            user = User.objects.create_user(f"page-staff-{index:02d}", first_name="分頁同仁")
            UserProfile.objects.create(user=user, department=self.department)
        self.client.force_login(self.admin)
        params = {"scope": "user", "q": "分頁同仁", "department": self.department.pk,
                  "status": "active", "page": 2, "target": self.user.pk}
        url = reverse("permission_management") + "?" + urlencode(params)
        response = self.client.get(url)
        self.assertEqual(len(response.context["target_list"]), 5)
        self.assertEqual(response.context["directory_page"].paginator.count, 25)
        self.assertEqual(response.context["target"], self.user)
        from urllib.parse import parse_qs, urlsplit
        link_params = parse_qs(urlsplit(response.context["previous_page_url"]).query)
        for key in ["q", "scope", "department", "status", "target"]:
            self.assertEqual(link_params[key], [str(params[key])])
        self.assertEqual(link_params["page"], ["1"])
        self.assertIn("page=2", response.context["target_list"][0]["url"])
        result = self.client.post(url, {**self.values(), "revision": response.context["permission_form"].initial["revision"]})
        self.assertEqual(result.status_code, 302)
        self.assertEqual(parse_qs(urlsplit(result.url).query)["page"], ["2"])

    def test_pagination_handles_invalid_pages_empty_results_and_resets_search(self):
        Department.objects.bulk_create([Department(name=f"頁碼測試 {i:02d}") for i in range(23)])
        self.client.force_login(self.admin)
        for value, expected in [("oops", 1), ("999", 2), ("-1", 2)]:
            response = self.client.get(reverse("permission_management"), {"page": value})
            self.assertEqual(response.context["directory_page"].number, expected)
        response = self.client.get(reverse("permission_management"), {"q": "不存在的部門", "page": "999"})
        self.assertEqual(response.context["directory_page"].number, 1)
        self.assertEqual(response.context["target_list"], [])
        self.assertFalse(response.context["previous_page_url"])
        self.assertFalse(response.context["next_page_url"])
        self.assertNotContains(response, 'name="page"')

    def test_employee_search_matches_name_mail_upn_and_department(self):
        from .models import MicrosoftIdentity
        self.user.first_name = "搜尋同仁"
        self.user.email = "searchable@example.com"
        self.user.save()
        MicrosoftIdentity.objects.create(user=self.user, tenant_id="11111111-1111-4111-8111-111111111111",
                                         object_id="22222222-2222-4222-8222-222222222222",
                                         principal_name="current-upn@example.com")
        self.client.force_login(self.admin)
        for query in ["搜尋同仁", "SEARCHABLE@EXAMPLE.COM", "CURRENT-UPN", "資訊部"]:
            with self.subTest(query=query):
                response = self.client.get(reverse("permission_management"), {"scope": "user", "q": query})
                self.assertIn(self.user.pk, [entry["id"] for entry in response.context["target_list"]])
                self.assertNotIn(self.manager.pk, [entry["id"] for entry in response.context["target_list"]])

    def test_empty_search_result_keeps_selected_target_and_escapes_query(self):
        self.client.force_login(self.admin)
        query = '<script>alert("test")</script>'
        response = self.client.get(self.url("user", self.user) + "&" + urlencode({"q": query}))
        self.assertEqual(response.context["target_list"], [])
        self.assertEqual(response.context["target"], self.user)
        self.assertContains(response, "找不到符合條件")
        self.assertNotContains(response, query)
        self.assertContains(response, "儲存權限設定")

    def test_search_is_preserved_when_saving_and_never_changes_other_users(self):
        self.client.force_login(self.admin)
        url = self.url("user", self.user) + "&q=permission-staff"
        response = self.client.get(url)
        result = self.client.post(url, {**self.values(**{"assets.manage": "allow"}),
                                       "revision": response.context["permission_form"].initial["revision"]})
        self.assertEqual(result.status_code, 302)
        self.assertIn("q=permission-staff", result.url)
        self.assertTrue(can_manage_assets(self.user))
        self.assertFalse(can_manage_assets(self.other))

    def test_old_short_department_name_does_not_grant_management(self):
        legacy = Department.objects.create(name="管理部")
        UserProfile.objects.filter(user=self.user).update(department=legacy)
        user = get_user_model().objects.get(pk=self.user.pk)
        self.assertFalse(can_manage_assets(user))

    def test_personal_deny_overrides_department_allow(self):
        self.rule("assets.manage", "allow", department=self.department)
        self.assertTrue(can_manage_assets(self.user))
        self.rule("assets.manage", "deny", user=self.user)
        self.assertFalse(can_manage_assets(self.user))
        self.assertTrue(can_manage_assets(self.other))

    def test_personal_allow_overrides_department_deny(self):
        self.rule("assets.manage", "deny", department=self.department)
        self.rule("assets.manage", "allow", user=self.user)
        self.assertTrue(can_manage_assets(self.user))
        self.assertFalse(can_manage_assets(self.other))

    def test_inherit_restores_department_and_changes_are_audited(self):
        self.rule("assets.manage", "allow", department=self.department)
        self.save("user", self.user, self.values(**{"assets.manage": "deny"}))
        self.assertFalse(can_manage_assets(self.user))
        self.save("user", self.user, self.values())
        self.assertTrue(can_manage_assets(self.user))
        self.assertEqual(PermissionAudit.objects.count(), 2)
        self.assertEqual(PermissionAudit.objects.first().changes["assets.manage"],
                         {"before": "deny", "after": "inherit"})

    def test_removing_seeded_rule_is_not_undone_when_department_saved(self):
        PermissionRule.objects.filter(department=self.management, permission="assets.manage").delete()
        self.management.save()
        self.assertFalse(can_manage_assets(self.manager))

    def test_permission_modules_are_independent_and_monitor_is_separate(self):
        self.rule("supplies.manage", "allow", user=self.user)
        self.rule("registrations.manage", "allow", user=self.user)
        self.assertTrue(can_manage_office_supply_applications(self.user))
        self.assertTrue(can_manage_registrations(self.user))
        self.assertFalse(can_manage_equipment_applications(self.user))
        self.assertFalse(can_manage_assets(self.user))
        self.assertFalse(can_monitor_database(self.user))

    def test_access_deny_blocks_direct_get_post_dashboard_and_navigation(self):
        foreign = OfficeSupplyApplication.objects.create(
            case_no="261111901", department=self.department, applicant=self.other,
            need_date=date(2026, 11, 20), created_by=self.other, updated_by=self.other,
        )
        self.rule("supplies.manage", "allow", user=self.user)
        self.rule("supplies.access", "deny", user=self.user)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("supplies")).status_code, 403)
        self.assertEqual(self.client.get(reverse("supply_detail", args=[foreign.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("supply_processing", args=[foreign.pk])).status_code, 403)
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, foreign.case_no)
        self.assertEqual(response.context["supply_pending"], 0)
        self.assertNotContains(response, 'href="/supplies/"')
        self.assertNotContains(response, 'href="/supplies/new/"')

    def test_all_module_access_gates_protect_direct_routes(self):
        self.client.force_login(self.user)
        for code, route in [
            ("equipment.access", "equipment_procurement"), ("assets.access", "asset_list"),
            ("registrations.access", "registration_list"), ("collaboration.access", "collaboration_task_list"),
            ("approvals.access", "approval_list"), ("database.monitor", "database_monitor"),
        ]:
            with self.subTest(code=code):
                self.rule(code, "deny", user=self.user)
                self.assertEqual(self.client.get(reverse(route)).status_code, 403)
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, 'href="' + reverse("asset_list") + '"')

    def test_asset_revision_cannot_bypass_registration_access_deny(self):
        self.client.force_login(self.user)
        self.rule("registrations.access", "deny", user=self.user)
        for method in [self.client.get, self.client.post]:
            self.assertEqual(method(reverse("asset_revise", args=[9999])).status_code, 403)

    def test_personal_processing_grant_allows_company_work_without_granting_other_modules(self):
        foreign = OfficeSupplyApplication.objects.create(
            case_no="261111902", department=self.department, applicant=self.other,
            need_date=date(2026, 11, 20), created_by=self.other, updated_by=self.other,
        )
        self.rule("supplies.manage", "allow", user=self.user)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("supplies")), foreign.case_no)
        self.assertEqual(self.client.post(reverse("supply_processing", args=[foreign.pk])).status_code, 302)
        foreign.refresh_from_db()
        self.assertEqual(foreign.status, "processing")
        self.assertFalse(can_manage_equipment_applications(self.user))

    def test_personal_grant_can_be_revoked_without_new_login(self):
        self.rule("assets.access", "allow", user=self.user)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("asset_list")).status_code, 200)
        self.rule("assets.access", "deny", user=self.user)
        self.assertEqual(self.client.get(reverse("asset_list")).status_code, 403)

    def test_entire_system_management_is_superuser_only_even_with_explicit_grants(self):
        self.rule("database.monitor", "allow", department=self.management)
        for user in [self.user, self.manager]:
            user.is_staff = True
            user.save(update_fields=["is_staff"])
            self.rule("database.monitor", "allow", user=user)
            self.client.force_login(user)
            response = self.client.get(reverse("home"))
            for text in ["系統管理</div>", "資料庫監看", "權限管理", "面板管理"]:
                self.assertNotContains(response, text)
            for route in ["database_monitor", "permission_management", "panel_management"]:
                for method in [self.client.get, self.client.post]:
                    self.assertEqual(method(reverse(route)).status_code, 403)
            self.assertFalse(can_monitor_database(user))
            self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("home"))
        for text in ["資料庫監看", "權限管理", "面板管理"]:
            self.assertContains(response, text)
        for route in ["database_monitor", "permission_management", "panel_management"]:
            self.assertEqual(self.client.get(reverse(route)).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)

    def test_approval_read_all_never_grants_someone_elses_signature(self):
        from approval_hub.models import ApprovalRequest, ApprovalStep
        approval = ApprovalRequest.objects.create(
            case_no="261111903", subject="權限驗證簽呈", content="test", department=self.department,
            applicant=self.other, created_by=self.other, updated_by=self.other, delivered_at=timezone.now(),
        )
        ApprovalStep.objects.create(request=approval, approver=self.other, sequence=1, status="pending")
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("approval_detail", args=[approval.pk])).status_code, 403)
        self.rule("approvals.view_all", "allow", user=self.user)
        self.assertEqual(self.client.get(reverse("approval_detail", args=[approval.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse("approval_approve", args=[approval.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("approval_withdraw", args=[approval.pk])).status_code, 403)

    def test_superuser_cannot_be_locked_out_by_permission_rules(self):
        for code in DEFAULTS:
            self.rule(code, "deny", user=self.admin)
            self.assertTrue(has_permission(self.admin, code))
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url()).status_code, 200)

    def test_disabled_user_has_no_permission_even_with_personal_grants(self):
        self.rule("assets.manage", "allow", user=self.user)
        self.user.is_active = False
        self.assertFalse(can_manage_assets(self.user))
        self.assertFalse(has_permission(self.user, "unknown.permission"))

    def test_only_superuser_can_manage_rules_in_view_and_service(self):
        self.assertEqual(self.client.get(self.url()).status_code, 302)
        for user in [self.user, self.manager]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url()).status_code, 403)
            self.assertEqual(self.client.post(self.url(), {}).status_code, 403)
            with self.assertRaises(PermissionDenied):
                self.save("department", self.department, self.values(), actor=user)

    def test_editor_get_does_not_write_and_post_saves_both_target_types(self):
        self.client.force_login(self.admin)
        for scope, target in [("department", self.department), ("user", self.user)]:
            response = self.client.get(self.url(scope, target))
            self.assertEqual(response.status_code, 200)
            self.assertTemplateUsed(response, "organization/permission_management.html")
            self.assertEqual(PermissionAudit.objects.filter(target_type=scope).count(), 0)
            data = self.values(**{"assets.manage": "allow"})
            data["revision"] = response.context["permission_form"].initial["revision"]
            result = self.client.post(self.url(scope, target), data)
            self.assertEqual(result.status_code, 302)
            self.assertEqual(PermissionAudit.objects.filter(target_type=scope).count(), 1)

    def test_editor_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(self.url(), {}).status_code, 403)

    def test_stale_revision_and_missing_fields_do_not_overwrite(self):
        old = revision_for({})
        self.save("department", self.department, self.values(**{"assets.manage": "allow"}))
        with self.assertRaises(ValidationError):
            self.save("department", self.department, self.values(), revision=old)
        with self.assertRaises(ValidationError):
            self.save("department", self.department, {"assets.manage": "deny"})
        self.assertTrue(can_manage_assets(self.user))
        self.assertEqual(PermissionAudit.objects.count(), 1)

    def test_stale_editor_post_returns_conflict_instead_of_overwriting(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url())
        revision = response.context["permission_form"].initial["revision"]
        self.save("department", self.department, self.values(**{"assets.manage": "allow"}))
        result = self.client.post(self.url(), {**self.values(), "revision": revision})
        self.assertEqual(result.status_code, 409)
        self.assertContains(result, "已由其他管理員更新", status_code=409)
        self.assertTrue(can_manage_assets(self.user))

    def test_target_types_and_unique_constraints_are_enforced(self):
        with self.assertRaises(ValidationError):
            self.save("user", self.department, self.values())
        with self.assertRaises(IntegrityError), transaction.atomic():
            PermissionRule.objects.create(user=self.user, department=self.department,
                                          permission="assets.access", effect="allow")
        with self.assertRaises(IntegrityError), transaction.atomic():
            PermissionRule.objects.create(permission="assets.access", effect="allow")
        self.rule("assets.access", "allow", user=self.user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PermissionRule.objects.create(user=self.user, permission="assets.access", effect="deny")


class ManagementMigrationTests(OpenPanelsTestCase):
    def migrate_defaults(self):
        from importlib import import_module
        from django.apps import apps
        from django.db import connection
        from types import SimpleNamespace
        migration = import_module("organization.migrations.0004_official_management_defaults")
        migration.seed_management(apps, SimpleNamespace(connection=connection))

    def test_short_name_is_renamed_preserving_profiles_and_department_id(self):
        legacy = Department.objects.create(name="管理部")
        user = get_user_model().objects.create_user("legacy-manager")
        UserProfile.objects.create(user=user, department=legacy)
        self.migrate_defaults()
        legacy.refresh_from_db()
        self.assertEqual(legacy.name, MANAGEMENT_DEPARTMENT_NAME)
        self.assertEqual(user.profile.department_id, legacy.pk)
        self.assertTrue(can_manage_assets(user))

    def test_existing_official_and_legacy_departments_are_not_merged_or_regranted(self):
        legacy = Department.objects.create(name="管理部")
        official = Department.objects.create(name=MANAGEMENT_DEPARTMENT_NAME)
        PermissionRule.objects.filter(department=official, permission="assets.manage").update(effect="deny")
        self.migrate_defaults()
        self.assertTrue(Department.objects.filter(pk=legacy.pk, name="管理部").exists())
        self.assertEqual(PermissionRule.objects.get(department=official, permission="assets.manage").effect, "deny")
        self.assertFalse(PermissionRule.objects.filter(department=legacy).exists())
