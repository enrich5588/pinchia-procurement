from django.db import migrations


def seed_management(apps, schema_editor):
    Department = apps.get_model("platform_stub", "Department")
    Rule = apps.get_model("platform_stub", "PermissionRule")
    alias = schema_editor.connection.alias
    departments = Department.objects.using(alias)
    official = departments.filter(name="管理與事業發展部").first()
    if official is None:
        official = departments.filter(name="管理部").first()
        if official:
            official.name = "管理與事業發展部"
            official.save(using=alias, update_fields=["name"])
    if official:
        for code in ["supplies.manage", "equipment.manage", "assets.manage",
                     "registrations.manage", "collaboration.manage", "database.monitor"]:
            Rule.objects.using(alias).get_or_create(
                department_id=official.pk, permission=code, defaults={"effect": "allow"},
            )


class Migration(migrations.Migration):
    dependencies = [("platform_stub", "0003_permission_rules_and_audit")]
    # Preserve names and administrator changes when rolling back only this seed.
    operations = [migrations.RunPython(seed_management, migrations.RunPython.noop)]
