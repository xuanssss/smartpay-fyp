from datetime import datetime
from time import perf_counter

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from analytics.forms import MonthlyBudgetForm
from analytics.models import MonthlyBudget, PerformanceLog
from .services.dashboard import (
    get_analysis_cross_filter_data,
    get_budget_summary,
    get_category_breakdown,
    get_effective_budget,
    get_month_summary,
    get_monthly_review_data,
    get_period_comparison,
    get_smart_insights,
)


def _selected_month(request):
    raw_month = request.GET.get("month", "")
    try:
        return datetime.strptime(raw_month, "%Y-%m").date().replace(day=1)
    except (TypeError, ValueError):
        return timezone.localdate().replace(day=1)


def _base_context(request, active_view):
    month = _selected_month(request)
    month_index = month.year * 12 + month.month - 1
    previous_year, previous_zero_month = divmod(month_index - 1, 12)
    next_year, next_zero_month = divmod(month_index + 1, 12)
    view_name = "dashboard_analysis" if active_view == "analysis" else "dashboard"
    return {
        "month": month,
        "month_value": month.strftime("%Y-%m"),
        "previous_month_value": f"{previous_year:04d}-{previous_zero_month + 1:02d}",
        "next_month_value": f"{next_year:04d}-{next_zero_month + 1:02d}",
        "dashboard_view_url": reverse(view_name),
        "active_dashboard_view": active_view,
    }


def _record_dashboard_load(user, started):
    PerformanceLog.objects.create(
        user=user,
        operation_name=PerformanceLog.Operation.DASHBOARD_LOADING,
        duration_ms=(perf_counter() - started) * 1000,
    )


@login_required
def dashboard(request):
    started = perf_counter()
    context = _base_context(request, "overview")
    month = context["month"]
    budget_summary = get_budget_summary(request.user, month)
    comparison = get_period_comparison(request.user, month)
    review = get_monthly_review_data(request.user, month)
    context.update({
        "budget_summary": budget_summary,
        "comparison": comparison,
        "smart_insights": get_smart_insights(request.user, month, budget_summary),
        "review": review,
        "review_interactions": review["interactions"],
        "review_trend": review["trend"],
    })
    _record_dashboard_load(request.user, started)
    return render(request, "analytics/dashboard.html", context)


@login_required
def dashboard_analysis(request):
    started = perf_counter()
    context = _base_context(request, "analysis")
    month = context["month"]
    breakdown = get_category_breakdown(request.user, month)
    comparison = get_period_comparison(request.user, month)
    context.update({
        "monthly_summary": get_month_summary(request.user, month),
        "comparison": comparison,
        "category_breakdown": breakdown,
        "category_labels_json": [row["final_category__name"] for row in breakdown],
        "category_values_json": [float(row["total"]) for row in breakdown],
        "category_shares_json": [row["share_percent"] for row in breakdown],
        "cross_filter_data": get_analysis_cross_filter_data(request.user, month),
    })
    _record_dashboard_load(request.user, started)
    return render(request, "analytics/dashboard_analysis.html", context)


@login_required
def dashboard_review(request):
    month = _selected_month(request)
    return redirect(f"{reverse('dashboard')}?month={month:%Y-%m}")


@login_required
def monthly_budget(request):
    selected_month = _selected_month(request)
    existing = MonthlyBudget.objects.filter(user=request.user, month=selected_month).first()
    effective_budget = get_effective_budget(request.user, selected_month)
    if request.method == "POST" and request.POST.get("action") == "delete":
        month_value = request.POST.get("month", "")
        try:
            month = datetime.strptime(month_value, "%Y-%m").date().replace(day=1)
        except (TypeError, ValueError):
            messages.error(request, "Choose a valid budget month.")
        else:
            MonthlyBudget.objects.filter(user=request.user, month=month).delete()
            messages.success(request, f"Budget for {month:%B %Y} removed.")
            return redirect(f"{reverse('dashboard')}?month={month:%Y-%m}")

    form = MonthlyBudgetForm(
        request.POST or None,
        initial={
            "month": selected_month,
            "amount": effective_budget.amount if effective_budget else None,
        },
    )
    if request.method == "POST" and request.POST.get("action") != "delete" and form.is_valid():
        month = form.cleaned_data["month"]
        MonthlyBudget.objects.update_or_create(
            user=request.user,
            month=month,
            defaults={"amount": form.cleaned_data["amount"]},
        )
        messages.success(request, f"Budget for {month:%B %Y} saved.")
        return redirect(f"{reverse('dashboard')}?month={month:%Y-%m}")
    return render(request, "analytics/monthly_budget_form.html", {
        "form": form,
        "budget": existing,
        "effective_budget": effective_budget,
        "month": selected_month,
    })
