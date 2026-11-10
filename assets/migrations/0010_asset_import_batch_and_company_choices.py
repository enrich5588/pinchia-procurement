import assets.storage
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0009_add_asset_company_pricing_fields"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="asset",
            name="company",
            field=models.CharField(
                choices=[
                    ("品嘉建設", "品嘉建設"), ("品嘉營造", "品嘉營造"),
                    ("品佳資產", "品佳資產"), ("廠商設備", "廠商設備"),
                    ("其他", "其他"),
                ],
                default="品嘉建設", max_length=20, verbose_name="公司",
            ),
        ),
        migrations.AlterField(
            model_name="assetregistration",
            name="company",
            field=models.CharField(
                choices=[
                    ("品嘉建設", "品嘉建設"), ("品嘉營造", "品嘉營造"),
                    ("品佳資產", "品佳資產"), ("廠商設備", "廠商設備"),
                    ("其他", "其他"),
                ],
                default="品嘉建設", max_length=20, verbose_name="公司",
            ),
        ),
        migrations.CreateModel(
            name="AssetImportBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_file", models.FileField(storage=assets.storage.asset_image_storage, upload_to=assets.storage.asset_import_path, verbose_name="Excel 暫存檔")),
                ("source_filename", models.CharField(max_length=255, verbose_name="原始檔名")),
                ("rows", models.JSONField(default=list, verbose_name="預覽資料")),
                ("skipped", models.JSONField(default=list, verbose_name="跳過資料")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="建立時間")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="asset_import_batches", to=settings.AUTH_USER_MODEL, verbose_name="建立者")),
            ],
            options={
                "verbose_name": "財產批量匯入暫存",
                "verbose_name_plural": "財產批量匯入暫存",
                "ordering": ["-created_at"],
            },
        ),
    ]
