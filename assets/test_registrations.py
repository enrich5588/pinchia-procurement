from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from organization.models import Department, UserProfile

from .forms import AssetRegistrationForm
from .models import Asset, AssetRegistration


class AssetRegistrationTests(TestCase):
    def setUp(self):
        self.it = Department.objects.create(name="資訊部")
        self.business = Department.objects.create(name="都更事業部")
        self.management = Department.objects.create(name="管理與事業發展部")
        self.staff = self._user("staff", self.it)
        self.other_staff = self._user("other", self.business)
        self.manager = self._user("manager", self.management)

    def _user(self, username, department):
        user = User.objects.create_user(username, password="x")
        UserProfile.objects.create(user=user, department=department)
        return user

    def _client(self, user):
        client = Client()
        client.force_login(user)
        return client

    def _data(self, **overrides):
        data = {
            "name": "申請筆電", "company": Asset.Company.PINJIA_ASSET,
            "category": Asset.Category.IT_EQUIPMENT,
            "brand": "ASUS", "specification": "ExampleBook 14", "custodian": self.staff.pk,
            "accessories": "變壓器", "quantity": 1,
            "unit_price": "20000.00", "business_tax": "1000.00",
            "department": self.it.pk,
            "purchase_date": "2026-08-21", "useful_life_years": 5,
            "notes": "保固三年",
        }
        data.update(overrides)
        return data

    def _registration(self, applicant=None, status=AssetRegistration.Status.PENDING, case_no="260821001"):
        applicant = applicant or self.staff
        department = applicant.profile.department
        return AssetRegistration.objects.create(
            case_no=case_no, name="申請筆電", company=Asset.Company.PINJIA_ASSET,
            category=Asset.Category.IT_EQUIPMENT, brand="ASUS",
            specification="ExampleBook 14", accessories="變壓器", quantity=1,
            unit_price="20000.00", business_tax="1000.00", department=department,
            custodian=applicant, purchase_date=date(2026, 8, 21),
            applicant=applicant, status=status,
        )

    def test_navigation_and_list_require_login(self):
        response = Client().get(reverse("registration_list"))
        self.assertRedirects(response, f"/accounts/login/?next={reverse('registration_list')}")
        response = self._client(self.staff).get(reverse("registration_list"))
        self.assertContains(response, "資產登記")
        self.assertContains(response, reverse("registration_create"))

    def test_staff_sees_only_own_requests_while_management_sees_all(self):
        own = self._registration()
        other = self._registration(self.other_staff, case_no="260821002")
        staff_response = self._client(self.staff).get(reverse("registration_list"))
        self.assertContains(staff_response, own.case_no)
        self.assertNotContains(staff_response, other.case_no)
        manager_response = self._client(self.manager).get(reverse("registration_list"))
        self.assertContains(manager_response, own.case_no)
        self.assertContains(manager_response, other.case_no)

    @patch("assets.services.timezone.localdate", return_value=date(2026, 8, 21))
    def test_create_assigns_department_audit_status_and_daily_case_number(self, _):
        client = self._client(self.staff)
        first = client.post(reverse("registration_create"), self._data())
        second = client.post(reverse("registration_create"), self._data(name="第二件"))
        self.assertRedirects(first, reverse("registration_list"))
        self.assertRedirects(second, reverse("registration_list"))
        registrations = list(AssetRegistration.objects.order_by("case_no"))
        self.assertEqual([item.case_no for item in registrations], ["260821001", "260821002"])
        self.assertTrue(all(item.brand == "ASUS" for item in registrations))
        self.assertTrue(all(item.company == Asset.Company.PINJIA_ASSET for item in registrations))
        self.assertTrue(all(str(item.total) == "21000.00" for item in registrations))
        self.assertTrue(all(item.department == self.it for item in registrations))
        self.assertTrue(all(item.applicant == self.staff for item in registrations))
        self.assertTrue(all(item.status == AssetRegistration.Status.PENDING for item in registrations))
        self.assertTrue(all(item.applied_at and item.modified_at for item in registrations))

    def test_department_is_editable_and_wrong_custodian_is_rejected(self):
        form = AssetRegistrationForm(department=self.it)
        self.assertIn("department", form.fields)
        self.assertEqual(form.initial["department"], self.it.pk)
        for hidden_name in (
            "case_no", "status", "applied_at", "applicant",
            "modified_at", "closed_at", "approved_by", "asset",
        ):
            self.assertNotIn(hidden_name, form.fields)
        response = self._client(self.staff).post(
            reverse("registration_create"), self._data(custodian=self.other_staff.pk)
        )
        self.assertContains(response, "errorlist")
        self.assertFalse(AssetRegistration.objects.exists())

    def test_staff_can_select_another_department_and_matching_custodian(self):
        response = self._client(self.staff).post(
            reverse("registration_create"),
            self._data(department=self.business.pk, custodian=self.other_staff.pk),
        )
        self.assertRedirects(response, reverse("registration_list"))
        registration = AssetRegistration.objects.get()
        self.assertEqual(registration.department, self.business)
        self.assertEqual(registration.custodian, self.other_staff)

    def test_staff_can_register_shared_department_asset_without_custodian(self):
        response = self._client(self.staff).post(
            reverse("registration_create"), self._data(custodian="")
        )
        self.assertRedirects(response, reverse("registration_list"))
        registration = AssetRegistration.objects.get()
        self.assertIsNone(registration.custodian)
        list_response = self._client(self.staff).get(reverse("registration_list"))
        self.assertContains(list_response, "部門資產")
        detail_response = self._client(self.staff).get(
            reverse("registration_detail", args=[registration.pk])
        )
        self.assertContains(detail_response, "部門資產（共用資源）")

    def test_shared_department_asset_stays_unassigned_after_approval(self):
        self._client(self.staff).post(
            reverse("registration_create"), self._data(custodian="")
        )
        registration = AssetRegistration.objects.get()
        response = self._client(self.manager).post(
            reverse("registration_approve", args=[registration.pk]),
            self._data(asset_no="SHARED-001", custodian=""),
        )
        self.assertRedirects(response, reverse("registration_list"))
        registration.refresh_from_db()
        self.assertIsNone(registration.custodian)
        self.assertIsNone(registration.asset.custodian)

    def test_custodian_options_endpoint_filters_by_department(self):
        response = self._client(self.staff).get(
            reverse("registration_custodians"), {"department": self.business.pk}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["custodians"], [
            {"id": self.other_staff.pk, "label": self.other_staff.username}
        ])

    def test_specification_is_optional(self):
        data = self._data(specification="")
        response = self._client(self.staff).post(reverse("registration_create"), data)
        self.assertRedirects(response, reverse("registration_list"))
        self.assertEqual(AssetRegistration.objects.get().specification, "")

    def test_brand_is_optional(self):
        response = self._client(self.staff).post(
            reverse("registration_create"), self._data(brand="")
        )
        self.assertRedirects(response, reverse("registration_list"))
        self.assertEqual(AssetRegistration.objects.get().brand, "")

    def test_management_cannot_create_and_other_employee_cannot_edit(self):
        item = self._registration()
        self.assertEqual(self._client(self.manager).get(reverse("registration_create")).status_code, 403)
        self.assertEqual(self._client(self.other_staff).get(reverse("registration_edit", args=[item.pk])).status_code, 404)

    def test_returned_request_can_be_edited_and_becomes_pending(self):
        item = self._registration(status=AssetRegistration.Status.RETURNED)
        response = self._client(self.staff).post(
            reverse("registration_edit", args=[item.pk]), self._data(name="修改後")
        )
        self.assertRedirects(response, reverse("registration_list"))
        item.refresh_from_db()
        self.assertEqual(item.name, "修改後")
        self.assertEqual(item.status, AssetRegistration.Status.PENDING)

    def test_edit_rechecks_database_status_and_returns_conflict(self):
        item = self._registration(status=AssetRegistration.Status.APPROVED)
        response = self._client(self.staff).post(
            reverse("registration_edit", args=[item.pk]), self._data(name="不應儲存"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "案件狀態已變更", status_code=409)
        item.refresh_from_db()
        self.assertNotEqual(item.name, "不應儲存")

    def test_employee_cancel_closes_request_and_closed_request_is_read_only(self):
        item = self._registration()
        response = self._client(self.staff).post(reverse("registration_cancel", args=[item.pk]))
        self.assertRedirects(response, reverse("registration_list"))
        item.refresh_from_db()
        self.assertEqual(item.status, AssetRegistration.Status.CANCELLED)
        self.assertIsNotNone(item.closed_at)
        self.assertEqual(self._client(self.staff).get(reverse("registration_edit", args=[item.pk])).status_code, 403)
        detail = self._client(self.staff).get(reverse("registration_detail", args=[item.pk]))
        self.assertEqual(detail.status_code, 200)

    def test_management_can_return_but_staff_cannot(self):
        item = self._registration()
        url = reverse("registration_return", args=[item.pk])
        self.assertEqual(self._client(self.staff).post(url).status_code, 403)
        self.assertRedirects(self._client(self.manager).post(url), reverse("registration_list"))
        item.refresh_from_db()
        self.assertEqual(item.status, AssetRegistration.Status.RETURNED)

    def test_approve_prefills_asset_form_and_atomically_creates_asset_and_closes(self):
        item = self._registration()
        approve_url = reverse("registration_approve", args=[item.pk])
        get_response = self._client(self.manager).get(
            approve_url, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertContains(get_response, 'value="ASUS"', html=False)
        self.assertContains(get_response, 'value="申請筆電"', html=False)
        self.assertContains(get_response, 'value="2026-08-21"', html=False)
        data = self._data(asset_no="NEW-001", department=self.it.pk)
        response = self._client(self.manager).post(approve_url, data)
        self.assertRedirects(response, reverse("registration_list"))
        item.refresh_from_db()
        asset = Asset.objects.get(asset_no="NEW-001")
        self.assertEqual(item.status, AssetRegistration.Status.APPROVED)
        self.assertEqual(item.approved_by, self.manager)
        self.assertEqual(item.asset, asset)
        self.assertEqual(asset.brand, "ASUS")
        self.assertEqual(asset.company, Asset.Company.PINJIA_ASSET)
        self.assertEqual(asset.accessories, "變壓器")
        self.assertEqual(asset.quantity, 1)
        self.assertEqual(str(asset.total), "21000.00")
        self.assertIsNotNone(item.closed_at)
        self.assertEqual(asset.created_by, self.manager)

    def test_non_manager_cannot_approve_and_approved_cannot_be_approved_twice(self):
        item = self._registration()
        url = reverse("registration_approve", args=[item.pk])
        self.assertEqual(self._client(self.staff).get(url).status_code, 403)
        item.status = AssetRegistration.Status.APPROVED
        item.save()
        self.assertEqual(self._client(self.manager).get(url).status_code, 403)

    def test_cancel_uses_custom_confirmation_dialog(self):
        item = self._registration()
        response = self._client(self.staff).get(reverse("registration_list"))
        self.assertContains(response, "data-registration-confirm")
        self.assertContains(response, reverse("registration_cancel", args=[item.pk]))
        self.assertNotContains(response, "confirm(")

    def test_management_bulk_return_is_atomic_and_staff_is_forbidden(self):
        first = self._registration()
        second = self._registration(case_no="260821002")
        url = reverse("registration_bulk_return")
        self.assertEqual(self._client(self.staff).post(url, {"registration_ids": [first.pk]}).status_code, 403)
        second.status = AssetRegistration.Status.APPROVED
        second.save()
        response = self._client(self.manager).post(url, {"registration_ids": [first.pk, second.pk]}, follow=True)
        first.refresh_from_db(); second.refresh_from_db()
        self.assertEqual(first.status, AssetRegistration.Status.PENDING)
        self.assertEqual(second.status, AssetRegistration.Status.APPROVED)
        self.assertContains(response, "已全部取消")
        second.status = AssetRegistration.Status.PENDING; second.save()
        self.assertRedirects(self._client(self.manager).post(url, {"registration_ids": [first.pk, second.pk]}), reverse("registration_list"))
        first.refresh_from_db(); second.refresh_from_db()
        self.assertEqual({first.status, second.status}, {AssetRegistration.Status.RETURNED})

    def test_bulk_approve_collects_numbers_and_creates_all_assets(self):
        first = self._registration()
        second = self._registration(case_no="260821002")
        url = reverse("registration_bulk_approve")
        prepare = self._client(self.manager).post(url, {"registration_ids": [first.pk, second.pk]})
        self.assertEqual(prepare.status_code, 200)
        self.assertContains(prepare, "批量核准資產登記")
        self.assertContains(prepare, first.case_no)
        commit = self._client(self.manager).post(url, {
            "commit": "1", "form-TOTAL_FORMS": "2", "form-INITIAL_FORMS": "2",
            "form-MIN_NUM_FORMS": "1", "form-MAX_NUM_FORMS": "1000",
            "form-0-registration_id": first.pk, "form-0-asset_no": "BULK-001",
            "form-1-registration_id": second.pk, "form-1-asset_no": "BULK-002",
        })
        self.assertRedirects(commit, reverse("registration_list"))
        first.refresh_from_db(); second.refresh_from_db()
        self.assertEqual(first.status, AssetRegistration.Status.APPROVED)
        self.assertEqual(second.status, AssetRegistration.Status.APPROVED)
        self.assertEqual(first.asset.brand, "ASUS")
        self.assertEqual(second.asset.brand, "ASUS")
        self.assertEqual(str(first.asset.total), "21000.00")
        self.assertEqual(str(second.asset.total), "21000.00")
        self.assertEqual({first.asset.asset_no, second.asset.asset_no}, {"BULK-001", "BULK-002"})

    def test_bulk_approve_rejects_duplicate_numbers_without_partial_creation(self):
        first = self._registration()
        second = self._registration(case_no="260821002")
        response = self._client(self.manager).post(reverse("registration_bulk_approve"), {
            "commit": "1", "form-TOTAL_FORMS": "2", "form-INITIAL_FORMS": "2",
            "form-MIN_NUM_FORMS": "1", "form-MAX_NUM_FORMS": "1000",
            "form-0-registration_id": first.pk, "form-0-asset_no": "SAME-001",
            "form-1-registration_id": second.pk, "form-1-asset_no": "same-001",
        })
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "不可重複", status_code=422)
        self.assertFalse(Asset.objects.filter(asset_no__iexact="SAME-001").exists())
        first.refresh_from_db(); second.refresh_from_db()
        self.assertEqual(first.status, AssetRegistration.Status.PENDING)
        self.assertEqual(second.status, AssetRegistration.Status.PENDING)

    def test_manager_list_has_bulk_selection_controls(self):
        item = self._registration()
        response = self._client(self.manager).get(reverse("registration_list"))
        self.assertContains(response, "批量核准")
        self.assertContains(response, "批量退回")
        self.assertContains(response, f'value="{item.pk}"', html=False)


class DatabaseMonitorTests(TestCase):
    def setUp(self):
        self.management = Department.objects.create(name="管理與事業發展部")
        self.it = Department.objects.create(name="資訊部")
        self.manager = User.objects.create_user("monitor_manager", password="x")
        self.staff = User.objects.create_user("monitor_staff", password="x")
        UserProfile.objects.create(user=self.manager, department=self.management)
        UserProfile.objects.create(user=self.staff, department=self.it)

    def _client(self, user):
        client = Client()
        client.force_login(user)
        return client

    def test_monitor_is_management_only_and_navigation_is_hidden_from_staff(self):
        url = reverse("database_monitor")
        self.assertEqual(self._client(self.staff).get(url).status_code, 403)
        self.assertNotContains(self._client(self.staff).get(reverse("asset_list")), url)
        self.assertContains(self._client(self.manager).get(reverse("asset_list")), url)

    def test_monitor_lists_tables_and_counts_without_writing(self):
        registration = AssetRegistration.objects.create(
            case_no="260824001", name="稽核用資產", category=Asset.Category.OTHER,
            specification="Audit Model", department=self.it, custodian=self.staff,
            purchase_date=date(2026, 8, 24), applicant=self.staff,
        )
        before = AssetRegistration.objects.count()
        response = self._client(self.manager).get(reverse("database_monitor"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "assets_assetregistration")
        self.assertContains(response, "唯讀")
        self.assertContains(response, "查看整張資料表")
        self.assertContains(response, "欄位名稱")
        self.assertContains(response, "case_no")
        self.assertContains(response, "主鍵")
        self.assertContains(response, "外鍵")
        self.assertContains(response, "共 1 筆")
        self.assertContains(response, "完整資料")
        self.assertContains(response, registration.case_no)
        self.assertContains(response, "applicant_id")
        self.assertContains(response, "monitor_staff")
        self.assertContains(response, "modified_at")
        self.assertContains(response, "後台紀錄")
        self.assertEqual(AssetRegistration.objects.count(), before)

    def test_invalid_refresh_interval_falls_back_to_fifteen_seconds(self):
        response = self._client(self.manager).get(
            reverse("database_monitor"), {"refresh": "1"}
        )
        self.assertEqual(response.context["refresh_seconds"], "15")
