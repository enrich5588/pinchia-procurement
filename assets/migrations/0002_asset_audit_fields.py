import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models
from django.db.models import F


def copy_creator_to_last_modifier(apps, schema_editor):
    Asset = apps.get_model("assets", "Asset")
    Asset.objects.filter(updated_by__isnull=True).update(updated_by=F("created_by"))


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="asset",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, verbose_name="建立日期"),
        ),
        migrations.AlterField(
            model_name="asset",
            name="created_by",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="created_assets",
                to=settings.AUTH_USER_MODEL,
                verbose_name="建立者",
            ),
        ),
        migrations.AddField(
            model_name="asset",
            name="updated_at",
            field=models.DateTimeField(
                auto_now=True, default=django.utils.timezone.now, verbose_name="修改日期"
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="asset",
            name="updated_by",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="updated_assets",
                to=settings.AUTH_USER_MODEL,
                verbose_name="最後修改者",
            ),
        ),
        migrations.RunPython(copy_creator_to_last_modifier, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="asset",
            name="updated_by",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="updated_assets",
                to=settings.AUTH_USER_MODEL,
                verbose_name="最後修改者",
            ),
        ),
    ]
