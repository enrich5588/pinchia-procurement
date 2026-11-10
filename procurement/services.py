from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import EquipmentApplicationDailySequence, OfficeSupplyApplicationDailySequence


def next_office_supply_case_no():
    today = timezone.localdate()
    with transaction.atomic():
        sequence, _ = OfficeSupplyApplicationDailySequence.objects.select_for_update().get_or_create(
            sequence_date=today
        )
        if sequence.last_sequence >= 999:
            raise ValidationError("當日用品申請案件已達 999 件上限。")
        sequence.last_sequence += 1
        sequence.save(update_fields=["last_sequence"])
    return f"{today:%y%m%d}{sequence.last_sequence:03d}"


def next_equipment_case_no():
    today = timezone.localdate()
    with transaction.atomic():
        sequence, _ = EquipmentApplicationDailySequence.objects.select_for_update().get_or_create(
            sequence_date=today
        )
        if sequence.last_sequence >= 999:
            raise ValidationError("當日設備申請案件已達 999 件上限。")
        sequence.last_sequence += 1
        sequence.save(update_fields=["last_sequence"])
    return f"{today:%y%m%d}{sequence.last_sequence:03d}"
