from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from organization.models import Department, UserProfile

from .forms import OfficeSupplyApplicationForm
from .models import OfficeSupplyApplication, OfficeSupplyApplicationItem


class OfficeSupplyApplicationTests(TestCase):
    def setUp(self):
        self.it = Department.objects.create(name="資訊部")
        self.business = Department.objects.create(name="都更事業部")
        self.management = Department.objects.create(name="管理部")
        self.staff = self._user("staff", self.it)
        self.other = self._user("other", self.business)
        self.manager = self._user("manager", self.management)

    def _user(self, username, department):
        user = User.objects.create_user(username, password="x")
        UserProfile.objects.create(user=user, department=department)
        return user

    def _client(self, user):
        client = Client(); client.force_login(user); return client

    def _data(self, product="ballpoint_pen", custom_name="", quantity=2, **extra):
        data = {"need_date":"2026-08-30", "notes":"測試備註", "items-TOTAL_FORMS":"1", "items-INITIAL_FORMS":"0", "items-MIN_NUM_FORMS":"1", "items-MAX_NUM_FORMS":"1000", "items-0-product":product, "items-0-custom_name":custom_name, "items-0-quantity":str(quantity)}
        data.update(extra); return data

    def _application(self, applicant=None, status="pending", case_no="260824001"):
        applicant = applicant or self.staff
        application = OfficeSupplyApplication.objects.create(case_no=case_no, department=applicant.profile.department, applicant=applicant, need_date=date(2026,8,30), status=status, created_by=applicant, updated_by=applicant)
        OfficeSupplyApplicationItem.objects.create(application=application, product="ballpoint_pen", quantity=2)
        return application

    def _edit_data(self, application, **extra):
        item = application.items.get()
        return self._data(**{"items-INITIAL_FORMS":"1", "items-0-id":str(item.pk), **extra})

    def test_list_scope_and_application_button(self):
        own = self._application(); other = self._application(self.other, case_no="260824002")
        response = self._client(self.staff).get(reverse("supplies"))
        self.assertContains(response, own.case_no); self.assertNotContains(response, other.case_no); self.assertContains(response, reverse("supply_create"))
        response = self._client(self.manager).get(reverse("supplies"))
        self.assertContains(response, own.case_no); self.assertContains(response, other.case_no); self.assertNotContains(response, reverse("supply_create"))

    @patch("procurement.services.timezone.localdate", return_value=date(2026,8,24))
    def test_create_assigns_audit_case_and_multiple_items(self, _):
        data = self._data(**{"items-TOTAL_FORMS":"2", "items-1-product":"other", "items-1-custom_name":"白板筆", "items-1-quantity":"3", "department":self.business.pk})
        self.assertRedirects(self._client(self.staff).post(reverse("supply_create"), data), reverse("supplies"))
        application = OfficeSupplyApplication.objects.get()
        self.assertEqual(application.case_no, "260824001"); self.assertEqual(application.department, self.it); self.assertEqual(application.applicant, self.staff)
        self.assertEqual(application.created_by, self.staff); self.assertEqual(application.updated_by, self.staff); self.assertIsNotNone(application.created_at)
        self.assertEqual(application.items.count(), 2); self.assertEqual(application.items.get(product="other").display_name, "白板筆")

    def test_server_fields_hidden_and_other_requires_name(self):
        form = OfficeSupplyApplicationForm(department=self.it, applicant=self.staff)
        for name in ("case_no","department","applicant","status","created_by","created_at","updated_by","updated_at","closed_at","approved_by"):
            self.assertNotIn(name, form.fields)
        response = self._client(self.staff).post(reverse("supply_create"), self._data(product="other"))
        self.assertContains(response, "選擇其他時，請填寫物品名稱"); self.assertFalse(OfficeSupplyApplication.objects.exists())

    def test_modal_dynamic_items_and_product_options(self):
        response = self._client(self.staff).get(reverse("supply_create"), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertContains(response, "data-add-supply-item"); self.assertContains(response, "data-empty-supply-item")
        self.assertContains(response, 'name="items-TOTAL_FORMS" value="1"', html=False)
        self.assertEqual(response.content.decode().count('name="items-0-product"'), 1)
        for label in ("原子筆","自動鉛筆","自動鉛筆芯","橡皮擦","尺(15cm)","尺(30cm鐵尺)","釘書機","訂書針(盒)","小迴紋針(盒)","大迴紋針(盒)","膠帶","封箱膠帶","膠帶台","封箱膠帶台","L夾","其他"):
            self.assertContains(response, label)

    def test_custom_name_frontend_is_enabled_only_for_other(self):
        response = self._client(self.staff).get(
            reverse("supply_create"), HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        custom_widget = response.context["formset"].forms[0].fields["custom_name"].widget
        self.assertTrue(custom_widget.attrs["disabled"])
        other_response = self._client(self.staff).post(
            reverse("supply_create"), self._data(product="other"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        other_widget = other_response.context["formset"].forms[0].fields["custom_name"].widget
        self.assertNotIn("disabled", other_widget.attrs)

    def test_management_cannot_apply_and_other_cannot_edit(self):
        application = self._application()
        self.assertEqual(self._client(self.manager).get(reverse("supply_create")).status_code, 403)
        self.assertEqual(self._client(self.other).get(reverse("supply_edit", args=[application.pk])).status_code, 404)

    def test_returned_edit_resubmits_and_stale_edit_conflicts(self):
        application = self._application(status="returned")
        response = self._client(self.staff).post(reverse("supply_edit", args=[application.pk]), self._edit_data(application, need_date="2026-09-01", **{"items-0-quantity":"5"}))
        self.assertRedirects(response, reverse("supplies")); application.refresh_from_db()
        self.assertEqual(application.status, "pending"); self.assertEqual(application.items.get().quantity, 5)
        application.status = "approved"; application.save()
        response = self._client(self.staff).post(reverse("supply_edit", args=[application.pk]), self._edit_data(application), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 409); self.assertContains(response, "案件狀態已變更", status_code=409)

    def test_management_return_approve_and_permissions(self):
        application = self._application()
        processing_url = reverse("supply_processing", args=[application.pk])
        self.assertEqual(self._client(self.staff).post(processing_url).status_code, 403)
        self.assertRedirects(self._client(self.manager).post(processing_url), reverse("supplies"))
        application.refresh_from_db(); self.assertEqual(application.status, "processing")
        self.assertEqual(self._client(self.staff).get(reverse("supply_edit", args=[application.pk])).status_code, 403)
        self._client(self.staff).post(reverse("supply_cancel", args=[application.pk])); application.refresh_from_db()
        self.assertEqual(application.status, "processing")
        return_url = reverse("supply_return", args=[application.pk])
        self.assertEqual(self._client(self.staff).post(return_url).status_code, 403); self.assertRedirects(self._client(self.manager).post(return_url), reverse("supplies"))
        application.refresh_from_db(); self.assertEqual(application.status, "returned")
        application.status = "pending"; application.save()
        self.assertRedirects(self._client(self.manager).post(processing_url), reverse("supplies"))
        approve_url = reverse("supply_approve", args=[application.pk])
        self.assertEqual(self._client(self.staff).post(approve_url).status_code, 403); self.assertRedirects(self._client(self.manager).post(approve_url), reverse("supplies"))
        application.refresh_from_db(); self.assertEqual(application.status, "approved"); self.assertEqual(application.approved_by, self.manager); self.assertIsNotNone(application.closed_at)
        completed_list = self._client(self.manager).get(reverse("supplies"))
        self.assertContains(completed_list, "已提供")

    def test_cancel_closes_and_uses_custom_dialog(self):
        application = self._application(); list_response = self._client(self.staff).get(reverse("supplies"))
        self.assertContains(list_response, "data-supply-confirm"); self.assertNotContains(list_response, "confirm(")
        self.assertRedirects(self._client(self.staff).post(reverse("supply_cancel", args=[application.pk])), reverse("supplies"))
        application.refresh_from_db(); self.assertEqual(application.status, "cancelled"); self.assertIsNotNone(application.closed_at)
        self.assertEqual(self._client(self.staff).get(reverse("supply_edit", args=[application.pk])).status_code, 403)

    def test_bulk_complete_updates_all_and_staff_is_forbidden(self):
        first = self._application()
        second = self._application(case_no="260824002", status="processing")
        url = reverse("supply_bulk_complete")
        self.assertEqual(self._client(self.staff).post(url, {"application_ids":[first.pk]}).status_code, 403)
        response = self._client(self.manager).post(url, {"application_ids":[first.pk, second.pk]})
        self.assertRedirects(response, reverse("supplies"))
        first.refresh_from_db(); second.refresh_from_db()
        self.assertEqual({first.status, second.status}, {"approved"})
        self.assertTrue(first.closed_at and second.closed_at)
        self.assertEqual(first.approved_by, self.manager)

    def test_bulk_processing_updates_selected_and_is_atomic(self):
        first = self._application()
        second = self._application(case_no="260824002", status="processing")
        url = reverse("supply_bulk_processing")
        self.assertEqual(self._client(self.staff).post(url, {"application_ids":[first.pk]}).status_code, 403)
        self.assertRedirects(self._client(self.manager).post(url, {"application_ids":[first.pk, second.pk]}), reverse("supplies"))
        first.refresh_from_db(); second.refresh_from_db()
        self.assertEqual({first.status, second.status}, {"processing"})
        third = self._application(case_no="260824003", status="returned")
        response = self._client(self.manager).post(url, {"application_ids":[first.pk, third.pk]}, follow=True)
        first.refresh_from_db(); third.refresh_from_db()
        self.assertEqual(first.status, "processing"); self.assertEqual(third.status, "returned")
        self.assertContains(response, "已全部取消")

    def test_bulk_return_cancels_whole_batch_when_one_status_changed(self):
        first = self._application()
        second = self._application(case_no="260824002", status="approved")
        response = self._client(self.manager).post(
            reverse("supply_bulk_return"), {"application_ids":[first.pk, second.pk]}, follow=True
        )
        first.refresh_from_db(); second.refresh_from_db()
        self.assertEqual(first.status, "pending")
        self.assertEqual(second.status, "approved")
        self.assertContains(response, "已全部取消")

    def test_manager_supply_list_has_bulk_controls_for_eligible_rows(self):
        application = self._application(status="processing")
        response = self._client(self.manager).get(reverse("supplies"))
        self.assertContains(response, "批量完成")
        self.assertContains(response, "批量處理")
        self.assertContains(response, "批量退回")
        self.assertContains(response, f'value="{application.pk}"', html=False)
