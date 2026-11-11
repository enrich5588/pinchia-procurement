import hashlib
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.auth import get_user_model
from django.db import transaction

from .models import Department, PermissionAudit, PermissionRule
from .permission_catalog import DEFAULTS


def target_filter(target_type, target):
    if target_type not in {"department", "user"}:
        raise ValidationError("權限對象類型不正確。")
    expected = Department if target_type == "department" else get_user_model()
    if not isinstance(target, expected) or not target.pk:
        raise ValidationError("權限對象與設定類型不符。")
    return {f"{target_type}_id": target.pk}


def explicit_rules(target_type, target):
    return dict(PermissionRule.objects.filter(**target_filter(target_type, target)).values_list("permission", "effect"))


def revision_for(rules):
    return hashlib.sha256(json.dumps(rules, sort_keys=True).encode()).hexdigest()


@transaction.atomic
def save_permissions(*, actor, target_type, target, values, revision):
    if not actor.is_authenticated or not actor.is_active or not actor.is_superuser:
        raise PermissionDenied("只有系統管理員可以設定權限。")
    type(target).objects.select_for_update().get(pk=target.pk)
    filters = target_filter(target_type, target)
    before = explicit_rules(target_type, target)
    if revision_for(before) != revision:
        raise ValidationError("此對象的權限已由其他管理員更新，請重新載入後再設定。")
    if set(values) != set(DEFAULTS) or any(value not in {"inherit", "allow", "deny"} for value in values.values()):
        raise ValidationError("權限欄位不完整或設定值無效。")
    changes = {}
    for code, effect in values.items():
        previous = before.get(code, "inherit")
        if effect == previous:
            continue
        changes[code] = {"before": previous, "after": effect}
        if effect == "inherit":
            PermissionRule.objects.filter(**filters, permission=code).delete()
        else:
            PermissionRule.objects.update_or_create(**filters, permission=code, defaults={"effect": effect})
    if changes:
        PermissionAudit.objects.create(
            actor=actor, actor_label=actor.get_username(), target_type=target_type,
            target_id=target.pk, target_label=str(target), changes=changes,
        )
    return changes
