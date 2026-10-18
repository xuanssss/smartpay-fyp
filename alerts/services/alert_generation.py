from datetime import timedelta
from decimal import Decimal
from statistics import mean, stdev
from time import perf_counter

from django.db.models import Avg, Sum

from alerts.models import Alert
from analytics.models import PerformanceLog
from payments.models import Transaction


def _add_alert(transaction, alert_type, severity, title, message, explanation):
    return Alert.objects.create(
        user=transaction.user,
        transaction=transaction,
        alert_type=alert_type,
        severity=severity,
        title=title,
        message=message,
        explanation=explanation,
    )


def generate_alerts(transaction):
    """Run explainable awareness rules for one newly-created simulated payment."""
    started = perf_counter()
    created = []
    prior = Transaction.objects.filter(user=transaction.user).exclude(pk=transaction.pk)
    merchant_prior = prior.filter(merchant_name__iexact=transaction.merchant_name)

    nearby = merchant_prior.filter(
        transaction_date__gte=transaction.transaction_date - timedelta(minutes=5),
        transaction_date__lte=transaction.transaction_date + timedelta(minutes=5),
    )
    for other in nearby:
        baseline = abs(other.amount) or Decimal("0.01")
        if abs(transaction.amount - other.amount) / baseline < Decimal("0.05"):
            created.append(_add_alert(
                transaction, Alert.AlertType.DUPLICATE, Alert.Severity.HIGH,
                "Possible duplicate payment",
                f"You made two similar payments to {transaction.merchant_name} within 5 minutes.",
                "This alert was generated because the same merchant appeared twice in a short time window and the amounts were very similar. This may be worth reviewing.",
            ))
            break

    historical_amounts = [float(value) for value in merchant_prior.values_list("amount", flat=True)]
    if len(historical_amounts) >= 3:
        deviation = stdev(historical_amounts)
        if deviation > 0 and float(transaction.amount) > mean(historical_amounts) + 2 * deviation:
            created.append(_add_alert(
                transaction, Alert.AlertType.UNUSUAL_AMOUNT, Alert.Severity.MEDIUM,
                "Unusual bill amount",
                f"This {transaction.merchant_name} payment is higher than your usual amount.",
                "The amount is more than two standard deviations above your previous payments to this merchant. This may be worth reviewing.",
            ))

    user_average = prior.aggregate(value=Avg("amount"))["value"]
    if not merchant_prior.exists() and user_average and transaction.amount > user_average * 2:
        created.append(_add_alert(
            transaction, Alert.AlertType.UNFAMILIAR_HIGH_VALUE, Alert.Severity.HIGH,
            "Unfamiliar high-value merchant",
            f"This is your first recorded payment to {transaction.merchant_name}, and the amount is higher than usual.",
            "The merchant has not appeared in your history and the amount is more than twice your average transaction. This may be worth reviewing.",
        ))

    month_start = transaction.transaction_date.date().replace(day=1)
    if month_start.month == 1:
        previous_start = month_start.replace(year=month_start.year - 1, month=12)
    else:
        previous_start = month_start.replace(month=month_start.month - 1)
    current_total = Transaction.objects.filter(
        user=transaction.user, final_category=transaction.final_category,
        transaction_date__year=month_start.year, transaction_date__month=month_start.month,
    ).aggregate(value=Sum("amount"))["value"] or Decimal("0")
    previous_total = Transaction.objects.filter(
        user=transaction.user, final_category=transaction.final_category,
        transaction_date__year=previous_start.year, transaction_date__month=previous_start.month,
    ).aggregate(value=Sum("amount"))["value"] or Decimal("0")
    category_title = f"High {transaction.final_category.name} spending"
    already_flagged = Alert.objects.filter(
        user=transaction.user, alert_type=Alert.AlertType.HIGH_CATEGORY,
        title=category_title, transaction__transaction_date__year=month_start.year,
        transaction__transaction_date__month=month_start.month,
    ).exists()
    if previous_total > 0 and current_total > previous_total * Decimal("1.50") and not already_flagged:
        created.append(_add_alert(
            transaction, Alert.AlertType.HIGH_CATEGORY, Alert.Severity.MEDIUM,
            category_title,
            f"Your {transaction.final_category.name} spending is over 50% higher than last month.",
            "This insight compares your current category total with the previous month. An increase is not necessarily a problem, but may be worth reviewing.",
        ))

    PerformanceLog.objects.create(
        user=transaction.user,
        operation_name=PerformanceLog.Operation.ALERT_GENERATION,
        duration_ms=(perf_counter() - started) * 1000,
    )
    return created
