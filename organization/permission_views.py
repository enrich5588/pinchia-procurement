from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from urllib.parse import urlencode

from .models import Department, PermissionAudit
from .permission_catalog import DEFAULTS, PERMISSIONS
from .permission_forms import PermissionEditForm, PermissionTargetForm
from .permission_service import explicit_rules, revision_for, save_permissions
from .permissions import resolve_permission


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def permission_management(request):
    if not request.user.is_superuser:
        raise PermissionDenied("只有系統管理員可以設定部門與個人權限。")
    scope = request.GET.get("scope", "department")
    if scope not in {"department", "user"}:
        scope = "department"
    query = request.GET.get("q", "").strip()[:200]
    target_data = request.GET.copy()
    target_data["scope"] = scope
    target_form = PermissionTargetForm(
        target_data if "target" in request.GET else None,
        scope=scope, initial={"scope": scope},
    )
    # Directory filters affect presentation only, never target validation or grants.
    department_id = request.GET.get("department", "")
    departments = list(Department.objects.order_by("name").annotate(
        member_count=Count("userprofile", distinct=True),
        rule_count=Count("permission_rules", distinct=True),
    ))
    department_ids = {str(department.pk) for department in departments}
    if department_id not in department_ids | {"unassigned"}:
        department_id = ""
    account_status = request.GET.get("status", "")
    if account_status not in {"active", "inactive"}:
        account_status = ""
    if scope != "user":
        department_id, account_status = "", ""
    directory_params = {"scope": scope, "q": query}
    if department_id:
        directory_params["department"] = department_id
    if account_status:
        directory_params["status"] = account_status
    targets = target_form.fields["target"].queryset
    total_targets = targets.count()
    if query:
        if scope == "user":
            targets = targets.filter(
                Q(first_name__icontains=query) | Q(last_name__icontains=query)
                | Q(username__icontains=query) | Q(email__icontains=query)
                | Q(microsoft_identity__principal_name__icontains=query)
                | Q(profile__department__name__icontains=query)
            )
        else:
            targets = targets.filter(name__icontains=query)
    if scope == "user":
        targets = targets.select_related("profile__department", "microsoft_identity")
        if department_id == "unassigned":
            targets = targets.filter(profile__isnull=True)
        elif department_id:
            targets = targets.filter(profile__department_id=department_id)
        if account_status:
            targets = targets.filter(is_active=(account_status == "active"))
    targets = targets.annotate(rule_count=Count("permission_rules", distinct=True))
    paginator = Paginator(targets, 20)
    directory_page = paginator.get_page(request.GET.get("page"))
    directory_params["page"] = directory_page.number
    member_counts = {department.pk: department.member_count for department in departments}
    target_list = []
    for item in directory_page:
        entry = {"id": item.pk, "name": str(item), "rules": item.rule_count,
                 "url": "?" + urlencode({**directory_params, "target": item.pk}) + "#permission-editor"}
        if scope == "user":
            identity = getattr(item, "microsoft_identity", None)
            profile = getattr(item, "profile", None)
            entry.update(name=item.get_full_name() or item.get_username(),
                         account=identity.principal_name if identity else item.get_username(),
                         email=item.email,
                         department=profile.department.name if profile else "未設定部門",
                         active=item.is_active, superuser=item.is_superuser, m365=bool(identity))
        else:
            entry.update(members=member_counts.get(item.pk, 0),
                         members_url="?" + urlencode({"scope": "user", "department": item.pk}))
        target_list.append(entry)
    department_list = [{"id": str(department.pk), "name": department.name,
                        "members": department.member_count,
                        "url": "?" + urlencode({"scope": "user", "department": department.pk,
                                                "q": query, "status": account_status})}
                       for department in departments]
    user_count = get_user_model().objects.count()
    unassigned_count = get_user_model().objects.filter(profile__isnull=True).count()
    target = None
    form = None
    rows = []
    history = []
    status = 200
    if target_form.is_bound and target_form.is_valid():
        target = target_form.cleaned_data["target"]
        rules = explicit_rules(scope, target)
        initial = {code: rules.get(code, "inherit") for code in DEFAULTS}
        initial["revision"] = revision_for(rules)
        form = PermissionEditForm(request.POST if request.method == "POST" else None, initial=initial)
        if request.method == "POST":
            if form.is_valid():
                try:
                    changes = save_permissions(
                        actor=request.user, target_type=scope, target=target,
                        values={code: form.cleaned_data[code] for code in DEFAULTS},
                        revision=form.cleaned_data["revision"],
                    )
                except ValidationError as error:
                    form.add_error(None, error)
                    status = 409
                else:
                    messages.success(request, f"已更新 {target} 的 {len(changes)} 項權限。" if changes else "權限設定未變更。")
                    return redirect(reverse("permission_management") + "?" + urlencode({**directory_params, "target": target.pk}) + "#permission-editor")
            else:
                status = 422
        for code, label, description, default in PERMISSIONS:
            if scope == "user":
                allowed, source = resolve_permission(target, code)
            else:
                allowed = rules.get(code, "allow" if default else "deny") == "allow"
                source = "部門設定" if code in rules else "系統預設"
            if allowed and (code.endswith(".manage") or code == "approvals.view_all"):
                access_code = code.split(".")[0] + ".access"
                access_allowed = (resolve_permission(target, access_code)[0] if scope == "user"
                                  else rules.get(access_code, "allow") == "allow")
                if not access_allowed:
                    allowed, source = False, "功能進入已拒絕"
            if code == "database.monitor" and scope == "department":
                allowed, source = False, "系統管理員專用"
            rows.append({"field": form[code], "description": description, "allowed": allowed,
                         "source": source, "default": default})
        history = PermissionAudit.objects.filter(target_type=scope, target_id=target.pk)[:20]
    elif request.method == "POST":
        status = 400
    pagination_params = {**directory_params, **({"target": target.pk} if target else {})}
    def page_url(number):
        return "?" + urlencode({**pagination_params, "page": number}) + "#permission-directory"
    page_links = [
        {"label": str(number), "url": page_url(number) if number != paginator.ELLIPSIS else "",
         "current": number == directory_page.number}
        for number in paginator.get_elided_page_range(directory_page.number, on_each_side=1, on_ends=1)
    ]
    return render(request, "organization/permission_management.html", {
        "target_form": target_form, "permission_form": form, "permission_rows": rows,
        "target": target, "scope": scope, "history": history,
        "target_list": target_list, "total_targets": total_targets, "search_query": query,
        "directory_page": directory_page, "page_links": page_links,
        "previous_page_url": page_url(directory_page.previous_page_number()) if directory_page.has_previous() else "",
        "next_page_url": page_url(directory_page.next_page_number()) if directory_page.has_next() else "",
        "departments": department_list, "selected_department": department_id,
        "account_status": account_status, "user_count": user_count,
        "department_count": len(departments), "unassigned_count": unassigned_count,
        "all_users_url": "?" + urlencode({"scope": "user", "q": query, "status": account_status}),
        "unassigned_url": "?" + urlencode({"scope": "user", "department": "unassigned",
                                           "q": query, "status": account_status}),
        "has_filters": bool(query or department_id or account_status),
        "reload_url": "?" + urlencode({**directory_params, **({"target": target.pk} if target else {})}) + "#permission-editor",
        "clear_search_url": "?" + urlencode({"scope": scope, **({"target": target.pk} if target else {})}),
        "target_label": (target_form.fields["target"].label_from_instance(target) if target else ""),
    }, status=status)
