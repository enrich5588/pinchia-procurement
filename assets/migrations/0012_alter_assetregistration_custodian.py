from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0011_assetimportbatch_import_type"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="assetregistration",
            name="custodian",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="asset_registration_custody",
                to=settings.AUTH_USER_MODEL,
                verbose_name="保管人員",
            ),
        ),
    ]
