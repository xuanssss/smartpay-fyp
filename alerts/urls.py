from django.urls import path
from . import views

urlpatterns = [
    path("", views.alert_list, name="alert_list"),
    path("<int:pk>/<str:status>/", views.update_alert_status, name="update_alert_status"),
]
