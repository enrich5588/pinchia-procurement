from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


OUT = Path(__file__).resolve().parent
FONT = r"C:\Windows\Fonts\msjh.ttc"
FONT_BOLD = r"C:\Windows\Fonts\msjhbd.ttc"

BG = "#F7F4EE"
INK = "#25231F"
MUTED = "#706B62"
LINE = "#908A80"
EMPLOYEE = "#E5F0EA"
SYSTEM = "#E8F0F7"
MANAGEMENT = "#F7EBD7"
COLLAB = "#EEE7F6"
SUCCESS = "#DDEDE5"
WARNING = "#F7E5DF"
NEUTRAL = "#ECE9E3"
WHITE = "#FFFFFF"


def font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT, size)


def wrap(draw: ImageDraw.ImageDraw, text: str, face, max_width: int) -> str:
    lines = []
    for paragraph in text.split("\n"):
        current = ""
        for char in paragraph:
            trial = current + char
            if current and draw.textbbox((0, 0), trial, font=face)[2] > max_width:
                lines.append(current)
                current = char
            else:
                current = trial
        lines.append(current)
    return "\n".join(lines)


class Flow:
    def __init__(self, title: str, subtitle: str, height: int, lanes: list[tuple[str, str]]):
        self.width = 2400
        self.height = height
        self.image = Image.new("RGB", (self.width, self.height), BG)
        self.draw = ImageDraw.Draw(self.image)
        self.nodes = {}
        self.draw.text((110, 65), title, font=font(60, True), fill=INK)
        self.draw.text((112, 145), subtitle, font=font(27), fill=MUTED)
        lane_width = (self.width - 160) / len(lanes)
        self.lane_centers = []
        for index, (name, color) in enumerate(lanes):
            left = 80 + index * lane_width
            right = 80 + (index + 1) * lane_width
            self.lane_centers.append((left + right) / 2)
            self.draw.rounded_rectangle(
                (left + 12, 220, right - 12, self.height - 70),
                radius=26,
                fill=WHITE,
                outline="#DDD8CE",
                width=3,
            )
            self.draw.rounded_rectangle(
                (left + 12, 220, right - 12, 300),
                radius=26,
                fill=color,
            )
            box = self.draw.textbbox((0, 0), name, font=font(30, True))
            self.draw.text(
                ((left + right - (box[2] - box[0])) / 2, 242),
                name,
                font=font(30, True),
                fill=INK,
            )

    def box(self, key, lane, y, text, fill, w=430, h=120, terminal=False):
        cx = self.lane_centers[lane]
        x1, y1, x2, y2 = cx - w / 2, y - h / 2, cx + w / 2, y + h / 2
        radius = h // 2 if terminal else 22
        self.draw.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=fill, outline="#B8B1A6", width=3)
        face = font(27, True)
        text = wrap(self.draw, text, face, w - 52)
        bbox = self.draw.multiline_textbbox((0, 0), text, font=face, spacing=8, align="center")
        self.draw.multiline_text(
            (cx - (bbox[2] - bbox[0]) / 2, y - (bbox[3] - bbox[1]) / 2),
            text,
            font=face,
            fill=INK,
            spacing=8,
            align="center",
        )
        self.nodes[key] = (cx, y, w, h)

    def diamond(self, key, lane, y, text, fill, w=420, h=155):
        cx = self.lane_centers[lane]
        points = [(cx, y - h / 2), (cx + w / 2, y), (cx, y + h / 2), (cx - w / 2, y)]
        self.draw.polygon(points, fill=fill, outline="#B8B1A6")
        self.draw.line(points + [points[0]], fill="#B8B1A6", width=3)
        face = font(26, True)
        text = wrap(self.draw, text, face, w * 0.58)
        bbox = self.draw.multiline_textbbox((0, 0), text, font=face, spacing=7, align="center")
        self.draw.multiline_text(
            (cx - (bbox[2] - bbox[0]) / 2, y - (bbox[3] - bbox[1]) / 2),
            text,
            font=face,
            fill=INK,
            spacing=7,
            align="center",
        )
        self.nodes[key] = (cx, y, w, h)

    def _anchor(self, key, side):
        cx, cy, w, h = self.nodes[key]
        return {
            "top": (cx, cy - h / 2),
            "bottom": (cx, cy + h / 2),
            "left": (cx - w / 2, cy),
            "right": (cx + w / 2, cy),
        }[side]

    def arrow(self, start, end, start_side="bottom", end_side="top", label=None, via=None, dashed=False):
        points = [self._anchor(start, start_side)]
        if via:
            points.extend(via)
        points.append(self._anchor(end, end_side))
        if dashed:
            for p1, p2 in zip(points, points[1:]):
                self._dashed_line(p1, p2)
        else:
            self.draw.line(points, fill=LINE, width=5, joint="curve")
        p1, p2 = points[-2], points[-1]
        angle = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
        size = 17
        head = [
            p2,
            (p2[0] - size * math.cos(angle - 0.55), p2[1] - size * math.sin(angle - 0.55)),
            (p2[0] - size * math.cos(angle + 0.55), p2[1] - size * math.sin(angle + 0.55)),
        ]
        self.draw.polygon(head, fill=LINE)
        if label:
            mx, my = points[len(points) // 2]
            face = font(22, True)
            bbox = self.draw.textbbox((0, 0), label, font=face)
            pad = 9
            self.draw.rounded_rectangle(
                (mx - (bbox[2] - bbox[0]) / 2 - pad, my - 31, mx + (bbox[2] - bbox[0]) / 2 + pad, my + 9),
                radius=10,
                fill=BG,
            )
            self.draw.text((mx - (bbox[2] - bbox[0]) / 2, my - 27), label, font=face, fill=MUTED)

    def _dashed_line(self, p1, p2, dash=18, gap=12):
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        length = math.hypot(dx, dy)
        if not length:
            return
        ux, uy = dx / length, dy / length
        pos = 0
        while pos < length:
            end = min(pos + dash, length)
            self.draw.line(
                (p1[0] + ux * pos, p1[1] + uy * pos, p1[0] + ux * end, p1[1] + uy * end),
                fill=LINE,
                width=4,
            )
            pos += dash + gap

    def note(self, x, y, text, color=WARNING, w=420):
        face = font(23)
        text = wrap(self.draw, text, face, w - 34)
        bbox = self.draw.multiline_textbbox((0, 0), text, font=face, spacing=6)
        h = bbox[3] - bbox[1] + 32
        self.draw.rounded_rectangle((x, y, x + w, y + h), radius=16, fill=color)
        self.draw.multiline_text((x + 17, y + 14), text, font=face, fill=INK, spacing=6)

    def save(self, filename):
        path = OUT / filename
        self.image.save(path, "JPEG", quality=95, subsampling=0, optimize=True, dpi=(200, 200))
        return path


def asset_registration():
    f = Flow(
        "財產登記流程",
        "申請人提出登記，管理部核准後才正式加入財產清冊",
        2300,
        [("申請人", EMPLOYEE), ("系統／狀態", SYSTEM), ("管理部", MANAGEMENT), ("財產清冊", SUCCESS)],
    )
    f.box("start", 0, 390, "填寫資產登記申請", EMPLOYEE)
    f.box("auto", 1, 390, "產生案件編號\n記錄申請人與日期", SYSTEM)
    f.box("pending", 1, 650, "申請中", SYSTEM, terminal=True)
    f.box("edit", 0, 890, "修改申請", EMPLOYEE)
    f.diamond("recheck", 1, 890, "送出時狀態仍可修改？", SYSTEM)
    f.box("cancel", 0, 1160, "取消申請", EMPLOYEE)
    f.box("cancelled", 1, 1160, "取消／結案", NEUTRAL, terminal=True)
    f.box("return", 2, 890, "退回申請", MANAGEMENT)
    f.box("returned", 1, 1400, "退回", WARNING, terminal=True)
    f.box("approve", 2, 1160, "核准／批量核准", MANAGEMENT)
    f.box("asset_form", 2, 1400, "開啟新增公司資產表單\n自動帶入申請內容", MANAGEMENT, h=145)
    f.diamond("unique", 2, 1660, "財產編號是否重複？", MANAGEMENT)
    f.box("create", 3, 1660, "建立公司資產", SUCCESS)
    f.box("ledger", 3, 1910, "加入財產清冊", SUCCESS, terminal=True)
    f.box("closed", 2, 2050, "登記案件已核准／結案", SUCCESS, terminal=True)

    f.arrow("start", "auto", "right", "left")
    f.arrow("auto", "pending")
    f.arrow("pending", "edit", "left", "right", "修改")
    f.arrow("edit", "recheck", "right", "left")
    f.arrow("recheck", "pending", "top", "left", "是", via=[(990, 770), (990, 650)])
    f.arrow("recheck", "cancelled", "bottom", "top", "否", via=[(850, 1040)])
    f.arrow("pending", "cancel", "left", "right", "取消", via=[(570, 650), (570, 1160)])
    f.arrow("cancel", "cancelled", "right", "left")
    f.arrow("pending", "return", "right", "left", "退回", via=[(1240, 650), (1240, 890)])
    f.arrow("return", "returned", "left", "right", via=[(1240, 890), (1240, 1400)])
    f.arrow("returned", "edit", "left", "bottom", "補正", via=[(400, 1400), (400, 970)])
    f.arrow("pending", "approve", "right", "left", "核准", via=[(1310, 650), (1310, 1160)])
    f.arrow("approve", "asset_form")
    f.arrow("asset_form", "unique")
    f.arrow("unique", "create", "right", "left", "未重複")
    f.arrow("create", "ledger")
    f.arrow("ledger", "closed", "left", "right", via=[(1830, 1910), (1830, 2050)])
    f.note(1320, 1780, "若財產編號重複，系統拒絕建立並要求修正。", WARNING, 470)
    return f.save("asset-registration-workflow.jpg")


def office_supply():
    f = Flow(
        "辦公用品採購流程",
        "申請人建立多項用品需求，管理部統一處理、退回或完成提供",
        2200,
        [("申請人", EMPLOYEE), ("系統／狀態", SYSTEM), ("管理部", MANAGEMENT)],
    )
    f.box("start", 0, 390, "填寫用品申請\n至少一筆用品與數量", EMPLOYEE, h=145)
    f.diamond("other", 0, 650, "物品選擇「其他」？", EMPLOYEE)
    f.box("custom", 0, 900, "填寫自訂物品名稱", EMPLOYEE)
    f.box("auto", 1, 650, "產生案件編號\n記錄建立者與時間", SYSTEM, h=145)
    f.box("pending", 1, 930, "申請中", SYSTEM, terminal=True)
    f.box("edit", 0, 1180, "修改並重新送出", EMPLOYEE)
    f.box("cancel", 0, 1450, "取消／結案", NEUTRAL, terminal=True)
    f.box("processing", 1, 1450, "處理中", SYSTEM, terminal=True)
    f.box("returned", 1, 1730, "退回", WARNING, terminal=True)
    f.box("done", 1, 1990, "已提供／結案", SUCCESS, terminal=True)
    f.box("manage", 2, 930, "管理部查看全部案件", MANAGEMENT)
    f.box("batch", 2, 1180, "單筆或批量操作", MANAGEMENT)
    f.diamond("action", 2, 1450, "選擇處理方式", MANAGEMENT)

    f.arrow("start", "other")
    f.arrow("other", "custom", label="是")
    f.arrow("other", "auto", "right", "left", "否／完成填寫")
    f.arrow("custom", "auto", "right", "left", via=[(700, 900), (700, 650)])
    f.arrow("auto", "pending")
    f.arrow("pending", "edit", "left", "right", "申請人修改")
    f.arrow("edit", "pending", "right", "left", "狀態重檢", via=[(760, 1180), (760, 930)])
    f.arrow("pending", "cancel", "left", "right", "申請人取消", via=[(590, 930), (590, 1450)])
    f.arrow("pending", "manage", "right", "left")
    f.arrow("manage", "batch")
    f.arrow("batch", "action")
    f.arrow("action", "processing", "left", "right", "開始處理")
    f.arrow("action", "returned", "left", "right", "退回", via=[(1690, 1450), (1690, 1730)])
    f.arrow("action", "done", "left", "right", "完成", via=[(1800, 1450), (1800, 1990)])
    f.arrow("processing", "returned", label="退回")
    f.arrow("processing", "done", "bottom", "top", "完成", via=[(1200, 1870)])
    f.arrow("returned", "edit", "left", "bottom", "補正", via=[(430, 1730), (430, 1260)])
    f.note(1640, 1690, "批量操作前會重新檢查全部案件；任一狀態不符時整批取消。", WARNING, 600)
    return f.save("office-supply-procurement-workflow.jpg")


def equipment_procurement():
    f = Flow(
        "設備採購流程",
        "設備申請可由管理部直接處理，也可轉發至協作專區交由協力部門執行",
        2860,
        [("申請人", EMPLOYEE), ("設備案件", SYSTEM), ("管理部", MANAGEMENT), ("協作部門／後續", COLLAB)],
    )
    f.box("start", 0, 390, "填寫設備申請\n至少一筆設備與數量", EMPLOYEE, h=145)
    f.box("auto", 1, 390, "產生案件編號\n記錄建立者與時間", SYSTEM, h=145)
    f.box("pending", 1, 670, "申請中", SYSTEM, terminal=True)
    f.box("edit", 0, 930, "修改並重新送出", EMPLOYEE)
    f.box("cancel", 0, 1200, "取消／結案", NEUTRAL, terminal=True)
    f.box("processing", 1, 1200, "處理中", SYSTEM, terminal=True)
    f.box("returned", 1, 1480, "退回", WARNING, terminal=True)
    f.box("manage", 2, 670, "管理部查看全部案件", MANAGEMENT)
    f.diamond("action", 2, 950, "選擇處理方式", MANAGEMENT)
    f.box("forward", 2, 1250, "轉發協力部門\n預設資訊部", MANAGEMENT, h=145)
    f.diamond("reminder", 2, 1580, "確認完成提醒\n記得完成資產登記", MANAGEMENT, h=175)
    f.box("done", 1, 1810, "已提供／結案", SUCCESS, terminal=True)

    f.box("collab", 3, 1250, "建立新協作案件編號", COLLAB)
    f.box("c_pending", 3, 1510, "協作：待處理", COLLAB, terminal=True)
    f.box("c_processing", 3, 1770, "協作：處理中", COLLAB, terminal=True)
    f.box("c_return", 3, 2050, "協作：已退回\n可填退回原因", WARNING, h=145, terminal=True)
    f.box("c_done", 3, 2330, "協作：已完成", SUCCESS, terminal=True)
    f.box("c_withdraw", 2, 2330, "管理部撤回協作案件", NEUTRAL, h=135)
    f.box("asset", 1, 2590, "另行完成資產登記", SUCCESS, terminal=True)

    f.arrow("start", "auto", "right", "left")
    f.arrow("auto", "pending")
    f.arrow("pending", "edit", "left", "right", "申請人修改")
    f.arrow("edit", "pending", "right", "left", "狀態重檢", via=[(810, 930), (810, 670)])
    f.arrow("pending", "cancel", "left", "right", "申請人取消", via=[(600, 670), (600, 1200)])
    f.arrow("pending", "manage", "right", "left")
    f.arrow("manage", "action")
    f.arrow("action", "processing", "left", "right", "處理中")
    f.arrow("action", "returned", "left", "right", "退回", via=[(1370, 950), (1370, 1480)])
    f.arrow("returned", "edit", "left", "bottom", "補正", via=[(430, 1480), (430, 1010)])
    f.arrow("action", "forward", label="轉發")
    f.arrow("forward", "processing", "left", "right", "原案件")
    f.arrow("forward", "collab", "right", "left", "新協作案件")
    f.arrow("action", "reminder", label="完成")
    f.arrow("processing", "reminder", "right", "left", "完成")
    f.arrow("reminder", "done", "left", "right", "確認")
    f.arrow("collab", "c_pending")
    f.arrow("c_pending", "c_processing", label="開始處理")
    f.arrow("c_pending", "c_return", "left", "left", "退回", via=[(2050, 1510), (2050, 2050)])
    f.arrow("c_processing", "c_return", label="退回")
    f.arrow("c_processing", "c_done", "bottom", "top", "完成", via=[(2130, 2190)])
    f.arrow("c_pending", "c_done", "right", "right", "直接完成", via=[(2325, 1510), (2325, 2330)])
    f.arrow("c_pending", "c_withdraw", "left", "right", "撤回", via=[(1720, 1510), (1720, 2330)])
    f.arrow("c_return", "c_withdraw", "left", "right", "撤回")
    f.arrow("c_withdraw", "forward", "top", "bottom", "可再次轉發", via=[(1550, 2150), (1550, 1390)], dashed=True)
    f.arrow("done", "asset", "bottom", "top", "提醒，不自動建立", dashed=True)
    f.note(1260, 1900, "未經提醒浮窗確認碼，後端會拒絕完成設備案件。", WARNING, 520)
    f.note(1810, 2500, "協作專區的「查看」會以浮窗即時載入原設備申請內容。", COLLAB, 500)
    return f.save("equipment-procurement-workflow.jpg")


if __name__ == "__main__":
    for result in (asset_registration(), office_supply(), equipment_procurement()):
        print(result)
