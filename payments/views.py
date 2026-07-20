from time import perf_counter

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.shortcuts import get_object_or_404, redirect, render

from alerts.services.alert_generation import generate_alerts
from analytics.models import PerformanceLog
from analytics.services.recurring import refresh_recurring_bills
from .forms import CategoryCorrectionForm, PaymentForm
from .models import Transaction
from .services.categorisation import categorise_transaction


@login_required
def create_payment(request):
    form = PaymentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        started = perf_counter()
        with db_transaction.atomic():
            payment = form.save(commit=False)
            payment.user = request.user
            result = categorise_transaction(payment.merchant_name, payment.payment_type, payment.note)
            payment.predicted_category = result.category
            payment.final_category = result.category
            payment.confidence_score = result.confidence
            payment.category_explanation = result.explanation
            payment.save()
        PerformanceLog.objects.create(
            user=request.user, operation_name=PerformanceLog.Operation.CATEGORISATION,
            duration_ms=(perf_counter() - started) * 1000,
        )
        generate_alerts(payment)
        refresh_recurring_bills(request.user)
        messages.success(request, "Payment saved and categorised.")
        return redirect("transaction_detail", pk=payment.pk)
    return render(request, "payments/payment_form.html", {"form": form})


@login_required
def transaction_history(request):
    transactions = request.user.transactions.select_related("final_category", "predicted_category").prefetch_related("alerts")
    return render(request, "payments/transaction_history.html", {"transactions": transactions})


@login_required
def transaction_detail(request, pk):
    payment = get_object_or_404(
        Transaction.objects.select_related("predicted_category", "final_category").prefetch_related("alerts"),
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
        corrected.save(update_fields=["final_category", "predicted_category", "user_corrected", "updated_at"])
        refresh_recurring_bills(request.user)
        messages.success(request, "Category updated. Your original prediction has been kept for evaluation.")
        return redirect("transaction_detail", pk=payment.pk)
    return render(request, "payments/change_category.html", {"form": form, "transaction": payment})
