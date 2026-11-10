from django.core.management.base import BaseCommand, CommandError

from organization.microsoft import configuration_problem


class Command(BaseCommand):
    help = "離線檢查 M365 登入設定（不連線 Microsoft、不顯示憑證或密鑰）。"

    def handle(self, *args, **options):
        problem = configuration_problem()
        if problem:
            raise CommandError(problem)
        self.stdout.write(self.style.SUCCESS(
            "M365 設定格式檢查通過；仍需實際登入確認 Entra 設定、憑證與 Graph 權限。"
        ))
