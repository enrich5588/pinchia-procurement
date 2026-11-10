from django.db import migrations, models


def populate_delivered_at(apps, schema_editor):
    ApprovalRequest = apps.get_model("approval_hub", "ApprovalRequest")
    for approval in ApprovalRequest.objects.filter(delivered_at__isnull=True).only(
        "pk", "created_at"
    ):
        ApprovalRequest.objects.filter(pk=approval.pk).update(
            delivered_at=approval.created_at
        )


class Migration(migrations.Migration):
    dependencies = [("approval_hub", "0003_default_amount_range")]

    operations = [
        migrations.AddField(
            model_name="approvalrequest",
            name="delivered_at",
            field=models.DateTimeField(
                null=True, verbose_name="目前關卡送達時間"
            ),
        ),
        migrations.RunPython(populate_delivered_at, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="approvalrequest",
            name="delivered_at",
            field=models.DateTimeField(verbose_name="目前關卡送達時間"),
        ),
    ]
