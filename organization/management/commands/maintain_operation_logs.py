import time

from django.contrib.admin.models import LogEntry
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, close_old_connections

from organization.audit import retention_cutoff, audit_context, record
from organization.models import OperationLog, PermissionAudit


def purge():
    cutoff = retention_cutoff()
    counts = {}
    for model, date_field in [(OperationLog, 'created_at'), (PermissionAudit, 'created_at'), (LogEntry, 'action_time')]:
        total = 0
        while True:
            ids = list(model.objects.filter(**{date_field + '__lt': cutoff}).values_list('pk', flat=True)[:500])
            if not ids:
                break
            deleted, _ = model.objects.filter(pk__in=ids).delete()
            total += deleted
        counts[model._meta.model_name] = total
    return counts


class Command(BaseCommand):
    help = '清理超過 30 天的操作、權限與後台紀錄；--watch 每小時執行。'

    def add_arguments(self, parser):
        parser.add_argument('--watch', action='store_true')

    def handle(self, *args, **options):
        while True:
            try:
                close_old_connections()
                with audit_context(source="操作紀錄保存維護"):
                    result = purge()
                    record("background", outcome="逾期紀錄清理完成", changes={key: {"before": None, "after": value} for key, value in result.items()})
                self.stdout.write(str(result))
            except DatabaseError as error:
                if not options['watch']:
                    raise CommandError('操作紀錄清理失敗，請檢查資料庫。') from error
                self.stderr.write('操作紀錄清理失敗，一小時後重試。')
            if not options['watch']:
                break
            try:
                time.sleep(3600)
            except KeyboardInterrupt:
                break
