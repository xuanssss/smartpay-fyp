from django.urls import path
from . import views

urlpatterns = [
    path("new/", views.create_payment, name="create_payment"),
    path("", views.transaction_history, name="transaction_history"),
    path("<int:pk>/", views.transaction_detail, name="transaction_detail"),
    path("<int:pk>/category/", views.change_category, name="change_category"),
]
