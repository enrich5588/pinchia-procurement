from django import forms
from django.contrib.auth import get_user_model

from .models import Department
from .permission_catalog import PERMISSIONS


class UserChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        name = obj.get_full_name()
        identity = getattr(obj, "microsoft_identity", None)
        account = identity.principal_name if identity and identity.principal_name else obj.username
        label = f"{name}（{account}）" if name else account
        return label if obj.is_active else f"{label}［已停用］"


class PermissionTargetForm(forms.Form):
    scope = forms.ChoiceField(label="設定類型", choices=[("department", "部門權限"), ("user", "個人權限")])

    def __init__(self, *args, scope="department", **kwargs):
        super().__init__(*args, **kwargs)
        if scope == "user":
            self.fields["target"] = UserChoiceField(label="選擇個人", queryset=get_user_model().objects.select_related("microsoft_identity").order_by("first_name", "username"))
        else:
            self.fields["target"] = forms.ModelChoiceField(label="選擇部門", queryset=Department.objects.order_by("name"))


class PermissionEditForm(forms.Form):
    revision = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for code, label, description, default in PERMISSIONS:
            self.fields[code] = forms.ChoiceField(
                label=label, help_text=description,
                choices=[("inherit", "繼承"), ("allow", "允許"), ("deny", "拒絕")],
            )
