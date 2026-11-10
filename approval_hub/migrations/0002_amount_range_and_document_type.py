from django.db import migrations, models


def convert_amounts_to_ranges(apps, schema_editor):
    ApprovalRequest = apps.get_model("approval_hub", "ApprovalRequest")
    for approval in ApprovalRequest.objects.all().only("pk", "amount"):
        if approval.amount <= 10000:
            amount_range = "up_to_10000"
        elif approval.amount <= 20000:
            amount_range = "10001_to_20000"
        elif approval.amount <= 40000:
            amount_range = "20001_to_40000"
        else:
            amount_range = "from_40001"
        ApprovalRequest.objects.filter(pk=approval.pk).update(amount_range=amount_range)


class Migration(migrations.Migration):
    dependencies = [("approval_hub", "0001_initial")]

    operations = [
        migrations.AddField(
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
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="approvalrequest",
            name="document_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("ordinary", "普通件公文（8 小時內完成）"),
                    ("confidential", "密件公文（4 小時內完成）"),
                    ("urgent", "急件公文（2 小時內完成）"),
                ],
                default="", max_length=20, verbose_name="公文種類",
            ),
        ),
        migrations.RunPython(convert_amounts_to_ranges, migrations.RunPython.noop),
        migrations.RemoveField(model_name="approvalrequest", name="amount"),
    ]
