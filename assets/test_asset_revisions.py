from datetime import date
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.storage import FileSystemStorage
from django.test import TestCase
from django.urls import reverse

from organization.models import Department, UserProfile

from .models import Asset, AssetImage, AssetRegistration
from .test_images import picture


class AssetRevisionTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        storage_patch = patch.object(
            AssetImage._meta.get_field("image"), "storage",
            FileSystemStorage(location=directory.name),
        )
        storage_patch.start()
        self.addCleanup(storage_patch.stop)

        self.department = Department.objects.create(name="資訊部")
        self.management = Department.objects.create(name="管理部")
        self.staff = self.user("staff", self.department)
        self.peer = self.user("peer", self.department)
        self.manager = self.user("manager", self.management)
        self.asset = Asset.objects.create(
            asset_no="REV-001", name="原始筆電", category=Asset.Category.IT_EQUIPMENT,
            brand="ASUS", specification="Original", department=self.department,
            custodian=self.staff, purchase_date=date(2026, 9, 1), useful_life_years=5,
            notes="原始資料", created_by=self.manager,
        )
        self.original = AssetRegistration.objects.create(
            case_no="260901001", name=self.asset.name, category=self.asset.category,
            brand=self.asset.brand, specification=self.asset.specification,
            department=self.department, custodian=self.staff,
            purchase_date=self.asset.purchase_date, useful_life_years=5,
            notes=self.asset.notes, applicant=self.staff,
            status=AssetRegistration.Status.APPROVED, approved_by=self.manager,
            asset=self.asset,
        )
        self.image = AssetImage(asset=self.asset, registration=self.original)
        upload = picture("original.png")
        self.image.image.save(upload.name, upload, save=False)
        self.image.save()
        self.client.force_login(self.staff)

    def user(self, username, department):
        user = User.objects.create_user(username)
        UserProfile.objects.create(user=user, department=department)
        return user

    def revision_data(self, **overrides):
        data = {
            "name": "修改後筆電", "company": Asset.Company.PINJIA_CONSTRUCTION,
            "category": Asset.Category.IT_EQUIPMENT,
            "brand": "Lenovo", "specification": "Revised",
            "accessories": "新滑鼠", "quantity": 2,
            "unit_price": "40000.00", "business_tax": "2000.00",
            "department": self.department.pk,
            "custodian": self.staff.pk, "purchase_date": "2026-09-02",
            "useful_life_years": 4, "notes": "異動內容",
        }
        data.update(overrides)
        return data

    def create_revision(self, **overrides):
        response = self.client.post(
            reverse("registration_revise", args=[self.original.pk]),
            self.revision_data(**overrides),
        )
        self.assertRedirects(response, reverse("registration_list"))
        return AssetRegistration.objects.exclude(pk=self.original.pk).get()

    def test_approved_registration_can_create_revision_without_changing_asset(self):
        url = reverse("registration_revise", args=[self.original.pk])
        response = self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertContains(response, 'value="原始筆電"', html=False)
        self.assertContains(response, 'value="ASUS"', html=False)
        self.assertContains(response, "核准前")
        self.assertContains(response, reverse("asset_image", args=[self.image.pk]))

        revision = self.create_revision(
            images=[picture("new.png")], asset_images_to_remove=[self.image.pk]
        )
        self.asset.refresh_from_db()
        self.original.refresh_from_db()
        self.assertEqual(Asset.objects.count(), 1)
        self.assertEqual(self.asset.name, "原始筆電")
        self.assertEqual(self.original.status, AssetRegistration.Status.APPROVED)
        self.assertEqual(revision.status, AssetRegistration.Status.PENDING)
        self.assertEqual(revision.target_asset, self.asset)
        self.assertIsNone(revision.asset_id)
        self.assertEqual(list(revision.asset_images_to_remove.all()), [self.image])
        self.assertEqual(revision.images.count(), 1)
        self.assertIsNone(revision.images.get().asset_id)
        listing = self.client.get(reverse("registration_list"))
        self.assertContains(listing, "財產異動")
        self.assertContains(listing, "再次修改")

    def test_only_original_applicant_or_custodian_can_revise_approved_asset(self):
        url = reverse("registration_revise", args=[self.original.pk])
        self.client.force_login(self.peer)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.staff)
        self.original.status = AssetRegistration.Status.PENDING
        self.original.save(update_fields=["status"])
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_only_one_active_revision_exists_per_asset(self):
        revision = self.create_revision()
        response = self.client.get(reverse("registration_revise", args=[self.original.pk]))
        self.assertRedirects(response, reverse("registration_edit", args=[revision.pk]))
        self.assertEqual(self.asset.revision_registrations.count(), 1)

    def test_returned_revision_can_be_edited_without_touching_asset(self):
        revision = self.create_revision()
        revision.status = AssetRegistration.Status.RETURNED
        revision.save(update_fields=["status"])
        response = self.client.post(
            reverse("registration_edit", args=[revision.pk]),
            self.revision_data(name="再次修改"),
        )
        self.assertRedirects(response, reverse("registration_list"))
        revision.refresh_from_db()
        self.asset.refresh_from_db()
        self.assertEqual(revision.name, "再次修改")
        self.assertEqual(revision.status, AssetRegistration.Status.PENDING)
        self.assertEqual(self.asset.name, "原始筆電")

    def test_approval_overwrites_same_asset_and_applies_image_changes(self):
        revision = self.create_revision(
            images=[picture("new.png")], asset_images_to_remove=[self.image.pk]
        )
        self.client.force_login(self.manager)
        approve_url = reverse("registration_approve", args=[revision.pk])
        response = self.client.get(approve_url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertContains(response, "套用變更並核准")
        self.assertContains(response, 'value="REV-001"', html=False)
        self.assertContains(response, "申請移除的現有圖片")
        detail = self.client.get(
            reverse("registration_detail", args=[revision.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertContains(detail, "核准後移除的現有圖片")
        response = self.client.post(
            approve_url,
            self.revision_data(asset_no="TAMPERED", department=self.department.pk),
        )
        self.assertRedirects(response, reverse("registration_list"))

        revision.refresh_from_db()
        self.asset.refresh_from_db()
        self.image.refresh_from_db()
        self.assertEqual(Asset.objects.count(), 1)
        self.assertEqual(self.asset.pk, revision.target_asset_id)
        self.assertEqual(self.asset.asset_no, "REV-001")
        self.assertEqual(self.asset.name, "修改後筆電")
        self.assertEqual(self.asset.brand, "Lenovo")
        self.assertEqual(self.asset.updated_by, self.manager)
        self.assertEqual(revision.status, AssetRegistration.Status.APPROVED)
        self.assertIsNone(revision.asset_id)
        self.assertIsNone(self.image.asset_id)
        self.assertTrue(self.image.image.storage.exists(self.image.image.name))
        self.assertEqual(self.asset.images.count(), 1)
        self.assertEqual(self.asset.images.get().registration, revision)
        history = self.client.get(
            reverse("registration_detail", args=[revision.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertContains(history, reverse("registration_image", args=[self.image.pk]))

    def test_return_or_cancel_never_changes_asset(self):
        revision = self.create_revision()
        self.client.force_login(self.manager)
        self.client.post(reverse("registration_return", args=[revision.pk]))
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.name, "原始筆電")
        self.client.force_login(self.staff)
        self.client.post(reverse("registration_cancel", args=[revision.pk]))
        self.asset.refresh_from_db()
        revision.refresh_from_db()
        self.assertEqual(self.asset.name, "原始筆電")
        self.assertEqual(revision.status, AssetRegistration.Status.CANCELLED)

    def test_revision_requires_individual_approval(self):
        revision = self.create_revision()
        self.client.force_login(self.manager)
        listing = self.client.get(reverse("registration_list"))
        self.assertNotContains(listing, f'value="{revision.pk}"', html=False)
        response = self.client.post(
            reverse("registration_bulk_approve"), {"registration_ids": [revision.pk]},
            follow=True,
        )
        self.assertContains(response, "須逐筆檢視後核准")
        revision.refresh_from_db()
        self.assertEqual(revision.status, AssetRegistration.Status.PENDING)

    def test_asset_detail_offers_revision_only_to_original_applicant(self):
        url = reverse("asset_detail", args=[self.asset.pk])
        response = self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertContains(response, "申請修改")
        self.assertContains(response, reverse("asset_revise", args=[self.asset.pk]))
        self.client.force_login(self.peer)
        self.assertNotContains(
            self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest"), "申請修改"
        )

    def test_current_custodian_can_submit_revision_even_when_not_original_applicant(self):
        custodian_asset = Asset.objects.create(
            asset_no="REV-002", name="保管設備", category=Asset.Category.OTHER,
            department=self.department, custodian=self.peer,
            purchase_date=date(2026, 9, 3), created_by=self.manager,
        )
        AssetRegistration.objects.create(
            case_no="260903001", name=custodian_asset.name,
            category=custodian_asset.category, department=self.department,
            custodian=self.peer, purchase_date=custodian_asset.purchase_date,
            applicant=self.staff, status=AssetRegistration.Status.APPROVED,
            approved_by=self.manager, asset=custodian_asset,
        )
        self.client.force_login(self.peer)
        detail = self.client.get(
            reverse("asset_detail", args=[custodian_asset.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertContains(detail, "申請修改")
        revise_url = reverse("asset_revise", args=[custodian_asset.pk])
        response = self.client.post(
            revise_url,
            self.revision_data(
                name="保管人修改", category=Asset.Category.OTHER,
                custodian=self.peer.pk,
            ),
        )
        self.assertRedirects(response, reverse("registration_list"))
        revision = AssetRegistration.objects.get(target_asset=custodian_asset)
        self.assertEqual(revision.applicant, self.peer)
        custodian_asset.refresh_from_db()
        self.assertEqual(custodian_asset.name, "保管設備")
        self.assertEqual(
            self.client.post(reverse("asset_edit", args=[custodian_asset.pk]), {}).status_code,
            403,
        )

    def test_management_edits_directly_and_cannot_open_custodian_revision_form(self):
        self.client.force_login(self.manager)
        self.assertEqual(
            self.client.get(reverse("asset_revise", args=[self.asset.pk])).status_code,
            403,
        )
