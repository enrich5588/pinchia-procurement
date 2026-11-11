"""UI directory filters must never change permission resolution or edit targets."""
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Department, MicrosoftIdentity, PermissionRule, UserProfile
from .permission_catalog import DEFAULTS


class PermissionDirectoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.design = Department.objects.create(name="設計部")
        cls.engineering = Department.objects.create(name="工程部")
        cls.empty = Department.objects.create(name="籌備部")
        cls.admin = User.objects.create_superuser("directory-admin", first_name="系統管理員")
        cls.staff = User.objects.create_user("design-staff", first_name="林怡君", email="yijun@example.com")
        cls.inactive = User.objects.create_user("inactive-staff", first_name="陳柏宇", is_active=False)
        cls.engineer = User.objects.create_user("engineer", first_name="王品安")
        for user, department in [(cls.staff, cls.design), (cls.inactive, cls.design),
                                 (cls.engineer, cls.engineering)]:
            UserProfile.objects.create(user=user, department=department)
        MicrosoftIdentity.objects.create(user=cls.staff,
            tenant_id="11111111-1111-4111-8111-111111111111",
            object_id="33333333-3333-4333-8333-333333333333",
            principal_name="lin.yijun@example.com")
        for code in ["assets.access", "assets.manage"]:
            PermissionRule.objects.create(department=cls.design, permission=code, effect="allow")
        PermissionRule.objects.create(user=cls.staff, permission="assets.manage", effect="deny")

    def setUp(self):
        self.client.force_login(self.admin)
        self.url = reverse("permission_management")

    def get(self, **params):
        return self.client.get(self.url, {"scope": "user", **params})

    def ids(self, response):
        self.assertEqual(response.status_code, 200)
        return {item["id"] for item in response.context["target_list"]}

    def test_department_counts_do_not_multiply_with_permission_rules(self):
        response = self.client.get(self.url)
        entry = next(item for item in response.context["target_list"] if item["id"] == self.design.pk)
        self.assertEqual(entry["members"], 2)
        self.assertEqual(entry["rules"], 2)
        empty = next(item for item in response.context["target_list"] if item["id"] == self.empty.pk)
        self.assertEqual(empty["members"], 0)
        self.assertContains(response, "查看人員")

    def test_department_and_status_filters_combine(self):
        self.assertEqual(self.ids(self.get(department=self.design.pk)), {self.staff.pk, self.inactive.pk})
        self.assertEqual(self.ids(self.get(department=self.design.pk, status="active")), {self.staff.pk})
        self.assertEqual(self.ids(self.get(department=self.design.pk, status="inactive")), {self.inactive.pk})
        self.assertEqual(self.ids(self.get(department=self.engineering.pk, q="不存在")), set())

    def test_unassigned_accounts_are_included(self):
        self.assertEqual(self.ids(self.get(department="unassigned")), {self.admin.pk})
        response = self.get()
        self.assertEqual(response.context["unassigned_count"], 1)

    def test_invalid_filters_are_ignored_and_escaped(self):
        for department in ["garbage", "999999999999999999999999999999999999999", '<script>alert(1)</script>']:
            response = self.get(department=department, status="invalid")
            self.assertEqual(len(self.ids(response)), 4)
            self.assertEqual(response.context["selected_department"], "")
            self.assertNotContains(response, '<script>alert(1)</script>')

    def test_personnel_metadata_and_accessible_edit_link(self):
        response = self.get(target=self.staff.pk)
        entry = next(item for item in response.context["target_list"] if item["id"] == self.staff.pk)
        self.assertEqual(entry["email"], "yijun@example.com")
        self.assertEqual(entry["account"], "lin.yijun@example.com")
        self.assertContains(response, 'aria-label="編輯 林怡君 的權限"')
        self.assertContains(response, "正在編輯")
        self.assertContains(response, 'class="permission-people"')
        self.assertContains(response, "儲存權限設定")

    def test_empty_state_keeps_editor_target(self):
        response = self.get(target=self.staff.pk, department=self.empty.pk)
        self.assertEqual(self.ids(response), set())
        self.assertEqual(response.context["target"], self.staff)
        self.assertContains(response, "找不到符合條件的人員")
        self.assertContains(response, "儲存權限設定")

    def test_filter_context_survives_target_links_reload_and_save(self):
        params = {"target": self.staff.pk, "department": self.design.pk, "status": "active", "q": "林"}
        response = self.get(**params)
        entry = response.context["target_list"][0]
        for link in [entry["url"], response.context["reload_url"]]:
            query = parse_qs(urlsplit(link).query)
            self.assertEqual(query["department"], [str(self.design.pk)])
            self.assertEqual(query["status"], ["active"])
            self.assertEqual(query["q"], ["林"])
        values = {code: "inherit" for code in DEFAULTS}
        values["revision"] = response.context["permission_form"].initial["revision"]
        result = self.client.post(self.url + "?" + urlsplit(entry["url"]).query, values)
        self.assertEqual(result.status_code, 302)
        self.assertEqual(parse_qs(urlsplit(result.url).query)["department"], [str(self.design.pk)])
        self.assertEqual(parse_qs(urlsplit(result.url).query)["status"], ["active"])
        self.assertTrue(PermissionRule.objects.filter(department=self.design, permission="assets.manage").exists())

    def test_filter_navigation_preserves_search_and_status(self):
        response = self.get(q="林", status="active")
        link = next(item["url"] for item in response.context["departments"] if item["id"] == str(self.design.pk))
        self.assertEqual(parse_qs(urlsplit(link).query)["q"], ["林"])
        self.assertEqual(parse_qs(urlsplit(link).query)["status"], ["active"])

    def test_only_superusers_can_view_or_post_directory(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.get().status_code, 403)
        self.assertEqual(self.client.post(self.url + "?scope=user&target=" + str(self.admin.pk), {}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.get().status_code, 302)
