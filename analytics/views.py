from time import perf_counter

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from alerts.models import Alert
from analytics.models import PerformanceLog
from .services.dashboard import (
    get_alert_summary,
    get_category_breakdown,
    get_largest_transactions,
    get_month_to_month_change,
    get_monthly_total,
    get_previous_month_total,
    get_recurring_bills,
    get_top_merchants,
)
from .services.recurring import refresh_recurring_bills


@login_required
def dashboard(request):
    started = perf_counter()
    month = timezone.localdate().replace(day=1)
    refresh_recurring_bills(request.user)
    breakdown = get_category_breakdown(request.user, month)
    current_total = get_monthly_total(request.user, month)
    previous_total = get_previous_month_total(request.user, month)
    high_spending_alerts = Alert.objects.filter(
        user=request.user,
        alert_type=Alert.AlertType.HIGH_CATEGORY,
        status=Alert.Status.ACTIVE,
    ).select_related("transaction")[:5]
    # TODO-FYP-TWEAK: Edit dashboard wording and labels here and in the template for the final study.
    context = {
        "month": month,
        "monthly_total": current_total,
        "previous_total": previous_total,
        "month_change": get_month_to_month_change(request.user, month),
        "category_breakdown": breakdown,
        "category_labels_json": [row["final_category__name"] for row in breakdown],
        "category_values_json": [float(row["total"]) for row in breakdown],
        "month_labels_json": ["Previous month", "This month"],
        "month_values_json": [float(previous_total), float(current_total)],
        "top_merchants": get_top_merchants(request.user, month),
        "largest_transactions": get_largest_transactions(request.user, month),
        "recurring_bills": get_recurring_bills(request.user),
        "alert_summary": get_alert_summary(request.user),
        "high_spending_alerts": high_spending_alerts,
    }
    context["month_change_abs"] = abs(context["month_change"]) if context["month_change"] is not None else None
    PerformanceLog.objects.create(
        user=request.user,
        operation_name=PerformanceLog.Operation.DASHBOARD_LOADING,
        duration_ms=(perf_counter() - started) * 1000,
    )
    return render(request, "analytics/dashboard.html", context)
