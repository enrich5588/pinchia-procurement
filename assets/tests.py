from datetime import date

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from organization.models import Department, UserProfile

from .forms import AssetForm
from .models import Asset


class AssetAccessTests(TestCase):
    def setUp(self):
        self.it = Department.objects.create(name="資訊部")
        self.business = Department.objects.create(name="都更事業部")
        self.management = Department.objects.create(name="管理與事業發展部")
        self.it_user = self._user("it_user", self.it)
        self.business_user = self._user("business_user", self.business)
        self.manager = self._user("manager", self.management)
        self.admin = User.objects.create_superuser("admin", "admin@example.com", "x")
        self.it_asset = self._asset("A-001", "資訊部筆電", self.it, Asset.Category.IT_EQUIPMENT)
        self.business_asset = self._asset(
            "A-002", "事業部辦公桌", self.business, Asset.Category.FURNITURE
        )

    def _user(self, username, department):
        user = User.objects.create_user(username, f"{username}@example.com", "x")
        UserProfile.objects.create(user=user, department=department)
        return user

    def _asset(self, asset_no, name, department, category):
        return Asset.objects.create(
            asset_no=asset_no,
            name=name,
            category=category,
            department=department,
            purchase_date=date(2026, 8, 20),
            created_by=self.manager,
        )

    def _client_for(self, user):
        client = Client()
        client.force_login(user)
        return client

    def test_list_requires_login(self):
        response = Client().get(reverse("asset_list"))
        self.assertRedirects(response, f"/accounts/login/?next={reverse('asset_list')}")

    def test_regular_user_only_sees_own_department_assets(self):
        response = self._client_for(self.it_user).get(reverse("asset_list"))
        self.assertContains(response, self.it_asset.name)
        self.assertNotContains(response, self.business_asset.name)
        self.assertNotContains(response, "全部部門")

    def test_regular_user_cannot_expand_scope_with_query_string(self):
        response = self._client_for(self.it_user).get(
            reverse("asset_list"), {"department": self.business.pk}
        )
        self.assertContains(response, self.it_asset.name)
        self.assertNotContains(response, self.business_asset.name)

    def test_management_and_admin_see_all_assets(self):
        for user in (self.manager, self.admin):
            with self.subTest(user=user.username):
                response = self._client_for(user).get(reverse("asset_list"))
                self.assertContains(response, self.it_asset.name)
                self.assertContains(response, self.business_asset.name)
                self.assertContains(response, "全部部門")

    def test_management_filters_auto_submit_without_apply_button(self):
        response = self._client_for(self.manager).get(reverse("asset_list"))
        self.assertContains(response, "data-auto-submit")
        self.assertContains(response, "assets/asset-filter.js")
        self.assertNotContains(response, "套用篩選")

    def test_management_can_filter_by_department_and_category(self):
        response = self._client_for(self.manager).get(reverse("asset_list"), {
            "department": self.business.pk,
            "category": Asset.Category.FURNITURE,
        })
        self.assertNotContains(response, self.it_asset.name)
        self.assertContains(response, self.business_asset.name)
        self.assertEqual(response.context["summary"]["total"], 1)
        self.assertEqual(response.context["summary"]["furniture"], 1)
        self.assertEqual(response.context["summary"]["it_equipment"], 0)

    def test_invalid_filters_do_not_cause_server_error(self):
        response = self._client_for(self.manager).get(reverse("asset_list"), {
            "department": "not-a-department",
            "category": "not-a-category",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.it_asset.name)
        self.assertContains(response, self.business_asset.name)

    def test_list_orders_assets_by_created_date_newest_first(self):
        response = self._client_for(self.manager).get(reverse("asset_list"))
        asset_ids = [asset.pk for asset in response.context["assets"]]
        self.assertEqual(asset_ids, [self.business_asset.pk, self.it_asset.pk])

    def test_table_uses_original_asset_field_names(self):
        response = self._client_for(self.manager).get(reverse("asset_list"))
        headers = (
            "財產編號",
            "財產名稱",
            "財產類別",
            "廠牌",
            "財產規格型號",
            "所屬部門",
            "保管人員",
            "採購日期",
            "使用年限",
            "備註（保固期限等）",
        )
        for header in headers:
            with self.subTest(header=header):
                self.assertContains(
                    response, f'<th scope="col">{header}</th>', html=True
                )


class AssetCreateTests(TestCase):
    def setUp(self):
        self.it = Department.objects.create(name="資訊部")
        self.management = Department.objects.create(name="管理與事業發展部")
        self.staff = self._user("staff", self.it)
        self.manager = self._user("manager", self.management)

    def _user(self, username, department):
        user = User.objects.create_user(username, password="x")
        UserProfile.objects.create(user=user, department=department)
        return user

    def _client_for(self, user):
        client = Client()
        client.force_login(user)
        return client

    def _valid_data(self):
        return {
            "asset_no": "A-100",
            "name": "測試筆電",
            "company": Asset.Company.PINJIA_CONSTRUCTION,
            "category": Asset.Category.IT_EQUIPMENT,
            "brand": "ASUS",
            "specification": "ExampleBook 14",
            "accessories": "充電器、滑鼠",
            "quantity": 2,
            "unit_price": "30000.00",
            "business_tax": "1500.00",
            "total": "999999.00",
            "department": self.it.pk,
            "custodian": self.staff.pk,
            "purchase_date": "2026-08-20",
            "useful_life_years": 5,
            "notes": "保固三年",
        }

    def test_regular_user_cannot_open_or_submit_create_form(self):
        client = self._client_for(self.staff)
        self.assertEqual(client.get(reverse("asset_create")).status_code, 403)
        self.assertEqual(client.post(reverse("asset_create"), self._valid_data()).status_code, 403)
        self.assertFalse(Asset.objects.filter(asset_no="A-100").exists())

    def test_management_can_create_asset(self):
        response = self._client_for(self.manager).post(
            reverse("asset_create"), self._valid_data(), follow=True
        )
        self.assertRedirects(response, reverse("asset_list"))
        asset = Asset.objects.get(asset_no="A-100")
        self.assertEqual(asset.created_by, self.manager)
        self.assertEqual(asset.updated_by, self.manager)
        self.assertIsNotNone(asset.created_at)
        self.assertIsNotNone(asset.updated_at)
        self.assertContains(response, "已新增財產")
        self.assertEqual(asset.brand, "ASUS")
        self.assertEqual(asset.company, Asset.Company.PINJIA_CONSTRUCTION)
        self.assertEqual(asset.accessories, "充電器、滑鼠")
        self.assertEqual(asset.quantity, 2)
        self.assertEqual(str(asset.total), "31500.00")
        self.assertContains(response, '<td data-label="廠牌">ASUS</td>', html=True)

    def test_category_is_manual_text_and_total_is_read_only(self):
        form = AssetForm()
        self.assertEqual(form.fields["category"].widget.input_type, "text")
        self.assertTrue(form.fields["total"].disabled)

    def test_quantity_and_company_are_required(self):
        data = self._valid_data()
        data.pop("company")
        data["quantity"] = 0
        response = self._client_for(self.manager).post(reverse("asset_create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "errorlist")
        self.assertFalse(Asset.objects.filter(asset_no="A-100").exists())

    def test_audit_fields_are_hidden_from_public_asset_form(self):
        form = AssetForm()
        for field_name in ("created_at", "updated_at", "created_by", "updated_by"):
            with self.subTest(field_name=field_name):
                self.assertNotIn(field_name, form.fields)

    def test_brand_can_be_left_blank(self):
        data = self._valid_data()
        data.pop("brand")
        response = self._client_for(self.manager).post(reverse("asset_create"), data)
        self.assertRedirects(response, reverse("asset_list"))
        self.assertEqual(Asset.objects.get(asset_no="A-100").brand, "")

    def test_custodian_must_belong_to_asset_department(self):
        data = self._valid_data()
        data["department"] = self.management.pk
        response = self._client_for(self.manager).post(reverse("asset_create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "保管人員必須屬於財產的所屬部門")
        self.assertFalse(Asset.objects.filter(asset_no="A-100").exists())

    def test_number_check_reports_duplicate_case_insensitively(self):
        Asset.objects.create(
            asset_no="ASSET-001",
            name="既有資產",
            category=Asset.Category.OTHER,
            department=self.management,
            purchase_date=date(2026, 8, 20),
            created_by=self.manager,
        )
        response = self._client_for(self.manager).get(
            reverse("asset_number_check"), {"asset_no": "asset-001"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "asset_no": "ASSET-001",
            "exists": True,
            "available": False,
        })

    def test_number_check_reports_available_number(self):
        response = self._client_for(self.manager).get(
            reverse("asset_number_check"), {"asset_no": "new-001"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "asset_no": "NEW-001",
            "exists": False,
            "available": True,
        })

    def test_regular_user_cannot_use_number_check(self):
        response = self._client_for(self.staff).get(
            reverse("asset_number_check"), {"asset_no": "A-100"}
        )
        self.assertEqual(response.status_code, 403)

    def test_submit_rejects_case_insensitive_duplicate(self):
        Asset.objects.create(
            asset_no="A-100",
            name="既有資產",
            category=Asset.Category.OTHER,
            department=self.it,
            purchase_date=date(2026, 8, 20),
            created_by=self.manager,
        )
        data = self._valid_data()
        data["asset_no"] = "a-100"
        response = self._client_for(self.manager).post(reverse("asset_create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "財產編號已存在，請使用其他編號")
        self.assertEqual(Asset.objects.filter(asset_no__iexact="A-100").count(), 1)

    def test_create_form_loads_number_check_behavior(self):
        response = self._client_for(self.manager).get(reverse("asset_create"))
        self.assertContains(response, reverse("asset_number_check"))
        self.assertContains(response, "assets/asset-form.js")
        self.assertContains(response, "data-number-status")

    def test_create_form_loads_as_modal_fragment(self):
        response = self._client_for(self.manager).get(
            reverse("asset_create"), HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-asset-form")
        self.assertNotContains(response, "<!doctype html>")

    def test_invalid_modal_create_stays_in_modal(self):
        response = self._client_for(self.manager).post(
            reverse("asset_create"),
            {"asset_no": ""},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "errorlist", status_code=422)

    def test_valid_modal_create_returns_success_json(self):
        response = self._client_for(self.manager).post(
            reverse("asset_create"),
            self._valid_data(),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "success": True,
            "redirect_url": reverse("asset_list"),
        })
        self.assertTrue(Asset.objects.filter(asset_no="A-100").exists())

    def test_asset_rows_open_detail_for_management_and_staff(self):
        asset = Asset.objects.create(
            asset_no="EDIT-001",
            name="待編輯資產",
            category=Asset.Category.OTHER,
            department=self.it,
            purchase_date=date(2026, 8, 20),
            created_by=self.manager,
        )
        detail_url = reverse("asset_detail", args=[asset.pk])
        manager_response = self._client_for(self.manager).get(reverse("asset_list"))
        staff_response = self._client_for(self.staff).get(reverse("asset_list"))
        self.assertContains(manager_response, detail_url)
        self.assertContains(manager_response, "data-asset-modal")
        self.assertContains(staff_response, detail_url)
        self.assertContains(staff_response, "data-asset-modal")
        self.assertContains(manager_response, 'aria-label="查看 EDIT-001 待編輯資產"')

    def test_edit_modal_locks_asset_number(self):
        asset = Asset.objects.create(
            asset_no="EDIT-001",
            name="待編輯資產",
            category=Asset.Category.OTHER,
            department=self.it,
            purchase_date=date(2026, 8, 20),
            created_by=self.manager,
        )
        response = self._client_for(self.manager).get(
            reverse("asset_edit", args=[asset.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "財產編號建立後不可修改")
        self.assertContains(response, 'name="asset_no"', html=False)
        self.assertContains(response, "disabled", html=False)
        self.assertContains(response, 'value="2026-08-20"', html=False)

    def test_edit_ignores_tampered_asset_number_and_updates_other_fields(self):
        asset = Asset.objects.create(
            asset_no="EDIT-001",
            name="原始名稱",
            category=Asset.Category.OTHER,
            department=self.it,
            purchase_date=date(2026, 8, 20),
            created_by=self.manager,
        )
        original_created_at = asset.created_at
        second_manager = self._user("manager2", self.management)
        data = self._valid_data()
        data["asset_no"] = "TAMPERED"
        data["name"] = "更新後名稱"
        response = self._client_for(second_manager).post(
            reverse("asset_edit", args=[asset.pk]),
            data,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        asset.refresh_from_db()
        self.assertEqual(asset.asset_no, "EDIT-001")
        self.assertEqual(asset.name, "更新後名稱")
        self.assertEqual(asset.brand, "ASUS")
        self.assertEqual(asset.created_by, self.manager)
        self.assertEqual(asset.created_at, original_created_at)
        self.assertEqual(asset.updated_by, second_manager)
        self.assertGreaterEqual(asset.updated_at, asset.created_at)

    def test_regular_user_cannot_edit_asset(self):
        asset = Asset.objects.create(
            asset_no="EDIT-001",
            name="待編輯資產",
            category=Asset.Category.OTHER,
            department=self.it,
            purchase_date=date(2026, 8, 20),
            created_by=self.manager,
        )
        edit_url = reverse("asset_edit", args=[asset.pk])
        client = self._client_for(self.staff)
        self.assertEqual(client.get(edit_url).status_code, 403)
        self.assertEqual(client.post(edit_url, self._valid_data()).status_code, 403)
