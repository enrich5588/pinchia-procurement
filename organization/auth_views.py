import logging
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import requests
import jwt
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.db import IntegrityError, OperationalError
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_GET, require_POST

from .audit import record
from .microsoft import (
    MicrosoftLoginError, build_client, configuration_problem,
    read_graph_profile, synchronize_user, validate_id_token,
)

logger = logging.getLogger(__name__)
FLOW_KEY = "m365_auth_flow"
FLOW_TTL = 600


def safe_next(request, value):
    if value and url_has_allowed_host_and_scheme(
        value, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return value
    return reverse("home")


@method_decorator(never_cache, name="dispatch")
class CompanyLoginView(LoginView):
    template_name = "login.html"

    def dispatch(self, request, *args, **kwargs):
        if request.method == "POST" and not settings.ALLOW_LOCAL_LOGIN:
            return HttpResponseNotAllowed(["GET"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        problem = configuration_problem()
        context.update(
            m365_ready=not problem, m365_problem=problem,
            allow_local_login=settings.ALLOW_LOCAL_LOGIN,
            next=safe_next(self.request, self.request.GET.get("next", "")),
        )
        return context


@require_POST
@never_cache
def microsoft_login(request):
    request.session.pop(FLOW_KEY, None)
    try:
        problem = configuration_problem()
        if problem:
            raise MicrosoftLoginError(problem)
        target = urlsplit(settings.M365_REDIRECT_URI)
        # A flow started on 127.0.0.1 cannot use a localhost session cookie.
        # Likewise, production login must start on the configured HTTPS host.
        if request.scheme != target.scheme or request.get_host().lower() != target.netloc.lower():
            return redirect(f"{target.scheme}://{target.netloc}{reverse('login')}?" + urlencode({
                "next": safe_next(request, request.POST.get("next", "")),
            }))
        flow = build_client().initiate_auth_code_flow(
            scopes=["User.Read"], redirect_uri=settings.M365_REDIRECT_URI,
            response_mode="query", prompt="select_account",
        )
        if "auth_uri" not in flow or "state" not in flow:
            raise MicrosoftLoginError("無法開始公司登入，請稍後再試。")
        nonces = parse_qs(urlsplit(flow["auth_uri"]).query).get("nonce", [])
        if len(nonces) != 1 or not nonces[0]:
            raise MicrosoftLoginError("無法建立登入驗證碼，請重新開始公司登入。")
    except (MicrosoftLoginError, ValueError, RuntimeError, jwt.PyJWTError, requests.RequestException) as error:
        record("login_failed", outcome="M365 登入啟動失敗")
        logger.warning("Microsoft login initiation failed: %s", type(error).__name__)
        messages.error(request, str(error) if isinstance(error, MicrosoftLoginError)
                       else "Microsoft 登入服務暫時無法連線，請稍後再試。")
        return redirect("login")
    request.session.cycle_key()
    request.session[FLOW_KEY] = {
        "flow": flow, "created_at": time.time(),
        "nonce": nonces[0],
        "next": safe_next(request, request.POST.get("next", "")),
    }
    return redirect(flow["auth_uri"])


@require_GET
@never_cache
@sensitive_variables("result", "claims", "profile")
def microsoft_callback(request):
    # Consume even failed flows so a callback cannot be replayed.
    saved = request.session.pop(FLOW_KEY, None)
    try:
        if not saved or not 0 <= time.time() - saved.get("created_at", 0) <= FLOW_TTL:
            raise MicrosoftLoginError("登入要求已逾時或不存在，請重新開始 M365 登入。")
        flow = saved["flow"]
        state = request.GET.get("state", "")
        if not state or not secrets.compare_digest(flow.get("state", ""), state):
            raise MicrosoftLoginError("登入驗證狀態不符，請重新開始 M365 登入。")
        result = build_client().acquire_token_by_auth_code_flow(flow, request.GET.dict())
        if "error" in result or not result.get("access_token"):
            raise MicrosoftLoginError("Microsoft 登入未完成或授權遭拒，請重試或聯絡資訊部。")
        claims = validate_id_token(result.get("id_token"), saved.get("nonce"))
        # Reject the wrong tenant before sending its token to Graph.
        if str(claims.get("tid", "")).lower() != settings.M365_TENANT_ID.lower():
            raise MicrosoftLoginError("請使用公司租用戶的 M365 帳號登入。")
        profile = read_graph_profile(result["access_token"])
        user = synchronize_user(claims, profile)
    except (MicrosoftLoginError, ValueError, RuntimeError, jwt.PyJWTError, requests.RequestException,
            IntegrityError, OperationalError) as error:
        record("login_failed", outcome="M365 登入驗證失敗")
        logger.warning("Microsoft callback failed: %s", type(error).__name__)
        messages.error(request, str(error) if isinstance(error, MicrosoftLoginError)
                       else "登入驗證或帳號同步失敗，請重新登入；若持續發生請聯絡資訊部。")
        return redirect("login")
    destination = safe_next(request, saved.get("next", ""))
    login(request, user, backend="organization.backends.MicrosoftBackend")
    request.session.set_expiry(8 * 60 * 60)
    messages.success(request, "已使用公司 M365 帳號登入，並同步所屬部門。")
    return redirect(destination)
