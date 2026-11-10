from django.urls import path

from . import views


urlpatterns = [
    path("", views.approval_list, name="approval_list"),
    path("new/", views.approval_create, name="approval_create"),
    path("<int:pk>/resubmit/", views.approval_resubmit, name="approval_resubmit"),
    path("<int:pk>/", views.approval_detail, name="approval_detail"),
    path("<int:pk>/approve/", views.approval_approve, name="approval_approve"),
    path("<int:pk>/return/", views.approval_return, name="approval_return"),
    path("<int:pk>/withdraw/", views.approval_withdraw, name="approval_withdraw"),
]
