import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from django.db.models import Avg, Count, Sum
from django.db.models.functions import ExtractDay
from django.utils import timezone

from alerts.models import Alert
from analytics.models import MonthlyBudget
from payments.models import Transaction


ZERO = Decimal("0.00")


def _month_start(month):
    if hasattr(month, "date"):
        month = month.date()
    return month.replace(day=1)


def _next_month(month):
    return date(month.year + (month.month == 12), 1 if month.month == 12 else month.month + 1, 1)


def _previous_month(month):
    return date(month.year - (month.month == 1), 12 if month.month == 1 else month.month - 1, 1)


def _transactions_between(user, start, end):
    return Transaction.objects.filter(
        user=user,
        transaction_date__date__gte=start,
        transaction_date__date__lt=end,
    )


def _visible_month_end(month, today=None):
    """Return the exclusive end date without exposing future current-month data."""
    month = _month_start(month)
    today = today or timezone.localdate()
    current_month = today.replace(day=1)
    if month < current_month:
        return _next_month(month)
    if month == current_month:
        return min(today + timedelta(days=1), _next_month(month))
    return month


def _transactions_for_month(user, month, today=None):
    start = _month_start(month)
    return _transactions_between(user, start, _visible_month_end(start, today=today))


def _total(queryset):
    return queryset.aggregate(total=Sum("amount"))["total"] or ZERO


def get_monthly_total(user, month):
    return _total(_transactions_for_month(user, month))


def get_previous_month_total(user, month):
    return get_monthly_total(user, _previous_month(_month_start(month)))


def get_month_to_month_change(user, month):
    current = get_monthly_total(user, month)
    previous = get_previous_month_total(user, month)
    if not previous:
        return None
    return round(float((current - previous) / previous * 100), 1)


def get_period_comparison(user, month, today=None, same_period=True):
    """Compare equivalent current-month periods by default, or complete calendar months."""
    month = _month_start(month)
    today = today or timezone.localdate()
    previous = _previous_month(month)
    current_end = _next_month(month)
    previous_end = _next_month(previous)
    label = "previous month"

    if same_period and month == today.replace(day=1):
        elapsed_days = today.day
        current_end = today + timedelta(days=1)
        previous_last_day = calendar.monthrange(previous.year, previous.month)[1]
        previous_day = min(elapsed_days, previous_last_day)
        previous_end = previous.replace(day=previous_day) + timedelta(days=1)
        label = "same point last month"

    current_total = _total(_transactions_between(user, month, current_end))
    previous_total = _total(_transactions_between(user, previous, previous_end))
    change = None
    if previous_total:
        change = round(float((current_total - previous_total) / previous_total * 100), 1)
    difference = current_total - previous_total
    return {
        "current_total": current_total,
        "previous_total": previous_total,
        "difference": difference,
        "difference_abs": abs(difference),
        "change": change,
        "change_abs": abs(change) if change is not None else None,
        "label": label,
        "previous_month": previous,
    }


def get_category_breakdown(user, month, today=None):
    rows = list(
        _transactions_for_month(user, month, today=today)
        .values("final_category__name")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("-total")
    )
    total = sum((row["total"] for row in rows), ZERO)
    for row in rows:
        row["share_percent"] = round(float(row["total"] / total * 100), 1) if total else 0
    return rows


def get_top_merchants(user, month, limit=5, today=None):
    return list(
        _transactions_for_month(user, month, today=today)
        .values("merchant_name")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("-total")[:limit]
    )


def get_merchant_analysis(user, month, limit=4, today=None):
    """Return leading merchants with a real previous-month amount comparison."""
    month = _month_start(month)
    today = today or timezone.localdate()
    previous = _previous_month(month)
    merchants = get_top_merchants(user, month, limit=limit, today=today)
    previous_end = _next_month(previous)
    if month == today.replace(day=1):
        previous_day = min(today.day, calendar.monthrange(previous.year, previous.month)[1])
        previous_end = previous.replace(day=previous_day) + timedelta(days=1)
    previous_totals = {
        row["merchant_name"]: row["total"]
        for row in _transactions_between(user, previous, previous_end)
        .values("merchant_name")
        .annotate(total=Sum("amount"))
    }
    for merchant in merchants:
        previous_total = previous_totals.get(merchant["merchant_name"], ZERO)
        difference = merchant["total"] - previous_total
        merchant.update({
            "previous_total": previous_total,
            "difference": difference,
            "difference_abs": abs(difference),
            "direction": "up" if difference > 0 else "down" if difference < 0 else "same",
        })
    return merchants


def get_largest_transactions(user, month, limit=5):
    return _transactions_for_month(user, month).select_related("final_category").order_by("-amount")[:limit]


def get_daily_spending(user, month, today=None):
    month = _month_start(month)
    today = today or timezone.localdate()
    day_count = calendar.monthrange(month.year, month.month)[1]
    if month < today.replace(day=1):
        observed_days = day_count
    elif month == today.replace(day=1):
        observed_days = today.day
    else:
        observed_days = 0
    totals = {
        row["day"]: row["total"]
        for row in _transactions_for_month(user, month, today=today)
        .annotate(day=ExtractDay("transaction_date"))
        .values("day")
        .annotate(total=Sum("amount"))
    }
    return {
        "labels": list(range(1, day_count + 1)),
        "values": [
            float(totals.get(day, ZERO)) if day <= observed_days else None
            for day in range(1, day_count + 1)
        ],
    }


def get_yearly_spending_trend(user, month, today=None):
    """Return twelve real monthly totals ending with the selected month."""
    month = _month_start(month)
    month_index = month.year * 12 + month.month - 1
    months = []
    for offset in range(-11, 1):
        year, zero_based_month = divmod(month_index + offset, 12)
        months.append(date(year, zero_based_month + 1, 1))
    return {
        "months": months,
        "labels": [item.strftime("%b %Y") for item in months],
        "values": [float(_total(_transactions_for_month(user, item, today=today))) for item in months],
    }


def get_month_summary(user, month, today=None):
    month = _month_start(month)
    today = today or timezone.localdate()
    aggregate = _transactions_for_month(user, month, today=today).aggregate(
        total=Sum("amount"),
        count=Count("id"),
        average=Avg("amount"),
    )
    total = aggregate["total"] or ZERO
    days_in_month = calendar.monthrange(month.year, month.month)[1]
    if month < today.replace(day=1):
        observed_days = days_in_month
    elif month == today.replace(day=1):
        observed_days = today.day
    else:
        observed_days = 0
    daily_average = total / observed_days if observed_days else ZERO
    return {
        "total": total,
        "count": aggregate["count"] or 0,
        "average": aggregate["average"] or ZERO,
        "daily_average": daily_average,
        "days_in_month": days_in_month,
        "observed_days": observed_days,
    }


def get_effective_budget(user, month):
    """Return the latest budget change effective for the selected month."""
    month = _month_start(month)
    return MonthlyBudget.objects.filter(user=user, month__lte=month).order_by("-month").first()


def get_budget_summary(user, month, today=None):
    month = _month_start(month)
    budget = get_effective_budget(user, month)
    summary = get_month_summary(user, month, today=today)
    if not budget:
        return {"budget": None, **summary}

    amount = budget.amount
    spent = summary["total"]
    remaining = amount - spent
    used_percent = float(spent / amount * 100) if amount else 0
    projected = spent
    today = today or timezone.localdate()
    if month == today.replace(day=1) and summary["observed_days"]:
        projected = spent / summary["observed_days"] * summary["days_in_month"]

    if spent > amount:
        status = "exceeded"
    elif month == today.replace(day=1) and projected > amount:
        status = "at_risk"
    else:
        status = "on_track"
    return {
        "budget": budget,
        "budget_source_month": budget.month,
        "budget_is_inherited": budget.month != month,
        "remaining": remaining,
        "remaining_abs": abs(remaining),
        "used_percent": round(used_percent, 1),
        "progress_percent": min(round(used_percent, 1), 100),
        "projected_total": projected,
        "status": status,
        **summary,
    }


def get_analysis_cross_filter_data(user, month, today=None):
    """Build the coordinated category, merchant, alert, and history drill-down."""
    month = _month_start(month)
    today = today or timezone.localdate()
    day_count = calendar.monthrange(month.year, month.month)[1]
    current_month = today.replace(day=1)
    observed_days = day_count if month < current_month else today.day if month == current_month else 0
    day_labels = list(range(1, day_count + 1))
    current_transactions = list(
        _transactions_for_month(user, month, today=today)
        .select_related("final_category")
        .order_by("-transaction_date", "-id")
    )

    previous = _previous_month(month)
    previous_end = _next_month(previous)
    comparison_label = "previous month"
    if month == current_month:
        previous_day = min(today.day, calendar.monthrange(previous.year, previous.month)[1])
        previous_end = previous.replace(day=previous_day) + timedelta(days=1)
        comparison_label = "same point last month"
    previous_transactions = list(
        _transactions_between(user, previous, previous_end).select_related("final_category")
    )

    def daily_values(transactions):
        totals = {}
        for transaction in transactions:
            day = timezone.localtime(transaction.transaction_date).day
            totals[day] = totals.get(day, ZERO) + transaction.amount
        return [float(totals.get(day, ZERO)) if day <= observed_days else None for day in day_labels]

    def totals_by_category(transactions):
        totals = {}
        for transaction in transactions:
            name = transaction.final_category.name
            totals[name] = totals.get(name, ZERO) + transaction.amount
        return totals

    current_category_totals = totals_by_category(current_transactions)
    previous_category_totals = totals_by_category(previous_transactions)
    current_total = sum(current_category_totals.values(), ZERO)
    previous_total = sum(previous_category_totals.values(), ZERO)

    merchant_rows = {}
    category_transactions = {}
    for transaction in current_transactions:
        category = transaction.final_category.name
        category_transactions.setdefault(category, []).append(transaction)
        key = f"{category}::{transaction.merchant_name}"
        row = merchant_rows.setdefault(key, {
            "key": key,
            "name": transaction.merchant_name,
            "category": category,
            "total": ZERO,
            "count": 0,
            "transactions": [],
        })
        row["total"] += transaction.amount
        row["count"] += 1
        local_date = timezone.localtime(transaction.transaction_date)
        row["transactions"].append({
            "id": transaction.pk,
            "date": local_date.strftime("%d %b %Y"),
            "time": local_date.strftime("%I:%M %p").lstrip("0"),
            "amount": float(transaction.amount),
            "category": category,
            "description": transaction.item_name or transaction.transaction_description or transaction.payment_type,
        })

    month_index = month.year * 12 + month.month - 1
    history_months = []
    for offset in range(-11, 1):
        year, zero_based_month = divmod(month_index + offset, 12)
        history_months.append(date(year, zero_based_month + 1, 1))
    history_start = history_months[0]
    history_transactions = list(
        _transactions_between(user, history_start, _visible_month_end(month, today=today))
        .select_related("final_category")
        .order_by("-transaction_date", "-id")
    )
    merchant_history = {}
    for transaction in history_transactions:
        category = transaction.final_category.name
        key = f"{category}::{transaction.merchant_name}"
        entry = merchant_history.setdefault(key, {
            "key": key,
            "name": transaction.merchant_name,
            "category": category,
            "monthly_totals": {},
        })
        local_date = timezone.localtime(transaction.transaction_date)
        month_key = local_date.date().replace(day=1)
        entry["monthly_totals"][month_key] = entry["monthly_totals"].get(month_key, ZERO) + transaction.amount

    merchants = {}
    history_labels = [item.strftime("%b %Y") for item in history_months]
    for key, row in merchant_rows.items():
        history = merchant_history.get(key, {"monthly_totals": {}})
        merchants[key] = {
            **row,
            "total": float(row["total"]),
            "history_labels": history_labels,
            "history_values": [float(history["monthly_totals"].get(item, ZERO)) for item in history_months],
            "transactions": row["transactions"],
        }

    alert_rows = []
    alerts = (
        Alert.objects.filter(
            user=user,
            status=Alert.Status.ACTIVE,
            transaction__transaction_date__date__gte=month,
            transaction__transaction_date__date__lt=_visible_month_end(month, today=today),
        )
        .select_related("transaction", "transaction__final_category")
        .order_by("-created_at")
    )
    for alert in alerts:
        transaction = alert.transaction
        category = transaction.final_category.name
        alert_rows.append({
            "id": alert.pk,
            "title": alert.title,
            "message": alert.message,
            "severity": alert.severity,
            "category": category,
            "merchant_name": transaction.merchant_name,
            "merchant_key": f"{category}::{transaction.merchant_name}",
            "transaction_id": transaction.pk,
            "amount": float(transaction.amount),
        })

    categories = {}
    for category, total in sorted(current_category_totals.items(), key=lambda item: item[1], reverse=True):
        previous_amount = previous_category_totals.get(category, ZERO)
        difference = total - previous_amount
        category_merchants = [
            {
                "key": row["key"],
                "name": row["name"],
                "category": row["category"],
                "total": float(row["total"]),
                "count": row["count"],
            }
            for row in merchant_rows.values()
            if row["category"] == category
        ]
        category_merchants.sort(key=lambda row: row["total"], reverse=True)
        categories[category] = {
            "total": float(total),
            "share": round(float(total / current_total * 100), 1) if current_total else 0,
            "daily_values": daily_values(category_transactions.get(category, [])),
            "previous_total": float(previous_amount),
            "difference": float(difference),
            "direction": "up" if difference > 0 else "down" if difference < 0 else "same",
            "merchants": category_merchants,
            "alerts": [row for row in alert_rows if row["category"] == category],
        }

    all_difference = current_total - previous_total
    return {
        "month_label": month.strftime("%B %Y"),
        "comparison_label": comparison_label,
        "day_labels": day_labels,
        "all": {
            "total": float(current_total),
            "daily_values": daily_values(current_transactions),
            "previous_total": float(previous_total),
            "difference": float(all_difference),
            "direction": "up" if all_difference > 0 else "down" if all_difference < 0 else "same",
            "alerts": alert_rows,
        },
        "categories": categories,
        "merchants": merchants,
    }


def get_category_changes(user, month, today=None, same_period=True):
    month = _month_start(month)
    today = today or timezone.localdate()
    previous = _previous_month(month)
    current_end = _next_month(month)
    previous_end = _next_month(previous)
    comparison_label = "previous month"

    if same_period and month == today.replace(day=1):
        current_end = today + timedelta(days=1)
        previous_day = min(today.day, calendar.monthrange(previous.year, previous.month)[1])
        previous_end = previous.replace(day=previous_day) + timedelta(days=1)
        comparison_label = "same point last month"

    def totals(start, end):
        return {
            row["final_category__name"]: row["total"]
            for row in _transactions_between(user, start, end)
            .values("final_category__name")
            .annotate(total=Sum("amount"))
        }

    current = totals(month, current_end)
    prior = totals(previous, previous_end)
    changes = []
    for name in sorted(set(current) | set(prior)):
        current_total = current.get(name, ZERO)
        previous_total = prior.get(name, ZERO)
        difference = current_total - previous_total
        percent = round(float(difference / previous_total * 100), 1) if previous_total else None
        changes.append({
            "name": name,
            "current_total": current_total,
            "previous_total": previous_total,
            "difference": difference,
            "difference_abs": abs(difference),
            "percent": percent,
            "direction": "up" if difference > 0 else "down" if difference < 0 else "same",
            "comparison_label": comparison_label,
        })
    changed_only = [row for row in changes if row["difference"] != ZERO]
    return sorted(changed_only, key=lambda row: row["difference_abs"], reverse=True)


def get_category_change_summary(user, month, limit=4, today=None, same_period=True):
    """Scale the largest category changes for a compact, comparable bar display."""
    changes = get_category_changes(
        user, month, today=today, same_period=same_period
    )[:limit]
    largest = max((row["difference_abs"] for row in changes), default=ZERO)
    return [
        {
            **row,
            "bar_percent": round(float(row["difference_abs"] / largest * 100), 1) if largest else 0,
        }
        for row in changes
    ]


def get_month_alerts(user, month, status=None, limit=None):
    month = _month_start(month)
    queryset = Alert.objects.filter(
        user=user,
        transaction__transaction_date__date__gte=month,
        transaction__transaction_date__date__lt=_visible_month_end(month),
    ).select_related("transaction")
    if status:
        queryset = queryset.filter(status=status)
    return queryset[:limit] if limit else queryset


def get_smart_insights(user, month, budget_summary=None, limit=4):
    """Create explainable insights solely from saved budgets and transaction data."""
    month = _month_start(month)
    budget_summary = budget_summary or get_budget_summary(user, month)
    insights = []
    budget = budget_summary.get("budget")

    if budget:
        if budget_summary["status"] == "exceeded":
            insights.append({
                "tone": "attention",
                "title": "Budget exceeded",
                "message": f"Spending is S${budget_summary['remaining_abs']:,.2f} above your saved budget.",
            })
        elif budget_summary["status"] == "at_risk":
            difference = budget_summary["projected_total"] - budget.amount
            insights.append({
                "tone": "attention",
                "title": "Current pace is above budget",
                "message": f"At your current pace, spending may finish about S${difference:,.2f} above budget.",
            })
        else:
            difference = budget.amount - budget_summary["projected_total"]
            current_month = timezone.localdate().replace(day=1)
            if month < current_month:
                title = "Finished within budget"
                message = f"Spending ended S${max(difference, ZERO):,.2f} below the saved budget."
            elif month > current_month:
                title = "Budget is ready"
                message = f"You have set aside S${budget.amount:,.2f} for this month."
            else:
                title = "Spending is within budget"
                message = f"Your current pace is about S${max(difference, ZERO):,.2f} below the saved budget."
            insights.append({"tone": "positive", "title": title, "message": message})

    comparison = get_period_comparison(user, month)
    if comparison["change"] is not None and comparison["change"] > 0:
        insights.append({
            "tone": "attention",
            "title": "Spending increased",
            "message": f"You spent {comparison['change_abs']:.1f}% more than the {comparison['label']}.",
        })
    elif comparison["change"] is not None and comparison["change"] < 0:
        insights.append({
            "tone": "positive",
            "title": "Spending decreased",
            "message": f"You spent {comparison['change_abs']:.1f}% less than the {comparison['label']}.",
        })
    elif comparison["change"] == 0:
        insights.append({
            "tone": "neutral",
            "title": "Spending is unchanged",
            "message": f"Total spending matches the {comparison['label']}.",
        })

    breakdown = get_category_breakdown(user, month)
    if breakdown and budget_summary["total"]:
        top = breakdown[0]
        share = float(top["total"] / budget_summary["total"] * 100)
        insights.append({
            "tone": "neutral",
            "title": f"{top['final_category__name']} is your top category",
            "message": f"It represents {share:.1f}% of spending for this month.",
        })

    active_alerts = get_month_alerts(user, month, status=Alert.Status.ACTIVE).count()
    if active_alerts:
        insights.append({
            "tone": "attention",
            "title": f"{active_alerts} item{'s' if active_alerts != 1 else ''} need attention",
            "message": "These alerts come from explainable payment-awareness rules and may be worth reviewing.",
        })
    return insights[:limit]


def get_monthly_review_data(user, month, today=None):
    """Build a time-based monthly recap without reusing category analysis."""
    month = _month_start(month)
    today = today or timezone.localdate()
    days_in_month = calendar.monthrange(month.year, month.month)[1]
    current_month = today.replace(day=1)
    observed_days = days_in_month if month < current_month else today.day if month == current_month else 0
    transactions = list(
        _transactions_for_month(user, month, today=today)
        .select_related("final_category")
        .order_by("transaction_date", "id")
    )

    def month_offset(base_month, offset):
        index = base_month.year * 12 + base_month.month - 1 + offset
        year, zero_based_month = divmod(index, 12)
        return date(year, zero_based_month + 1, 1)

    def money(value):
        return f"S${Decimal(value):,.2f}"

    daily = defaultdict(list)
    for transaction in transactions:
        daily[timezone.localtime(transaction.transaction_date).day].append(transaction)
    daily_totals = {
        day: sum((item.amount for item in items), ZERO)
        for day, items in daily.items()
    }
    total = sum((item.amount for item in transactions), ZERO)
    count = len(transactions)
    average = total / count if count else ZERO

    previous_month = _previous_month(month)
    previous_transactions = list(_transactions_for_month(user, previous_month, today=today))
    previous_total = sum((item.amount for item in previous_transactions), ZERO)
    previous_days = calendar.monthrange(previous_month.year, previous_month.month)[1]
    change = round(float((total - previous_total) / previous_total * 100), 1) if previous_total else None

    budget_summary = get_budget_summary(user, month, today=today)
    six_months = [month_offset(month, offset) for offset in range(-5, 1)]
    six_totals = [_total(_transactions_for_month(user, item, today=today)) for item in six_months]
    spending_rank = 1 + sum(1 for value in six_totals if value > total) if total else None
    if not total:
        headline = f"No spending was recorded in {month:%B}"
    elif spending_rank == 1:
        headline = f"{month:%B} was your highest-spending month in the last 6 months"
    else:
        suffix = "th" if 10 <= spending_rank % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(spending_rank % 10, "th")
        headline = f"{month:%B} ranked {spending_rank}{suffix} for spending in the last 6 months"

    if change is None:
        comparison_text = f"no spending was recorded in {previous_month:%B} for comparison"
    elif change > 0:
        comparison_text = f"up {abs(change):g}% from {previous_month:%B}"
    elif change < 0:
        comparison_text = f"down {abs(change):g}% from {previous_month:%B}"
    else:
        comparison_text = f"unchanged from {previous_month:%B}"
    budget_text = (
        f"{budget_summary['used_percent']:.1f}% of your budget was used"
        if budget_summary["budget"]
        else "no monthly budget was set"
    )

    biggest_day = max(daily_totals, key=lambda day: (daily_totals[day], -day), default=None)
    busiest_day = max(daily, key=lambda day: (len(daily[day]), -day), default=None)
    latest_day = max(daily, default=None)
    typical_spending_day = Decimal(str(median([float(value) for value in daily_totals.values()]))) if daily_totals else ZERO
    cumulative_values = []
    cumulative_counts = []
    running_total = ZERO
    running_count = 0
    for day in range(1, observed_days + 1):
        running_total += daily_totals.get(day, ZERO)
        running_count += len(daily.get(day, []))
        cumulative_values.append(float(running_total))
        cumulative_counts.append(running_count)

    def cumulative_at(day):
        return Decimal(str(cumulative_values[day - 1])) if day and cumulative_values else ZERO

    def count_at(day):
        return cumulative_counts[day - 1] if day and cumulative_counts else 0

    def pace_at(day):
        previous_to_day = sum(
            (
                item.amount for item in previous_transactions
                if timezone.localtime(item.transaction_date).day <= min(day, previous_days)
            ),
            ZERO,
        )
        difference = cumulative_at(day) - previous_to_day
        if difference > 0:
            return f"{money(difference)} ahead of {previous_month:%B} pace"
        if difference < 0:
            return f"{money(abs(difference))} behind {previous_month:%B} pace"
        return f"Matching {previous_month:%B} pace"

    def budget_at(day):
        if not budget_summary.get("budget"):
            return "No budget set"
        percent = float(cumulative_at(day) / budget_summary["budget"].amount * 100)
        return f"{percent:.1f}% of budget"

    milestones = []

    def add_milestone(key, day, value, label, story_title, story_value, narrative, context):
        if day is None:
            return
        milestones.append({
            "key": key,
            "day": day,
            "date": month.replace(day=day).strftime("%b %-d"),
            "position": round((day - 1) / max(days_in_month - 1, 1) * 100, 1),
            "value": value,
            "label": label,
            "story_title": story_title,
            "story_value": story_value,
            "narrative": narrative,
            "context": context,
            "metrics": [
                {"label": "By this point", "value": f"{money(cumulative_at(day))} spent"},
                {"label": "Payments so far", "value": str(count_at(day))},
                {"label": "Budget used", "value": budget_at(day)},
                {"label": "Previous-month pace", "value": pace_at(day)},
            ],
        })

    if biggest_day:
        day_share = float(daily_totals[biggest_day] / total * 100) if total else 0
        typical_multiple = float(daily_totals[biggest_day] / typical_spending_day) if typical_spending_day else 0
        add_milestone(
            "biggest-day",
            biggest_day,
            f"{money(daily_totals[biggest_day])} spent",
            "Biggest spending day",
            "Your biggest spending day",
            money(daily_totals[biggest_day]),
            f"{day_share:.1f}% of your entire month's spending happened on this day.",
            f"{typical_multiple:.1f}× your typical spending day",
        )
    if busiest_day:
        busiest_count = len(daily[busiest_day])
        payment_label = f"{busiest_count} payment{'s' if busiest_count != 1 else ''}"
        add_milestone(
            "busiest-day",
            busiest_day,
            payment_label,
            "Busiest transaction day",
            "Your busiest transaction day",
            payment_label,
            f"{payment_label} happened on this day, adding {money(daily_totals[busiest_day])} to monthly spending.",
            f"{count_at(busiest_day)} payment{'s' if count_at(busiest_day) != 1 else ''} had been made by this point",
        )
    cumulative = ZERO
    passed_day = None
    if previous_total and total > previous_total:
        for day in sorted(daily_totals):
            cumulative += daily_totals[day]
            if cumulative > previous_total:
                passed_day = day
                break
    if passed_day:
        add_milestone(
            "passed-previous",
            passed_day,
            f"Passed {previous_month:%B}",
            f"Spending moved above {money(previous_total)}",
            f"You passed {previous_month:%B}'s total",
            money(cumulative_at(passed_day)),
            f"Cumulative spending moved above {previous_month:%B}'s {money(previous_total)} total on this day.",
            f"This happened on day {passed_day} of the month",
        )
    if latest_day:
        add_milestone(
            "month-total",
            latest_day,
            f"{money(total)} total",
            "Latest recorded total",
            "Your latest monthly total",
            money(total),
            f"By {month.replace(day=latest_day):%b %-d}, recorded spending had reached {money(total)}.",
            f"Across {count} payment{'s' if count != 1 else ''}",
        )
    first_week_total = sum((daily_totals.get(day, ZERO) for day in range(1, min(7, observed_days) + 1)), ZERO)
    first_week_share = round(float(first_week_total / total * 100), 1) if total else 0
    no_spend_days = [day for day in range(1, observed_days + 1) if day not in daily]
    longest_no_spend_streak = 0
    current_streak = 0
    for day in range(1, observed_days + 1):
        if day in daily:
            current_streak = 0
        else:
            current_streak += 1
            longest_no_spend_streak = max(longest_no_spend_streak, current_streak)

    habits = [
        {
            "key": "no-spend-days",
            "value": str(len(no_spend_days)),
            "label": "No-spend days",
            "detail": f"{len(no_spend_days)} of {observed_days} observed days had no payments.",
        },
        {
            "key": "biggest-day",
            "value": money(daily_totals[biggest_day]) if biggest_day else "No spending",
            "label": "Biggest day",
            "detail": f"{month.replace(day=biggest_day):%b %-d} was {float(daily_totals[biggest_day] / typical_spending_day):.1f}× a typical spending day." if biggest_day and typical_spending_day else "No payments were recorded.",
        },
        {
            "key": "first-week",
            "value": f"{first_week_share:g}%",
            "label": "Spent in the first week",
            "detail": f"{money(first_week_total)} of {money(total)} was spent from {month:%b} 1 to {month:%b} 7.",
        },
    ]

    trend_months = [month_offset(month, offset) for offset in range(-11, 1)]
    trend_labels = []
    trend_values = []
    trend_counts = []
    trend_averages = []
    for trend_month in trend_months:
        aggregate = _transactions_for_month(user, trend_month, today=today).aggregate(
            total=Sum("amount"),
            count=Count("id"),
            average=Avg("amount"),
        )
        trend_labels.append(trend_month.strftime("%b %Y"))
        trend_values.append(float(aggregate["total"] or ZERO))
        trend_counts.append(aggregate["count"] or 0)
        trend_averages.append(float(aggregate["average"] or ZERO))
    recorded_six_month_values = [value for value in trend_values[-6:] if value > 0]
    six_month_average = (
        sum(recorded_six_month_values) / len(recorded_six_month_values)
        if recorded_six_month_values
        else 0
    )
    six_month_multiple = round(float(total) / six_month_average, 1) if six_month_average else None

    previous_six_values = [value for value in trend_values[-7:-1] if value > 0]
    previous_six_average = (
        sum(previous_six_values) / len(previous_six_values)
        if previous_six_values
        else 0
    )
    previous_month_difference = total - previous_total
    best_previous_value = max(trend_values[:-1], default=0)
    best_previous_index = trend_values[:-1].index(best_previous_value) if best_previous_value else None
    best_previous_label = trend_labels[best_previous_index] if best_previous_index is not None else "previous months"
    best_previous_difference = float(total) - best_previous_value

    def difference_title(reference_name, difference, percent=None):
        if percent is not None:
            if percent > 0:
                return f"{month:%B} was {abs(percent):g}% higher"
            if percent < 0:
                return f"{month:%B} was {abs(percent):g}% lower"
            return f"{month:%B} matched {reference_name}"
        if difference > 0:
            return f"{month:%B} was {money(difference)} higher"
        if difference < 0:
            return f"{month:%B} was {money(abs(difference))} lower"
        return f"{month:%B} matched {reference_name}"

    comparisons = [
        {
            "key": "previous",
            "label": previous_month.strftime("%B"),
            "title": difference_title(previous_month.strftime("%B"), previous_month_difference, change),
            "copy": f"{money(total)} compared with {money(previous_total)} in {previous_month:%B}.",
        },
        {
            "key": "six-average",
            "label": "6-month average",
            "title": (
                f"{month:%B} was {float(total) / previous_six_average:.1f}× your usual spending"
                if previous_six_average
                else "More history is needed"
            ),
            "copy": (
                f"{money(total)} compared with a {money(previous_six_average)} average across recorded prior months."
                if previous_six_average
                else "There are not enough earlier recorded months for this comparison."
            ),
        },
        {
            "key": "best-previous",
            "label": "Highest previous month",
            "title": difference_title(best_previous_label, Decimal(str(best_previous_difference))),
            "copy": (
                f"{money(total)} compared with {money(best_previous_value)} in {best_previous_label}."
                if best_previous_value
                else "No earlier recorded month is available for comparison."
            ),
        },
    ]

    review_interactions = {
        "month": month.strftime("%B %Y"),
        "days_in_month": days_in_month,
        "observed_days": observed_days,
        "first_weekday": month.weekday(),
        "spent_days": sorted(daily),
        "no_spend_days": no_spend_days,
        "cumulative_labels": list(range(1, observed_days + 1)),
        "cumulative_values": cumulative_values,
        "comparisons": comparisons,
        "details": {
            habit["key"]: {"title": habit["label"], "copy": habit["detail"]}
            for habit in habits
        },
    }
    review_interactions["details"]["no-spend-days"].update({
        "kind": "calendar",
        "longest_streak": longest_no_spend_streak,
    })
    review_interactions["details"]["biggest-day"].update({
        "kind": "biggest-day",
        "biggest_amount": float(daily_totals.get(biggest_day, ZERO)),
        "typical_amount": float(typical_spending_day),
    })
    review_interactions["details"]["first-week"].update({
        "kind": "first-week",
        "first_amount": float(first_week_total),
        "rest_amount": float(total - first_week_total),
        "first_share": first_week_share,
        "rest_share": round(100 - first_week_share, 1),
    })
    return {
        "headline": headline,
        "headline_total": total,
        "comparison_text": comparison_text,
        "budget_text": budget_text,
        "budget_used_percent": budget_summary.get("used_percent"),
        "payment_count": count,
        "average_payment": average,
        "milestones": milestones,
        "habits": habits,
        "comparisons": comparisons,
        "trend": {
            "labels": trend_labels,
            "values": trend_values,
            "counts": trend_counts,
            "averages": trend_averages,
            "six_month_average": six_month_average,
            "six_month_multiple": six_month_multiple,
        },
        "recap": [
            {
                "title": "Spending was concentrated early" if first_week_share >= 50 else "Spending was spread through the month",
                "copy": f"{first_week_share:g}% of spending happened in the first week.",
            },
            {
                "title": "You stayed within budget" if budget_summary.get("budget") and budget_summary["used_percent"] <= 100 else "Budget context",
                "copy": (
                    f"You used {budget_summary['used_percent']:.1f}% of your {money(budget_summary['budget'].amount)} budget."
                    if budget_summary.get("budget")
                    else "Set a monthly budget to add budget context to future reviews."
                ),
            },
        ],
        "interactions": review_interactions,
    }


def get_alert_summary(user):
    queryset = Alert.objects.filter(user=user)
    counts = {row["status"]: row["count"] for row in queryset.values("status").annotate(count=Count("id"))}
    return {"active": counts.get(Alert.Status.ACTIVE, 0), "total": queryset.count()}
