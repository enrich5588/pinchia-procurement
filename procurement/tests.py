"""示範測試 —— 交付標準是「每個行為都有測試釘住」,照這個樣式寫。

跑法:.venv/bin/python manage.py test procurement
"""
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from organization.models import Department, UserProfile

from .models import DepartmentManager, is_department_manager


class SmokeTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("t1", "t1@example.com", "x")

    def _cli(self):
        c = Client()
        c.force_login(self.user)
        return c

    def test_supply_list_requires_login(self):
        r = Client().get("/supplies/")
        self.assertEqual(r.status_code, 302, "未登入要被導去登入頁")

    def test_supply_list_renders_for_logged_in_user(self):
        r = self._cli().get("/supplies/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "採購申請專區")
        self.assertContains(r, "辦公用品申請")
        self.assertContains(r, "設備申請")
        self.assertContains(r, reverse("equipment_procurement"))

    def test_equipment_procurement_requires_login(self):
        response = Client().get(reverse("equipment_procurement"))
        self.assertEqual(response.status_code, 302)

    def test_equipment_procurement_tab_renders_for_logged_in_user(self):
        response = self._cli().get(reverse("equipment_procurement"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "採購申請專區")
        self.assertContains(response, "辦公用品申請")
        self.assertContains(response, "設備申請清單")
        self.assertContains(response, 'aria-current="page"')


class DepartmentManagerTests(TestCase):
    def test_seed_creates_three_idempotent_manager_accounts(self):
        call_command("seed_department_managers", verbosity=0)
        call_command("seed_department_managers", verbosity=0)

        expected = {
            "management_manager": "管理部",
            "it_manager": "資訊部",
            "renewal_manager": "都更事業部",
        }
        self.assertEqual(DepartmentManager.objects.count(), 3)
        for username, department_name in expected.items():
            with self.subTest(username=username):
                user = User.objects.get(username=username)
                self.assertTrue(user.check_password("demo"))
                self.assertTrue(user.is_active)
                self.assertFalse(user.is_staff)
                self.assertFalse(user.is_superuser)
                self.assertEqual(user.profile.department.name, department_name)
                self.assertTrue(is_department_manager(user))

    def test_manager_assignment_requires_matching_department(self):
        info = Department.objects.create(name="資訊部")
        management = Department.objects.create(name="管理部")
        user = User.objects.create_user("wrong_manager", password="demo")
        UserProfile.objects.create(user=user, department=info)

        with self.assertRaises(ValidationError):
            DepartmentManager.objects.create(user=user, department=management)

    def test_user_without_department_fails_closed(self):
        user = User.objects.create_user("no_department", password="demo")
        self.assertFalse(is_department_manager(user))
