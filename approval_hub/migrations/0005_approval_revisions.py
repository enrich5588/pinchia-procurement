from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("approval_hub", "0004_delivered_at")]

    operations = [
        migrations.AddField(
            model_name="approvalrequest",
            name="revision",
            field=models.PositiveSmallIntegerField(default=1, verbose_name="送簽版本"),
        ),
        migrations.AddField(
            model_name="approvalstep",
            name="round_number",
            field=models.PositiveSmallIntegerField(default=1, verbose_name="送簽版本"),
        ),
        migrations.RemoveConstraint(
            model_name="approvalstep",
            name="unique_approval_request_sequence",
        ),
        migrations.AlterModelOptions(
            name="approvalstep",
            options={
                "ordering": ["round_number", "sequence"],
                "verbose_name": "簽核關卡",
                "verbose_name_plural": "簽核關卡",
            },
        ),
        migrations.AddConstraint(
            model_name="approvalstep",
            constraint=models.UniqueConstraint(
                fields=("request", "round_number", "sequence"),
                name="unique_approval_request_round_sequence",
            ),
        ),
    ]
