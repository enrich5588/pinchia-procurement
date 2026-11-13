from datetime import date, datetime, timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from organization.gate import feature_required
from organization.models import Department, user_department
from project_options.assets import (
    DATABASE_MONITOR_DEFAULT_REFRESH,
    DATABASE_MONITOR_REFRESH_OPTIONS,
)

from .forms import (
    AssetBulkApprovalFormSet,
    AssetBulkUploadForm,
    AssetImportPreviewFormSet,
    AssetForm,
    AssetRegistrationForm,
    RegistrationImportPreviewFormSet,
)
from .excel_templates import build_asset_import_template, build_registration_import_template
from .importers import (
    AssetWorkbookError,
    import_asset_preview,
    import_registration_preview,
    prepare_asset_workbook,
    prepare_registration_workbook,
)
from .models import Asset, AssetImage, AssetImportBatch, AssetRegistration
from .permissions import can_manage_assets, can_manage_registrations, can_monitor_database
from organization.permissions import has_permission
from .services import (
    apply_registration_image_changes,
    next_registration_case_no,
    save_asset_form,
    save_registration_images,
)


@login_required
@feature_required
def asset_list(request):
    department = user_department(request.user)
    can_manage = can_manage_assets(request.user)
    assets = _visible_assets(request.user).prefetch_related("images")
    categories = list(
        assets.exclude(category="").order_by("category")
        .values_list("category", flat=True).distinct()
    )

    selected_department = ""
    selected_category = ""
    if can_manage:
        selected_department = request.GET.get("department", "")
        selected_category = request.GET.get("category", "")
        if selected_department.isdigit() and Department.objects.filter(
            pk=selected_department
        ).exists():
            assets = assets.filter(department_id=selected_department)
        elif selected_department:
            selected_department = ""
        if selected_category in categories:
            assets = assets.filter(category=selected_category)
        elif selected_category:
            selected_category = ""
    elif department is None:
        assets = assets.none()

    assets = assets.order_by("-created_at", "-pk")

    summary = assets.aggregate(
        total=Count("pk"),
        it_equipment=Count("pk", filter=Q(category=Asset.Category.IT_EQUIPMENT)),
        furniture=Count("pk", filter=Q(category=Asset.Category.FURNITURE)),
        other=Count("pk", filter=Q(category=Asset.Category.OTHER)),
        pinjia_development=Count(
            "pk", filter=Q(company=Asset.Company.PINJIA_DEVELOPMENT)
        ),
        pinjia_construction=Count(
            "pk", filter=Q(company=Asset.Company.PINJIA_CONSTRUCTION)
        ),
        pinjia_asset=Count("pk", filter=Q(company=Asset.Company.PINJIA_ASSET)),
    )

    return render(request, "assets/asset_list.html", {
        "assets": assets,
        "summary": summary,
        "can_manage": can_manage,
        "departments": Department.objects.order_by("name") if can_manage else (),
        "categories": categories,
        "selected_department": selected_department,
        "selected_category": selected_category,
        "department": department,
    })


@login_required
@feature_required
def asset_detail(request, pk):
    asset = get_object_or_404(_visible_assets(request.user).prefetch_related("images"), pk=pk)
    can_request_revision = False
    if not can_manage_assets(request.user):
        has_approved_registration = AssetRegistration.objects.filter(
            Q(asset=asset) | Q(target_asset=asset),
            applicant=request.user,
            status=AssetRegistration.Status.APPROVED,
        ).exists()
        can_request_revision = has_permission(request.user, "registrations.access") and (
            asset.custodian_id == request.user.pk or has_approved_registration
        )
    template = "assets/_asset_detail.html" if _is_modal_request(request) else "assets/asset_detail.html"
    return render(request, template, {
        "asset": asset,
        "can_manage": can_manage_assets(request.user),
        "can_request_revision": can_request_revision,
        "is_modal": _is_modal_request(request),
    })


@login_required
@feature_required
def asset_create(request):
    if not can_manage_assets(request.user):
        raise PermissionDenied("只有具備處理權限的人員可新增公司財產。")

    form = AssetForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        asset = save_asset_form(form, request.user)
        messages.success(request, f"已新增財產：{asset.asset_no} {asset.name}")
        if _is_modal_request(request):
            return JsonResponse({"success": True, "redirect_url": reverse("asset_list")})
        return redirect("asset_list")

    return _render_asset_form(
        request,
        form,
        title="新增公司財產",
        submit_label="儲存財產",
        status=422 if request.method == "POST" and _is_modal_request(request) else 200,
    )


@login_required
@feature_required
def asset_bulk_upload(request):
    if not can_manage_assets(request.user):
        raise PermissionDenied("只有具備處理權限的人員可批量上傳公司財產。")

    expired_batches = AssetImportBatch.objects.filter(
        created_at__lt=timezone.now() - timedelta(days=1)
    )
    for expired in expired_batches:
        expired.source_file.delete(save=False)
    expired_batches.delete()

    form = AssetBulkUploadForm(request.POST or None, request.FILES or None)
    import_errors = []
    if request.method == "POST" and form.is_valid():
        try:
            preview = prepare_asset_workbook(
                form.cleaned_data["excel_file"],
                fallback_department=(
                    form.cleaned_data["fallback_department"]
                    if form.cleaned_data.get("testing_compatibility") else None
                ),
            )
        except AssetWorkbookError as exc:
            import_errors = exc.errors
        else:
            upload = form.cleaned_data["excel_file"]
            upload.seek(0)
            batch = AssetImportBatch(
                source_filename=upload.name,
                rows=preview.rows,
                skipped=preview.skipped,
                created_by=request.user,
            )
            batch.source_file.save(upload.name, upload, save=False)
            batch.save()
            return redirect("asset_bulk_upload_preview", pk=batch.pk)

    return render(request, "assets/asset_bulk_upload.html", {
        "form": form,
        "import_errors": import_errors,
    })


@login_required
@feature_required
def asset_bulk_upload_template(request):
    if not can_manage_assets(request.user):
        raise PermissionDenied("只有具備處理權限的人員可下載財產批量上傳範本。")
    output = build_asset_import_template()
    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = (
        "attachment; filename*=UTF-8''%E8%B2%A1%E7%94%A2%E6%89%B9%E9%87%8F%E4%B8%8A%E5%82%B3%E7%AF%84%E6%9C%AC.xlsx"
    )
    return response


@login_required
@feature_required
def asset_bulk_upload_preview(request, pk):
    if not can_manage_assets(request.user):
        raise PermissionDenied("只有具備處理權限的人員可確認批量上傳公司財產。")
    batch = get_object_or_404(
        AssetImportBatch, pk=pk, created_by=request.user,
        import_type=AssetImportBatch.ImportType.ASSET,
    )
    initial = [
        dict(
            row,
            row_index=index,
            source_row_number=row["row_number"],
            image_status="有圖片" if row.get("image_path") else "無圖片",
            include=True,
        )
        for index, row in enumerate(batch.rows)
    ]
    import_errors = []

    if request.method == "POST" and request.POST.get("action") == "cancel":
        batch.source_file.delete(save=False)
        batch.delete()
        messages.success(request, "已取消本次批量匯入。")
        return redirect("asset_bulk_upload")

    formset = AssetImportPreviewFormSet(
        request.POST or None,
        initial=initial,
        prefix="rows",
    )
    if request.method == "POST" and formset.is_valid():
        try:
            result = import_asset_preview(batch, formset.cleaned_data, request.user)
        except AssetWorkbookError as exc:
            import_errors = exc.errors
        except (ValidationError, IntegrityError) as exc:
            import_errors = [f"資料無法匯入：{exc}"]
        else:
            message = f"批量匯入完成：新增 {result.asset_count} 筆財產、{result.image_count} 張圖片。"
            if result.year_only_date_count:
                message += f" 其中 {result.year_only_date_count} 筆僅有年份，採購日期已設為該年 1 月 1 日。"
            if result.fallback_department_count:
                message += f" {result.fallback_department_count} 筆使用替代部門。"
            if result.unmatched_user_count:
                message += f" {result.unmatched_user_count} 筆保管人員暫時留空。"
            if batch.skipped:
                message += f" 已跳過 {len(batch.skipped)} 筆缺少必要欄位的資料。"
            messages.success(request, message)
            return redirect("asset_list")

    return render(request, "assets/asset_bulk_upload_preview.html", {
        "batch": batch,
        "formset": formset,
        "import_errors": import_errors,
    })


@login_required
@feature_required
def registration_bulk_upload(request):
    department = user_department(request.user)
    if can_manage_registrations(request.user) or department is None:
        raise PermissionDenied("只有已設定部門的申請人可批量送出資產登記。")

    form = AssetBulkUploadForm(request.POST or None, request.FILES or None)
    import_errors = []
    if request.method == "POST" and form.is_valid():
        try:
            preview = prepare_registration_workbook(
                form.cleaned_data["excel_file"],
                fallback_department=(
                    form.cleaned_data["fallback_department"]
                    if form.cleaned_data.get("testing_compatibility") else None
                ),
            )
        except AssetWorkbookError as exc:
            import_errors = exc.errors
        else:
            if not preview.rows:
                import_errors = preview.skipped or ["沒有可送出的資產登記資料。"]
            else:
                upload = form.cleaned_data["excel_file"]
                upload.seek(0)
                batch = AssetImportBatch(
                    import_type=AssetImportBatch.ImportType.REGISTRATION,
                    source_filename=upload.name,
                    rows=preview.rows,
                    skipped=preview.skipped,
                    created_by=request.user,
                )
                batch.source_file.save(upload.name, upload, save=False)
                batch.save()
                return redirect("registration_bulk_upload_preview", pk=batch.pk)

    return render(request, "assets/registration_bulk_upload.html", {
        "form": form,
        "import_errors": import_errors,
    })


@login_required
@feature_required
def registration_bulk_upload_template(request):
    if can_manage_registrations(request.user) or user_department(request.user) is None:
        raise PermissionDenied("只有已設定部門的申請人可下載資產登記批量上傳範本。")
    output = build_registration_import_template()
    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = (
        "attachment; filename*=UTF-8''%E8%B3%87%E7%94%A2%E7%99%BB%E8%A8%98%E6%89%B9%E9%87%8F%E4%B8%8A%E5%82%B3%E7%AF%84%E6%9C%AC.xlsx"
    )
    return response


@login_required
@feature_required
def registration_bulk_upload_preview(request, pk):
    department = user_department(request.user)
    if can_manage_registrations(request.user) or department is None:
        raise PermissionDenied("只有已設定部門的申請人可確認資產登記批量上傳。")
    batch = get_object_or_404(
        AssetImportBatch, pk=pk, created_by=request.user,
        import_type=AssetImportBatch.ImportType.REGISTRATION,
    )
    initial = [
        dict(
            row,
            row_index=index,
            source_row_number=row["row_number"],
            image_status="有圖片" if row.get("image_path") else "無圖片",
            include=True,
        )
        for index, row in enumerate(batch.rows)
    ]
    import_errors = []

    if request.method == "POST" and request.POST.get("action") == "cancel":
        batch.source_file.delete(save=False)
        batch.delete()
        messages.success(request, "已取消本次資產登記批量上傳。")
        return redirect("registration_bulk_upload")

    formset = RegistrationImportPreviewFormSet(
        request.POST or None, initial=initial, prefix="rows"
    )
    if request.method == "POST" and formset.is_valid():
        try:
            result = import_registration_preview(batch, formset.cleaned_data, request.user)
        except AssetWorkbookError as exc:
            import_errors = exc.errors
        except (ValidationError, IntegrityError) as exc:
            import_errors = [f"資料無法送出：{exc}"]
        else:
            message = (
                f"批量送出完成：建立 {result.asset_count} 筆待審核資產登記、"
                f"{result.image_count} 張圖片。"
            )
            if result.year_only_date_count:
                message += f" 其中 {result.year_only_date_count} 筆採購日期設為該年 1 月 1 日。"
            if batch.skipped:
                message += f" 已跳過 {len(batch.skipped)} 筆缺少必要欄位的資料。"
            messages.success(request, message)
            return redirect("registration_list")

    return render(request, "assets/registration_bulk_upload_preview.html", {
        "batch": batch,
        "formset": formset,
        "import_errors": import_errors,
    })


@login_required
@feature_required
def asset_edit(request, pk):
    if not can_manage_assets(request.user):
        raise PermissionDenied("只有具備處理權限的人員可編輯公司財產。")

    asset = get_object_or_404(Asset, pk=pk)
    form = AssetForm(request.POST or None, request.FILES or None, instance=asset)
    if request.method == "POST" and form.is_valid():
        asset = save_asset_form(form, request.user)
        messages.success(request, f"已更新財產：{asset.asset_no} {asset.name}")
        if _is_modal_request(request):
            return JsonResponse({"success": True, "redirect_url": reverse("asset_list")})
        return redirect("asset_list")

    return _render_asset_form(
        request,
        form,
        title=f"編輯財產 {asset.asset_no}",
        submit_label="儲存變更",
        status=422 if request.method == "POST" and _is_modal_request(request) else 200,
    )


@login_required
@feature_required
def asset_number_check(request):
    if not can_manage_assets(request.user):
        raise PermissionDenied("只有具備處理權限的人員可查詢財產編號。")

    asset_no = request.GET.get("asset_no", "").strip().upper()
    exists = bool(asset_no) and Asset.objects.filter(
        asset_no__iexact=asset_no
    ).exists()
    return JsonResponse({
        "asset_no": asset_no,
        "exists": exists,
        "available": bool(asset_no) and not exists,
    })


@login_required
@feature_required
def asset_image(request, pk):
    visible_assets = _visible_assets(request.user)
    images = AssetImage.objects.select_related("asset").filter(asset__in=visible_assets)
    image = get_object_or_404(images, pk=pk)
    return _image_response(image)


@login_required
@feature_required
def registration_image(request, pk):
    images = AssetImage.objects.filter(registration__isnull=False)
    if not can_manage_registrations(request.user):
        images = images.filter(registration__applicant=request.user)
    return _image_response(get_object_or_404(images, pk=pk))


def _image_response(image):
    try:
        response = FileResponse(image.image.open("rb"))
    except FileNotFoundError:
        raise Http404("圖片不存在。")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _visible_assets(user):
    assets = Asset.objects.select_related("department", "custodian")
    if can_manage_assets(user):
        return assets
    department = user_department(user)
    return assets.filter(department=department) if department else assets.none()


@login_required
@feature_required
def registration_list(request):
    can_manage = can_manage_registrations(request.user)
    department = user_department(request.user)
    registrations = AssetRegistration.objects.select_related(
        "department", "custodian", "applicant", "approved_by", "asset", "target_asset"
    )
    if not can_manage:
        registrations = registrations.filter(applicant=request.user)

    summary = registrations.aggregate(
        total=Count("pk"),
        pending=Count("pk", filter=Q(status=AssetRegistration.Status.PENDING)),
        returned=Count("pk", filter=Q(status=AssetRegistration.Status.RETURNED)),
        closed=Count(
            "pk", filter=Q(status__in=[
                AssetRegistration.Status.APPROVED,
                AssetRegistration.Status.CANCELLED,
            ])
        ),
    )
    return render(request, "assets/registration_list.html", {
        "registrations": registrations,
        "summary": summary,
        "can_manage": can_manage,
        "can_apply": not can_manage and department is not None,
        "department": department,
        "departments": Department.objects.order_by("name"),
    })


@login_required
@feature_required
def registration_create(request):
    department = user_department(request.user)
    if can_manage_registrations(request.user):
        raise PermissionDenied("案件處理人員請由處理清單核准資產登記申請。")
    if department is None:
        raise PermissionDenied("帳號尚未設定所屬部門，無法申請資產登記。")

    form = AssetRegistrationForm(request.POST or None, request.FILES or None, department=department)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            registration = form.save(commit=False)
            registration.case_no = next_registration_case_no()
            registration.applicant = request.user
            registration.save()
            save_registration_images(form, registration)
        messages.success(request, f"資產登記申請 {registration.case_no} 已送出。")
        return _modal_success_or_redirect(request, "registration_list")

    return _render_registration_form(
        request, form, department=department, title="資產登記申請",
        submit_label="送出申請",
        status=422 if request.method == "POST" and _is_modal_request(request) else 200,
    )


@login_required
@feature_required
def registration_custodians(request):
    department_id = request.GET.get("department", "")
    if not department_id.isdigit():
        return JsonResponse({"custodians": []})
    users = get_user_model().objects.filter(
        profile__department_id=department_id
    ).order_by("username")
    return JsonResponse({
        "custodians": [
            {
                "id": user.pk,
                "label": (
                    f"{user.username}（{user.get_full_name()}）"
                    if user.get_full_name() else user.username
                ),
            }
            for user in users
        ]
    })


@login_required
@feature_required
def registration_revise(request, pk):
    if can_manage_registrations(request.user):
        raise PermissionDenied("案件處理人員不可提出財產異動申請。")
    source = get_object_or_404(
        AssetRegistration.objects.select_related("asset", "target_asset"),
        pk=pk,
    )
    target_asset = source.asset or source.target_asset
    if source.status != AssetRegistration.Status.APPROVED or target_asset is None:
        raise PermissionDenied("只有已核准並建立財產的案件可以提出修改。")
    if source.applicant_id != request.user.pk and target_asset.custodian_id != request.user.pk:
        raise PermissionDenied("只有原申請人或目前保管人員可以修改此財產。")
    return _handle_asset_revision(request, target_asset)


@login_required
@feature_required
def asset_revise(request, pk):
    if not has_permission(request.user, "registrations.access"):
        raise PermissionDenied("您沒有提出資產異動申請的權限。")
    if can_manage_assets(request.user):
        raise PermissionDenied("案件處理人員請直接編輯財產清冊。")
    target_asset = get_object_or_404(_visible_assets(request.user), pk=pk)
    is_original_applicant = AssetRegistration.objects.filter(
        Q(asset=target_asset) | Q(target_asset=target_asset),
        applicant=request.user,
        status=AssetRegistration.Status.APPROVED,
    ).exists()
    if target_asset.custodian_id != request.user.pk and not is_original_applicant:
        raise PermissionDenied("只有原申請人或目前保管人員可以修改此財產。")
    return _handle_asset_revision(request, target_asset)


def _handle_asset_revision(request, target_asset):
    department = user_department(request.user)
    if department != target_asset.department:
        raise PermissionDenied("您目前的所屬部門無法修改此財產。")

    active_revision = AssetRegistration.objects.filter(
        target_asset=target_asset,
        status__in=[AssetRegistration.Status.PENDING, AssetRegistration.Status.RETURNED],
    ).first()
    if active_revision:
        if active_revision.applicant_id != request.user.pk:
            raise PermissionDenied("此財產已有進行中的異動申請。")
        messages.info(request, f"財產已有異動申請 {active_revision.case_no}，請繼續修改該案件。")
        return redirect("registration_edit", pk=active_revision.pk)

    form = AssetRegistrationForm(
        request.POST or None,
        request.FILES or None,
        department=department,
        target_asset=target_asset,
        initial=_asset_registration_initial(target_asset),
    )
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                locked_asset = get_object_or_404(
                    Asset.objects.select_for_update(), pk=target_asset.pk
                )
                if AssetRegistration.objects.select_for_update().filter(
                    target_asset=locked_asset,
                    status__in=[
                        AssetRegistration.Status.PENDING,
                        AssetRegistration.Status.RETURNED,
                    ],
                ).exists():
                    form.add_error(None, "此財產已有進行中的異動申請，請重新整理後再試。")
                    return _render_registration_form(
                        request, form, department=department,
                        title=f"修改財產 {locked_asset.asset_no}",
                        submit_label="送出異動申請", status=409,
                        source_asset=locked_asset,
                    )
                registration = form.save(commit=False)
                registration.case_no = next_registration_case_no()
                registration.applicant = request.user
                registration.target_asset = locked_asset
                registration.save()
                save_registration_images(form, registration)
        except IntegrityError:
            form.add_error(None, "此財產已有進行中的異動申請，請重新整理後再試。")
            return _render_registration_form(
                request, form, department=department,
                title=f"修改財產 {target_asset.asset_no}",
                submit_label="送出異動申請", status=409,
                source_asset=target_asset,
            )
        messages.success(
            request,
            f"財產 {target_asset.asset_no} 的異動申請 {registration.case_no} 已送出；核准前清冊資料維持不變。",
        )
        return _modal_success_or_redirect(request, "registration_list")

    return _render_registration_form(
        request, form, department=department,
        title=f"修改財產 {target_asset.asset_no}",
        submit_label="送出異動申請",
        status=422 if request.method == "POST" and _is_modal_request(request) else 200,
        source_asset=target_asset,
    )


@login_required
@feature_required
def registration_edit(request, pk):
    if can_manage_registrations(request.user):
        raise PermissionDenied("案件處理人員不可修改員工的資產登記申請。")
    department = user_department(request.user)
    registration = get_object_or_404(
        AssetRegistration, pk=pk, applicant=request.user
    )
    editable_statuses = {
        AssetRegistration.Status.PENDING, AssetRegistration.Status.RETURNED
    }
    if request.method == "GET" and registration.status not in editable_statuses:
        raise PermissionDenied("已結案的申請不可修改。")

    form = AssetRegistrationForm(
        request.POST or None, request.FILES or None, instance=registration,
        department=department, target_asset=registration.target_asset,
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            locked = get_object_or_404(
                AssetRegistration.objects.select_for_update(),
                pk=pk, applicant=request.user,
            )
            if locked.status not in editable_statuses:
                form.add_error(None, "案件狀態已變更，無法儲存本次修改。")
                return _render_registration_form(
                    request, form, department=department,
                    title=f"修改申請 {locked.case_no}", submit_label="重新送出申請",
                    status=409,
                )
            locked_form = AssetRegistrationForm(
                request.POST, request.FILES or None, instance=locked,
                department=department, target_asset=locked.target_asset,
            )
            if not locked_form.is_valid():
                form = locked_form
            else:
                registration = locked_form.save(commit=False)
                registration.status = AssetRegistration.Status.PENDING
                registration.closed_at = None
                registration.approved_by = None
                registration.save()
                save_registration_images(locked_form, registration)
                messages.success(request, f"申請 {registration.case_no} 已重新送出。")
                return _modal_success_or_redirect(request, "registration_list")

    return _render_registration_form(
        request, form, department=department,
        title=f"修改申請 {registration.case_no}", submit_label="重新送出申請",
        status=422 if request.method == "POST" and _is_modal_request(request) else 200,
        source_asset=registration.target_asset,
    )


@login_required
@feature_required
def registration_detail(request, pk):
    registration = get_object_or_404(
        AssetRegistration.objects.select_related(
            "department", "custodian", "asset", "target_asset"
        ), pk=pk
    )
    if not can_manage_registrations(request.user) and registration.applicant_id != request.user.pk:
        raise PermissionDenied("您無權查看此資產登記申請。")
    template = "assets/_registration_detail.html" if _is_modal_request(request) else "assets/registration_detail.html"
    return render(request, template, {
        "registration": registration, "is_modal": _is_modal_request(request)
    })


@login_required
@feature_required
@require_POST
def registration_return(request, pk):
    if not can_manage_registrations(request.user):
        raise PermissionDenied("只有具備處理權限的人員可退回申請。")
    with transaction.atomic():
        registration = get_object_or_404(
            AssetRegistration.objects.select_for_update(), pk=pk
        )
        if registration.status != AssetRegistration.Status.PENDING:
            messages.error(request, "案件狀態已變更，無法退回。")
        else:
            registration.status = AssetRegistration.Status.RETURNED
            registration.save(update_fields=["status", "modified_at"])
            messages.success(request, f"申請 {registration.case_no} 已退回。")
    return redirect("registration_list")


@login_required
@feature_required
@require_POST
def registration_cancel(request, pk):
    if can_manage_registrations(request.user):
        raise PermissionDenied("案件處理人員不可代替員工取消申請。")
    with transaction.atomic():
        registration = get_object_or_404(
            AssetRegistration.objects.select_for_update(), pk=pk, applicant=request.user
        )
        if registration.status not in {
            AssetRegistration.Status.PENDING, AssetRegistration.Status.RETURNED
        }:
            messages.error(request, "案件狀態已變更，無法取消。")
        else:
            registration.status = AssetRegistration.Status.CANCELLED
            registration.closed_at = timezone.now()
            registration.save(update_fields=["status", "closed_at", "modified_at"])
            messages.success(request, f"申請 {registration.case_no} 已取消並結案。")
    return redirect("registration_list")


@login_required
@feature_required
def registration_approve(request, pk):
    if not can_manage_registrations(request.user):
        raise PermissionDenied("只有具備處理權限的人員可核准申請。")
    registration = get_object_or_404(AssetRegistration, pk=pk)
    initial = {
        "name": registration.name,
        "company": registration.company,
        "category": registration.category,
        "brand": registration.brand,
        "specification": registration.specification,
        "accessories": registration.accessories,
        "quantity": registration.quantity,
        "unit_price": registration.unit_price,
        "business_tax": registration.business_tax,
        "total": registration.total,
        "department": registration.department,
        "custodian": registration.custodian,
        "purchase_date": registration.purchase_date,
        "useful_life_years": registration.useful_life_years,
        "notes": registration.notes,
    }
    target_asset = registration.target_asset
    form = AssetForm(
        request.POST or None, request.FILES or None,
        instance=target_asset, initial=initial,
    )
    form.registration_images = registration.images.all()
    form.requested_image_removals = registration.asset_images_to_remove.all()
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            locked = get_object_or_404(
                AssetRegistration.objects.select_for_update(), pk=pk
            )
            if locked.status != AssetRegistration.Status.PENDING:
                form.add_error(None, "案件狀態已變更，無法核准。")
                return _render_asset_form(
                    request, form, title=f"核准申請 {locked.case_no}",
                    submit_label="建立公司資產並核准", status=409,
                )
            if locked.target_asset_id:
                asset = get_object_or_404(
                    Asset.objects.select_for_update(), pk=locked.target_asset_id
                )
                for field_name in AssetForm.Meta.fields:
                    if field_name not in {"asset_no", "total"}:
                        setattr(asset, field_name, form.cleaned_data[field_name])
                form.instance = asset
            else:
                asset = None
            asset = save_asset_form(form, request.user)
            apply_registration_image_changes(locked, asset)
            locked.status = AssetRegistration.Status.APPROVED
            locked.closed_at = timezone.now()
            locked.approved_by = request.user
            update_fields = ["status", "closed_at", "approved_by", "modified_at"]
            if not locked.target_asset_id:
                locked.asset = asset
                update_fields.append("asset")
            locked.save(update_fields=update_fields)
        action = "更新財產" if locked.target_asset_id else "建立財產"
        messages.success(request, f"申請 {locked.case_no} 已核准並{action} {asset.asset_no}。")
        return _modal_success_or_redirect(request, "registration_list")

    if request.method == "GET" and registration.status != AssetRegistration.Status.PENDING:
        raise PermissionDenied("只有申請中的案件可以核准。")
    return _render_asset_form(
        request, form, title=f"核准申請 {registration.case_no}",
        submit_label="套用變更並核准" if target_asset else "建立公司資產並核准",
        status=422 if request.method == "POST" and _is_modal_request(request) else 200,
    )


@login_required
@feature_required
@require_POST
def registration_bulk_return(request):
    if not can_manage_registrations(request.user):
        raise PermissionDenied("只有具備處理權限的人員可批量退回申請。")
    registration_ids = _selected_ids(request.POST.getlist("registration_ids"))
    if not registration_ids:
        messages.error(request, "請至少勾選一筆資產登記申請。")
        return redirect("registration_list")
    with transaction.atomic():
        registrations = list(
            AssetRegistration.objects.select_for_update().filter(pk__in=registration_ids)
        )
        if len(registrations) != len(registration_ids) or any(
            item.status != AssetRegistration.Status.PENDING for item in registrations
        ):
            messages.error(request, "部分案件狀態已變更，本次批量退回已全部取消。")
            return redirect("registration_list")
        for item in registrations:
            item.status = AssetRegistration.Status.RETURNED
            item.save(update_fields=["status", "modified_at"])
    messages.success(request, f"已批量退回 {len(registrations)} 筆資產登記申請。")
    return redirect("registration_list")


@login_required
@feature_required
@require_POST
def registration_bulk_approve(request):
    if not can_manage_registrations(request.user):
        raise PermissionDenied("只有具備處理權限的人員可批量核准申請。")

    if "commit" not in request.POST:
        registration_ids = _selected_ids(request.POST.getlist("registration_ids"))
        if not registration_ids:
            messages.error(request, "請至少勾選一筆資產登記申請。")
            return redirect("registration_list")
        registrations = list(
            AssetRegistration.objects.select_related("department", "custodian", "target_asset")
            .filter(pk__in=registration_ids, status=AssetRegistration.Status.PENDING)
            .order_by("applied_at", "pk")
        )
        if len(registrations) != len(registration_ids):
            messages.error(request, "部分案件狀態已變更，請重新勾選。")
            return redirect("registration_list")
        if any(item.target_asset_id for item in registrations):
            messages.error(request, "財產異動案件須逐筆檢視後核准。")
            return redirect("registration_list")
        formset = AssetBulkApprovalFormSet(initial=[
            {"registration_id": item.pk, "asset_no": ""} for item in registrations
        ])
        return _render_bulk_asset_approval(request, formset, registrations)

    formset = AssetBulkApprovalFormSet(request.POST)
    registration_ids = []
    if formset.is_valid():
        registration_ids = [form.cleaned_data["registration_id"] for form in formset]
        if len(registration_ids) != len(set(registration_ids)):
            formset._non_form_errors = formset.error_class(
                ["同一筆資產登記申請不可重複送出。"]
            )
    registrations = list(
        AssetRegistration.objects.select_related("department", "custodian", "target_asset")
        .filter(pk__in=registration_ids).order_by("applied_at", "pk")
    ) if registration_ids else []
    if formset.is_valid() and len(registrations) == len(registration_ids):
        if any(item.target_asset_id for item in registrations):
            messages.error(request, "財產異動案件須逐筆檢視後核准。")
            return redirect("registration_list")
        registration_map = {item.pk: item for item in registrations}
        try:
            with transaction.atomic():
                locked = list(
                    AssetRegistration.objects.select_for_update()
                    .select_related("department", "custodian")
                    .filter(pk__in=registration_ids)
                )
                if len(locked) != len(registration_ids) or any(
                    item.status != AssetRegistration.Status.PENDING for item in locked
                ):
                    messages.error(request, "部分案件狀態已變更，本次批量核准已全部取消。")
                    return redirect("registration_list")
                locked_map = {item.pk: item for item in locked}
                for row_form in formset:
                    item = locked_map[row_form.cleaned_data["registration_id"]]
                    asset = Asset(
                        asset_no=row_form.cleaned_data["asset_no"], name=item.name,
                        company=item.company, category=item.category, brand=item.brand,
                        specification=item.specification, accessories=item.accessories,
                        quantity=item.quantity, unit_price=item.unit_price,
                        business_tax=item.business_tax,
                        department=item.department, custodian=item.custodian,
                        purchase_date=item.purchase_date,
                        useful_life_years=item.useful_life_years, notes=item.notes,
                        created_by=request.user, updated_by=request.user,
                    )
                    asset.full_clean()
                    asset.save()
                    item.images.update(asset=asset)
                    item.status = AssetRegistration.Status.APPROVED
                    item.closed_at = timezone.now()
                    item.approved_by = request.user
                    item.asset = asset
                    item.save(update_fields=[
                        "status", "closed_at", "approved_by", "asset", "modified_at"
                    ])
        except (IntegrityError, ValidationError):
            messages.error(request, "批量建檔資料驗證失敗，本次核准已全部取消。")
            return redirect("registration_list")
        messages.success(request, f"已批量核准並建立 {len(registration_ids)} 筆公司財產。")
        return redirect("registration_list")
    if registration_ids and len(registrations) != len(registration_ids):
        messages.error(request, "部分案件不存在或狀態已變更，請重新勾選。")
        return redirect("registration_list")
    return _render_bulk_asset_approval(request, formset, registrations, status=422)


@login_required
@feature_required
def database_monitor(request):
    if not can_monitor_database(request.user):
        raise PermissionDenied("只有系統管理員可查看資料庫狀態。")

    refresh_seconds = request.GET.get("refresh", DATABASE_MONITOR_DEFAULT_REFRESH)
    allowed_refresh_values = {value for value, _ in DATABASE_MONITOR_REFRESH_OPTIONS}
    if refresh_seconds not in allowed_refresh_values:
        refresh_seconds = DATABASE_MONITOR_DEFAULT_REFRESH

    user_labels = dict(get_user_model().objects.values_list("pk", "username"))
    department_labels = dict(Department.objects.values_list("pk", "name"))
    asset_labels = dict(Asset.objects.values_list("pk", "asset_no"))
    relation_labels = {
        "department_id": department_labels,
        "custodian_id": user_labels,
        "created_by_id": user_labels,
        "updated_by_id": user_labels,
        "applicant_id": user_labels,
        "approved_by_id": user_labels,
        "approver_id": user_labels,
        "returned_by_id": user_labels,
        "asset_id": asset_labels,
        "target_asset_id": asset_labels,
        "assigned_department_id": department_labels,
    }
    audit_fields = {
        "created_at", "created_by_id", "updated_at", "updated_by_id",
        "applied_at", "applicant_id", "modified_at", "closed_at",
        "approved_by_id",
        "acted_at",
    }
    tables = []
    with connection.cursor() as cursor:
        for table_name in sorted(connection.introspection.table_names(cursor)):
            quoted_name = connection.ops.quote_name(table_name)
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {quoted_name}")
                row_count = cursor.fetchone()[0]
                description = connection.introspection.get_table_description(cursor, table_name)
                constraints = connection.introspection.get_constraints(cursor, table_name)
                columns = []
                for field in description:
                    field_constraints = [
                        details for details in constraints.values()
                        if field.name in details.get("columns", [])
                    ]
                    foreign_keys = [
                        details["foreign_key"] for details in field_constraints
                        if details.get("foreign_key")
                    ]
                    try:
                        field_type = connection.introspection.get_field_type(
                            field.type_code, field
                        )
                    except (KeyError, TypeError):
                        field_type = str(field.type_code)
                    columns.append({
                        "name": field.name,
                        "type": field_type,
                        "nullable": bool(field.null_ok),
                        "default": field.default,
                        "is_audit": field.name in audit_fields,
                        "primary_key": any(item.get("primary_key") for item in field_constraints),
                        "unique": any(item.get("unique") for item in field_constraints),
                        "indexed": any(item.get("index") for item in field_constraints),
                        "foreign_key": ", ".join(
                            f"{target_table}.{target_column}"
                            for target_table, target_column in foreign_keys
                        ),
                    })
                column_count = len(columns)
                data_rows = []
                is_data_table = table_name.startswith((
                    "assets_", "procurement_", "collaboration_hub_", "approval_hub_"
                ))
                if is_data_table:
                    cursor.execute(f"SELECT * FROM {quoted_name}")
                    for record_number, raw_row in enumerate(cursor.fetchall(), start=1):
                        values = []
                        for field, raw_value in zip(description, raw_row):
                            display_value = _format_monitor_value(raw_value)
                            related_label = relation_labels.get(field.name, {}).get(raw_value)
                            if raw_value is not None and related_label:
                                display_value = f"{display_value} — {related_label}"
                            values.append({
                                "name": field.name,
                                "value": display_value,
                                "is_null": raw_value is None,
                                "is_audit": field.name in audit_fields,
                            })
                        data_rows.append({"number": record_number, "values": values})
                status = "正常"
            except Exception:
                row_count = None
                column_count = None
                columns = []
                data_rows = []
                status = "讀取失敗"
                is_data_table = False
            tables.append({
                "name": table_name,
                "row_count": row_count,
                "column_count": column_count,
                "columns": columns,
                "data_rows": data_rows,
                "status": status,
                "is_asset_table": table_name.startswith("assets_"),
                "is_data_table": is_data_table,
            })

    return render(request, "assets/database_monitor.html", {
        "tables": tables,
        "table_count": len(tables),
        "total_rows": sum(item["row_count"] or 0 for item in tables),
        "asset_table_count": sum(item["is_asset_table"] for item in tables),
        "database_vendor": connection.vendor,
        "checked_at": timezone.localtime(),
        "refresh_seconds": refresh_seconds,
        "refresh_options": DATABASE_MONITOR_REFRESH_OPTIONS,
    })


def _format_monitor_value(value):
    if value is None:
        return "NULL"
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.strftime("%Y/%m/%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y/%m/%d")
    if isinstance(value, bool):
        return "True" if value else "False"
    return str(value)


def _is_modal_request(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _selected_ids(raw_ids):
    return list(dict.fromkeys(int(value) for value in raw_ids if value.isdigit()))


def _render_bulk_asset_approval(request, formset, registrations, status=200):
    registration_map = {item.pk: item for item in registrations}
    rows = []
    for row_form in formset:
        raw_id = row_form["registration_id"].value()
        try:
            registration = registration_map.get(int(raw_id))
        except (TypeError, ValueError):
            registration = None
        rows.append((row_form, registration))
    return render(request, "assets/registration_bulk_approve.html", {
        "formset": formset, "rows": rows,
    }, status=status)


def _modal_success_or_redirect(request, route_name):
    if _is_modal_request(request):
        return JsonResponse({"success": True, "redirect_url": reverse(route_name)})
    return redirect(route_name)


def _asset_registration_initial(asset):
    return {
        "name": asset.name,
        "company": asset.company,
        "category": asset.category,
        "brand": asset.brand,
        "specification": asset.specification,
        "accessories": asset.accessories,
        "quantity": asset.quantity,
        "unit_price": asset.unit_price,
        "business_tax": asset.business_tax,
        "total": asset.total,
        "department": asset.department,
        "custodian": asset.custodian,
        "purchase_date": asset.purchase_date,
        "useful_life_years": asset.useful_life_years,
        "notes": asset.notes,
    }


def _render_registration_form(
    request, form, *, department, title, submit_label, status, source_asset=None
):
    context = {
        "form": form, "department": department, "form_title": title,
        "submit_label": submit_label, "form_action": request.path,
        "is_modal": _is_modal_request(request),
        "source_asset": source_asset,
    }
    template = "assets/_registration_form.html" if _is_modal_request(request) else "assets/registration_form.html"
    return render(request, template, context, status=status)


def _render_asset_form(request, form, *, title, submit_label, status):
    context = {
        "form": form,
        "form_title": title,
        "submit_label": submit_label,
        "form_action": request.path,
        "is_edit": bool(form.instance.pk),
        "is_modal": _is_modal_request(request),
    }
    template = (
        "assets/_asset_form.html"
        if _is_modal_request(request)
        else "assets/asset_form.html"
    )
    return render(request, template, context, status=status)
