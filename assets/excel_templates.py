from io import BytesIO

from django.contrib.auth import get_user_model
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from organization.models import Department

from .importers import REGISTRATION_SHEET_NAME, SHEET_NAME
from .models import Asset


HEADERS = [
    "進貨日期", "公司代碼", "資產名稱", "廠牌", "型號", "商品名稱", "規格",
    "配件", "數量", "單價", "營業稅", "合計", "部門", "使用者", "財產編號",
    "圖檔", "序列號", "公司編號", "部門編號", "分類編號", "備註",
]

REGISTRATION_HEADERS = [header for header in HEADERS if header != "財產編號"]


def build_asset_import_template():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET_NAME
    options = workbook.create_sheet("選項")
    instructions = workbook.create_sheet("填寫說明", 0)

    instructions.append(["財產批量上傳範本"])
    instructions.append(["1. 請在「固定資產設備-總清單」工作表填寫資料，勿修改第一列欄位名稱。"])
    instructions.append(["2. 必填欄位：進貨日期、公司代碼、資產名稱、商品名稱、部門、財產編號。"])
    instructions.append(["3. 公司可使用下拉選單；數量空白時系統會自動使用 1。"])
    instructions.append(["4. 圖片請使用 Excel 的「置於儲存格中」功能放入「圖檔」欄。"])
    instructions.append(["5. 上傳後會先進入預覽表，可修改資料，確認後才會寫入資料庫。"])
    instructions.column_dimensions["A"].width = 100
    instructions["A1"].font = Font(size=16, bold=True, color="FFFFFF")
    instructions["A1"].fill = PatternFill("solid", fgColor="315C4B")
    for row in range(2, 7):
        instructions[f"A{row}"].alignment = Alignment(wrap_text=True, vertical="top")
        instructions.row_dimensions[row].height = 28

    sheet.append(HEADERS)
    header_fill = PatternFill("solid", fgColor="315C4B")
    required_fill = PatternFill("solid", fgColor="244638")
    required_headers = {"進貨日期", "公司代碼", "資產名稱", "商品名稱", "部門", "財產編號"}
    for cell in sheet[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = required_fill if cell.value in required_headers else header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}501"
    sheet.row_dimensions[1].height = 32

    widths = [14, 14, 18, 16, 18, 22, 28, 20, 10, 14, 14, 14, 18, 18, 24, 18, 18, 16, 16, 16, 28]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for row in range(2, 502):
        sheet[f"A{row}"].number_format = "yyyy-mm-dd"
        sheet[f"I{row}"].number_format = "0"
        for column in ("J", "K", "L"):
            sheet[f"{column}{row}"].number_format = '#,##0.00'
        sheet[f"L{row}"] = f'=IF(COUNTA(J{row}:K{row})=0,"",SUM(J{row}:K{row}))'

    sheet["A1"].comment = Comment("可填 YYYY-MM-DD；若只填年份，系統會轉為該年 1 月 1 日。", "品嘉平台")
    sheet["B1"].comment = Comment("請由下拉選單選擇公司。", "品嘉平台")
    sheet["P1"].comment = Comment("請使用 Excel 的「置於儲存格中」功能插入圖片。", "品嘉平台")

    company_values = [choice[0] for choice in Asset.Company.choices]
    department_values = list(Department.objects.order_by("name").values_list("name", flat=True))
    user_values = list(
        get_user_model().objects.filter(profile__isnull=False)
        .order_by("username").values_list("username", flat=True)
    )
    options.append(["公司", "部門", "使用者"])
    max_options = max(len(company_values), len(department_values), len(user_values), 1)
    for index in range(max_options):
        options.append([
            company_values[index] if index < len(company_values) else None,
            department_values[index] if index < len(department_values) else None,
            user_values[index] if index < len(user_values) else None,
        ])

    validations = [
        ("B2:B501", "A", len(company_values)),
        ("M2:M501", "B", len(department_values)),
        ("N2:N501", "C", len(user_values)),
    ]
    for target, column, count in validations:
        if not count:
            continue
        validation = DataValidation(
            type="list",
            formula1=f"'選項'!${column}$2:${column}${count + 1}",
            allow_blank=True,
        )
        validation.error = "請從下拉選單選擇有效資料。"
        validation.errorTitle = "資料格式錯誤"
        validation.prompt = "請從清單選擇，或保留空白後於匯入預覽頁修正。"
        validation.promptTitle = "批量匯入欄位"
        validation.showErrorMessage = True
        validation.showInputMessage = True
        sheet.add_data_validation(validation)
        validation.add(target)

    options.sheet_state = "hidden"
    sheet.sheet_view.showGridLines = False
    workbook.active = 1
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    output.seek(0)
    return output


def build_registration_import_template():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = REGISTRATION_SHEET_NAME
    options = workbook.create_sheet("選項")
    instructions = workbook.create_sheet("填寫說明", 0)

    instructions.append(["資產登記批量上傳範本"])
    instructions.append([f"1. 請在「{REGISTRATION_SHEET_NAME}」工作表填寫資料，勿修改第一列欄位名稱。"])
    instructions.append(["2. 必填欄位：進貨日期、公司代碼、資產名稱、商品名稱、部門。"])
    instructions.append(["3. 資產登記不需填財產編號；管理部核准時才會指定財產編號。"])
    instructions.append(["4. 公司可使用下拉選單；使用者可自由輸入帳號或姓名，部門共用資產可留空；數量空白時系統會自動使用 1。"])
    instructions.append(["5. 圖片請使用 Excel 的「置於儲存格中」功能放入「圖檔」欄。"])
    instructions.append(["6. 上傳後會先進入預覽表，可修改資料，確認後才會建立待審核案件。"])
    instructions.column_dimensions["A"].width = 100
    instructions["A1"].font = Font(size=16, bold=True, color="FFFFFF")
    instructions["A1"].fill = PatternFill("solid", fgColor="315C4B")
    for row in range(2, 8):
        instructions[f"A{row}"].alignment = Alignment(wrap_text=True, vertical="top")
        instructions.row_dimensions[row].height = 28

    sheet.append(REGISTRATION_HEADERS)
    header_fill = PatternFill("solid", fgColor="315C4B")
    required_fill = PatternFill("solid", fgColor="244638")
    required_headers = {
        "進貨日期", "公司代碼", "資產名稱", "商品名稱", "部門"
    }
    for cell in sheet[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = required_fill if cell.value in required_headers else header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(REGISTRATION_HEADERS))}501"
    sheet.row_dimensions[1].height = 32

    widths = [14, 14, 18, 16, 18, 22, 28, 20, 10, 14, 14, 14, 18, 18, 18, 18, 16, 16, 16, 28]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for row in range(2, 502):
        sheet[f"A{row}"].number_format = "yyyy-mm-dd"
        sheet[f"I{row}"].number_format = "0"
        for column in ("J", "K", "L"):
            sheet[f"{column}{row}"].number_format = '#,##0.00'
        sheet[f"L{row}"] = f'=IF(COUNTA(J{row}:K{row})=0,"",SUM(J{row}:K{row}))'

    sheet["A1"].comment = Comment("可填 YYYY-MM-DD；若只填年份，系統會轉為該年 1 月 1 日。", "品嘉平台")
    sheet["B1"].comment = Comment("請由下拉選單選擇公司。", "品嘉平台")
    sheet["O1"].comment = Comment("請使用 Excel 的「置於儲存格中」功能插入圖片。", "品嘉平台")

    company_values = [choice[0] for choice in Asset.Company.choices]
    department_values = list(Department.objects.order_by("name").values_list("name", flat=True))
    user_values = list(
        get_user_model().objects.filter(profile__isnull=False)
        .order_by("username").values_list("username", flat=True)
    )
    options.append(["公司", "部門", "使用者"])
    max_options = max(len(company_values), len(department_values), len(user_values), 1)
    for index in range(max_options):
        options.append([
            company_values[index] if index < len(company_values) else None,
            department_values[index] if index < len(department_values) else None,
            user_values[index] if index < len(user_values) else None,
        ])

    for target, column, count in [
        ("B2:B501", "A", len(company_values)),
        ("M2:M501", "B", len(department_values)),
    ]:
        if not count:
            continue
        validation = DataValidation(
            type="list", formula1=f"'選項'!${column}$2:${column}${count + 1}",
            allow_blank=True,
        )
        validation.error = "請從下拉選單選擇有效資料。"
        validation.errorTitle = "資料格式錯誤"
        validation.prompt = "請從清單選擇，或保留空白後於匯入預覽頁修正。"
        validation.promptTitle = "批量匯入欄位"
        validation.showErrorMessage = True
        validation.showInputMessage = True
        sheet.add_data_validation(validation)
        validation.add(target)

    options.sheet_state = "hidden"
    sheet.sheet_view.showGridLines = False
    workbook.active = 1
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    output.seek(0)
    return output
