from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import AssetImage, AssetRegistrationDailySequence


def save_asset_form(form, user):
    stored_files = []
    try:
        with transaction.atomic():
            asset = form.save(commit=False)
            if not asset.pk:
                asset.created_by = user
            asset.updated_by = user
            asset.save()
            for upload in form.cleaned_data.get("images", []):
                image = AssetImage(asset=asset)
                image.image.save(upload.name, upload, save=False)
                stored_files.append((image.image.storage, image.image.name))
                image.save()
            for image in form.cleaned_data.get("remove_images", []):
                if image.registration_id:
                    image.asset = None
                    image.save(update_fields=["asset"])
                    continue
                storage, name = image.image.storage, image.image.name
                image.delete()
                transaction.on_commit(lambda s=storage, n=name: s.delete(n))
        return asset
    except Exception:
        for storage, name in stored_files:
            storage.delete(name)
        raise


def save_registration_images(form, registration):
    stored_files = []
    try:
        for upload in form.cleaned_data.get("images", []):
            image = AssetImage(registration=registration)
            image.image.save(upload.name, upload, save=False)
            stored_files.append((image.image.storage, image.image.name))
            image.save()
        for image in form.cleaned_data.get("remove_images", []):
            storage, name = image.image.storage, image.image.name
            image.delete()
            transaction.on_commit(lambda s=storage, n=name: s.delete(n))
        if "asset_images_to_remove" in form.cleaned_data:
            registration.asset_images_to_remove.set(
                form.cleaned_data.get("asset_images_to_remove", [])
            )
    except Exception:
        for storage, name in stored_files:
            storage.delete(name)
        raise


def apply_registration_image_changes(registration, asset):
    for image in registration.asset_images_to_remove.select_for_update():
        if image.asset_id != asset.pk:
            continue
        if image.registration_id:
            image.asset = None
            image.save(update_fields=["asset"])
        else:
            storage, name = image.image.storage, image.image.name
            image.delete()
            transaction.on_commit(lambda s=storage, n=name: s.delete(n))
    registration.images.update(asset=asset)


def next_registration_case_no():
    """在交易鎖內取得 YYMMDDNNN 格式的每日案件編號。"""
    today = timezone.localdate()
    with transaction.atomic():
        sequence, _ = AssetRegistrationDailySequence.objects.select_for_update().get_or_create(
            sequence_date=today
        )
        if sequence.last_sequence >= 999:
            raise ValidationError("當日資產登記案件已達 999 件上限。")
        sequence.last_sequence += 1
        sequence.save(update_fields=["last_sequence"])
    return f"{today:%y%m%d}{sequence.last_sequence:03d}"
