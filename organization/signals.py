from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Department, PermissionRule
from .permission_catalog import MANAGEMENT_DEPARTMENT_NAME, MANAGEMENT_GRANTS


@receiver(post_save, sender=Department)
def initial_management_permissions(sender, instance, created, **kwargs):
    # Seed once, never re-grant a rule an administrator subsequently removes.
    if created and instance.name == MANAGEMENT_DEPARTMENT_NAME:
        PermissionRule.objects.bulk_create([
            PermissionRule(department=instance, permission=code, effect="allow")
            for code in MANAGEMENT_GRANTS
        ])
