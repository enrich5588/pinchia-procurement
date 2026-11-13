from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
import hashlib
import json
import posixpath
import re
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models.functions import Lower, Trim
from django.core.files.base import ContentFile
from django.db import transaction
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.utils.datetime import from_excel
from PIL import Image, UnidentifiedImageError

from organization.models import Department, user_department

from .models import Asset, AssetImage, AssetRegistration


SHEET_NAME = "固定資產設備-總清單"
REGISTRATION_SHEET_NAME = "資產登記批量上傳"
REQUIRED_HEADERS = (
    "進貨日期", "公司代碼", "資產名稱", "型號", "商品名稱", "規格",
    "部門", "使用者", "財產編號", "圖檔",
)
COMPANIES = {
    "pca": Asset.Company.PINJIA_DEVELOPMENT,
    "品嘉建設": Asset.Company.PINJIA_DEVELOPMENT,
    "pcb": Asset.Company.PINJIA_CONSTRUCTION,
    "品嘉營造": Asset.Company.PINJIA_CONSTRUCTION,
    "pcc": Asset.Company.PINJIA_ASSET,
    "品佳資產": Asset.Company.PINJIA_ASSET,
    "廠商設備": Asset.Company.VENDOR_EQUIPMENT,
    "其他": Asset.Company.OTHER,
}
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
IMAGE_SUFFIXES = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif"}

REGISTRATION_REQUIRED_HEADERS = tuple(
    header for header in REQUIRED_HEADERS if header != "財產編號"
)


class AssetWorkbookError(Exception):
    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("；".join(self.errors))


@dataclass(frozen=True)
class AssetWorkbookResult:
    asset_count: int
    image_count: int
    year_only_date_count: int
    fallback_department_count: int
    unmatched_user_count: int
    updated_count: int = 0


@dataclass(frozen=True)
class AssetWorkbookPreview:
    rows: list
    skipped: list


@dataclass
class _ImportRow:
    row_number: int
    asset: Asset
    image_path: str | None
    image_name: str | None
    year_only_date: bool
    used_fallback_department: bool
    unmatched_user: bool


def _text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _key(value):
    return re.sub(r"\s+", "", _text(value)).casefold()


def _asset_number(value):
    return re.sub(r"\s+", "", _text(value)).upper()


def _decimal(value, label):
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value).replace(",", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label}格式不正確")
    if result < 0:
        raise ValueError(f"{label}不可小於 0")
    return result


def _quantity(value):
    if value in (None, ""):
        return 1
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("數量必須是正整數")
    if number != number.to_integral_value() or number < 1:
        raise ValueError("數量必須是正整數")
    return int(number)


def _purchase_date(value, workbook_epoch):
    if isinstance(value, datetime):
        return value.date(), False
    if isinstance(value, date):
        return value, False
    if isinstance(value, (int, float)):
        if 1900 <= value <= 2100 and float(value).is_integer():
            return date(int(value), 1, 1), True
        try:
            converted = from_excel(value, workbook_epoch)
            return (converted.date() if isinstance(converted, datetime) else converted), False
        except (TypeError, ValueError, OverflowError):
            pass
    text = _text(value)
    if re.fullmatch(r"\d{4}", text):
        year = int(text)
        if 1900 <= year <= 2100:
            return date(year, 1, 1), True
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, pattern).date(), False
        except ValueError:
            continue
    raise ValueError("進貨日期格式不正確")


def _unique_lookup(items, names):
    lookup = {}
    ambiguous = set()
    for item in items:
        for name in names(item):
            key = _key(name)
            if not key:
                continue
            if key in lookup and lookup[key].pk != item.pk:
                ambiguous.add(key)
            else:
                lookup[key] = item
    for key in ambiguous:
        lookup.pop(key, None)
    return lookup


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def _relationship_map(root):
    return {
        element.attrib["Id"]: element.attrib["Target"]
        for element in root.iter()
        if _local_name(element.tag) == "Relationship"
    }


def _worksheet_path(archive, sheet_name):
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = _relationship_map(ET.fromstring(archive.read("xl/_rels/workbook.xml.rels")))
    for sheet in workbook.iter():
        if _local_name(sheet.tag) == "sheet" and sheet.attrib.get("name") == sheet_name:
            relationship_id = next(
                (value for name, value in sheet.attrib.items() if name.endswith("}id")), None
            )
            if relationship_id in rels:
                return posixpath.normpath(posixpath.join("xl", rels[relationship_id]))
    return None


def _cell_image_paths(upload, sheet_name):
    upload.seek(0)
    try:
        with ZipFile(upload) as archive:
            required = {
                "xl/richData/rdrichvalue.xml",
                "xl/richData/richValueRel.xml",
                "xl/richData/_rels/richValueRel.xml.rels",
            }
            if not required.issubset(archive.namelist()):
                return {}
            sheet_path = _worksheet_path(archive, sheet_name)
            if not sheet_path:
                return {}
            sheet_root = ET.fromstring(archive.read(sheet_path))
            rich_values = [
                node for node in ET.fromstring(archive.read("xl/richData/rdrichvalue.xml")).iter()
                if _local_name(node.tag) == "rv"
            ]
            relation_ids = [
                node.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                for node in ET.fromstring(archive.read("xl/richData/richValueRel.xml")).iter()
                if _local_name(node.tag) == "rel"
            ]
            targets = _relationship_map(ET.fromstring(
                archive.read("xl/richData/_rels/richValueRel.xml.rels")
            ))
            result = {}
            for cell in sheet_root.iter():
                if _local_name(cell.tag) != "c" or "vm" not in cell.attrib:
                    continue
                try:
                    rich_value = rich_values[int(cell.attrib["vm"]) - 1]
                    values = [node.text for node in rich_value if _local_name(node.tag) == "v"]
                    relation_id = relation_ids[int(values[0])]
                    target = targets[relation_id]
                    path = posixpath.normpath(posixpath.join("xl/richData", target))
                except (IndexError, KeyError, TypeError, ValueError):
                    continue
                if path in archive.namelist():
                    result[cell.attrib["r"]] = path
            return result
    except (BadZipFile, ET.ParseError, KeyError) as exc:
        raise AssetWorkbookError(["Excel 圖片資料無法讀取，請確認檔案未損壞。"]) from exc
    finally:
        upload.seek(0)


def _validate_image(archive, path, row_number):
    data = archive.read(path)
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("圖檔超過 10 MB")
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
            image_format = image.format
    except (UnidentifiedImageError, OSError):
        raise ValueError("圖檔不是有效的圖片")
    if image_format not in ALLOWED_IMAGE_FORMATS:
        raise ValueError("圖檔格式僅支援 JPG、PNG、WebP 或 GIF")
    return data, f"excel-row-{row_number}{IMAGE_SUFFIXES[image_format]}"



def asset_revision(asset):
    from organization.audit import snapshot
    return hashlib.sha256(json.dumps(snapshot(asset), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def matching_assets(number):
    return Asset.objects.annotate(import_key=Lower(Trim('asset_no'))).filter(import_key=number.strip().lower())


def annotate_asset_targets(rows):
    keys = [row['asset_no'].strip().lower() for row in rows]
    grouped = {}
    for asset in Asset.objects.annotate(import_key=Lower(Trim('asset_no'))).filter(import_key__in=keys):
        grouped.setdefault(asset.asset_no.strip().lower(), []).append(asset)
    for row in rows:
        matches = grouped.get(row['asset_no'].strip().lower(), [])
        if len(matches) > 1:
            raise AssetWorkbookError([f"財產編號 {row['asset_no']} 對應多筆既有資料，請先整理重複編號。"])
        target = matches[0] if matches else None
        row['target_id'] = target.pk if target else None
        row['target_revision'] = asset_revision(target) if target else ''
    return rows


def prepare_asset_workbook(upload, *, fallback_department=None):
    """Parse an Excel workbook into editable JSON-safe rows without writing assets."""
    if fallback_department is not None and not settings.DEBUG:
        raise AssetWorkbookError(["正式環境不支援測試相容模式。"])
    upload.seek(0)
    try:
        workbook = load_workbook(upload, data_only=True, read_only=True)
    except Exception as exc:
        upload.seek(0)
        raise AssetWorkbookError(["Excel 檔案無法開啟，請確認檔案格式與內容。"]) from exc
    try:
        if SHEET_NAME not in workbook.sheetnames:
            raise AssetWorkbookError([f"找不到工作表「{SHEET_NAME}」。"])
        sheet = workbook[SHEET_NAME]
        headers = {_text(cell.value): cell.column for cell in sheet[1] if _text(cell.value)}
        missing_headers = [header for header in REQUIRED_HEADERS if header not in headers]
        if missing_headers:
            raise AssetWorkbookError([f"缺少必要欄位：{', '.join(missing_headers)}"])
        if sheet.max_row > 501:
            raise AssetWorkbookError(["單次最多匯入 500 筆財產。"])

        image_paths = _cell_image_paths(upload, SHEET_NAME)
        departments = _unique_lookup(Department.objects.all(), lambda item: [item.name])
        users = _unique_lookup(
            get_user_model().objects.filter(profile__isnull=False).select_related("profile__department"),
            lambda item: [item.username, item.get_full_name(), item.first_name],
        )

        def value(row_values, header):
            index = headers[header] - 1
            return row_values[index] if index < len(row_values) else None

        rows = []
        skipped = []
        for row_number, row_values in enumerate(
            sheet.iter_rows(min_row=2, values_only=True), start=2
        ):
            substantive = any(value(row_values, header) not in (None, "") for header in (
                "進貨日期", "公司代碼", "資產名稱", "廠牌", "型號", "商品名稱",
                "規格", "配件", "數量", "單價", "營業稅", "部門", "使用者",
            ) if header in headers)
            if not substantive:
                continue

            asset_no = _asset_number(value(row_values, "財產編號"))
            name = _text(value(row_values, "商品名稱"))
            category = _text(value(row_values, "資產名稱"))
            company_text = _text(value(row_values, "公司代碼"))
            source_department = _text(value(row_values, "部門"))
            required_missing = []
            if not _text(value(row_values, "進貨日期")):
                required_missing.append("進貨日期")
            if not company_text:
                required_missing.append("公司代碼")
            if not category:
                required_missing.append("資產名稱")
            if not name:
                required_missing.append("商品名稱")
            if not source_department:
                required_missing.append("部門")
            if not asset_no or asset_no.startswith("#"):
                required_missing.append("財產編號")
            if required_missing:
                skipped.append(f"第 {row_number} 列缺少必要欄位：{', '.join(required_missing)}，已跳過。")
                continue

            department = departments.get(_key(source_department))
            used_fallback = bool(not department and fallback_department)
            if used_fallback:
                department = fallback_department
            custodian_text = _text(value(row_values, "使用者"))
            custodian = users.get(_key(custodian_text)) if custodian_text else None
            unmatched_user = bool(custodian_text and not custodian)
            if department and custodian and user_department(custodian) != department:
                custodian = None
                unmatched_user = True

            try:
                parsed_date, year_only = _purchase_date(
                    value(row_values, "進貨日期"), workbook.epoch
                )
                purchase_date = parsed_date.isoformat()
            except ValueError:
                purchase_date = _text(value(row_values, "進貨日期"))
                year_only = False

            specification = "\n".join(filter(None, [
                _text(value(row_values, "型號")), _text(value(row_values, "規格")),
            ]))
            notes = []
            if used_fallback:
                notes.append(f"Excel 原始部門：{source_department}")
            if unmatched_user and fallback_department:
                notes.append(f"Excel 原始使用者：{custodian_text}")
            coordinate = f"{get_column_letter(headers['圖檔'])}{row_number}"
            rows.append({
                "row_number": row_number,
                "asset_no": asset_no,
                "name": name,
                "company": COMPANIES.get(_key(company_text), company_text),
                "category": category,
                "brand": _text(value(row_values, "廠牌")) if "廠牌" in headers else "",
                "specification": specification,
                "accessories": _text(value(row_values, "配件")) if "配件" in headers else "",
                "quantity": _text(value(row_values, "數量")) or "1",
                "unit_price": _text(value(row_values, "單價")) if "單價" in headers else "",
                "business_tax": _text(value(row_values, "營業稅")) if "營業稅" in headers else "",
                "department": department.pk if department else None,
                "custodian": custodian.pk if custodian else None,
                "purchase_date": purchase_date,
                "notes": "；".join(notes),
                "image_path": image_paths.get(coordinate),
                "year_only_date": year_only,
                "source_department": source_department,
                "source_user": custodian_text,
            })
        if not rows and not skipped:
            raise AssetWorkbookError(["工作表中沒有可匯入的財產資料。"])
        return AssetWorkbookPreview(rows=annotate_asset_targets(rows), skipped=skipped)
    finally:
        workbook.close()
        upload.seek(0)


def prepare_registration_workbook(upload, *, fallback_department=None):
    """Parse registration rows without requiring or reading a property number."""
    if fallback_department is not None and not settings.DEBUG:
        raise AssetWorkbookError(["正式環境不支援測試相容模式。"])
    upload.seek(0)
    try:
        workbook = load_workbook(upload, data_only=True, read_only=True)
    except Exception as exc:
        upload.seek(0)
        raise AssetWorkbookError(["Excel 檔案無法開啟，請確認檔案格式與內容。"]) from exc
    try:
        if REGISTRATION_SHEET_NAME not in workbook.sheetnames:
            raise AssetWorkbookError([f"找不到工作表「{REGISTRATION_SHEET_NAME}」。"])
        sheet = workbook[REGISTRATION_SHEET_NAME]
        headers = {_text(cell.value): cell.column for cell in sheet[1] if _text(cell.value)}
        missing_headers = [
            header for header in REGISTRATION_REQUIRED_HEADERS if header not in headers
        ]
        if missing_headers:
            raise AssetWorkbookError([f"缺少必要欄位：{', '.join(missing_headers)}"])
        if sheet.max_row > 501:
            raise AssetWorkbookError(["單次最多匯入 500 筆資產登記申請。"])

        image_paths = _cell_image_paths(upload, REGISTRATION_SHEET_NAME)
        departments = _unique_lookup(Department.objects.all(), lambda item: [item.name])
        users = _unique_lookup(
            get_user_model().objects.filter(profile__isnull=False).select_related(
                "profile__department"
            ),
            lambda item: [item.username, item.get_full_name(), item.first_name],
        )

        def value(row_values, header):
            index = headers[header] - 1
            return row_values[index] if index < len(row_values) else None

        rows = []
        skipped = []
        for row_number, row_values in enumerate(
            sheet.iter_rows(min_row=2, values_only=True), start=2
        ):
            substantive = any(
                value(row_values, header) not in (None, "")
                for header in (
                    "進貨日期", "公司代碼", "資產名稱", "廠牌", "型號",
                    "商品名稱", "規格", "配件", "數量", "單價", "營業稅",
                    "部門", "使用者",
                )
                if header in headers
            )
            if not substantive:
                continue

            name = _text(value(row_values, "商品名稱"))
            category = _text(value(row_values, "資產名稱"))
            company_text = _text(value(row_values, "公司代碼"))
            source_department = _text(value(row_values, "部門"))
            custodian_text = _text(value(row_values, "使用者"))
            required_missing = []
            if not _text(value(row_values, "進貨日期")):
                required_missing.append("進貨日期")
            if not company_text:
                required_missing.append("公司代碼")
            if not category:
                required_missing.append("資產名稱")
            if not name:
                required_missing.append("商品名稱")
            if not source_department:
                required_missing.append("部門")
            if required_missing:
                skipped.append(
                    f"第 {row_number} 列缺少必要欄位：{', '.join(required_missing)}，已跳過。"
                )
                continue

            department = departments.get(_key(source_department))
            used_fallback = bool(not department and fallback_department)
            if used_fallback:
                department = fallback_department
            custodian = users.get(_key(custodian_text))
            unmatched_user = bool(not custodian)
            if department and custodian and user_department(custodian) != department:
                custodian = None
                unmatched_user = True

            try:
                parsed_date, year_only = _purchase_date(
                    value(row_values, "進貨日期"), workbook.epoch
                )
                purchase_date = parsed_date.isoformat()
            except ValueError:
                purchase_date = _text(value(row_values, "進貨日期"))
                year_only = False

            specification = "\n".join(filter(None, [
                _text(value(row_values, "型號")), _text(value(row_values, "規格")),
            ]))
            notes = []
            if used_fallback:
                notes.append(f"Excel 原始部門：{source_department}")
            if unmatched_user and fallback_department:
                notes.append(f"Excel 原始使用者：{custodian_text}")
            coordinate = f"{get_column_letter(headers['圖檔'])}{row_number}"
            rows.append({
                "row_number": row_number,
                "name": name,
                "company": COMPANIES.get(_key(company_text), company_text),
                "category": category,
                "brand": _text(value(row_values, "廠牌")) if "廠牌" in headers else "",
                "specification": specification,
                "accessories": _text(value(row_values, "配件")) if "配件" in headers else "",
                "quantity": _text(value(row_values, "數量")) or "1",
                "unit_price": _text(value(row_values, "單價")) if "單價" in headers else "",
                "business_tax": _text(value(row_values, "營業稅")) if "營業稅" in headers else "",
                "department": department.pk if department else None,
                "custodian": custodian.pk if custodian else None,
                "purchase_date": purchase_date,
                "notes": "；".join(notes),
                "image_path": image_paths.get(coordinate),
                "year_only_date": year_only,
                "source_department": source_department,
                "source_user": custodian_text,
            })
        if not rows and not skipped:
            raise AssetWorkbookError(["工作表中沒有可匯入的資產登記資料。"])
        return AssetWorkbookPreview(rows=rows, skipped=skipped)
    finally:
        workbook.close()
        upload.seek(0)


@transaction.atomic
def import_asset_preview(batch, cleaned_rows, actor):
    from .permissions import can_manage_assets
    if batch.created_by_id != actor.pk or not can_manage_assets(actor):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('無權確認此批次匯入。')
    if not settings.DEBUG and batch.testing_compatibility:
        raise AssetWorkbookError(['測試環境預覽不可在正式環境匯入。'])
    selected = [row for row in cleaned_rows if row.get("include")]
    keys = [row['asset_no'].strip().upper() for row in selected]
    if len(keys) != len(set(keys)):
        raise AssetWorkbookError(['匯入資料中的財產編號不可重複。'])
    created_count = updated_count = 0
    sources = batch.rows
    saved_files = []
    image_count = 0
    try:
        with batch.source_file.open("rb") as source, ZipFile(source) as archive, transaction.atomic():
            for cleaned in selected:
                row_index = cleaned["row_index"]
                if row_index < 0 or row_index >= len(sources):
                    raise AssetWorkbookError(["預覽資料索引無效，請重新上傳 Excel。"])
                original = sources[row_index]
                number = cleaned['asset_no'].strip().upper()
                matches = list(matching_assets(number).select_for_update())
                if len(matches) > 1:
                    raise AssetWorkbookError([f'財產編號 {number} 對應多筆資料，無法覆蓋。'])
                asset = matches[0] if matches else None
                if asset and not batch.overwrite_existing:
                    raise AssetWorkbookError([f'財產編號 {number} 已存在；本批次未啟用覆蓋。'])
                if batch.overwrite_existing:
                    if number != original['asset_no'].strip().upper():
                        raise AssetWorkbookError(['覆蓋模式不可變更財產編號；請重新上傳以預覽新的比對對象。'])
                    expected = original.get('target_id')
                    if (asset.pk if asset else None) != expected or (asset and asset_revision(asset) != original.get('target_revision')):
                        raise AssetWorkbookError([f'財產 {number} 在預覽後已有異動，請重新上傳確認，避免覆蓋他人的修改。'])
                is_update = asset is not None
                if asset is None:
                    asset = Asset(asset_no=number, created_by=actor)
                for field in ['name','company','category','brand','specification','accessories','quantity',
                              'unit_price','business_tax','department','custodian','purchase_date','notes']:
                    setattr(asset, field, cleaned.get(field))
                asset.updated_by = actor
                asset.full_clean(validate_unique=False)
                asset.save()
                if is_update:
                    updated_count += 1
                else:
                    created_count += 1
                image_path = original.get("image_path")
                if image_path:
                    try:
                        image_data, image_name = _validate_image(
                            archive, image_path, original["row_number"]
                        )
                    except (KeyError, ValueError) as exc:
                        raise AssetWorkbookError([
                            f"Excel 第 {original['row_number']} 列：圖片無法讀取（{exc}）"
                        ]) from exc
                    image = AssetImage(asset=asset)
                    image.image.save(image_name, ContentFile(image_data), save=False)
                    saved_files.append((image.image.storage, image.image.name))
                    image.save()
                    image_count += 1
            storage, source_name = batch.source_file.storage, batch.source_file.name
            batch.delete()
            transaction.on_commit(lambda: storage.delete(source_name), robust=True)
    except Exception:
        for storage, name in saved_files:
            storage.delete(name)
        raise

    result = AssetWorkbookResult(
        asset_count=created_count, updated_count=updated_count, image_count=image_count,
        year_only_date_count=sum(
            bool(sources[row["row_index"]].get("year_only_date")) for row in selected
        ),
        fallback_department_count=sum(
            "Excel 原始部門：" in (row.get("notes") or "") for row in selected
        ),
        unmatched_user_count=sum(
            "Excel 原始使用者：" in (row.get("notes") or "") for row in selected
        ),
    )
    return result


def import_registration_preview(batch, cleaned_rows, actor):
    selected = [row for row in cleaned_rows if row.get("include")]
    sources = batch.rows
    saved_files = []
    image_count = 0
    try:
        with batch.source_file.open("rb") as source, ZipFile(source) as archive, transaction.atomic():
            from .services import next_registration_case_no

            for cleaned in selected:
                row_index = cleaned["row_index"]
                if row_index < 0 or row_index >= len(sources):
                    raise AssetWorkbookError(["預覽資料索引無效，請重新上傳 Excel。"])
                original = sources[row_index]
                registration = AssetRegistration(
                    case_no=next_registration_case_no(),
                    name=cleaned["name"], company=cleaned["company"],
                    category=cleaned["category"], brand=cleaned.get("brand", ""),
                    specification=cleaned.get("specification", ""),
                    accessories=cleaned.get("accessories", ""),
                    quantity=cleaned["quantity"], unit_price=cleaned.get("unit_price"),
                    business_tax=cleaned.get("business_tax"),
                    department=cleaned["department"], custodian=cleaned["custodian"],
                    purchase_date=cleaned["purchase_date"], notes=cleaned.get("notes", ""),
                    applicant=actor,
                )
                registration.full_clean(validate_unique=False)
                registration.save()
                image_path = original.get("image_path")
                if image_path:
                    try:
                        image_data, image_name = _validate_image(
                            archive, image_path, original["row_number"]
                        )
                    except (KeyError, ValueError) as exc:
                        raise AssetWorkbookError([
                            f"Excel 第 {original['row_number']} 列：圖片無法讀取（{exc}）"
                        ]) from exc
                    image = AssetImage(registration=registration)
                    image.image.save(image_name, ContentFile(image_data), save=False)
                    saved_files.append((image.image.storage, image.image.name))
                    image.save()
                    image_count += 1
    except Exception:
        for storage, name in saved_files:
            storage.delete(name)
        raise

    result = AssetWorkbookResult(
        asset_count=len(selected), image_count=image_count,
        year_only_date_count=sum(
            bool(sources[row["row_index"]].get("year_only_date")) for row in selected
        ),
        fallback_department_count=sum(
            "Excel 原始部門：" in (row.get("notes") or "") for row in selected
        ),
        unmatched_user_count=sum(
            "Excel 原始使用者：" in (row.get("notes") or "") for row in selected
        ),
    )
    batch.source_file.delete(save=False)
    batch.delete()
    return result


def import_asset_workbook(upload, actor, *, fallback_department=None):
    if fallback_department is not None and not settings.DEBUG:
        raise AssetWorkbookError(["正式環境不支援測試相容模式。"])
    upload.seek(0)
    try:
        workbook = load_workbook(upload, data_only=True, read_only=True)
    except Exception as exc:
        upload.seek(0)
        raise AssetWorkbookError(["Excel 檔案無法開啟，請確認檔案格式與內容。"])
    try:
        if SHEET_NAME not in workbook.sheetnames:
            raise AssetWorkbookError([f"找不到工作表「{SHEET_NAME}」。"])
        sheet = workbook[SHEET_NAME]
        headers = {_text(cell.value): cell.column for cell in sheet[1] if _text(cell.value)}
        missing = [header for header in REQUIRED_HEADERS if header not in headers]
        if missing:
            raise AssetWorkbookError([f"缺少必要欄位：{', '.join(missing)}"])
        if sheet.max_row > 501:
            raise AssetWorkbookError(["單次最多匯入 500 筆財產。"])

        image_paths = _cell_image_paths(upload, SHEET_NAME)
        departments = _unique_lookup(Department.objects.all(), lambda item: [item.name])
        users = _unique_lookup(
            get_user_model().objects.filter(profile__isnull=False).select_related("profile__department"),
            lambda item: [item.username, item.get_full_name(), item.first_name],
        )
        rows = []
        errors = []
        seen_numbers = set()

        def value(row_values, header):
            index = headers[header] - 1
            return row_values[index] if index < len(row_values) else None

        for row_number, row_values in enumerate(
            sheet.iter_rows(min_row=2, values_only=True), start=2
        ):
            substantive = any(value(row_values, header) not in (None, "") for header in (
                "進貨日期", "公司代碼", "資產名稱", "廠牌", "型號", "商品名稱",
                "規格", "配件", "數量", "單價", "營業稅", "部門", "使用者",
            ) if header in headers)
            if not substantive:
                continue
            row_errors = []
            asset_no = _asset_number(value(row_values, "財產編號"))
            name = _text(value(row_values, "商品名稱"))
            category = _text(value(row_values, "資產名稱"))
            company = COMPANIES.get(_key(value(row_values, "公司代碼")))
            source_department = _text(value(row_values, "部門"))
            department = departments.get(_key(source_department))
            used_fallback_department = bool(not department and fallback_department)
            if used_fallback_department:
                department = fallback_department
            custodian_text = _text(value(row_values, "使用者"))
            custodian = users.get(_key(custodian_text)) if custodian_text else None
            unmatched_user = False
            if not asset_no or asset_no.startswith("#"):
                row_errors.append("財產編號不可空白且必須可由 Excel 計算")
            elif asset_no.casefold() in seen_numbers:
                row_errors.append(f"財產編號 {asset_no} 在檔案中重複")
            else:
                seen_numbers.add(asset_no.casefold())
            if not name:
                row_errors.append("商品名稱不可空白")
            if not category:
                row_errors.append("資產名稱不可空白")
            if not company:
                row_errors.append("公司代碼無法對應公司")
            if not department:
                row_errors.append("部門不存在")
            if custodian_text and not custodian:
                if fallback_department:
                    unmatched_user = True
                else:
                    row_errors.append("使用者無法對應保管人員，或名稱不唯一")
            if department and custodian and user_department(custodian) != department:
                if fallback_department:
                    custodian = None
                    unmatched_user = True
                else:
                    row_errors.append("保管人員不屬於指定部門")
            try:
                purchase_date, year_only = _purchase_date(
                    value(row_values, "進貨日期"), workbook.epoch
                )
            except ValueError as exc:
                row_errors.append(str(exc))
                purchase_date, year_only = date.today(), False
            try:
                quantity = _quantity(value(row_values, "數量") if "數量" in headers else None)
                unit_price = _decimal(value(row_values, "單價"), "單價") if "單價" in headers else None
                business_tax = _decimal(value(row_values, "營業稅"), "營業稅") if "營業稅" in headers else None
            except ValueError as exc:
                row_errors.append(str(exc))
                quantity, unit_price, business_tax = 1, None, None
            specification = "\n".join(filter(None, [
                _text(value(row_values, "型號")), _text(value(row_values, "規格")),
            ]))
            trace_notes = []
            if used_fallback_department:
                trace_notes.append(f"Excel 原始部門：{source_department or '空白'}")
            if unmatched_user:
                trace_notes.append(f"Excel 原始使用者：{custodian_text or '空白'}")
            asset = Asset(
                asset_no=asset_no, name=name, company=company or "", category=category,
                brand=_text(value(row_values, "廠牌")) if "廠牌" in headers else "",
                specification=specification,
                accessories=_text(value(row_values, "配件")) if "配件" in headers else "",
                quantity=quantity, unit_price=unit_price, business_tax=business_tax,
                department=department, custodian=custodian, purchase_date=purchase_date,
                notes="；".join(trace_notes), created_by=actor, updated_by=actor,
            )
            if not row_errors:
                try:
                    asset.full_clean(validate_unique=False)
                except Exception as exc:
                    if hasattr(exc, "message_dict"):
                        row_errors.extend(
                            f"{field}：{'、'.join(messages)}"
                            for field, messages in exc.message_dict.items()
                        )
                    else:
                        row_errors.append(str(exc))
            if row_errors:
                errors.append(f"第 {row_number} 列：{'；'.join(row_errors)}")
            else:
                coordinate = f"{get_column_letter(headers['圖檔'])}{row_number}"
                rows.append(_ImportRow(
                    row_number, asset, image_paths.get(coordinate), None, year_only,
                    used_fallback_department, unmatched_user,
                ))

        if not rows and not errors:
            errors.append("工作表中沒有可匯入的財產資料。")
        requested_numbers = {row.asset.asset_no.casefold() for row in rows}
        existing = {
            number.casefold() for number in Asset.objects.values_list("asset_no", flat=True)
            if number.casefold() in requested_numbers
        }
        for row in rows:
            if row.asset.asset_no.casefold() in existing:
                errors.append(f"第 {row.row_number} 列：財產編號 {row.asset.asset_no} 已存在")
        if errors:
            raise AssetWorkbookError(errors[:200])

        saved_files = []
        image_count = 0
        upload.seek(0)
        try:
            with ZipFile(upload) as archive, transaction.atomic():
                for row in rows:
                    image_data = image_name = None
                    if row.image_path:
                        try:
                            image_data, image_name = _validate_image(
                                archive, row.image_path, row.row_number
                            )
                        except ValueError as exc:
                            raise AssetWorkbookError([f"第 {row.row_number} 列：{exc}"])
                    row.asset.save()
                    if image_data:
                        image = AssetImage(asset=row.asset)
                        image.image.save(image_name, ContentFile(image_data), save=False)
                        saved_files.append((image.image.storage, image.image.name))
                        image.save()
                        image_count += 1
        except Exception:
            for storage, name in saved_files:
                storage.delete(name)
            raise
        return AssetWorkbookResult(
            asset_count=len(rows), image_count=image_count,
            year_only_date_count=sum(row.year_only_date for row in rows),
            fallback_department_count=sum(row.used_fallback_department for row in rows),
            unmatched_user_count=sum(row.unmatched_user for row in rows),
        )
    finally:
        workbook.close()
        upload.seek(0)
