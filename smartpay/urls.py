from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from accounts.forms import EmailOrUsernameAuthenticationForm

urlpatterns = [
    path(
        "favicon.ico",
        RedirectView.as_view(url="/static/favicon.svg", permanent=True),
        name="favicon",
    ),
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(
        template_name="registration/login.html",
        authentication_form=EmailOrUsernameAuthenticationForm,
    ), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("accounts.urls")),
    path("payments/", include("payments.urls")),
    path("dashboard/", include("analytics.urls")),
    path("alerts/", include("alerts.urls")),
]
