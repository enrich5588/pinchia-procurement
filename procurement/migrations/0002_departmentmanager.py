import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("platform_stub", "0001_initial"),
        ("procurement", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DepartmentManager",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("assigned_at", models.DateTimeField(auto_now_add=True, verbose_name="指派時間")),
                (
                    "department",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="procurement_manager_assignment",
                        to="platform_stub.department",
                        verbose_name="部門",
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="procurement_manager_assignment",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="主管",
                    ),
                ),
            ],
            options={
                "verbose_name": "部門主管",
                "verbose_name_plural": "部門主管",
            },
        ),
    ]
