from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from openpyxl import Workbook, load_workbook

from organization.models import Department, UserProfile

from .excel_templates import REGISTRATION_HEADERS
from .importers import REGISTRATION_SHEET_NAME
from .models import Asset, AssetImportBatch, AssetRegistration


def registration_workbook_upload(rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = REGISTRATION_SHEET_NAME
    sheet.append(REGISTRATION_HEADERS)
    for row in rows:
        sheet.append(row)
    content = BytesIO()
    workbook.save(content)
    workbook.close()
    return SimpleUploadedFile(
        "registrations.xlsx", content.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


class RegistrationBulkUploadTests(TestCase):
    def setUp(self):
        self.management = Department.objects.create(name="管理與事業發展部")
        self.it = Department.objects.create(name="資訊部")
        self.manager = User.objects.create_user("manager", password="x")
        self.staff = User.objects.create_user("tony", password="x")
        UserProfile.objects.create(user=self.manager, department=self.management)
        UserProfile.objects.create(user=self.staff, department=self.it)

    def client_for(self, user):
        client = Client()
        client.force_login(user)
        return client

    def valid_row(self):
        return [
            2025, "PCA", "電腦設備", "ASUS", "B1402", "商務筆電",
            "16GB RAM", "充電器", 2, 30000, 1500, 31500, "資訊部",
            "tony", None, None, None, None, None, "",
        ]

    def preview_post_data(self, batch):
        data = {
            "rows-TOTAL_FORMS": str(len(batch.rows)),
            "rows-INITIAL_FORMS": str(len(batch.rows)),
            "rows-MIN_NUM_FORMS": "0",
            "rows-MAX_NUM_FORMS": "500",
            "action": "confirm",
        }
        fields = (
            "name", "company", "category", "brand", "specification", "accessories",
            "quantity", "unit_price", "business_tax", "department", "custodian",
            "purchase_date", "notes",
        )
        for index, row in enumerate(batch.rows):
            prefix = f"rows-{index}-"
            data[prefix + "row_index"] = str(index)
            data[prefix + "include"] = "on"
            for field in fields:
                value = row.get(field)
                data[prefix + field] = "" if value is None else str(value)
        return data

    def upload_for_preview(self):
        client = self.client_for(self.staff)
        response = client.post(
            reverse("registration_bulk_upload"),
            {"excel_file": registration_workbook_upload([self.valid_row()])},
        )
        batch = AssetImportBatch.objects.get()
        self.assertEqual(batch.import_type, AssetImportBatch.ImportType.REGISTRATION)
        self.assertRedirects(
            response, reverse("registration_bulk_upload_preview", args=[batch.pk]),
            fetch_redirect_response=False,
        )
        return client, batch

    def test_staff_can_preview_then_create_pending_registrations_without_asset_number(self):
        client, batch = self.upload_for_preview()
        self.assertFalse(AssetRegistration.objects.exists())
        self.assertNotIn("asset_no", batch.rows[0])
        response = client.post(
            reverse("registration_bulk_upload_preview", args=[batch.pk]),
            self.preview_post_data(batch),
        )
        self.assertRedirects(response, reverse("registration_list"))
        registration = AssetRegistration.objects.get()
        self.assertEqual(registration.status, AssetRegistration.Status.PENDING)
        self.assertEqual(registration.applicant, self.staff)
        self.assertEqual(registration.custodian, self.staff)
        self.assertEqual(registration.department, self.it)
        self.assertEqual(registration.specification, "B1402\n16GB RAM")
        self.assertTrue(registration.case_no)
        self.assertFalse(Asset.objects.exists())

    def test_template_and_buttons_are_available_to_applicant_and_have_no_asset_number(self):
        client = self.client_for(self.staff)
        page = client.get(reverse("registration_list"))
        self.assertContains(page, reverse("registration_bulk_upload"))
        self.assertContains(page, reverse("registration_bulk_upload_template"))
        response = client.get(reverse("registration_bulk_upload_template"))
        self.assertEqual(response.status_code, 200)
        workbook = load_workbook(BytesIO(response.content), data_only=False)
        headers = [cell.value for cell in workbook[REGISTRATION_SHEET_NAME][1]]
        self.assertEqual(headers, REGISTRATION_HEADERS)
        self.assertNotIn("財產編號", headers)
        validations = workbook[REGISTRATION_SHEET_NAME].data_validations.dataValidation
        self.assertEqual(len(validations), 2)
        self.assertFalse(any("N2:N501" in str(item.sqref) for item in validations))
        workbook.close()

    def test_management_cannot_use_applicant_bulk_upload(self):
        client = self.client_for(self.manager)
        self.assertEqual(client.get(reverse("registration_bulk_upload")).status_code, 403)
        self.assertEqual(
            client.get(reverse("registration_bulk_upload_template")).status_code, 403
        )

    def test_blank_user_creates_shared_department_asset_preview(self):
        row = self.valid_row()
        row[13] = ""
        client = self.client_for(self.staff)
        response = client.post(
            reverse("registration_bulk_upload"),
            {"excel_file": registration_workbook_upload([row])},
        )
        batch = AssetImportBatch.objects.get()
        self.assertRedirects(
            response, reverse("registration_bulk_upload_preview", args=[batch.pk]),
            fetch_redirect_response=False,
        )
        self.assertIsNone(batch.rows[0]["custodian"])
        confirm = client.post(
            reverse("registration_bulk_upload_preview", args=[batch.pk]),
            self.preview_post_data(batch),
        )
        self.assertRedirects(confirm, reverse("registration_list"))
        self.assertIsNone(AssetRegistration.objects.get().custodian)
