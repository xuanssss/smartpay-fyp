from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from .forms import (
    CataloguePurchaseForm,
    CategoryCorrectionForm,
    PaymentMethodForm,
    PayAnotherMerchantForm,
)
from .models import CatalogueItem, PaymentMethod, Transaction
from .services.catalog import get_browse_group_for_slug, get_catalogue
from .services.categorisation import CategorisationUnavailable
from .services.payment_processing import create_catalogue_purchase, create_merchant_payment


@login_required
def create_payment(request):
    browse_groups, selected_category, items = get_catalogue(
        request.GET.get("category", "food")
    )
    selected_category_label = next(
        (group["label"] for group in browse_groups if group["slug"] == selected_category),
        "Items",
    )
    return render(request, "payments/payment_form.html", {
        "browse_groups": browse_groups,
        "selected_category": selected_category,
        "selected_category_label": selected_category_label,
        "items": items,
    })


@login_required
def catalogue_item_detail(request, slug):
    item = get_object_or_404(
        CatalogueItem.objects.select_related("browse_category", "ground_truth_category"),
        slug=slug, is_active=True, browse_category__is_active=True,
    )
    form = CataloguePurchaseForm(request.POST or None, user=request.user, item=item)
    has_methods = PaymentMethod.objects.filter(user=request.user, is_active=True).exists()
    if request.method == "POST" and form.is_valid():
        try:
            payment, created = create_catalogue_purchase(
                user=request.user,
                item=item,
                quantity=form.cleaned_data.get("quantity", 1),
                amount=form.total_amount(),
                payment_method=form.cleaned_data["payment_method"],
                submission_token=form.cleaned_data["submission_token"],
            )
        except CategorisationUnavailable as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(
                request,
                "Purchase completed and categorised." if created else "This purchase was already submitted.",
            )
            return redirect("transaction_detail", pk=payment.pk)
    return render(request, "payments/catalogue_item_detail.html", {
        "item": item,
        "form": form,
        "has_methods": has_methods,
        "browse_group": get_browse_group_for_slug(item.browse_category.slug),
    })


@login_required
def pay_another_merchant(request):
    form = PayAnotherMerchantForm(request.POST or None, user=request.user)
    has_methods = PaymentMethod.objects.filter(user=request.user, is_active=True).exists()
    if request.method == "POST" and form.is_valid():
        try:
            payment, created = create_merchant_payment(
                user=request.user, cleaned_data=form.cleaned_data
            )
        except CategorisationUnavailable as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(
                request,
                "Payment completed and categorised." if created else "This payment was already submitted.",
            )
            return redirect("transaction_detail", pk=payment.pk)
    return render(request, "payments/pay_another_merchant.html", {
        "form": form,
        "has_methods": has_methods,
    })


@login_required
def payment_method_list(request):
    methods = PaymentMethod.objects.filter(user=request.user)
    return render(request, "payments/payment_method_list.html", {"payment_methods": methods})


@login_required
def add_payment_method(request):
    form = PaymentMethodForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        method = form.save(commit=False)
        method.user = request.user
        method.is_simulated = True
        method.save()
        messages.success(request, "Payment method added.")
        return redirect("payment_method_list")
    return render(request, "payments/payment_method_form.html", {"form": form})


@login_required
def set_default_payment_method(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    method = get_object_or_404(PaymentMethod, pk=pk, user=request.user, is_active=True)
    method.is_default = True
    method.save(update_fields=["is_default", "updated_at"])
    messages.success(request, f"{method.display_name} is now your default method.")
    return redirect("payment_method_list")


@login_required
def deactivate_payment_method(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    method = get_object_or_404(PaymentMethod, pk=pk, user=request.user, is_active=True)
    method.deactivate()
    messages.success(request, "Payment method removed from active use.")
    return redirect("payment_method_list")


@login_required
def transaction_history(request):
    transactions = request.user.transactions.select_related(
        "final_category", "predicted_category", "catalogue_item", "payment_method"
    ).prefetch_related("alerts")
    return render(request, "payments/transaction_history.html", {"transactions": transactions})


@login_required
def transaction_detail(request, pk):
    payment = get_object_or_404(
        Transaction.objects.select_related(
            "predicted_category", "final_category", "catalogue_item__browse_category", "payment_method"
        ).prefetch_related("alerts"),
        pk=pk, user=request.user,
    )
    return render(request, "payments/transaction_detail.html", {"transaction": payment})


@login_required
def change_category(request, pk):
    payment = get_object_or_404(Transaction, pk=pk, user=request.user)
    predicted_id = payment.predicted_category_id
    form = CategoryCorrectionForm(request.POST or None, instance=payment)
    if request.method == "POST" and form.is_valid():
        corrected = form.save(commit=False)
        corrected.predicted_category_id = predicted_id
        corrected.user_corrected = True
        corrected.categorisation_source = Transaction.CategorisationSource.USER_CORRECTION
        corrected.save(update_fields=[
            "final_category", "predicted_category", "user_corrected", "categorisation_source", "updated_at",
        ])
        messages.success(request, "Category updated. The original prediction remains available for evaluation.")
        return redirect("transaction_detail", pk=payment.pk)
    return render(request, "payments/change_category.html", {"form": form, "transaction": payment})
