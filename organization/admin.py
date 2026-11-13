from django.contrib import admin
from django.conf import settings

from .models import Department, DepartmentSyncState, MicrosoftIdentity, PermissionAudit, UserProfile

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not settings.M365_DEPARTMENT_SYNC_ENABLED and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return not settings.M365_DEPARTMENT_SYNC_ENABLED and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not settings.M365_DEPARTMENT_SYNC_ENABLED and super().has_delete_permission(request, obj)


@admin.register(DepartmentSyncState)
class DepartmentSyncStateAdmin(admin.ModelAdmin):
    list_display = ["last_success", "next_attempt", "department_count", "employee_count", "last_error"]
    readonly_fields = ["last_success", "next_attempt", "department_count", "employee_count", "last_error", "lease_until"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

admin.site.register(UserProfile)


@admin.register(MicrosoftIdentity)
class MicrosoftIdentityAdmin(admin.ModelAdmin):
    list_display = ["user", "tenant_id", "object_id", "department_name", "last_synced_at"]
    search_fields = ["user__username", "principal_name"]
    autocomplete_fields = ["user"]
    readonly_fields = ["principal_name", "department_name", "last_synced_at"]


@admin.register(PermissionAudit)
class PermissionAuditAdmin(admin.ModelAdmin):
    list_display = ["created_at", "actor_label", "target_type", "target_label"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser


from .models import OperationLog

@admin.register(OperationLog)
class OperationLogAdmin(admin.ModelAdmin):
    list_display = ['created_at','actor_label','action','model_label','object_id','outcome']
    list_filter = ['action','source']
    search_fields = ['actor_label','object_label','object_id','path']
    readonly_fields = [field.name for field in OperationLog._meta.fields]
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False
    def has_view_permission(self, request, obj=None): return request.user.is_superuser
    def get_queryset(self, request):
        from .audit import retention_cutoff
        return super().get_queryset(request).filter(created_at__gte=retention_cutoff())
