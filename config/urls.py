from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from procurement import views as pviews
from organization.auth_views import CompanyLoginView, microsoft_callback, microsoft_login
from organization.permission_views import permission_management
from organization.panel_views import panel_management

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", CompanyLoginView.as_view(), name="login"),
    path("accounts/microsoft/login/", microsoft_login, name="microsoft_login"),
    path("accounts/microsoft/callback/", microsoft_callback, name="microsoft_callback"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("permissions/", permission_management, name="permission_management"),
    path("panels/", panel_management, name="panel_management"),
    path("", pviews.home, name="home"),
    path("supplies/", include("procurement.urls")),
    path("assets/", include("assets.urls")),
    path("collaboration/", include("collaboration_hub.urls")),
    path("approvals/", include("approval_hub.urls")),
]
