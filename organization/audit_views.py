from django.contrib.auth.decorators import login_required
from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .audit import retention_cutoff
from .models import OperationLog


@login_required
@never_cache
@require_GET
def operation_logs(request):
    if not request.user.is_superuser:
        raise PermissionDenied('只有系統管理員可查看操作紀錄。')
    query = request.GET.get('q', '').strip()[:200]
    action = request.GET.get('action', '')
    logs = OperationLog.objects.filter(created_at__gte=retention_cutoff())
    if query:
        logs = logs.filter(Q(actor_label__icontains=query) | Q(object_label__icontains=query)
                           | Q(model_label__icontains=query) | Q(path__icontains=query)
                           | Q(object_id__icontains=query))
    if action in dict(OperationLog.ACTIONS):
        logs = logs.filter(action=action)
    page = Paginator(logs, 20).get_page(request.GET.get('page'))
    for log in page:
        try:
            model = apps.get_model(log.model_label) if log.model_label else None
        except (LookupError, ValueError):
            model = None
        log.detail_changes = []
        for name, values in log.changes.items():
            try:
                field = model._meta.get_field(name) if model else None
            except FieldDoesNotExist:
                field = None
            def display(value):
                if value is None:
                    return '未設定'
                if field and field.choices and isinstance(value, (str,int,bool)):
                    return dict(field.flatchoices).get(value, value)
                if isinstance(field, models.DateTimeField) and isinstance(value, str):
                    moment = parse_datetime(value)
                    if moment and timezone.is_aware(moment):
                        return timezone.localtime(moment).strftime('%Y/%m/%d %H:%M:%S（台北時間）')
                if isinstance(value, bool):
                    return '是' if value else '否'
                return value
            log.detail_changes.append({'label': str(field.verbose_name) + ('（ID）' if field.is_relation else '') if field else name,
                                       'before': display(values.get('before')), 'after': display(values.get('after'))})
    return render(request, 'organization/operation_logs.html', {
        'logs': page, 'query': query, 'action': action, 'actions': OperationLog.ACTIONS,
    })
