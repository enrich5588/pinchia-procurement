from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from .models import (
    EquipmentApplication,
    EquipmentApplicationItem,
    OfficeSupplyApplication,
    OfficeSupplyApplicationItem,
)


class OfficeSupplyApplicationForm(forms.ModelForm):
    class Meta:
        model = OfficeSupplyApplication
        fields = ["need_date", "notes"]
        widgets = {
            "need_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, department, applicant, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.department = department
        self.instance.applicant = applicant


class OfficeSupplyApplicationItemForm(forms.ModelForm):
    class Meta:
        model = OfficeSupplyApplicationItem
        fields = ["product", "custom_name", "quantity"]
        widgets = {
            "custom_name": forms.TextInput(attrs={"placeholder": "請輸入物品名稱"}),
            "quantity": forms.NumberInput(attrs={"min": 1}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_bound:
            selected_product = self.data.get(self.add_prefix("product"), "")
        else:
            selected_product = self.instance.product if self.instance.pk else ""
        if selected_product != OfficeSupplyApplicationItem.Product.OTHER:
            self.fields["custom_name"].widget.attrs["disabled"] = True

    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get("product")
        custom_name = (cleaned_data.get("custom_name") or "").strip()
        if product == OfficeSupplyApplicationItem.Product.OTHER and not custom_name:
            self.add_error("custom_name", "選擇其他時，請填寫物品名稱。")
        if product != OfficeSupplyApplicationItem.Product.OTHER:
            cleaned_data["custom_name"] = ""
        return cleaned_data


class BaseOfficeSupplyItemFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        active_forms = [
            form for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE", False)
        ]
        if not active_forms:
            raise forms.ValidationError("請至少新增一個申請用品項目。")


OfficeSupplyItemFormSet = inlineformset_factory(
    OfficeSupplyApplication,
    OfficeSupplyApplicationItem,
    form=OfficeSupplyApplicationItemForm,
    formset=BaseOfficeSupplyItemFormSet,
    extra=0,
    can_delete=True,
    min_num=1,
    validate_min=True,
)


class EquipmentApplicationForm(forms.ModelForm):
    class Meta:
        model = EquipmentApplication
        fields = ["need_date", "notes"]
        widgets = {
            "need_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, department, applicant, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.department = department
        self.instance.applicant = applicant


class EquipmentApplicationItemForm(forms.ModelForm):
    class Meta:
        model = EquipmentApplicationItem
        fields = ["equipment_name", "quantity"]
        widgets = {
            "equipment_name": forms.TextInput(attrs={"placeholder": "請輸入設備名稱"}),
            "quantity": forms.NumberInput(attrs={"min": 1}),
        }


class BaseEquipmentItemFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        active_forms = [
            form for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE", False)
        ]
        if not active_forms:
            raise forms.ValidationError("請至少新增一個申請設備項目。")


EquipmentItemFormSet = inlineformset_factory(
    EquipmentApplication,
    EquipmentApplicationItem,
    form=EquipmentApplicationItemForm,
    formset=BaseEquipmentItemFormSet,
    extra=0,
    can_delete=True,
    min_num=1,
    validate_min=True,
)
