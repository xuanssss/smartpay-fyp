from collections import defaultdict
from decimal import Decimal

import numpy as np
from django.db import transaction as db_transaction
from django.utils import timezone

from analytics.models import RecurringBill


def refresh_recurring_bills(user):
    """Detect monthly-like bills and keep the user's summary table in sync."""
    grouped = defaultdict(list)
    transactions = user.transactions.select_related("final_category").order_by("transaction_date")
    for item in transactions:
        grouped[item.merchant_name.strip().casefold()].append(item)

    detected_keys = set()
    with db_transaction.atomic():
        for _, items in grouped.items():
            distinct_months = {(item.transaction_date.year, item.transaction_date.month) for item in items}
            if len(items) < 3 or len(distinct_months) < 3:
                continue
            amounts = np.array([float(item.amount) for item in items], dtype=float)
            average = float(amounts.mean())
            # TODO-FYP-TWEAK: Change the 20% amount-variation tolerance for recurring bills.
            if average <= 0 or float(amounts.std()) / average > 0.20:
                continue
            latest = max(items, key=lambda item: item.transaction_date)
            canonical_name = items[0].merchant_name.strip()
            detected_keys.add(canonical_name.casefold())
            RecurringBill.objects.update_or_create(
                user=user,
                merchant_name=canonical_name,
                defaults={
                    "category": latest.final_category,
                    "average_amount": Decimal(str(round(average, 2))),
                    "frequency_label": "Monthly",
                    "transaction_count": len(items),
                    "last_detected_at": timezone.now(),
                },
            )
        for bill in RecurringBill.objects.filter(user=user):
            if bill.merchant_name.casefold() not in detected_keys:
                bill.delete()
    return RecurringBill.objects.filter(user=user).select_related("category")
