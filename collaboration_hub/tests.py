from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import Client, TestCase
from django.urls import reverse

from organization.models import Department, UserProfile
from procurement.models import EquipmentApplication, EquipmentApplicationItem

from .models import CollaborationTask


class CollaborationTaskTests(TestCase):
    def setUp(self):
        self.management = Department.objects.create(name="管理與事業發展部")
        self.it = Department.objects.create(name="資訊部")
        self.business = Department.objects.create(name="都更事業部")
        self.manager = self._user("manager", self.management)
        self.it_user = self._user("it_user", self.it)
        self.business_user = self._user("business_user", self.business)
        self.application = EquipmentApplication.objects.create(
            case_no="260826001", department=self.business,
            applicant=self.business_user, need_date=date(2026, 9, 10),
            created_by=self.business_user, updated_by=self.business_user,
        )
        EquipmentApplicationItem.objects.create(
            application=self.application, equipment_name="工作站", quantity=2
        )

    def _user(self, username, department):
        user = User.objects.create_user(username, password="x")
        UserProfile.objects.create(user=user, department=department)
        return user

    def _client(self, user):
        client = Client()
        client.force_login(user)
        return client

    def _task(self, department=None, case_no="260826001", status="pending"):
        return CollaborationTask.objects.create(
            case_no=case_no,
            assigned_department=department or self.it,
            source_form=CollaborationTask.SourceForm.EQUIPMENT_APPLICATION,
            source_case_no=self.application.case_no,
            source_content_type=ContentType.objects.get_for_model(EquipmentApplication),
            source_object_id=self.application.pk,
            status=status,
            created_by=self.manager,
            updated_by=self.manager,
        )

    def test_navigation_and_department_scoped_task_list(self):
        task = self._task()
        response = self._client(self.it_user).get(reverse("collaboration_task_list"))
        self.assertContains(response, "協作專區")
        self.assertContains(response, task.case_no)
        self.assertContains(response, self.application.case_no)
        response = self._client(self.business_user).get(reverse("collaboration_task_list"))
        self.assertNotContains(response, task.case_no)
        response = self._client(self.manager).get(reverse("collaboration_task_list"))
        self.assertContains(response, task.case_no)

    def test_manager_sees_forward_action_and_staff_does_not(self):
        response = self._client(self.manager).get(reverse("equipment_procurement"))
        self.assertContains(response, reverse(
            "collaboration_forward_equipment", args=[self.application.pk]
        ))
        response = self._client(self.business_user).get(reverse("equipment_procurement"))
        self.assertNotContains(response, "data-collaboration-forward-url")

    def test_forward_modal_defaults_to_it_and_excludes_management(self):
        response = self._client(self.manager).get(
            reverse("collaboration_forward_equipment", args=[self.application.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "轉發設備需求")
        field = response.context["form"].fields["assigned_department"]
        self.assertEqual(response.context["form"].initial["assigned_department"], self.it)
        self.assertIn(self.it, field.queryset)
        self.assertNotIn(self.management, field.queryset)

    @patch("collaboration_hub.services.timezone.localdate", return_value=date(2026, 8, 26))
    def test_forward_creates_linked_task_and_sets_equipment_processing(self, _):
        response = self._client(self.manager).post(
            reverse("collaboration_forward_equipment", args=[self.application.pk]),
            {"assigned_department": self.it.pk},
        )
        self.assertRedirects(response, reverse("equipment_procurement"))
        task = CollaborationTask.objects.get()
        self.assertEqual(task.case_no, "260826001")
        self.assertEqual(task.assigned_department, self.it)
        self.assertEqual(task.status, "pending")
        self.assertEqual(task.source_form, "equipment_application")
        self.assertEqual(task.source_case_no, self.application.case_no)
        self.assertEqual(task.source_object, self.application)
        self.assertEqual(task.created_by, self.manager)
        self.assertEqual(task.updated_by, self.manager)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, "processing")
        self.assertEqual(self.application.updated_by, self.manager)

    def test_only_management_can_forward_and_invalid_target_changes_nothing(self):
        url = reverse("collaboration_forward_equipment", args=[self.application.pk])
        self.assertEqual(self._client(self.business_user).post(
            url, {"assigned_department": self.it.pk}
        ).status_code, 403)
        response = self._client(self.manager).post(
            url, {"assigned_department": self.management.pk}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CollaborationTask.objects.exists())
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, "pending")

    def test_duplicate_forward_is_blocked_but_action_remains_visible(self):
        self._task()
        self.application.status = "processing"
        self.application.save()
        url = reverse("collaboration_forward_equipment", args=[self.application.pk])
        response = self._client(self.manager).post(
            url, {"assigned_department": self.business.pk},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "不可重複轉發", status_code=422)
        self.assertEqual(CollaborationTask.objects.count(), 1)
        list_response = self._client(self.manager).get(reverse("equipment_procurement"))
        self.assertContains(list_response, f'data-collaboration-forward-url="{url}"', html=False)

    @patch("collaboration_hub.services.timezone.localdate", return_value=date(2026, 8, 26))
    def test_withdrawn_collaboration_can_be_forwarded_again(self, _):
        old_task = self._task(case_no="260825001", status="withdrawn")
        self.application.status = "processing"
        self.application.save()
        response = self._client(self.manager).post(
            reverse("collaboration_forward_equipment", args=[self.application.pk]),
            {"assigned_department": self.business.pk},
        )
        self.assertRedirects(response, reverse("equipment_procurement"))
        self.assertEqual(CollaborationTask.objects.count(), 2)
        new_task = CollaborationTask.objects.exclude(pk=old_task.pk).get()
        self.assertEqual(old_task.status, "withdrawn")
        self.assertEqual(new_task.status, "pending")
        self.assertEqual(new_task.assigned_department, self.business)
        self.assertEqual(new_task.case_no, "260826001")

    def test_closed_equipment_cannot_be_forwarded(self):
        self.application.status = "approved"
        self.application.save()
        response = self._client(self.manager).post(
            reverse("collaboration_forward_equipment", args=[self.application.pk]),
            {"assigned_department": self.it.pk},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 422)
        self.assertFalse(CollaborationTask.objects.exists())

    def test_assigned_department_can_view_source_but_other_department_cannot(self):
        task = self._task()
        response = self._client(self.it_user).get(
            reverse("collaboration_task_detail", args=[task.pk])
        )
        self.assertContains(response, "來源表單內容")
        self.assertContains(response, "工作站")
        self.assertContains(response, self.application.case_no)
        self.assertEqual(self._client(self.business_user).get(
            reverse("collaboration_task_detail", args=[task.pk])
        ).status_code, 403)
        self.assertContains(self._client(self.manager).get(
            reverse("collaboration_task_detail", args=[task.pk])
        ), "工作站")

    def test_detail_is_returned_as_modal_fragment(self):
        task = self._task()
        response = self._client(self.it_user).get(
            reverse("collaboration_task_detail", args=[task.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertContains(response, "來源表單內容")
        self.assertContains(response, "data-collaboration-task-close")
        self.assertNotContains(response, "<!doctype html>", html=False)
        list_response = self._client(self.it_user).get(reverse("collaboration_task_list"))
        self.assertContains(list_response, "data-collaboration-detail-url")
        self.assertContains(list_response, "data-collaboration-task-modal")

    def test_receiving_department_can_process_and_complete(self):
        task = self._task()
        processing_url = reverse("collaboration_task_processing", args=[task.pk])
        self.assertEqual(self._client(self.business_user).post(processing_url).status_code, 403)
        self.assertRedirects(
            self._client(self.it_user).post(processing_url),
            reverse("collaboration_task_list"),
        )
        task.refresh_from_db()
        self.assertEqual(task.status, "processing")
        self.assertEqual(task.updated_by, self.it_user)
        self.assertRedirects(
            self._client(self.it_user).post(
                reverse("collaboration_task_complete", args=[task.pk])
            ),
            reverse("collaboration_task_list"),
        )
        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        self.assertIsNotNone(task.closed_at)

    def test_receiver_returns_with_optional_reason_and_sender_can_see_it(self):
        task = self._task(status="processing")
        url = reverse("collaboration_task_return", args=[task.pk])
        modal = self._client(self.it_user).get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertContains(modal, "退回原因")
        self.assertContains(modal, "非必填")
        response = self._client(self.it_user).post(
            url, {"return_reason": "請補充預算來源"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.status, "returned")
        self.assertEqual(task.return_reason, "請補充預算來源")
        self.assertEqual(task.returned_by, self.it_user)
        self.assertIsNotNone(task.returned_at)
        sender_list = self._client(self.manager).get(reverse("collaboration_task_list"))
        self.assertContains(sender_list, "請補充預算來源")
        sender_detail = self._client(self.manager).get(
            reverse("collaboration_task_detail", args=[task.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertContains(sender_detail, "請補充預算來源")

    def test_return_reason_can_be_blank_and_stale_return_is_rejected(self):
        task = self._task()
        url = reverse("collaboration_task_return", args=[task.pk])
        self._client(self.it_user).post(url, {"return_reason": ""})
        task.refresh_from_db()
        self.assertEqual(task.status, "returned")
        self.assertEqual(task.return_reason, "")
        response = self._client(self.it_user).post(
            url, {"return_reason": "late"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "案件狀態已變更", status_code=409)

    def test_sender_can_withdraw_pending_or_returned_but_not_processing(self):
        task = self._task()
        url = reverse("collaboration_task_withdraw", args=[task.pk])
        self.assertEqual(self._client(self.it_user).post(url).status_code, 403)
        self.assertRedirects(self._client(self.manager).post(url), reverse("collaboration_task_list"))
        task.refresh_from_db()
        self.assertEqual(task.status, "withdrawn")
        self.assertIsNotNone(task.closed_at)

        task.status = "processing"
        task.closed_at = None
        task.save()
        self._client(self.manager).post(url)
        task.refresh_from_db()
        self.assertEqual(task.status, "processing")
        list_response = self._client(self.manager).get(reverse("collaboration_task_list"))
        self.assertContains(list_response, "data-collaboration-withdraw-confirm")
        self.assertNotContains(list_response, "confirm(")

    def test_statuses_are_ready_for_followup_workflow(self):
        self.assertEqual(
            dict(CollaborationTask.Status.choices),
            {
                "pending": "待處理", "processing": "處理中", "completed": "已完成",
                "returned": "已退回", "withdrawn": "已撤回",
            },
        )
