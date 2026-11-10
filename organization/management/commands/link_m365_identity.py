from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from organization.models import MicrosoftIdentity


class Command(BaseCommand):
    help = "將經資訊部確認的 Entra Object ID 綁定到既有本機帳號，保留案件與角色。"

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--object-id", required=True)
        parser.add_argument("--tenant-id", default=settings.M365_TENANT_ID)

    def handle(self, *args, **options):
        try:
            tenant_id = UUID(options["tenant_id"])
            object_id = UUID(options["object_id"])
        except (ValueError, TypeError, AttributeError) as error:
            raise CommandError("請提供有效的 Tenant ID 與 Object ID。") from error
        if settings.M365_TENANT_ID and tenant_id != UUID(settings.M365_TENANT_ID):
            raise CommandError("Tenant ID 與本系統設定不符。")
        try:
            with transaction.atomic():
                user = get_user_model().objects.get(username=options["username"])
                identity, created = MicrosoftIdentity.objects.get_or_create(
                    user=user, defaults={"tenant_id": tenant_id, "object_id": object_id},
                )
                if identity.tenant_id != tenant_id or identity.object_id != object_id:
                    raise CommandError("此帳號已綁定其他 M365 身分，不會自動覆寫。")
        except get_user_model().DoesNotExist as error:
            raise CommandError("找不到指定的本機帳號。") from error
        except IntegrityError as error:
            raise CommandError("此 M365 身分已綁定其他帳號，不會轉移綁定。") from error
        self.stdout.write(self.style.SUCCESS(
            f"{'已建立' if created else '已確認'} M365 綁定：{user.username}。"
        ))
