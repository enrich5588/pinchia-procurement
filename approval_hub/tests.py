from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from organization.testing import OpenPanelsTestCase
from django.urls import reverse
from django.utils import timezone

from organization.models import Department, UserProfile
from project_options.approvals import ApprovalAmountRange

from .models import ApprovalRequest, ApprovalStep
from .services import (
    ApprovalConfigurationError,
    ApprovalStateError,
    approver_usernames_for_amount_range,
    create_approval_request,
    decide_approval,
    resubmit_approval_request,
    withdraw_approval,
)


class ApprovalWorkflowTests(OpenPanelsTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.department = Department.objects.create(name="測試部")
        User = get_user_model()
        cls.applicant = User.objects.create_user("applicant", password="demo")
        cls.other = User.objects.create_user("other", password="demo")
        UserProfile.objects.create(user=cls.applicant, department=cls.department)
        UserProfile.objects.create(user=cls.other, department=cls.department)
        cls.approvers = {
            username: User.objects.create_user(username, password="demo")
            for username in ("wang", "kao", "gardine", "hu")
        }
        for user in cls.approvers.values():
            UserProfile.objects.create(user=user, department=cls.department)

    def create_request(self, amount_range=ApprovalAmountRange.FROM_40001, document_type=""):
        return create_approval_request(
            applicant=self.applicant, department=self.department,
            subject="設備更新簽呈", content="汰換老舊設備",
            amount_range=amount_range, document_type=document_type,
        )

    def test_amount_ranges_select_exact_sequential_route(self):
        cases = {
            ApprovalAmountRange.UP_TO_10000: ("wang",),
            ApprovalAmountRange.FROM_10001_TO_20000: ("wang", "kao"),
            ApprovalAmountRange.FROM_20001_TO_40000: ("wang", "kao", "gardine"),
            ApprovalAmountRange.FROM_40001: ("wang", "kao", "gardine", "hu"),
        }
        for amount_range, expected in cases.items():
            with self.subTest(amount_range=amount_range):
                self.assertEqual(approver_usernames_for_amount_range(amount_range), expected)

    def test_submission_freezes_route_and_audit_fields(self):
        approval = self.create_request(
            ApprovalAmountRange.FROM_20001_TO_40000, "urgent"
        )
        steps = list(approval.steps.select_related("approver"))
        self.assertEqual([step.approver.username for step in steps], ["wang", "kao", "gardine"])
        self.assertEqual([step.status for step in steps], ["pending", "waiting", "waiting"])
        self.assertEqual(approval.created_by, self.applicant)
        self.assertEqual(approval.updated_by, self.applicant)
        self.assertEqual(approval.document_type, "urgent")
        self.assertIsNotNone(approval.created_at)
        self.assertRegex(approval.case_no, r"^\d{9}$")

    def test_approval_advances_in_order_and_final_approval_closes(self):
        approval = self.create_request(ApprovalAmountRange.FROM_10001_TO_20000)
        with self.assertRaises(ApprovalStateError):
            decide_approval(request_id=approval.pk, approver=self.approvers["kao"], approve=True)
        decide_approval(
            request_id=approval.pk, approver=self.approvers["wang"],
            approve=True, comment="第一關同意",
        )
        approval.refresh_from_db()
        self.assertEqual(approval.current_step, 2)
        self.assertEqual(approval.status, ApprovalRequest.Status.PENDING)
        self.assertEqual(approval.steps.get(sequence=2).status, ApprovalStep.Status.PENDING)
        decide_approval(request_id=approval.pk, approver=self.approvers["kao"], approve=True)
        approval.refresh_from_db()
        self.assertEqual(approval.status, ApprovalRequest.Status.APPROVED)
        self.assertIsNotNone(approval.closed_at)

    def test_return_stops_later_steps(self):
        approval = self.create_request(ApprovalAmountRange.FROM_40001)
        decide_approval(
            request_id=approval.pk, approver=self.approvers["wang"],
            approve=False, comment="資料不足",
        )
        approval.refresh_from_db()
        self.assertEqual(approval.status, ApprovalRequest.Status.RETURNED)
        self.assertEqual(approval.steps.get(sequence=1).comment, "資料不足")
        self.assertEqual(approval.steps.get(sequence=2).status, ApprovalStep.Status.WAITING)
        with self.assertRaises(ApprovalStateError):
            decide_approval(request_id=approval.pk, approver=self.approvers["wang"], approve=True)

    def test_returned_request_can_be_edited_and_resubmitted_without_losing_history(self):
        approval = self.create_request(ApprovalAmountRange.FROM_40001)
        case_no = approval.case_no
        decide_approval(
            request_id=approval.pk, approver=self.approvers["wang"],
            approve=False, comment="請補充資料",
        )
        resubmit_approval_request(
            request_id=approval.pk, applicant=self.applicant,
            subject="補充後簽呈", content="已補充",
            amount_range=ApprovalAmountRange.FROM_10001_TO_20000,
            document_type="urgent",
        )
        approval.refresh_from_db()
        self.assertEqual(approval.case_no, case_no)
        self.assertEqual(approval.revision, 2)
        self.assertEqual(approval.status, ApprovalRequest.Status.PENDING)
        self.assertEqual(approval.subject, "補充後簽呈")
        self.assertEqual(approval.document_type, "urgent")
        self.assertEqual(
            list(approval.steps.filter(round_number=1).values_list("status", flat=True)),
            ["returned", "waiting", "waiting", "waiting"],
        )
        self.assertEqual(
            list(approval.steps.filter(round_number=2).values_list(
                "approver__username", "status"
            )),
            [("wang", "pending"), ("kao", "waiting")],
        )

    def test_resubmission_starts_at_the_supervisor_who_returned_it(self):
        approval = self.create_request(ApprovalAmountRange.FROM_40001)
        decide_approval(
            request_id=approval.pk, approver=self.approvers["wang"], approve=True
        )
        decide_approval(
            request_id=approval.pk, approver=self.approvers["kao"], approve=True
        )
        decide_approval(
            request_id=approval.pk, approver=self.approvers["gardine"],
            approve=False, comment="請修正內容",
        )
        self.client.force_login(self.applicant)
        preview = self.client.get(
            reverse("approval_resubmit", args=[approval.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertContains(preview, "wang（已核准）")
        self.assertContains(preview, "kao（已核准）")
        self.assertContains(preview, "gardine → hu")
        self.assertNotContains(preview, "wang → kao → gardine → hu")
        resubmit_approval_request(
            request_id=approval.pk, applicant=self.applicant,
            subject="修正版", content="已修正",
            amount_range=ApprovalAmountRange.FROM_40001,
        )
        approval.refresh_from_db()
        self.assertEqual(approval.current_step, 3)
        self.assertEqual(
            list(approval.steps.filter(round_number=2).values_list(
                "approver__username", "status"
            )),
            [
                ("wang", "approved"), ("kao", "approved"),
                ("gardine", "pending"), ("hu", "waiting"),
            ],
        )
        self.assertEqual(
            list(approval.steps.filter(round_number=1).values_list(
                "approver__username", "status"
            )),
            [
                ("wang", "approved"), ("kao", "approved"),
                ("gardine", "returned"), ("hu", "waiting"),
            ],
        )
        self.client.force_login(self.applicant)
        self.assertContains(
            self.client.get(reverse("approval_list")), "第 3／4 關"
        )

    def test_only_applicant_can_withdraw_pending_request(self):
        approval = self.create_request()
        with self.assertRaises(ApprovalStateError):
            withdraw_approval(request_id=approval.pk, applicant=self.other)
        withdraw_approval(request_id=approval.pk, applicant=self.applicant)
        approval.refresh_from_db()
        self.assertEqual(approval.status, ApprovalRequest.Status.WITHDRAWN)
        with self.assertRaises(ApprovalStateError):
            withdraw_approval(request_id=approval.pk, applicant=self.applicant)

    def test_missing_configured_approver_prevents_submission(self):
        self.approvers["hu"].is_active = False
        self.approvers["hu"].save(update_fields=["is_active"])
        with self.assertRaises(ApprovalConfigurationError):
            self.create_request(ApprovalAmountRange.FROM_40001)
        self.assertFalse(ApprovalRequest.objects.exists())


class ApprovalViewTests(ApprovalWorkflowTests):
    def test_create_uses_logged_in_identity_and_department(self):
        self.client.force_login(self.applicant)
        response = self.client.post(reverse("approval_create"), {
            "subject": "年度軟體授權", "content": "續約",
            "amount_range": ApprovalAmountRange.FROM_10001_TO_20000,
            "document_type": "",
            "department": "999", "applicant": self.other.pk,
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        approval = ApprovalRequest.objects.get()
        self.assertEqual(approval.applicant, self.applicant)
        self.assertEqual(approval.department, self.department)
        self.assertEqual(approval.amount_range, ApprovalAmountRange.FROM_10001_TO_20000)
        self.assertEqual(approval.document_type, "")

    def test_unrelated_user_cannot_view_request(self):
        approval = self.create_request()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("approval_detail", args=[approval.pk])).status_code, 403)
        self.assertNotContains(self.client.get(reverse("approval_list")), approval.case_no)

    def test_current_approver_can_act_but_future_approver_cannot(self):
        approval = self.create_request(ApprovalAmountRange.FROM_10001_TO_20000)
        self.client.force_login(self.approvers["kao"])
        self.assertEqual(
            self.client.post(reverse("approval_approve", args=[approval.pk]), {"comment": "搶先簽"}).status_code,
            403,
        )
        self.client.force_login(self.approvers["wang"])
        response = self.client.post(
            reverse("approval_approve", args=[approval.pk]), {"comment": "同意"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"success": True, "redirect_url": reverse("approval_list")})

    def test_decision_confirmation_is_modal_only(self):
        approval = self.create_request(ApprovalAmountRange.FROM_10001_TO_20000)
        self.client.force_login(self.approvers["wang"])
        decision_url = reverse("approval_approve", args=[approval.pk])
        regular_response = self.client.get(decision_url)
        self.assertRedirects(regular_response, reverse("approval_list"))
        modal_response = self.client.get(
            decision_url, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(modal_response.status_code, 200)
        self.assertContains(modal_response, "核准簽呈")
        self.assertNotContains(modal_response, "<!doctype html>")

    def test_only_applicant_can_open_resubmit_and_stale_status_is_rejected(self):
        approval = self.create_request()
        decide_approval(
            request_id=approval.pk, approver=self.approvers["wang"], approve=False
        )
        url = reverse("approval_resubmit", args=[approval.pk])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 403)

        self.client.force_login(self.applicant)
        modal = self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertContains(modal, "修改並重送簽呈")
        self.assertContains(modal, "設備更新簽呈")

        ApprovalRequest.objects.filter(pk=approval.pk).update(
            status=ApprovalRequest.Status.APPROVED
        )
        response = self.client.post(url, {
            "subject": "不應送出", "content": "狀態已變更",
            "amount_range": ApprovalAmountRange.UP_TO_10000,
            "document_type": "",
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 409)
        approval.refresh_from_db()
        self.assertEqual(approval.revision, 1)
        self.assertNotEqual(approval.subject, "不應送出")

    def test_create_modal_exposes_amount_route_preview(self):
        self.client.force_login(self.applicant)
        response = self.client.get(reverse("approval_create"), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertContains(response, "預計簽核路徑")
        self.assertContains(response, "wang → kao → gardine → hu")
        self.assertEqual(response.context["form"]["amount_range"].value(), "up_to_10000")
        self.assertContains(response, "--------")

        self.client.force_login(self.approvers["kao"])
        manager_response = self.client.get(
            reverse("approval_create"), HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertContains(manager_response, "依主管權限自動核准")
        self.assertContains(manager_response, "gardine → hu")

    def test_request_becomes_visible_to_approvers_one_step_at_a_time(self):
        approval = self.create_request(ApprovalAmountRange.FROM_40001)
        self.client.force_login(self.applicant)
        self.assertContains(self.client.get(reverse("approval_list")), approval.case_no)
        self.assertContains(self.client.get(reverse("approval_list")), "第 1／4 關")

        self.client.force_login(self.approvers["wang"])
        self.assertContains(self.client.get(reverse("approval_list")), approval.case_no)
        for username in ("kao", "gardine", "hu"):
            self.client.force_login(self.approvers[username])
            self.assertNotContains(self.client.get(reverse("approval_list")), approval.case_no)
            self.assertEqual(
                self.client.get(reverse("approval_detail", args=[approval.pk])).status_code,
                403,
            )

        decide_approval(
            request_id=approval.pk, approver=self.approvers["wang"], approve=True
        )
        for username in ("wang", "kao"):
            self.client.force_login(self.approvers[username])
            self.assertContains(self.client.get(reverse("approval_list")), approval.case_no)
        for username in ("gardine", "hu"):
            self.client.force_login(self.approvers[username])
            self.assertNotContains(self.client.get(reverse("approval_list")), approval.case_no)

        delivered_to_kao = ApprovalRequest.objects.get(pk=approval.pk).delivered_at
        decide_approval(
            request_id=approval.pk, approver=self.approvers["kao"], approve=True
        )
        approval.refresh_from_db()
        self.assertGreaterEqual(approval.delivered_at, delivered_to_kao)
        self.client.force_login(self.approvers["gardine"])
        self.assertContains(self.client.get(reverse("approval_list")), approval.case_no)
        self.client.force_login(self.approvers["hu"])
        self.assertNotContains(self.client.get(reverse("approval_list")), approval.case_no)

    def test_manager_requests_use_only_higher_approval_levels(self):
        direct_cases = (
            ("wang", ApprovalAmountRange.UP_TO_10000),
            ("kao", ApprovalAmountRange.FROM_10001_TO_20000),
            ("gardine", ApprovalAmountRange.FROM_20001_TO_40000),
            ("hu", ApprovalAmountRange.FROM_40001),
        )
        for username, amount_range in direct_cases:
            with self.subTest(username=username):
                request = create_approval_request(
                    applicant=self.approvers[username], department=self.department,
                    subject="權限內簽呈", content="測試",
                    amount_range=amount_range,
                )
                self.assertEqual(request.status, ApprovalRequest.Status.APPROVED)
                step = request.steps.get()
                self.assertEqual(step.approver.username, username)
                self.assertEqual(step.status, ApprovalStep.Status.APPROVED)

        request = create_approval_request(
            applicant=self.approvers["kao"], department=self.department,
            subject="五萬元簽呈", content="測試",
            amount_range=ApprovalAmountRange.FROM_40001,
        )
        self.assertEqual(request.status, ApprovalRequest.Status.PENDING)
        self.assertEqual(
            list(request.steps.values_list("approver__username", flat=True)),
            ["gardine", "hu"],
        )

    def test_pending_queue_orders_by_document_priority_then_delivery_time(self):
        approved = self.create_request(ApprovalAmountRange.UP_TO_10000)
        decide_approval(
            request_id=approved.pk, approver=self.approvers["wang"], approve=True
        )
        ordinary = self.create_request(document_type="ordinary")
        blank = self.create_request(document_type="")
        urgent_newer = self.create_request(document_type="urgent")
        urgent_older = self.create_request(document_type="urgent")
        confidential = self.create_request(document_type="confidential")
        now = timezone.now()
        ApprovalRequest.objects.filter(pk=urgent_older.pk).update(
            delivered_at=now - timedelta(hours=2)
        )
        ApprovalRequest.objects.filter(pk=urgent_newer.pk).update(
            delivered_at=now - timedelta(hours=1)
        )

        self.client.force_login(self.applicant)
        response = self.client.get(reverse("approval_list"))
        ordered_ids = [item.pk for item in response.context["approvals"]]
        self.assertEqual(
            ordered_ids,
            [urgent_older.pk, urgent_newer.pk, confidential.pk, ordinary.pk, blank.pk, approved.pk],
        )
