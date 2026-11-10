from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from organization.models import Department, UserProfile
from procurement.models import DepartmentManager


MANAGER_ACCOUNTS = (
    ("management_manager", "管理部"),
    ("it_manager", "資訊部"),
    ("renewal_manager", "都更事業部"),
)


class Command(BaseCommand):
    help = "建立三個部門主管測試帳號（密碼皆為 demo）"

    def handle(self, *args, **options):
        User = get_user_model()
        for username, department_name in MANAGER_ACCOUNTS:
            department, _ = Department.objects.get_or_create(name=department_name)
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={"email": f"{username}@example.com"},
            )
            user.set_password("demo")
            user.is_active = True
            user.is_staff = False
            user.is_superuser = False
            user.save()
            UserProfile.objects.update_or_create(
                user=user, defaults={"department": department}
            )
            DepartmentManager.objects.update_or_create(
                department=department, defaults={"user": user}
            )

        self.stdout.write(self.style.SUCCESS(
            "部門主管帳號就緒：management_manager / it_manager / renewal_manager（密碼 demo）"
        ))
