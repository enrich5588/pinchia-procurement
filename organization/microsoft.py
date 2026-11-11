"""Entra authorization-code flow and Graph /me synchronization."""
from pathlib import Path
from functools import lru_cache
import secrets
from urllib.parse import urlsplit
from uuid import UUID

import msal
import jwt
import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import Department, MicrosoftIdentity, UserProfile


class MicrosoftLoginError(ValueError):
    """A safe, user-facing login failure; never include tokens or provider payloads."""


@lru_cache(maxsize=8)
def signing_keys(tenant_id):
    # The URL is derived only from validated server configuration, not JWT headers.
    return jwt.PyJWKClient(
        f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys",
        timeout=10,
    )


def validate_id_token(id_token, expected_nonce):
    """MSAL 1.38+ decodes claims but delegates JWT validation to the application."""
    if not isinstance(id_token, str) or not id_token or not expected_nonce:
        raise MicrosoftLoginError("Microsoft 未提供完整的登入驗證資料，請重新登入。")
    try:
        tenant_id = str(UUID(settings.M365_TENANT_ID))
        key = signing_keys(tenant_id).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token, key.key, algorithms=["RS256"],
            audience=settings.M365_CLIENT_ID,
            issuer=f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            leeway=60,
            options={"require": ["iss", "sub", "aud", "exp", "iat", "nonce", "tid", "oid"],
                     "strict_aud": True},
        )
    except (jwt.PyJWTError, ValueError, TypeError) as error:
        raise MicrosoftLoginError("Microsoft 登入憑證驗證失敗，請重新登入。") from error
    nonce = claims.get("nonce")
    if not isinstance(nonce, str) or not secrets.compare_digest(nonce, expected_nonce):
        raise MicrosoftLoginError("登入驗證碼不符，請重新開始 M365 登入。")
    return claims


def configuration_problem():
    if not all([settings.M365_TENANT_ID, settings.M365_CLIENT_ID, settings.M365_REDIRECT_URI]):
        return "公司 M365 登入尚未完成設定，請聯絡系統管理員。"
    try:
        UUID(settings.M365_TENANT_ID)
        UUID(settings.M365_CLIENT_ID)
    except (ValueError, TypeError, AttributeError):
        return "M365 Tenant ID 或 Client ID 設定格式不正確。"
    try:
        uri = urlsplit(settings.M365_REDIRECT_URI)
    except ValueError:
        return "M365 回呼網址格式不正確。"
    local_http = settings.DEBUG and uri.scheme == "http" and uri.hostname == "localhost"
    if (not (uri.scheme == "https" or local_http) or not uri.hostname
            or uri.username or uri.password or uri.query or uri.fragment
            or uri.path != "/accounts/microsoft/callback/"):
        return "M365 回呼網址設定不正確，請由管理員確認 HTTPS 網址與回呼路徑。"
    certificate = settings.M365_CERT_PRIVATE_KEY_PATH and settings.M365_CERT_THUMBPRINT
    if bool(settings.M365_CERT_PRIVATE_KEY_PATH) != bool(settings.M365_CERT_THUMBPRINT):
        return "M365 憑證設定不完整。"
    if bool(settings.M365_CLIENT_SECRET) == bool(certificate):
        return "請設定一種 M365 應用程式認證方式：憑證或 Client secret。"
    if settings.SESSION_ENGINE == "django.contrib.sessions.backends.signed_cookies":
        return "M365 登入需要伺服器端 Session 儲存。"
    return ""


def build_client():
    problem = configuration_problem()
    if problem:
        raise MicrosoftLoginError(problem)
    credential = settings.M365_CLIENT_SECRET
    if settings.M365_CERT_PRIVATE_KEY_PATH:
        try:
            key = Path(settings.M365_CERT_PRIVATE_KEY_PATH).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise MicrosoftLoginError("M365 憑證無法讀取，請聯絡系統管理員。") from error
        credential = {"private_key": key, "thumbprint": settings.M365_CERT_THUMBPRINT}
    return msal.ConfidentialClientApplication(
        settings.M365_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{settings.M365_TENANT_ID}",
        client_credential=credential,
        timeout=(5, 15), exclude_scopes=["offline_access"],
        enable_pii_log=False,
    )


def read_graph_profile(access_token):
    try:
        response = requests.get(
            "https://graph.microsoft.com/v1.0/me",
            params={"$select": "id,displayName,userPrincipalName,mail,department,userType"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=(5, 15), allow_redirects=False,
        )
        if response.status_code != 200:
            raise MicrosoftLoginError("無法讀取公司帳號資料，請稍後重試或聯絡資訊部確認 Graph 權限。")
        profile = response.json()
    except (requests.RequestException, ValueError) as error:
        if isinstance(error, MicrosoftLoginError):
            raise
        raise MicrosoftLoginError("公司帳號資料服務暫時無法連線，請稍後再試。") from error
    if not isinstance(profile, dict):
        raise MicrosoftLoginError("公司帳號資料格式不正確，請聯絡資訊部。")
    return profile


@transaction.atomic
def synchronize_user(claims, profile):
    """Caller supplies claims returned by MSAL, never browser-supplied JWT data."""
    try:
        tenant_id = UUID(claims.get("tid", ""))
        object_id = UUID(claims.get("oid", ""))
        graph_id = UUID(profile.get("id", ""))
    except (ValueError, TypeError, AttributeError) as error:
        raise MicrosoftLoginError("Microsoft 帳號識別資料不完整，請重新登入。") from error
    if tenant_id != UUID(settings.M365_TENANT_ID) or object_id != graph_id:
        raise MicrosoftLoginError("此帳號不屬於允許的公司租用戶，或 Graph 身分不符。")
    if not settings.M365_ALLOW_GUESTS and profile.get("userType") != "Member":
        raise MicrosoftLoginError("此系統僅開放公司成員帳號登入。")
    department_name = profile.get("department")
    if not isinstance(department_name, str) or not department_name.strip():
        raise MicrosoftLoginError("您的 M365 帳號尚未設定部門，請聯絡資訊部補齊後再登入。")
    department_name = department_name.strip()
    if len(department_name) > 100:
        raise MicrosoftLoginError("M365 部門名稱格式不正確，請聯絡資訊部。")
    name = profile.get("displayName") or ""
    email = profile.get("mail") or ""
    principal = profile.get("userPrincipalName") or ""
    if not all(isinstance(value, str) for value in (name, email, principal)):
        raise MicrosoftLoginError("公司帳號資料格式不正確，請聯絡資訊部。")
    identity = MicrosoftIdentity.objects.select_for_update().select_related("user").filter(
        tenant_id=tenant_id, object_id=object_id,
    ).first()
    if identity:
        user = identity.user
        if not user.is_active:
            raise MicrosoftLoginError("此系統帳號已停用，請聯絡系統管理員。")
    else:
        # Deliberately do not match email, UPN or its local part to existing users.
        User = get_user_model()
        username = principal
        if not username or len(username) > 150 or User.objects.filter(username=username).exists():
            username = f"m365_{tenant_id.hex}_{object_id.hex}"
        user = User.objects.create_user(username=username, password=None)
        identity = MicrosoftIdentity(user=user, tenant_id=tenant_id, object_id=object_id)
    user.first_name = name[:150]
    user.email = email[:254]
    fields = ["first_name", "email"]
    if (settings.M365_DEFAULT_ADMIN_UPN
            and principal.strip().casefold() == settings.M365_DEFAULT_ADMIN_UPN
            and profile.get("userType") == "Member"):
        user.is_staff = True
        user.is_superuser = True
        fields.extend(["is_staff", "is_superuser"])
    user.save(update_fields=fields)
    department, _ = Department.objects.get_or_create(name=department_name)
    UserProfile.objects.update_or_create(user=user, defaults={"department": department})
    identity.principal_name = principal[:320]
    identity.department_name = department_name
    identity.last_synced_at = timezone.now()
    identity.save()
    return user
