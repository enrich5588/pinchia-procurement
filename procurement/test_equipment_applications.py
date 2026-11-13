from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client
from organization.testing import OpenPanelsTestCase
from django.urls import reverse

from organization.models import Department, UserProfile

from .forms import EquipmentApplicationForm
from .models import EquipmentApplication, EquipmentApplicationItem


class EquipmentApplicationTests(OpenPanelsTestCase):
    def setUp(self):
        self.it = Department.objects.create(name="資訊部")
        self.business = Department.objects.create(name="都更事業部")
        self.management = Department.objects.create(name="管理與事業發展部")
        self.staff = self._user("staff", self.it)
        self.other = self._user("other", self.business)
        self.manager = self._user("manager", self.management)

    def _user(self, username, department):
        user = User.objects.create_user(username, password="x")
        UserProfile.objects.create(user=user, department=department)
        return user

    def _client(self, user):
        client = Client()
        client.force_login(user)
        return client

    def _data(self, **extra):
        data = {
            "need_date": "2026-09-10", "notes": "需支援雙螢幕",
            "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "1", "items-MAX_NUM_FORMS": "1000",
            "items-0-equipment_name": "筆記型電腦", "items-0-quantity": "2",
        }
        data.update(extra)
        return data

    def _application(self, applicant=None, status="pending", case_no="260826001"):
        applicant = applicant or self.staff
        application = EquipmentApplication.objects.create(
            case_no=case_no, department=applicant.profile.department,
            applicant=applicant, need_date=date(2026, 9, 10), status=status,
            created_by=applicant, updated_by=applicant,
        )
        EquipmentApplicationItem.objects.create(
            application=application, equipment_name="螢幕", quantity=1
        )
        return application

    @patch("procurement.services.timezone.localdate", return_value=date(2026, 8, 26))
    def test_create_uses_login_identity_audit_and_multiple_manual_items(self, _):
        data = self._data(**{
            "department": self.business.pk, "items-TOTAL_FORMS": "2",
            "items-1-equipment_name": "擴充基座", "items-1-quantity": "3",
        })
        response = self._client(self.staff).post(reverse("equipment_create"), data)
        self.assertRedirects(response, reverse("equipment_procurement"))
        application = EquipmentApplication.objects.get()
        self.assertEqual(application.case_no, "260826001")
        self.assertEqual(application.department, self.it)
        self.assertEqual(application.applicant, self.staff)
        self.assertEqual(application.created_by, self.staff)
        self.assertEqual(application.updated_by, self.staff)
        self.assertEqual(application.items.count(), 2)
        self.assertEqual(application.items.get(equipment_name="擴充基座").quantity, 3)

    def test_modal_starts_with_one_free_text_item_and_hides_server_fields(self):
        response = self._client(self.staff).get(
            reverse("equipment_create"), HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertContains(response, "data-add-equipment-item")
        self.assertContains(response, 'name="items-TOTAL_FORMS" value="1"', html=False)
        self.assertContains(response, 'name="items-0-equipment_name"', html=False)
        self.assertNotContains(response, "custom_name")
        form = EquipmentApplicationForm(department=self.it, applicant=self.staff)
        for field in ("department", "applicant", "case_no", "status", "created_by", "updated_by", "closed_at"):
            self.assertNotIn(field, form.fields)

    def test_list_scope_and_management_permissions(self):
        own = self._application()
        other = self._application(self.other, case_no="260826002")
        response = self._client(self.staff).get(reverse("equipment_procurement"))
        self.assertContains(response, own.case_no)
        self.assertNotContains(response, other.case_no)
        self.assertContains(response, reverse("equipment_create"))
        response = self._client(self.manager).get(reverse("equipment_procurement"))
        self.assertContains(response, own.case_no)
        self.assertContains(response, other.case_no)
        self.assertContains(response, "批量處理")
        self.assertNotContains(response, reverse("equipment_create"))
        self.assertEqual(self._client(self.manager).get(reverse("equipment_create")).status_code, 403)

    def test_returned_edit_resubmits_but_processing_cannot_be_changed(self):
        application = self._application(status="returned")
        item = application.items.get()
        data = self._data(**{
            "items-INITIAL_FORMS": "1", "items-0-id": str(item.pk),
            "items-0-equipment_name": "27 吋螢幕", "items-0-quantity": "2",
        })
        self.assertRedirects(
            self._client(self.staff).post(reverse("equipment_edit", args=[application.pk]), data),
            reverse("equipment_procurement"),
        )
        application.refresh_from_db()
        self.assertEqual(application.status, "pending")
        self.assertEqual(application.items.get().equipment_name, "27 吋螢幕")
        application.status = "processing"
        application.save()
        response = self._client(self.staff).post(
            reverse("equipment_edit", args=[application.pk]), data,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 409)
        self._client(self.staff).post(reverse("equipment_cancel", args=[application.pk]))
        application.refresh_from_db()
        self.assertEqual(application.status, "processing")

    def test_manager_transitions_and_completion_audit(self):
        application = self._application()
        processing = reverse("equipment_processing", args=[application.pk])
        self.assertEqual(self._client(self.staff).post(processing).status_code, 403)
        self._client(self.manager).post(processing)
        application.refresh_from_db()
        self.assertEqual(application.status, "processing")
        self._client(self.manager).post(reverse("equipment_return", args=[application.pk]))
        application.refresh_from_db()
        self.assertEqual(application.status, "returned")
        application.status = "pending"
        application.save()
        self._client(self.manager).post(
            reverse("equipment_complete", args=[application.pk]),
            {"asset_registration_reminder_confirmed": "1"},
        )
        application.refresh_from_db()
        self.assertEqual(application.status, "approved")
        self.assertEqual(application.approved_by, self.manager)
        self.assertEqual(application.updated_by, self.manager)
        self.assertIsNotNone(application.closed_at)

    def test_completion_uses_asset_registration_reminder_dialog(self):
        application = self._application()
        response = self._client(self.manager).get(reverse("equipment_procurement"))
        self.assertContains(response, "若有新增採購設備請記得完成資產登記")
        self.assertContains(response, "data-equipment-complete-confirm")
        self.assertContains(response, f'data-equipment-complete-url="{reverse("equipment_complete", args=[application.pk])}"', html=False)
        self.assertContains(response, "data-equipment-bulk-complete-url")
        self.assertContains(response, 'name="asset_registration_reminder_confirmed" value="1"', html=False)
        self.assertNotContains(response, "confirm(")

        self._client(self.manager).post(reverse("equipment_complete", args=[application.pk]))
        application.refresh_from_db()
        self.assertEqual(application.status, "pending")

    def test_cancel_and_batch_actions_are_atomic(self):
        cancelled = self._application()
        response = self._client(self.staff).get(reverse("equipment_procurement"))
        self.assertContains(response, "data-equipment-confirm")
        self._client(self.staff).post(reverse("equipment_cancel", args=[cancelled.pk]))
        cancelled.refresh_from_db()
        self.assertEqual(cancelled.status, "cancelled")
        first = self._application(case_no="260826002")
        second = self._application(case_no="260826003", status="processing")
        self._client(self.manager).post(reverse("equipment_bulk_complete"), {
            "application_ids": [first.pk, second.pk],
            "asset_registration_reminder_confirmed": "1",
        })
        first.refresh_from_db(); second.refresh_from_db()
        self.assertEqual({first.status, second.status}, {"approved"})
        valid = self._application(case_no="260826004")
        invalid = self._application(case_no="260826005", status="returned")
        response = self._client(self.manager).post(
            reverse("equipment_bulk_processing"),
            {"application_ids": [valid.pk, invalid.pk]}, follow=True,
        )
        valid.refresh_from_db(); invalid.refresh_from_db()
        self.assertEqual(valid.status, "pending")
        self.assertEqual(invalid.status, "returned")
        self.assertContains(response, "已全部取消")

    def test_detail_and_edit_are_owner_scoped(self):
        application = self._application()
        self.assertEqual(self._client(self.other).get(reverse("equipment_detail", args=[application.pk])).status_code, 403)
        self.assertEqual(self._client(self.other).get(reverse("equipment_edit", args=[application.pk])).status_code, 404)
        self.assertContains(self._client(self.manager).get(reverse("equipment_detail", args=[application.pk])), "螢幕")
