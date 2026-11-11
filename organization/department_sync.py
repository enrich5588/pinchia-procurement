"""App-only Graph department discovery. Never delete or reassign business data."""
from datetime import timedelta
from time import monotonic
from urllib.parse import urlsplit
from uuid import UUID

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.contrib.auth import get_user_model
from django.utils import timezone

from .microsoft import MicrosoftLoginError, build_client
from .models import Department, DepartmentSyncState, MicrosoftIdentity, UserProfile


class DepartmentSyncError(ValueError):
    pass


def fetch_directory():
    try:
        token = build_client().acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        if not isinstance(token, dict) or not token.get("access_token"):
            raise DepartmentSyncError("無法取得 M365 應用程式授權，請確認憑證與管理員同意。")
        url = "https://graph.microsoft.com/v1.0/users?$select=id,displayName,userPrincipalName,mail,department,userType,accountEnabled&$top=999"
        names, visited, employees = set(), set(), {}
        started = monotonic()
        while url:
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or parsed.netloc != "graph.microsoft.com"
                    or parsed.path != "/v1.0/users" or parsed.fragment
                    or url in visited or len(visited) >= 10000 or monotonic() - started > 240):
                raise DepartmentSyncError("M365 分頁資料不完整或同步逾時，保留原有部門。")
            visited.add(url)
            response = requests.get(url, headers={"Authorization": f"Bearer {token['access_token']}"},
                                    timeout=(5, 15), allow_redirects=False)
            if response.status_code in (401, 403):
                raise DepartmentSyncError("讀取全公司部門需要 Graph Application User.Read.All，並完成管理員同意。")
            if response.status_code == 429:
                raise DepartmentSyncError("M365 暫時限制請求，系統稍後自動重試。")
            if response.status_code != 200:
                raise DepartmentSyncError("M365 部門服務暫時無法讀取，保留原有部門並稍後重試。")
            page = response.json()
            if not isinstance(page, dict) or not isinstance(page.get("value"), list):
                raise DepartmentSyncError("M365 部門資料格式不正確，保留原有部門。")
            for user in page["value"]:
                if not isinstance(user, dict):
                    raise DepartmentSyncError("M365 使用者資料格式不正確。")
                if user.get("userType") != "Member":
                    continue
                try:
                    object_id = UUID(user.get("id", ""))
                except (ValueError, TypeError, AttributeError) as error:
                    raise DepartmentSyncError("M365 員工識別資料不正確，保留原有資料。") from error
                if not all(user.get(key) is None or isinstance(user.get(key), str)
                           for key in ("displayName", "userPrincipalName", "mail")):
                    raise DepartmentSyncError("M365 員工資料格式不正確，保留原有資料。")
                if type(user.get("accountEnabled")) is not bool:
                    raise DepartmentSyncError("無法確認 M365 員工帳號狀態，保留原有資料。")
                employees[object_id] = user
                name = user.get("department")
                if name is None:
                    continue
                if not isinstance(name, str) or len(name.strip()) > 100:
                    raise DepartmentSyncError("M365 部門名稱格式不正確，保留原有部門。")
                if name.strip():
                    names.add(name.strip())
            url = page.get("@odata.nextLink")
            if url is not None and (not isinstance(url, str) or not url):
                raise DepartmentSyncError("M365 分頁資料格式不正確。")
        return names, employees
    except (MicrosoftLoginError, requests.RequestException, ValueError, RuntimeError) as error:
        if isinstance(error, DepartmentSyncError):
            raise
        raise DepartmentSyncError("M365 部門同步無法連線或設定不完整，請檢查憑證與網路。") from error


def sync_departments(*, force=False):
    if not settings.M365_DEPARTMENT_SYNC_ENABLED:
        return None
    now = timezone.now()
    DepartmentSyncState.objects.get_or_create(pk=1)
    eligible = DepartmentSyncState.objects.filter(pk=1).filter(
        Q(lease_until__isnull=True) | Q(lease_until__lte=now))
    if not force:
        eligible = eligible.filter(Q(next_attempt__isnull=True) | Q(next_attempt__lte=now))
    lease = now + timedelta(minutes=10)
    if not eligible.update(lease_until=lease):
        return None
    try:
        names, employees = fetch_directory()
        with transaction.atomic():
            state = DepartmentSyncState.objects.select_for_update().get(pk=1)
            if state.lease_until != lease:
                raise DepartmentSyncError("同步工作已由其他程序接手，保留原有部門。")
            created = sum(Department.objects.get_or_create(name=name)[1] for name in sorted(names))
            for object_id, profile in employees.items():
                sync_employee(object_id, profile)
            state.last_success = timezone.now()
            state.next_attempt = state.last_success + timedelta(seconds=settings.M365_DEPARTMENT_SYNC_SECONDS)
            state.lease_until = None
            state.last_error = ""
            state.department_count = len(names)
            state.employee_count = len(employees)
            state.save()
        return {"departments": len(names), "created": created, "employees": len(employees)}
    except DepartmentSyncError as error:
        DepartmentSyncState.objects.filter(pk=1, lease_until=lease).update(
            last_error=str(error), lease_until=None, next_attempt=timezone.now() + timedelta(minutes=15))
        raise


def sync_employee(object_id, profile):
    """Called inside the complete-directory transaction. Never link by email."""
    tenant_id = UUID(settings.M365_TENANT_ID)
    identity = MicrosoftIdentity.objects.select_for_update().select_related("user").filter(
        tenant_id=tenant_id, object_id=object_id).first()
    principal = (profile.get("userPrincipalName") or "").strip()
    if identity:
        user = identity.user
    else:
        User = get_user_model()
        username = principal
        if not username or len(username) > 150 or User.objects.filter(username__iexact=username).exists():
            username = f"m365_{tenant_id.hex}_{object_id.hex}"
        user = User.objects.create_user(username=username, password=None, is_active=profile["accountEnabled"])
        identity = MicrosoftIdentity(user=user, tenant_id=tenant_id, object_id=object_id)
    user.first_name = (profile.get("displayName") or "")[:150]
    user.email = (profile.get("mail") or "")[:254]
    # M365 can disable accounts; do not undo a local administrator's suspension.
    if not profile["accountEnabled"]:
        user.is_active = False
    user.save(update_fields=["first_name", "email", "is_active"])
    department_name = (profile.get("department") or "").strip()
    if department_name:
        department = Department.objects.get(name=department_name)
        UserProfile.objects.update_or_create(user=user, defaults={"department": department})
    else:
        # A cleared directory department must not retain the former department's permissions.
        UserProfile.objects.filter(user=user).delete()
    identity.principal_name = principal[:320]
    identity.department_name = department_name
    identity.last_synced_at = timezone.now()
    identity.save()
