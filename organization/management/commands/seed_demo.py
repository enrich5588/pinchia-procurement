"""建立測試帳號與部門(冪等,重跑不會壞)。"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from organization.models import Department, UserProfile
from project_options.approvals import APPROVAL_AUTHORITY_ORDER


class Command(BaseCommand):
    help = "建立 開發測試帳號(staff1/staff2/manager1/admin,密碼都是 demo)"

    def handle(self, *args, **opts):
        depts = {n: Department.objects.get_or_create(name=n)[0]
                 for n in ("資訊部", "都更事業部", "管理部")}
        plan = [("staff1", "資訊部", False), ("staff2", "都更事業部", False),
                ("manager1", "管理部", False)]
        plan.extend((name, "管理部", False) for name in APPROVAL_AUTHORITY_ORDER)
        for username, dept, _ in plan:
            u, created = User.objects.get_or_create(
                username=username, defaults={"email": f"{username}@example.com"})
            if created:
                u.set_password("demo")
                u.save()
            UserProfile.objects.get_or_create(user=u,
                                              defaults={"department": depts[dept]})
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser("admin", "admin@example.com", "demo")
            # 管理員可沒有部門，業務功能須能處理此情況。
        self.stdout.write(self.style.SUCCESS(
            "測試帳號就緒:staff1/staff2/manager1/admin/"
            + "/".join(APPROVAL_AUTHORITY_ORDER) + "（新帳號密碼 demo）"))
