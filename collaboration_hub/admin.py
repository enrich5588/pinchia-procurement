from django.contrib import admin

from .models import CollaborationTask


@admin.register(CollaborationTask)
class CollaborationTaskAdmin(admin.ModelAdmin):
    list_display = (
        "case_no", "assigned_department", "status", "source_form",
        "source_case_no", "created_by", "created_at",
    )
    list_filter = ("status", "assigned_department", "source_form")
    search_fields = ("case_no", "source_case_no", "created_by__username")
    readonly_fields = (
        "case_no", "source_form", "source_case_no", "source_content_type",
        "source_object_id", "created_by", "created_at", "updated_by", "updated_at",
        "returned_by", "returned_at", "closed_at",
    )
