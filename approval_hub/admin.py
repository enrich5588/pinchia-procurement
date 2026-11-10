from django.contrib import admin

from .models import ApprovalRequest, ApprovalRequestDailySequence, ApprovalStep


class ApprovalStepInline(admin.TabularInline):
    model = ApprovalStep
    extra = 0
    readonly_fields = ("sequence", "approver", "status", "comment", "acted_at")


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = ("case_no", "subject", "amount_range", "document_type", "department", "applicant", "status", "created_at")
    list_filter = ("status", "department")
    search_fields = ("case_no", "subject", "applicant__username")
    readonly_fields = ("case_no", "created_at", "updated_at", "closed_at")
    inlines = (ApprovalStepInline,)


admin.site.register(ApprovalRequestDailySequence)
