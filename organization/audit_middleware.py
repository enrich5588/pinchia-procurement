from .audit import audit_context, record


class OperationAuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/static/') or request.path in {'/health/', '/healthz/'}:
            return self.get_response(request)
        with audit_context(source='網站', request=request) as context_state:
            response = self.get_response(request)
            user = getattr(request, 'user', None)
            if user and user.is_authenticated:
                from .models import OperationLog
                OperationLog.objects.filter(request_id=context_state['request_id'], actor__isnull=True).update(
                    actor_id=user.pk, actor_label=user.get_username())
            record('request', status_code=response.status_code,
                   outcome='拒絕' if response.status_code in (401, 403) else
                           ('失敗' if response.status_code >= 400 else '完成'))
            return response
