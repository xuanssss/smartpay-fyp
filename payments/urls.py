from django.urls import path
from . import views

urlpatterns = [
    path("new/", views.create_payment, name="create_payment"),
    path("catalogue/<slug:slug>/", views.catalogue_item_detail, name="catalogue_item_detail"),
    path("merchant/", views.pay_another_merchant, name="pay_another_merchant"),
    path("methods/", views.payment_method_list, name="payment_method_list"),
    path("methods/add/", views.add_payment_method, name="add_payment_method"),
    path("methods/<int:pk>/default/", views.set_default_payment_method, name="set_default_payment_method"),
    path("methods/<int:pk>/deactivate/", views.deactivate_payment_method, name="deactivate_payment_method"),
    path("", views.transaction_history, name="transaction_history"),
    path("<int:pk>/", views.transaction_detail, name="transaction_detail"),
    path("<int:pk>/category/", views.change_category, name="change_category"),
]
