from django import forms

from organization.models import Department
from procurement.permissions import MANAGEMENT_DEPARTMENT_NAME


class EquipmentForwardForm(forms.Form):
    assigned_department = forms.ModelChoiceField(
        label="欲轉發需求的部門",
        queryset=Department.objects.none(),
        empty_label=None,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_department"].queryset = Department.objects.exclude(
            name=MANAGEMENT_DEPARTMENT_NAME
        ).order_by("name")


class CollaborationReturnForm(forms.Form):
    return_reason = forms.CharField(
        label="退回原因",
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 4,
            "placeholder": "可填寫需要補充或調整的內容（非必填）",
        }),
    )
