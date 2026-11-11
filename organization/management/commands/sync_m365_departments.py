import time

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, close_old_connections

from organization.department_sync import DepartmentSyncError, sync_departments


class Command(BaseCommand):
    help = "同步 M365 全公司部門與員工；--watch 持續自動更新（預設每六小時），失敗十五分鐘後重試。"

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true")
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **options):
        while True:
            try:
                close_old_connections()
                result = sync_departments(force=options["force"])
                if result is not None:
                    self.stdout.write(f"M365 departments: {result['departments']}; added: {result['created']}; employees: {result['employees']}")
            except (DepartmentSyncError, DatabaseError) as error:
                message = str(error) if isinstance(error, DepartmentSyncError) else "部門同步資料庫暫時忙碌，稍後重試。"
                if not options["watch"]:
                    raise CommandError(message) from error
                self.stderr.write(message)
            if not options["watch"]:
                break
            options["force"] = False
            try:
                time.sleep(30)
            except KeyboardInterrupt:
                break
