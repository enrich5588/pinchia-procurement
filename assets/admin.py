from django.contrib import admin

from .models import Asset, AssetRegistration


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = (
        "asset_no",
        "name",
        "company",
        "category",
        "brand",
        "quantity",
        "total",
        "department",
        "custodian",
        "purchase_date",
    )
    list_filter = ("company", "department", "category")
    search_fields = ("asset_no", "name", "brand", "specification", "accessories")
    exclude = ("created_by", "created_at", "updated_by", "updated_at")

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(AssetRegistration)
class AssetRegistrationAdmin(admin.ModelAdmin):
    list_display = ("case_no", "name", "company", "quantity", "total", "department", "custodian", "status")
    list_filter = ("status", "company", "department", "category")
    search_fields = ("case_no", "name", "brand", "specification", "accessories")
    readonly_fields = (
        "case_no", "status", "applied_at", "applicant", "modified_at",
        "closed_at", "approved_by", "asset", "target_asset", "asset_images_to_remove",
    )
