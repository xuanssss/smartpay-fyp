from datetime import date
from decimal import Decimal

from django.db.models import Count, Sum

from alerts.models import Alert
from analytics.models import RecurringBill
from payments.models import Transaction


def _month_start(month):
    if hasattr(month, "date"):
        month = month.date()
    return month.replace(day=1)


def _next_month(month):
    return date(month.year + (month.month == 12), 1 if month.month == 12 else month.month + 1, 1)


def _previous_month(month):
    return date(month.year - (month.month == 1), 12 if month.month == 1 else month.month - 1, 1)


def _transactions_for_month(user, month):
    start = _month_start(month)
    end = _next_month(start)
    return Transaction.objects.filter(user=user, transaction_date__date__gte=start, transaction_date__date__lt=end)


def get_monthly_total(user, month):
    return _transactions_for_month(user, month).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")


def get_previous_month_total(user, month):
    return get_monthly_total(user, _previous_month(_month_start(month)))


def get_month_to_month_change(user, month):
    current = get_monthly_total(user, month)
    previous = get_previous_month_total(user, month)
    if not previous:
        return None
    return round(float((current - previous) / previous * 100), 1)


def get_category_breakdown(user, month):
    return list(
        _transactions_for_month(user, month)
        .values("final_category__name")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("-total")
    )


def get_top_merchants(user, month, limit=5):
    return list(
        _transactions_for_month(user, month)
        .values("merchant_name")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("-total")[:limit]
    )


def get_largest_transactions(user, month, limit=5):
    return _transactions_for_month(user, month).select_related("final_category").order_by("-amount")[:limit]


def get_recurring_bills(user):
    return list(RecurringBill.objects.filter(user=user).select_related("category"))


def get_alert_summary(user):
    queryset = Alert.objects.filter(user=user)
    counts = {row["status"]: row["count"] for row in queryset.values("status").annotate(count=Count("id"))}
    return {"active": counts.get(Alert.Status.ACTIVE, 0), "total": queryset.count()}
