from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0010_asset_import_batch_and_company_choices"),
    ]

    operations = [
        migrations.AddField(
            model_name="assetimportbatch",
            name="import_type",
            field=models.CharField(
                choices=[("asset", "財產清冊"), ("registration", "資產登記")],
                default="asset",
                max_length=20,
                verbose_name="匯入類型",
            ),
        ),
    ]
