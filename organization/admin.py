from django.contrib import admin

from .models import Department, MicrosoftIdentity, UserProfile

admin.site.register(Department)
admin.site.register(UserProfile)


@admin.register(MicrosoftIdentity)
class MicrosoftIdentityAdmin(admin.ModelAdmin):
    list_display = ["user", "tenant_id", "object_id", "department_name", "last_synced_at"]
    search_fields = ["user__username", "principal_name"]
    autocomplete_fields = ["user"]
    readonly_fields = ["principal_name", "department_name", "last_synced_at"]
