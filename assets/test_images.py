from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
from django.contrib.auth.models import User
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from organization.testing import OpenPanelsTestCase
from django.urls import reverse

from organization.models import Department, UserProfile
from .models import Asset, AssetImage


def picture(name="photo.png"):
    data = BytesIO()
    Image.new("RGB", (20, 20), "blue").save(data, format="PNG")
    return SimpleUploadedFile(name, data.getvalue(), content_type="image/png")


class AssetImageTests(OpenPanelsTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        storage_patch = patch.object(
            AssetImage._meta.get_field("image"), "storage",
            FileSystemStorage(location=self.directory.name),
        )
        storage_patch.start()
        self.addCleanup(storage_patch.stop)
        self.management = Department.objects.create(name="管理與事業發展部")
        self.department = Department.objects.create(name="資訊部")
        self.other_department = Department.objects.create(name="其他部門")
        self.manager = self.user("manager", self.management)
        self.staff = self.user("staff", self.department)
        self.other = self.user("other", self.other_department)
        self.client.force_login(self.manager)

    def user(self, name, department):
        user = User.objects.create_user(name)
        UserProfile.objects.create(user=user, department=department)
        return user

    def data(self, **overrides):
        data = {
            "asset_no": "IMG-001", "name": "相機",
            "company": Asset.Company.PINJIA_DEVELOPMENT,
            "category": Asset.Category.OTHER, "quantity": 1,
            "department": self.department.pk, "purchase_date": "2026-09-17",
        }
        data.update(overrides)
        return data

    def create(self, **overrides):
        response = self.client.post(reverse("asset_create"), self.data(**overrides))
        self.assertRedirects(response, reverse("asset_list"))
        return Asset.objects.get(asset_no=overrides.get("asset_no", "IMG-001"))

    def test_multiple_uploads_persist_and_list_links_to_images(self):
        asset = self.create(images=[picture(), picture()])
        self.assertEqual(asset.images.count(), 2)
        names = [image.image.name for image in asset.images.all()]
        self.assertEqual(len(set(names)), 2)
        response = self.client.get(reverse("asset_list"))
        for image in asset.images.all():
            self.assertTrue(image.image.storage.exists(image.image.name))
            self.assertContains(response, reverse("asset_image", args=[image.pk]))
        form = self.client.get(reverse("asset_edit", args=[asset.pk]))
        self.assertContains(form, 'enctype="multipart/form-data"')
        self.assertContains(form, "multiple")
        self.assertContains(form, "現有圖片")

    def test_edit_keeps_existing_images_and_can_append_then_remove(self):
        asset = self.create(images=[picture()])
        first = asset.images.get()
        url = reverse("asset_edit", args=[asset.pk])
        self.client.post(url, self.data(name="新名稱"))
        self.assertEqual(asset.images.count(), 1)
        response = self.client.post(url, self.data(images=[picture()]), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertTrue(response.json()["success"])
        self.assertEqual(asset.images.count(), 2)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, self.data(remove_images=[first.pk]))
        self.assertRedirects(response, reverse("asset_list"))
        self.assertEqual(asset.images.count(), 1)
        self.assertFalse(first.image.storage.exists(first.image.name))

    def test_invalid_file_in_batch_rejects_entire_submission(self):
        response = self.client.post(reverse("asset_create"), self.data(images=[
            SimpleUploadedFile("fake.png", b"not an image", content_type="image/png"), picture(),
        ]), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Asset.objects.exists())
        self.assertFalse(AssetImage.objects.exists())
        self.assertEqual(list(Path(self.directory.name).rglob("*")), [])

    def test_upload_limits_are_validated_on_server(self):
        too_large = picture()
        too_large.size = 5 * 1024 * 1024 + 1
        from .forms import MultipleImageField
        from django.core.exceptions import ValidationError
        with self.assertRaisesMessage(ValidationError, "5 MB"):
            MultipleImageField().clean([too_large])
        response = self.client.post(reverse("asset_create"), self.data(images=[picture() for _ in range(11)]))
        self.assertContains(response, "每次最多上傳 10 張")
        self.assertFalse(Asset.objects.exists())

    def test_cannot_remove_another_assets_image(self):
        first = self.create(images=[picture()])
        second = self.create(asset_no="IMG-002", images=[picture()])
        response = self.client.post(reverse("asset_edit", args=[first.pk]), self.data(
            remove_images=[second.images.get().pk], name="不可儲存",
        ), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 422)
        first.refresh_from_db()
        self.assertEqual(first.name, "相機")
        self.assertEqual(AssetImage.objects.count(), 2)

    def test_invalid_edit_preserves_existing_image_and_changes_nothing(self):
        asset = self.create(images=[picture()])
        image = asset.images.get()
        response = self.client.post(reverse("asset_edit", args=[asset.pk]), self.data(
            name="", remove_images=[image.pk], images=[picture()],
        ), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(asset.images.count(), 1)
        self.assertTrue(image.image.storage.exists(image.image.name))

    def test_unsupported_image_format_is_rejected(self):
        data = BytesIO()
        Image.new("RGB", (10, 10)).save(data, format="BMP")
        response = self.client.post(reverse("asset_create"), self.data(images=[
            SimpleUploadedFile("photo.bmp", data.getvalue(), content_type="image/bmp"),
        ]))
        self.assertContains(response, "僅支援 JPG")
        self.assertFalse(Asset.objects.exists())

    def test_image_view_obeys_department_permissions_and_requires_login(self):
        asset = self.create(images=[picture()])
        url = reverse("asset_image", args=[asset.images.get().pk])
        for user in (self.manager, self.staff):
            self.client.force_login(user)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "image/png")
            self.assertEqual(response["Cache-Control"], "private, no-store")
            response.close()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_asset_detail_shows_all_images_and_obeys_list_permissions(self):
        asset = self.create(images=[picture(), picture()])
        detail_url = reverse("asset_detail", args=[asset.pk])
        self.client.force_login(self.staff)
        response = self.client.get(detail_url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, asset.asset_no)
        self.assertContains(response, asset.name)
        self.assertContains(response, "財產圖片")
        self.assertContains(response, "2 張")
        for image in asset.images.all():
            self.assertContains(response, reverse("asset_image", args=[image.pk]))
        self.assertNotContains(response, "編輯財產")

        self.client.force_login(self.manager)
        manager_response = self.client.get(detail_url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertContains(manager_response, "編輯財產")
        self.assertContains(manager_response, reverse("asset_edit", args=[asset.pk]))

        self.client.force_login(self.other)
        self.assertEqual(self.client.get(detail_url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(detail_url).status_code, 302)

    def test_staff_cannot_upload_or_remove_images(self):
        asset = self.create(images=[picture()])
        self.client.force_login(self.staff)
        response = self.client.post(reverse("asset_edit", args=[asset.pk]), self.data(
            images=[picture()], remove_images=[asset.images.get().pk],
        ))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(asset.images.count(), 1)

    def test_failed_database_write_cleans_uploaded_files(self):
        with patch.object(AssetImage, "save", side_effect=RuntimeError("write failed")):
            with self.assertRaisesMessage(RuntimeError, "write failed"):
                self.client.post(reverse("asset_create"), self.data(images=[picture()]))
        self.assertFalse(Asset.objects.exists())
        self.assertFalse(any(path.is_file() for path in Path(self.directory.name).rglob("*")))
