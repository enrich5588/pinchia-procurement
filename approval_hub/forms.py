from django import forms

from project_options.approvals import ApprovalDocumentType

from .models import ApprovalRequest


class ApprovalRequestForm(forms.ModelForm):
    document_type = forms.ChoiceField(
        label="公文種類", required=False,
        choices=(("", "--------"), *ApprovalDocumentType.choices),
        widget=forms.RadioSelect,
    )

    class Meta:
        model = ApprovalRequest
        fields = ["subject", "content", "amount_range", "document_type"]
        widgets = {
            "subject": forms.TextInput(attrs={"placeholder": "請輸入簽呈主旨"}),
            "content": forms.Textarea(attrs={"rows": 7, "placeholder": "請說明事由、目的與執行內容"}),
            "amount_range": forms.RadioSelect,
            "document_type": forms.RadioSelect,
        }


class ApprovalDecisionForm(forms.Form):
    comment = forms.CharField(
        label="簽核意見", required=False,
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "可填寫核准或退回原因"}),
    )
