from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .models import FeaturePanel, PermissionAudit
from .panels import PANELS, PANEL_KEYS
from .permission_service import revision_for


class PanelForm(forms.Form):
    revision = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for code, label, *_ in PANELS:
            self.fields[code] = forms.ChoiceField(label=f"{label}開放狀態", choices=FeaturePanel.Status.choices)


@transaction.atomic
def save_panels(actor, values, revision):
    if not actor.is_authenticated or not actor.is_active or not actor.is_superuser:
        raise PermissionDenied("只有系統管理員可管理面板。")
    panels = {panel.code: panel for panel in FeaturePanel.objects.select_for_update().filter(code__in=PANEL_KEYS).order_by("code")}
    if set(panels) != PANEL_KEYS or set(values) != PANEL_KEYS:
        raise ValidationError("面板設定不完整，請確認資料庫已更新。")
    before = {code: panel.status for code, panel in panels.items()}
    if revision_for(before) != revision:
        raise ValidationError("其他管理員已更新面板狀態，請重新載入後再設定。")
    if any(value not in FeaturePanel.Status.values for value in values.values()):
        raise ValidationError("面板狀態不正確。")
    labels = {code: label for code, label, *_ in PANELS}
    changed = 0
    for code, panel in panels.items():
        if panel.status == values[code]:
            continue
        previous = panel.status
        panel.status, panel.updated_by = values[code], actor
        panel.save(update_fields=["status", "updated_by", "updated_at"])
        PermissionAudit.objects.create(actor=actor, actor_label=actor.get_username(),
            target_type="panel", target_id=panel.pk, target_label=labels[code],
            changes={"status": {"before": previous, "after": panel.status}})
        changed += 1
    return changed


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def panel_management(request):
    if not request.user.is_superuser:
        raise PermissionDenied("只有系統管理員可管理面板。")
    panels = {panel.code: panel for panel in FeaturePanel.objects.select_related("updated_by").filter(code__in=PANEL_KEYS)}
    initial = {code: panel.status for code, panel in panels.items()}
    initial["revision"] = revision_for({code: panel.status for code, panel in panels.items()})
    form = PanelForm(request.POST if request.method == "POST" else None, initial=initial)
    status = 200
    if request.method == "POST":
        if form.is_valid():
            try:
                changed = save_panels(request.user, {code: form.cleaned_data[code] for code in PANEL_KEYS}, form.cleaned_data["revision"])
            except ValidationError as error:
                form.add_error(None, error)
                status = 409
            else:
                messages.success(request, f"已更新 {changed} 個面板；後續請求立即生效。" if changed else "面板設定未變更。")
                return redirect("panel_management")
        else:
            status = 422
    rows = [{"field": form[code], "label": label, "description": description, "icon": icon,
             "panel": panels.get(code)} for code, label, description, icon in PANELS]
    return render(request, "organization/panel_management.html", {
        "panel_form": form, "panels": rows, "global_open": settings.FEATURE_OPEN_TO_ALL,
        "open_count": sum(panel.status == FeaturePanel.Status.OPEN for panel in panels.values()),
        "history": PermissionAudit.objects.filter(target_type="panel")[:20],
    }, status=status)
