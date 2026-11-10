from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from organization.models import Department, UserProfile
from .models import Asset, AssetImage, AssetRegistration
from .test_images import picture


class RegistrationImageTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        storage_patch = patch.object(AssetImage._meta.get_field("image"), "storage",
                                     FileSystemStorage(location=directory.name))
        storage_patch.start()
        self.addCleanup(storage_patch.stop)
        self.department = Department.objects.create(name="資訊部")
        management = Department.objects.create(name="管理部")
        self.staff = self.user("staff", self.department)
        self.peer = self.user("peer", self.department)
        self.manager = self.user("manager", management)
        self.client.force_login(self.staff)

    def user(self, name, department):
        user = User.objects.create_user(name)
        UserProfile.objects.create(user=user, department=department)
        return user

    def data(self, **overrides):
        data = {"name": "登記筆電", "company": Asset.Company.PINJIA_DEVELOPMENT,
                "category": Asset.Category.IT_EQUIPMENT, "quantity": 1,
                "department": self.department.pk,
                "custodian": self.staff.pk, "purchase_date": "2026-09-17"}
        data.update(overrides)
        return data

    def create(self):
        response = self.client.post(reverse("registration_create"), self.data(images=[picture(), picture()]))
        self.assertRedirects(response, reverse("registration_list"))
        return AssetRegistration.objects.latest("pk")

    def test_create_uploads_multiple_images_and_renders_form_and_detail(self):
        item = self.create()
        self.assertEqual(item.images.count(), 2)
        self.assertFalse(Asset.objects.exists())
        response = self.client.get(reverse("registration_detail", args=[item.pk]))
        self.assertContains(response, reverse("registration_image", args=[item.images.first().pk]))
        for modal in (False, True):
            headers = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"} if modal else {}
            response = self.client.get(reverse("registration_edit", args=[item.pk]), **headers)
            self.assertContains(response, 'enctype="multipart/form-data"')
            self.assertContains(response, 'name="images"')
            self.assertContains(response, "現有圖片")
            self.assertContains(response, "data-image-preview")

    def test_edit_preserves_appends_and_removes_images(self):
        item = self.create()
        first = item.images.first()
        item.status = AssetRegistration.Status.RETURNED
        item.save()
        url = reverse("registration_edit", args=[item.pk])
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, self.data(images=[picture()], remove_images=[first.pk]),
                                        HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertTrue(response.json()["success"])
        self.assertEqual(item.images.count(), 2)
        self.assertFalse(first.image.storage.exists(first.image.name))
        item.refresh_from_db()
        self.assertEqual(item.status, AssetRegistration.Status.PENDING)
        self.client.post(url, self.data())
        self.assertEqual(item.images.count(), 2)

    def test_invalid_batch_does_not_save_registration(self):
        response = self.client.post(reverse("registration_create"), self.data(images=[
            picture(), SimpleUploadedFile("fake.png", b"invalid", content_type="image/png"),
        ]), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 422)
        self.assertFalse(AssetRegistration.objects.exists())
        self.assertFalse(AssetImage.objects.exists())

    def test_images_are_private_to_applicant_and_management_before_approval(self):
        item = self.create()
        image = item.images.first()
        url = reverse("registration_image", args=[image.pk])
        for user in (self.staff, self.manager):
            self.client.force_login(user)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            response.close()
            self.assertEqual(self.client.get(reverse("asset_image", args=[image.pk])).status_code, 404)
        self.client.force_login(self.peer)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_single_approval_carries_images_and_asset_removal_preserves_application(self):
        item = self.create()
        self.client.force_login(self.manager)
        url = reverse("registration_approve", args=[item.pk])
        self.assertContains(self.client.get(url), "申請圖片")
        response = self.client.post(url, self.data(asset_no="REG-001", department=self.department.pk, images=[picture()]))
        self.assertRedirects(response, reverse("registration_list"))
        item.refresh_from_db()
        self.assertEqual(item.asset.images.count(), 3)
        image = item.images.first()
        self.client.post(reverse("asset_edit", args=[item.asset_id]), self.data(
            asset_no="REG-001", department=self.department.pk, remove_images=[image.pk],
        ))
        self.assertEqual(item.asset.images.count(), 2)
        self.assertEqual(item.images.count(), 2)
        self.assertTrue(image.image.storage.exists(image.image.name))

    def test_bulk_approval_carries_all_images(self):
        items = [self.create(), self.create()]
        self.client.force_login(self.manager)
        data = {"commit": "1", "form-TOTAL_FORMS": "2", "form-INITIAL_FORMS": "2"}
        for index, item in enumerate(items):
            data[f"form-{index}-registration_id"] = item.pk
            data[f"form-{index}-asset_no"] = f"BULK-{index}"
        response = self.client.post(reverse("registration_bulk_approve"), data)
        self.assertRedirects(response, reverse("registration_list"))
        for item in items:
            item.refresh_from_db()
            self.assertEqual(item.asset.images.count(), 2)

    def test_other_requests_images_cannot_be_removed(self):
        first, second = self.create(), self.create()
        response = self.client.post(reverse("registration_edit", args=[first.pk]),
                                    self.data(remove_images=[second.images.first().pk]),
                                    HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(AssetImage.objects.count(), 4)

    def test_closed_and_other_users_requests_cannot_change_images(self):
        item = self.create()
        url = reverse("registration_edit", args=[item.pk])
        self.client.force_login(self.peer)
        self.assertEqual(self.client.post(url, self.data(images=[picture()])).status_code, 404)
        self.client.force_login(self.staff)
        item.status = AssetRegistration.Status.CANCELLED
        item.save()
        response = self.client.post(url, self.data(images=[picture()], remove_images=[item.images.first().pk]),
                                    HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(item.images.count(), 2)
