from django.urls import path
from .views import dashboard, dashboard_analysis, dashboard_review, monthly_budget

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("analysis/", dashboard_analysis, name="dashboard_analysis"),
    path("monthly-review/", dashboard_review, name="dashboard_review"),
    path("budget/", monthly_budget, name="monthly_budget"),
]
