from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.files.storage import FileSystemStorage


def asset_image_storage():
    # Images are served through a permission-checked view, never a public media URL.
    return FileSystemStorage(location=getattr(
        settings, "ASSET_IMAGE_ROOT", Path(settings.BASE_DIR) / "private-media" / "assets"
    ))


def asset_image_path(instance, filename):
    if instance.registration_id:
        return f"registrations/{instance.registration_id}/{uuid4().hex}{Path(filename).suffix.lower()}"
    return f"{instance.asset_id}/{uuid4().hex}{Path(filename).suffix.lower()}"


def asset_import_path(instance, filename):
    return f"imports/{instance.created_by_id}/{uuid4().hex}.xlsx"
