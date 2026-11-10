from django import forms
from django.contrib.auth import get_user_model
from django.forms import BaseFormSet, formset_factory

from organization.models import Department, user_department

from .models import Asset, AssetImage, AssetRegistration


class MultipleImageInput(forms.FileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    widget = MultipleImageInput(attrs={"accept": "image/jpeg,image/png,image/webp,image/gif"})

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, (list, tuple)) else [data]
        if len(files) > 10:
            raise forms.ValidationError("每次最多上傳 10 張圖片。")
        cleaned = []
        for upload in files:
            if upload.size > 5 * 1024 * 1024:
                raise forms.ValidationError("每張圖片不可超過 5 MB。")
            image = super().clean(upload, initial)
            if image.image.format not in {"JPEG", "PNG", "WEBP", "GIF"}:
                raise forms.ValidationError("僅支援 JPG、PNG、WebP 與 GIF 圖片。")
            cleaned.append(image)
        return cleaned


class AssetForm(forms.ModelForm):
    total = forms.DecimalField(
        label="合計", required=False, disabled=True, decimal_places=2,
        widget=forms.NumberInput(attrs={"readonly": True, "data-asset-total": ""}),
        help_text="由單價與營業稅自動加總，無法修改。",
    )
    images = MultipleImageField(
        label="上傳財產圖片", required=False,
        help_text="可一次選取多張 JPG、PNG、WebP 或 GIF；每張最多 5 MB，每次最多 10 張。",
    )
    remove_images = forms.ModelMultipleChoiceField(
        label="移除圖片", queryset=AssetImage.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="勾選後按儲存變更，才會移除圖片。",
    )
    class Meta:
        model = Asset
        fields = [
            "asset_no",
            "name",
            "company",
            "category",
            "brand",
            "specification",
            "accessories",
            "quantity",
            "unit_price",
            "business_tax",
            "department",
            "custodian",
            "purchase_date",
            "useful_life_years",
            "notes",
        ]
        widgets = {
            "category": forms.TextInput(attrs={"placeholder": "請輸入財產類別"}),
            "accessories": forms.Textarea(attrs={"rows": 2}),
            "quantity": forms.NumberInput(attrs={"min": 1, "step": 1}),
            "unit_price": forms.NumberInput(attrs={
                "min": 0, "step": "0.01", "data-asset-unit-price": "",
            }),
            "business_tax": forms.NumberInput(attrs={
                "min": 0, "step": "0.01", "data-asset-business-tax": "",
            }),
            "purchase_date": forms.DateInput(
                format="%Y-%m-%d", attrs={"type": "date"}
            ),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["total"].initial = (
            self.instance.total if self.instance.pk else self.initial.get("total", 0)
        )
        if self.instance.pk:
            self.fields["remove_images"].queryset = self.instance.images.all()
        else:
            self.fields.pop("remove_images")
        self.fields["custodian"].queryset = (
            get_user_model().objects.filter(profile__isnull=False).order_by("username")
        )
        self.fields["custodian"].empty_label = "部門資產（共用資源）"
        if self.instance.pk:
            self.fields["asset_no"].disabled = True
            self.fields["asset_no"].help_text = "財產編號建立後不可修改。"
        self.order_fields([
            "asset_no", "name", "company", "category", "brand", "specification",
            "accessories", "quantity", "unit_price", "business_tax", "total",
            "department", "custodian", "purchase_date", "useful_life_years",
            "notes", "images", "remove_images",
        ])

    def clean_asset_no(self):
        asset_no = self.cleaned_data["asset_no"].strip().upper()
        duplicates = Asset.objects.filter(asset_no__iexact=asset_no)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError("財產編號已存在，請使用其他編號。")
        return asset_no


class AssetRegistrationForm(forms.ModelForm):
    total = forms.DecimalField(
        label="合計", required=False, disabled=True, decimal_places=2,
        widget=forms.NumberInput(attrs={"readonly": True, "data-asset-total": ""}),
        help_text="由單價與營業稅自動加總，無法修改。",
    )
    images = MultipleImageField(
        label="上傳財產圖片", required=False,
        help_text="可一次選取多張 JPG、PNG、WebP 或 GIF；每張最多 5 MB，每次最多 10 張。核准後會一併加入財產清冊。",
    )
    remove_images = forms.ModelMultipleChoiceField(
        label="移除圖片", queryset=AssetImage.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="勾選後重新送出申請，才會移除圖片。",
    )
    asset_images_to_remove = forms.ModelMultipleChoiceField(
        label="核准後移除的現有圖片", queryset=AssetImage.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="財產清冊中的圖片會保留至管理部核准；勾選的圖片將於核准後移除。",
    )
    class Meta:
        model = AssetRegistration
        fields = [
            "name", "company", "category", "brand", "specification", "accessories",
            "quantity", "unit_price", "business_tax", "department", "custodian",
            "purchase_date", "useful_life_years", "notes",
        ]
        widgets = {
            "category": forms.TextInput(attrs={"placeholder": "請輸入財產類別"}),
            "accessories": forms.Textarea(attrs={"rows": 2}),
            "quantity": forms.NumberInput(attrs={"min": 1, "step": 1}),
            "unit_price": forms.NumberInput(attrs={
                "min": 0, "step": "0.01", "data-asset-unit-price": "",
            }),
            "business_tax": forms.NumberInput(attrs={
                "min": 0, "step": "0.01", "data-asset-business-tax": "",
            }),
            "purchase_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, department, target_asset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["total"].initial = (
            self.instance.total if self.instance.pk else self.initial.get("total", 0)
        )
        self.target_asset = target_asset or getattr(self.instance, "target_asset", None)
        if self.instance.pk:
            self.fields["remove_images"].queryset = self.instance.images.all()
        else:
            self.fields.pop("remove_images")
        if self.target_asset:
            self.fields["asset_images_to_remove"].queryset = self.target_asset.images.all()
            if self.instance.pk:
                self.initial["asset_images_to_remove"] = self.instance.asset_images_to_remove.all()
        else:
            self.fields.pop("asset_images_to_remove")
        self.fields["department"].queryset = Department.objects.order_by("name")
        self.fields["department"].widget.attrs["data-registration-department"] = ""
        if not self.instance.pk and "department" not in self.initial:
            self.initial["department"] = department.pk
        if self.is_bound:
            selected_department_id = self.data.get(self.add_prefix("department"))
        elif self.instance.pk:
            selected_department_id = self.instance.department_id
        else:
            initial_department = self.initial.get("department", department.pk)
            selected_department_id = getattr(initial_department, "pk", initial_department)
        selected_department = Department.objects.filter(pk=selected_department_id).first()
        self.fields["custodian"].queryset = get_user_model().objects.filter(
            profile__department=selected_department
        ).order_by("username")
        self.fields["custodian"].widget.attrs["data-registration-custodian"] = ""
        self.fields["custodian"].empty_label = "部門資產（共用資源）"
        self.fields["custodian"].help_text = "共用資產未指定個人保管時，請選擇「部門資產」。"
        self.order_fields([
            "name", "company", "category", "brand", "specification", "accessories",
            "quantity", "unit_price", "business_tax", "total", "department", "custodian",
            "purchase_date", "useful_life_years", "notes", "images",
            "remove_images", "asset_images_to_remove",
        ])

    def clean_custodian(self):
        custodian = self.cleaned_data["custodian"]
        department = self.cleaned_data.get("department")
        if custodian and department and user_department(custodian) != department:
            raise forms.ValidationError("保管人員必須屬於所選部門。")
        return custodian


class AssetBulkApprovalRowForm(forms.Form):
    registration_id = forms.IntegerField(widget=forms.HiddenInput)
    asset_no = forms.CharField(label="財產編號", max_length=50)

    def clean_asset_no(self):
        return self.cleaned_data["asset_no"].strip().upper()


class BaseAssetBulkApprovalFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        numbers = [form.cleaned_data["asset_no"] for form in self.forms]
        normalized = [number.casefold() for number in numbers]
        if len(normalized) != len(set(normalized)):
            raise forms.ValidationError("批量核准中的財產編號不可重複。")
        existing = [
            number for number in numbers
            if Asset.objects.filter(asset_no__iexact=number).exists()
        ]
        if existing:
            raise forms.ValidationError(
                f"下列財產編號已存在：{', '.join(existing)}"
            )


AssetBulkApprovalFormSet = formset_factory(
    AssetBulkApprovalRowForm,
    formset=BaseAssetBulkApprovalFormSet,
    extra=0,
    min_num=1,
    validate_min=True,
)


class AssetBulkUploadForm(forms.Form):
    excel_file = forms.FileField(
        label="Excel 檔案",
        help_text="請上傳 .xlsx 檔案，檔案上限 150 MB。",
        widget=forms.FileInput(attrs={"accept": ".xlsx"}),
    )
    testing_compatibility = forms.BooleanField(
        label="測試環境相容模式",
        required=False,
        help_text=(
            "找不到的部門會改用下方指定部門；找不到或部門不符的使用者會先留空。"
            "Excel 原始資料會保留在財產備註。"
        ),
    )
    fallback_department = forms.ModelChoiceField(
        label="替代部門",
        queryset=Department.objects.none(),
        required=False,
        empty_label="請選擇測試用替代部門",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fallback_department"].queryset = Department.objects.order_by("name")

    def clean_excel_file(self):
        upload = self.cleaned_data["excel_file"]
        if not upload.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("僅支援 .xlsx 格式的 Excel 檔案。")
        if upload.size > 150 * 1024 * 1024:
            raise forms.ValidationError("Excel 檔案不可超過 150 MB。")
        return upload

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("testing_compatibility") and not cleaned.get("fallback_department"):
            self.add_error("fallback_department", "啟用測試環境相容模式時，請選擇替代部門。")
        return cleaned


class AssetImportPreviewRowForm(forms.Form):
    row_index = forms.IntegerField(widget=forms.HiddenInput)
    source_row_number = forms.IntegerField(label="Excel 列", required=False, disabled=True)
    image_status = forms.CharField(label="圖片", required=False, disabled=True)
    include = forms.BooleanField(label="匯入", required=False, initial=True)
    asset_no = forms.CharField(label="財產編號", max_length=50, required=False)
    name = forms.CharField(label="財產名稱", max_length=200, required=False)
    company = forms.ChoiceField(
        label="公司", choices=[("", "請選擇")] + list(Asset.Company.choices), required=False
    )
    category = forms.CharField(label="財產類別", max_length=100, required=False)
    brand = forms.CharField(label="廠牌", max_length=100, required=False)
    specification = forms.CharField(
        label="財產規格型號", max_length=255, required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    accessories = forms.CharField(
        label="配件", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )
    quantity = forms.IntegerField(label="數量", min_value=1, required=False)
    unit_price = forms.DecimalField(
        label="單價", min_value=0, max_digits=12, decimal_places=2, required=False
    )
    business_tax = forms.DecimalField(
        label="營業稅", min_value=0, max_digits=12, decimal_places=2, required=False
    )
    department = forms.ModelChoiceField(
        label="所屬部門", queryset=Department.objects.none(), required=False
    )
    custodian = forms.ModelChoiceField(
        label="保管人員", queryset=get_user_model().objects.none(), required=False,
        empty_label="未指定",
    )
    purchase_date = forms.DateField(
        label="採購日期", required=False,
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    notes = forms.CharField(label="備註", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.order_by("name")
        self.fields["custodian"].queryset = (
            get_user_model().objects.filter(profile__isnull=False).order_by("username")
        )

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("include"):
            return cleaned
        for field in ("asset_no", "name", "company", "category", "quantity", "department", "purchase_date"):
            if cleaned.get(field) in (None, ""):
                self.add_error(field, "此欄位為必要欄位。")
        asset_no = cleaned.get("asset_no")
        if asset_no:
            cleaned["asset_no"] = asset_no.strip().upper()
        custodian = cleaned.get("custodian")
        department = cleaned.get("department")
        if custodian and department and user_department(custodian) != department:
            self.add_error("custodian", "保管人員必須屬於所選部門。")
        return cleaned


class BaseAssetImportPreviewFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        selected = [
            form for form in self.forms
            if getattr(form, "cleaned_data", {}).get("include")
        ]
        if not selected:
            raise forms.ValidationError("請至少選擇一筆資料匯入。")
        if any(form.errors for form in selected):
            return
        numbers = [form.cleaned_data["asset_no"] for form in selected]
        normalized = [number.casefold() for number in numbers]
        if len(normalized) != len(set(normalized)):
            raise forms.ValidationError("匯入資料中的財產編號不可重複。")
        requested = set(normalized)
        existing = [
            number for number in Asset.objects.values_list("asset_no", flat=True)
            if number.casefold() in requested
        ]
        if existing:
            raise forms.ValidationError(f"下列財產編號已存在：{', '.join(existing)}")


AssetImportPreviewFormSet = formset_factory(
    AssetImportPreviewRowForm,
    formset=BaseAssetImportPreviewFormSet,
    extra=0,
    max_num=500,
    validate_max=True,
)


class RegistrationImportPreviewRowForm(forms.Form):
    row_index = forms.IntegerField(widget=forms.HiddenInput)
    source_row_number = forms.IntegerField(label="Excel 列", required=False, disabled=True)
    image_status = forms.CharField(label="圖片", required=False, disabled=True)
    include = forms.BooleanField(label="匯入", required=False, initial=True)
    name = forms.CharField(label="財產名稱", max_length=200, required=False)
    company = forms.ChoiceField(
        label="公司", choices=[("", "請選擇")] + list(Asset.Company.choices), required=False
    )
    category = forms.CharField(label="財產類別", max_length=100, required=False)
    brand = forms.CharField(label="廠牌", max_length=100, required=False)
    specification = forms.CharField(
        label="財產規格型號", max_length=255, required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    accessories = forms.CharField(
        label="配件", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )
    quantity = forms.IntegerField(label="數量", min_value=1, required=False)
    unit_price = forms.DecimalField(
        label="單價", min_value=0, max_digits=12, decimal_places=2, required=False
    )
    business_tax = forms.DecimalField(
        label="營業稅", min_value=0, max_digits=12, decimal_places=2, required=False
    )
    department = forms.ModelChoiceField(
        label="所屬部門", queryset=Department.objects.none(), required=False
    )
    custodian = forms.ModelChoiceField(
        label="保管人員", queryset=get_user_model().objects.none(), required=False,
        empty_label="部門資產（共用資源）",
    )
    purchase_date = forms.DateField(
        label="採購日期", required=False,
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    notes = forms.CharField(label="備註", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.order_by("name")
        self.fields["custodian"].queryset = (
            get_user_model().objects.filter(profile__isnull=False).order_by("username")
        )

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("include"):
            return cleaned
        for field in (
            "name", "company", "category", "quantity", "department",
            "purchase_date",
        ):
            if cleaned.get(field) in (None, ""):
                self.add_error(field, "此欄位為必要欄位。")
        custodian = cleaned.get("custodian")
        department = cleaned.get("department")
        if custodian and department and user_department(custodian) != department:
            self.add_error("custodian", "保管人員必須屬於所選部門。")
        return cleaned


class BaseRegistrationImportPreviewFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        selected = [
            form for form in self.forms
            if getattr(form, "cleaned_data", {}).get("include")
        ]
        if not selected:
            raise forms.ValidationError("請至少選擇一筆資料送出申請。")


RegistrationImportPreviewFormSet = formset_factory(
    RegistrationImportPreviewRowForm,
    formset=BaseRegistrationImportPreviewFormSet,
    extra=0,
    max_num=500,
    validate_max=True,
)
