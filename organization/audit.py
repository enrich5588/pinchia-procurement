"""Operation history without request bodies, query strings or credentials."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
import json
import uuid

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models.signals import pre_save, post_save, pre_delete, post_delete, m2m_changed
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.utils import timezone

context = ContextVar('operation_audit', default=None)
BUSINESS_APPS = {'procurement', 'assets', 'approval_hub', 'collaboration_hub', 'platform_stub'}
EXCLUDED_MODELS = {'operationlog', 'permissionaudit', 'departmentsyncstate'}
EXCLUDED_FIELDS = {'password', 'last_login', 'rows', 'skipped'}


@contextmanager
def audit_context(source='系統／背景作業', request=None):
    initial = getattr(request, 'user', None)
    actor = initial if initial and initial.is_authenticated else None
    state = {'request': request, 'actor': actor, 'source': source, 'request_id': uuid.uuid4()}
    token = context.set(state)
    try:
        yield state
    finally:
        context.reset(token)


def tracked(model):
    from django.apps import apps
    meta = model._meta
    return (meta.apps is apps and not meta.auto_created and not meta.proxy and meta.model_name not in EXCLUDED_MODELS
            and not meta.model_name.endswith('dailysequence')
            and (meta.app_label in BUSINESS_APPS or meta.label_lower in {'auth.user', 'auth.group'}))


def snapshot(instance):
    result = {}
    for field in instance._meta.concrete_fields:
        name = field.name
        if name in EXCLUDED_FIELDS or any(word in name.lower() for word in ['token', 'secret', 'private_key']):
            continue
        value = getattr(instance, field.attname)
        # Files are represented by storage names; never read or copy their contents.
        if hasattr(value, 'name') and hasattr(value, 'storage'):
            value = value.name
        result[name] = value
    return json.loads(json.dumps(result, cls=DjangoJSONEncoder, ensure_ascii=False))


def object_label(instance):
    from django.core.exceptions import ObjectDoesNotExist
    try:
        if instance._meta.model_name == 'featurepanel':
            from .panels import PANELS
            return next((label for code,label,*_ in PANELS if code == instance.code), instance.code)
        if instance._meta.model_name == 'permissionrule':
            target = instance.user.get_username() if instance.user_id else str(instance.department)
            return f'{target} · {instance.permission}'
        return str(instance)
    except ObjectDoesNotExist:
        return f'{instance._meta.verbose_name} #{instance.pk}'


def record(action, *, instance=None, changes=None, outcome='', status_code=None, actor=None):
    from .models import OperationLog
    state = context.get() or {}
    request = state.get('request')
    user = actor or (getattr(request, 'user', None) if request else None)
    if not user or not user.is_authenticated:
        user = state.get('actor')
    authenticated = bool(user and user.is_authenticated)
    match = getattr(request, 'resolver_match', None)
    return OperationLog.objects.create(
        actor_id=user.pk if authenticated else None,
        actor_label=user.get_username() if authenticated else ('未登入' if request else '系統／背景作業'),
        action=action, source=state.get('source', '系統／命令列'),
        request_id=state.get('request_id', uuid.uuid4()),
        model_label=instance._meta.label_lower if instance is not None else '',
        object_id=str(instance.pk)[:100] if instance is not None else '',
        object_label=object_label(instance)[:200] if instance is not None else '',
        changes=changes or {}, method=request.method if request else '',
        path=request.path[:500] if request else '',
        route=(match.view_name if match else '')[:150], status_code=status_code, outcome=outcome,
    )


def record_change(instance, before, after, created=False):
    changes = {name: {'before': before.get(name), 'after': after.get(name)}
               for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
    if getattr(instance, '_audit_password_changed', False):
        changes['password'] = {'before': '[不記錄]', 'after': '[密碼已變更]'}
    if changes:
        record('create' if created else 'update', instance=instance, changes=changes, outcome='成功')


def before_save(sender, instance, raw=False, using='default', **kwargs):
    if raw or not tracked(sender):
        return
    previous = sender._base_manager.using(using).filter(pk=instance.pk).first() if instance.pk is not None else None
    instance._audit_before = snapshot(previous) if previous else {}
    instance._audit_password_before = previous.password if previous is not None and hasattr(previous, 'password') else None


def after_save(sender, instance, created, raw=False, **kwargs):
    if not raw and tracked(sender):
        saved = sender._base_manager.using(kwargs.get('using', 'default')).get(pk=instance.pk)
        old_password = getattr(instance, '_audit_password_before', None)
        saved._audit_password_changed = old_password is not None and old_password != getattr(saved, 'password', None)
        record_change(saved, getattr(instance, '_audit_before', {}), snapshot(saved), created)


def before_delete(sender, instance, **kwargs):
    if tracked(sender):
        values = snapshot(instance)
        for field in instance._meta.many_to_many:
            values[field.name] = list(getattr(instance, field.name).values_list('pk', flat=True))
        if instance._meta.label_lower == 'auth.group':
            values['members'] = list(instance.user_set.values_list('pk', flat=True))
        instance._audit_deleted = values


def after_delete(sender, instance, **kwargs):
    if tracked(sender):
        record('delete', instance=instance,
               changes={key: {'before': value, 'after': None} for key, value in getattr(instance, '_audit_deleted', snapshot(instance)).items()}, outcome='成功')


def relation_changed(sender, instance, action, reverse=False, **kwargs):
    if not tracked(type(instance)):
        return
    links = [field for field in sender._meta.fields if field.is_relation]
    related = [field for field in links if field.remote_field.model == type(instance)]
    if len(related) != 1:
        return
    def values():
        return list(sender._base_manager.filter(**{related[0].attname: instance.pk})
                    .order_by(*[field.attname for field in links]).values(*[field.attname for field in links]))
    key = '_audit_m2m_' + sender._meta.label_lower
    if action.startswith('pre_'):
        setattr(instance, key, values())
    elif action.startswith('post_'):
        before, after = getattr(instance, key, []), values()
        if before != after:
            record('update', instance=instance,
                   changes={sender._meta.label_lower: {'before': before, 'after': after}}, outcome='成功')


def auth_login(sender, request, user, **kwargs):
    record('login', actor=user, outcome='成功')


def auth_logout(sender, request, user, **kwargs):
    if user and user.is_authenticated:
        record('logout', actor=user, outcome='成功')


def auth_failed(sender, **kwargs):
    # Never inspect credentials, even sanitized provider error payloads.
    record('login_failed', outcome='登入失敗')


def install():
    for signal, handler in [(pre_save, before_save), (post_save, after_save),
                            (pre_delete, before_delete), (post_delete, after_delete), (m2m_changed, relation_changed),
                            (user_logged_in, auth_login), (user_logged_out, auth_logout),
                            (user_login_failed, auth_failed)]:
        signal.connect(handler, weak=False, dispatch_uid='operation_audit.' + handler.__name__)


def retention_cutoff():
    return timezone.now() - timedelta(days=30)
