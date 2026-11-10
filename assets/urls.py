from django.urls import path

from . import views


urlpatterns = [
    path("", views.asset_list, name="asset_list"),
    path("new/", views.asset_create, name="asset_create"),
    path("bulk-upload/", views.asset_bulk_upload, name="asset_bulk_upload"),
    path("bulk-upload/template/", views.asset_bulk_upload_template, name="asset_bulk_upload_template"),
    path("bulk-upload/<int:pk>/preview/", views.asset_bulk_upload_preview, name="asset_bulk_upload_preview"),
    path("images/<int:pk>/", views.asset_image, name="asset_image"),
    path("registrations/images/<int:pk>/", views.registration_image, name="registration_image"),
    path("check-number/", views.asset_number_check, name="asset_number_check"),
    path("registrations/", views.registration_list, name="registration_list"),
    path("registrations/new/", views.registration_create, name="registration_create"),
    path("registrations/bulk-upload/", views.registration_bulk_upload, name="registration_bulk_upload"),
    path("registrations/bulk-upload/template/", views.registration_bulk_upload_template, name="registration_bulk_upload_template"),
    path("registrations/bulk-upload/<int:pk>/preview/", views.registration_bulk_upload_preview, name="registration_bulk_upload_preview"),
    path("registrations/custodians/", views.registration_custodians, name="registration_custodians"),
    path("registrations/bulk-return/", views.registration_bulk_return, name="registration_bulk_return"),
    path("registrations/bulk-approve/", views.registration_bulk_approve, name="registration_bulk_approve"),
    path("registrations/<int:pk>/", views.registration_detail, name="registration_detail"),
    path("registrations/<int:pk>/edit/", views.registration_edit, name="registration_edit"),
    path("registrations/<int:pk>/revise/", views.registration_revise, name="registration_revise"),
    path("registrations/<int:pk>/return/", views.registration_return, name="registration_return"),
    path("registrations/<int:pk>/cancel/", views.registration_cancel, name="registration_cancel"),
    path("registrations/<int:pk>/approve/", views.registration_approve, name="registration_approve"),
    path("database-monitor/", views.database_monitor, name="database_monitor"),
    path("<int:pk>/", views.asset_detail, name="asset_detail"),
    path("<int:pk>/revise/", views.asset_revise, name="asset_revise"),
    path("<int:pk>/edit/", views.asset_edit, name="asset_edit"),
]
