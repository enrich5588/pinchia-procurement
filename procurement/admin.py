from django.contrib import admin

from .models import (
    DepartmentManager, EquipmentApplication, EquipmentApplicationItem,
    OfficeSupplyApplication, OfficeSupplyApplicationItem, SupplyRequest,
)


@admin.register(SupplyRequest)
class SupplyRequestAdmin(admin.ModelAdmin):
    list_display = ("record_no", "status", "filled_on", "department", "created_by")


class OfficeSupplyApplicationItemInline(admin.TabularInline):
    model = OfficeSupplyApplicationItem
    extra = 0


@admin.register(OfficeSupplyApplication)
class OfficeSupplyApplicationAdmin(admin.ModelAdmin):
    list_display = ("case_no", "department", "applicant", "need_date", "status")
    list_filter = ("status", "department")
    search_fields = ("case_no", "applicant__username", "notes")
    readonly_fields = ("case_no", "status", "created_by", "created_at", "updated_by", "updated_at", "closed_at", "approved_by")
    inlines = (OfficeSupplyApplicationItemInline,)


class EquipmentApplicationItemInline(admin.TabularInline):
    model = EquipmentApplicationItem
    extra = 0


@admin.register(EquipmentApplication)
class EquipmentApplicationAdmin(admin.ModelAdmin):
    list_display = ("case_no", "department", "applicant", "need_date", "status")
    list_filter = ("status", "department")
    search_fields = ("case_no", "applicant__username", "notes", "items__equipment_name")
    readonly_fields = ("case_no", "status", "created_by", "created_at", "updated_by", "updated_at", "closed_at", "approved_by")
    inlines = (EquipmentApplicationItemInline,)


@admin.register(DepartmentManager)
class DepartmentManagerAdmin(admin.ModelAdmin):
    list_display = ("department", "user", "assigned_at")
    list_select_related = ("department", "user")
