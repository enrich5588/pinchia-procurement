from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("approval_hub", "0002_amount_range_and_document_type")]

    operations = [
        migrations.AlterField(
            model_name="approvalrequest",
            name="amount_range",
            field=models.CharField(
                choices=[
                    ("up_to_10000", "10,000 元以下"),
                    ("10001_to_20000", "10,001～20,000 元"),
                    ("20001_to_40000", "20,001～40,000 元"),
                    ("from_40001", "40,001 元以上"),
                ],
                default="up_to_10000", max_length=20, verbose_name="涉及金額",
            ),
        ),
    ]
