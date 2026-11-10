from django.db import transaction
from django.utils import timezone

from .models import CollaborationTaskDailySequence


def next_collaboration_case_no():
    sequence_date = timezone.localdate()
    with transaction.atomic():
        sequence, _ = CollaborationTaskDailySequence.objects.select_for_update().get_or_create(
            sequence_date=sequence_date,
            defaults={"last_sequence": 0},
        )
        if sequence.last_sequence >= 999:
            raise ValueError("今日協作案件已達 999 件上限。")
        sequence.last_sequence += 1
        sequence.save(update_fields=["last_sequence"])
    return f"{sequence_date:%y%m%d}{sequence.last_sequence:03d}"
