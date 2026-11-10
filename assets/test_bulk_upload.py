from io import BytesIO
from zipfile import ZipFile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from openpyxl import Workbook, load_workbook

from organization.models import Department, UserProfile

from .excel_templates import HEADERS as TEMPLATE_HEADERS
from .importers import SHEET_NAME, _cell_image_paths
from .models import Asset, AssetImportBatch


HEADERS = [
    "進貨日期", "公司代碼", "資產名稱", "廠牌", "型號", "商品名稱",
    "規格", "配件", "數量", "單價", "營業稅", "合計", "部門",
    "使用者", "財產編號", "圖檔",
]


def workbook_upload(rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET_NAME
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    content = BytesIO()
    workbook.save(content)
    workbook.close()
    return SimpleUploadedFile(
        "assets.xlsx", content.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


class AssetBulkUploadTests(TestCase):
    def setUp(self):
        self.management = Department.objects.create(name="管理部")
        self.it = Department.objects.create(name="資訊部")
        self.manager = User.objects.create_user("manager", password="x")
        self.staff = User.objects.create_user("tony", password="x", first_name="王小明")
        UserProfile.objects.create(user=self.manager, department=self.management)
        UserProfile.objects.create(user=self.staff, department=self.it)

    def client_for(self, user):
        client = Client()
        client.force_login(user)
        return client

    def valid_row(self, asset_no="PCA-01-001"):
        return [
            2025, "PCA", "電腦設備", "ASUS", "B1402", "商務筆電",
            "16GB RAM", "充電器", 2, 30000, 1500, 31500, "資訊部",
            "tony", asset_no, None,
        ]

    def upload_for_preview(self, client, rows, extra=None):
        data = {"excel_file": workbook_upload(rows)}
        data.update(extra or {})
        response = client.post(reverse("asset_bulk_upload"), data)
        batch = AssetImportBatch.objects.latest("pk")
        self.assertRedirects(
            response, reverse("asset_bulk_upload_preview", args=[batch.pk]),
            fetch_redirect_response=False,
        )
        return batch

    def preview_post_data(self, batch):
        data = {
            "rows-TOTAL_FORMS": str(len(batch.rows)),
            "rows-INITIAL_FORMS": str(len(batch.rows)),
            "rows-MIN_NUM_FORMS": "0",
            "rows-MAX_NUM_FORMS": "500",
            "action": "confirm",
        }
        fields = (
            "asset_no", "name", "company", "category", "brand", "specification",
            "accessories", "quantity", "unit_price", "business_tax", "department",
            "custodian", "purchase_date", "notes",
        )
        for index, row in enumerate(batch.rows):
            prefix = f"rows-{index}-"
            data[prefix + "row_index"] = str(index)
            data[prefix + "include"] = "on"
            for field in fields:
                value = row.get(field)
                data[prefix + field] = "" if value is None else str(value)
        return data

    def test_manager_can_import_mapped_asset_fields(self):
        client = self.client_for(self.manager)
        batch = self.upload_for_preview(client, [self.valid_row()])
        self.assertFalse(Asset.objects.exists())
        response = client.post(
            reverse("asset_bulk_upload_preview", args=[batch.pk]),
            self.preview_post_data(batch), follow=True,
        )
        self.assertRedirects(response, reverse("asset_list"))
        asset = Asset.objects.get(asset_no="PCA-01-001")
        self.assertEqual(asset.company, Asset.Company.PINJIA_DEVELOPMENT)
        self.assertEqual(asset.category, "電腦設備")
        self.assertEqual(asset.name, "商務筆電")
        self.assertEqual(asset.specification, "B1402\n16GB RAM")
        self.assertEqual(asset.department, self.it)
        self.assertEqual(asset.custodian, self.staff)
        self.assertEqual(asset.quantity, 2)
        self.assertEqual(str(asset.total), "31500.00")
        self.assertEqual(asset.purchase_date.isoformat(), "2025-01-01")
        self.assertContains(response, "僅有年份")

    def test_invalid_row_rolls_back_entire_upload(self):
        invalid = self.valid_row("PCA-01-002")
        invalid[12] = "不存在的部門"
        client = self.client_for(self.manager)
        batch = self.upload_for_preview(client, [self.valid_row(), invalid])
        response = client.post(
            reverse("asset_bulk_upload_preview", args=[batch.pk]),
            self.preview_post_data(batch),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "此欄位為必要欄位")
        self.assertEqual(Asset.objects.count(), 0)

    def test_missing_required_row_is_skipped_and_reported(self):
        missing_name = self.valid_row("PCA-01-099")
        missing_name[5] = ""
        client = self.client_for(self.manager)
        batch = self.upload_for_preview(client, [self.valid_row(), missing_name])
        self.assertEqual(len(batch.rows), 1)
        self.assertEqual(len(batch.skipped), 1)
        preview = client.get(reverse("asset_bulk_upload_preview", args=[batch.pk]))
        self.assertContains(preview, "第 3 列缺少必要欄位：商品名稱，已跳過")
        response = client.post(
            reverse("asset_bulk_upload_preview", args=[batch.pk]),
            self.preview_post_data(batch), follow=True,
        )
        self.assertRedirects(response, reverse("asset_list"))
        self.assertEqual(Asset.objects.count(), 1)
        self.assertContains(response, "已跳過 1 筆")

    def test_preview_edits_are_used_for_final_import(self):
        client = self.client_for(self.manager)
        batch = self.upload_for_preview(client, [self.valid_row()])
        data = self.preview_post_data(batch)
        data["rows-0-name"] = "預覽中修正的名稱"
        data["rows-0-company"] = Asset.Company.VENDOR_EQUIPMENT
        response = client.post(
            reverse("asset_bulk_upload_preview", args=[batch.pk]), data,
        )
        self.assertRedirects(response, reverse("asset_list"))
        asset = Asset.objects.get(asset_no="PCA-01-001")
        self.assertEqual(asset.name, "預覽中修正的名稱")
        self.assertEqual(asset.company, Asset.Company.VENDOR_EQUIPMENT)

    def test_company_choices_include_vendor_equipment_and_other(self):
        self.assertIn(("廠商設備", "廠商設備"), Asset.Company.choices)
        self.assertIn(("其他", "其他"), Asset.Company.choices)

    def test_large_preview_post_can_exceed_django_default_field_count(self):
        rows = [self.valid_row(f"PCA-LOAD-{index:03d}") for index in range(70)]
        client = self.client_for(self.manager)
        batch = self.upload_for_preview(client, rows)
        data = self.preview_post_data(batch)
        self.assertGreater(len(data), 1000)
        response = client.post(
            reverse("asset_bulk_upload_preview", args=[batch.pk]), data,
        )
        self.assertRedirects(response, reverse("asset_list"))
        self.assertEqual(Asset.objects.count(), 70)

    def test_testing_mode_uses_fallback_department_and_keeps_source_values(self):
        row = self.valid_row()
        row[12] = "正式環境才有的工程部"
        row[13] = "正式環境使用者"
        client = self.client_for(self.manager)
        batch = self.upload_for_preview(
            client, [row], {
                "testing_compatibility": "on",
                "fallback_department": self.it.pk,
            },
        )
        response = client.post(
            reverse("asset_bulk_upload_preview", args=[batch.pk]),
            self.preview_post_data(batch), follow=True,
        )
        self.assertRedirects(response, reverse("asset_list"))
        asset = Asset.objects.get(asset_no="PCA-01-001")
        self.assertEqual(asset.department, self.it)
        self.assertIsNone(asset.custodian)
        self.assertIn("Excel 原始部門：正式環境才有的工程部", asset.notes)
        self.assertIn("Excel 原始使用者：正式環境使用者", asset.notes)
        self.assertContains(response, "1 筆使用替代部門")
        self.assertContains(response, "1 筆保管人員暫時留空")

    def test_testing_mode_requires_fallback_department(self):
        response = self.client_for(self.manager).post(
            reverse("asset_bulk_upload"),
            {
                "excel_file": workbook_upload([self.valid_row()]),
                "testing_compatibility": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "請選擇替代部門")
        self.assertFalse(Asset.objects.exists())

    def test_regular_user_cannot_open_or_submit_bulk_upload(self):
        client = self.client_for(self.staff)
        self.assertEqual(client.get(reverse("asset_bulk_upload")).status_code, 403)
        response = client.post(
            reverse("asset_bulk_upload"),
            {"excel_file": workbook_upload([self.valid_row()])},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Asset.objects.exists())

    def test_bulk_upload_button_only_shows_for_management(self):
        manager_response = self.client_for(self.manager).get(reverse("asset_list"))
        staff_response = self.client_for(self.staff).get(reverse("asset_list"))
        self.assertContains(manager_response, reverse("asset_bulk_upload"))
        self.assertNotContains(staff_response, reverse("asset_bulk_upload"))

    def test_manager_can_download_editable_import_template(self):
        client = self.client_for(self.manager)
        asset_page = client.get(reverse("asset_list"))
        upload_page = client.get(reverse("asset_bulk_upload"))
        self.assertContains(asset_page, reverse("asset_bulk_upload_template"))
        self.assertNotContains(upload_page, reverse("asset_bulk_upload_template"))
        response = client.get(reverse("asset_bulk_upload_template"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml.sheet", response["Content-Type"])
        self.assertIn("filename*=UTF-8", response["Content-Disposition"])
        workbook = load_workbook(BytesIO(response.content), data_only=False)
        self.assertIn(SHEET_NAME, workbook.sheetnames)
        self.assertIn("填寫說明", workbook.sheetnames)
        self.assertEqual(workbook["選項"].sheet_state, "hidden")
        sheet = workbook[SHEET_NAME]
        self.assertEqual([cell.value for cell in sheet[1]], TEMPLATE_HEADERS)
        self.assertEqual(sheet["L2"].value, '=IF(COUNTA(J2:K2)=0,"",SUM(J2:K2))')
        self.assertEqual(len(sheet.data_validations.dataValidation), 3)
        self.assertIn("廠商設備", [cell.value for cell in workbook["選項"]["A"]])
        workbook.close()

    def test_regular_user_cannot_download_import_template(self):
        response = self.client_for(self.staff).get(reverse("asset_bulk_upload_template"))
        self.assertEqual(response.status_code, 403)

    def test_in_cell_rich_image_relationship_maps_to_cell(self):
        content = BytesIO()
        with ZipFile(content, "w") as archive:
            archive.writestr("xl/workbook.xml", '''
                <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                  <sheets><sheet name="固定資產設備-總清單" sheetId="1" r:id="rId1"/></sheets>
                </workbook>''')
            archive.writestr("xl/_rels/workbook.xml.rels", '''
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                  <Relationship Id="rId1" Target="worksheets/sheet1.xml"/>
                </Relationships>''')
            archive.writestr("xl/worksheets/sheet1.xml", '''
                <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                  <sheetData><row r="2"><c r="P2" vm="1" t="e"><v>#VALUE!</v></c></row></sheetData>
                </worksheet>''')
            archive.writestr("xl/richData/rdrichvalue.xml", '<rvData><rv><v>0</v><v>5</v></rv></rvData>')
            archive.writestr(
                "xl/richData/richValueRel.xml",
                '<richValueRels xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><rel r:id="rId1"/></richValueRels>',
            )
            archive.writestr(
                "xl/richData/_rels/richValueRel.xml.rels",
                '<Relationships><Relationship Id="rId1" Target="../media/image1.png"/></Relationships>',
            )
            archive.writestr("xl/media/image1.png", b"image")
        content.seek(0)
        self.assertEqual(
            _cell_image_paths(content, SHEET_NAME),
            {"P2": "xl/media/image1.png"},
        )
