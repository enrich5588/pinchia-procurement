from django.db import migrations
from django.utils import timezone


PANEL_CODES = ("supplies", "equipment", "assets", "registrations", "collaboration", "approvals")


def default_panels_to_developing(apps, schema_editor):
    Panel = apps.get_model("platform_stub", "FeaturePanel")
    Audit = apps.get_model("platform_stub", "PermissionAudit")
    alias = schema_editor.connection.alias
    edited_ids = Audit.objects.using(alias).filter(target_type="panel").values_list("target_id", flat=True)
    Panel.objects.using(alias).filter(
        code__in=PANEL_CODES, status="open", updated_by__isnull=True,
    ).exclude(pk__in=edited_ids).update(status="developing", updated_at=timezone.now())
    for code in PANEL_CODES:
        Panel.objects.using(alias).get_or_create(code=code, defaults={"status": "developing"})


class Migration(migrations.Migration):
    dependencies = [("platform_stub", "0007_featurepanel")]
    operations = [migrations.RunPython(default_panels_to_developing, migrations.RunPython.noop)]
