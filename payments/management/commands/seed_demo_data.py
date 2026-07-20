import random
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.utils import timezone

from alerts.services.alert_generation import generate_alerts
from analytics.services.recurring import refresh_recurring_bills
from payments.models import Category, MerchantRule, Transaction
from payments.services.categorisation import categorise_transaction


# TODO-FYP-TWEAK: Edit the category list and descriptions for the final taxonomy.
CATEGORIES = {
    "Food & Dining": "Meals, drinks, food courts, and delivery.",
    "Transport": "Public transport, taxis, and ride services.",
    "Shopping": "Retail, online purchases, and groceries.",
    "Utilities": "Electricity, water, broadband, and phone bills.",
    "Subscriptions": "Recurring digital and membership services.",
    "Education": "Courses, school fees, and learning materials.",
    "Healthcare": "Pharmacy, clinic, and healthcare spending.",
    "Housing / Rent": "Rent, housing fees, and property costs.",
    "Entertainment": "Movies, events, attractions, and leisure.",
    "Others": "Payments without a strong category match.",
}


# TODO-FYP-TWEAK: Extend merchant rules and explanations using study findings.
MERCHANT_RULES = [
    ("grab ride", "Transport", 0.88, "Merchant wording indicates a Grab ride or transport payment."),
    ("grab taxi", "Transport", 0.88, "Merchant wording indicates a Grab ride or transport payment."),
    ("grab transport", "Transport", 0.88, "Merchant wording indicates a Grab ride or transport payment."),
    ("grab food", "Food & Dining", 0.88, "Merchant wording indicates a Grab food or delivery payment."),
    ("grab eat", "Food & Dining", 0.88, "Merchant wording indicates a Grab food or delivery payment."),
    ("grab delivery", "Food & Dining", 0.88, "Merchant wording indicates a Grab food or delivery payment."),
    ("Foodpanda", "Food & Dining", 0.95, "Merchant name matches a known food delivery provider."),
    ("Deliveroo", "Food & Dining", 0.95, "Merchant name matches a known food delivery provider."),
    ("McDonald's", "Food & Dining", 0.95, "Merchant name matches a known food and dining provider."),
    ("Koufu", "Food & Dining", 0.95, "Merchant name matches a known food and dining provider."),
    ("Starbucks", "Food & Dining", 0.95, "Merchant name matches a known food and dining provider."),
    ("ComfortDelGro", "Transport", 0.95, "Merchant name matches a known transport provider."),
    ("Gojek", "Transport", 0.95, "Merchant name matches a known transport provider."),
    ("MRT", "Transport", 0.95, "Merchant name matches a known public transport provider."),
    ("SimplyGo", "Transport", 0.95, "Merchant name matches a known public transport provider."),
    ("Shopee", "Shopping", 0.95, "Merchant name matches a known shopping provider."),
    ("Lazada", "Shopping", 0.95, "Merchant name matches a known shopping provider."),
    ("Amazon", "Shopping", 0.95, "Merchant name matches a known shopping provider."),
    ("FairPrice", "Shopping", 0.95, "Merchant name matches a known retail or grocery provider."),
    ("SP Group", "Utilities", 0.95, "Merchant name matches a known utility provider."),
    ("Geneco", "Utilities", 0.95, "Merchant name matches a known utility provider."),
    ("Singtel", "Utilities", 0.95, "Merchant name matches a known utility or telco provider."),
    ("StarHub", "Utilities", 0.95, "Merchant name matches a known utility or telco provider."),
    ("M1", "Utilities", 0.95, "Merchant name matches a known utility or telco provider."),
    ("Netflix", "Subscriptions", 0.95, "Merchant name matches a known subscription provider."),
    ("Spotify", "Subscriptions", 0.95, "Merchant name matches a known subscription provider."),
    ("Disney+", "Subscriptions", 0.95, "Merchant name matches a known subscription provider."),
    ("YouTube Premium", "Subscriptions", 0.95, "Merchant name matches a known subscription provider."),
    ("SMU", "Education", 0.95, "Merchant name matches a known education provider."),
    ("Coursera", "Education", 0.95, "Merchant name matches a known education provider."),
    ("Udemy", "Education", 0.95, "Merchant name matches a known education provider."),
    ("Guardian", "Healthcare", 0.95, "Merchant name matches a known healthcare retailer."),
    ("Watsons", "Healthcare", 0.95, "Merchant name matches a known healthcare retailer."),
    ("Rent", "Housing / Rent", 0.95, "Merchant wording indicates a housing or rent payment."),
    ("Landlord", "Housing / Rent", 0.95, "Merchant wording indicates a housing or rent payment."),
    ("Cathay", "Entertainment", 0.95, "Merchant name matches a known entertainment provider."),
    ("Golden Village", "Entertainment", 0.95, "Merchant name matches a known entertainment provider."),
]


class Command(BaseCommand):
    help = "Create categories, rules, the demo account, and presentation-ready sample transactions."

    @db_transaction.atomic
    def handle(self, *args, **options):
        random.seed(42)
        categories = {
            name: Category.objects.update_or_create(name=name, defaults={"description": description})[0]
            for name, description in CATEGORIES.items()
        }
        for keyword, category_name, confidence, explanation in MERCHANT_RULES:
            MerchantRule.objects.update_or_create(
                keyword=keyword,
                defaults={
                    "category": categories[category_name],
                    "confidence_score": confidence,
                    "explanation_template": explanation,
                },
            )

        User = get_user_model()
        user, _ = User.objects.get_or_create(username="demo", defaults={"email": "demo@example.com"})
        user.email = "demo@example.com"
        user.set_password("demo12345")
        user.save()
        user.transactions.all().delete()

        now = timezone.localtime().replace(second=0, microsecond=0)
        month_starts = [self._shift_month(now, offset) for offset in (-2, -1, 0)]
        recurring = [
            ("Netflix", "Subscription", [15.98, 15.98, 15.98]),
            ("SP Group", "Bill", [96.20, 101.40, 99.80]),
            ("Singtel", "Bill", [48.00, 48.00, 48.00]),
            ("Landlord", "Housing", [850.00, 850.00, 850.00]),
        ]
        variable = [
            ("Foodpanda", "Food", 18, 45), ("Koufu", "Food", 5, 14),
            ("Starbucks", "Food", 6, 16), ("ComfortDelGro", "Transport", 12, 38),
            ("SimplyGo", "Transport", 3, 12), ("Shopee", "Shopping", 18, 95),
            ("FairPrice", "Shopping", 25, 85), ("Guardian", "Healthcare", 10, 55),
            ("Spotify", "Subscription", 10, 13), ("Coursera", "Education", 25, 80),
            ("Watsons", "Healthcare", 8, 45), ("Golden Village", "Entertainment", 12, 30),
            ("McDonald's", "Food", 7, 22), ("Gojek", "Transport", 10, 30),
            ("Lazada", "Shopping", 15, 80), ("Cathay", "Entertainment", 12, 28),
        ]

        # TODO-FYP-TWEAK: Replace or expand these generated sample transactions for your evaluation scenarios.
        for month_index, month_start in enumerate(month_starts):
            for merchant, payment_type, amounts in recurring:
                self._create(user, merchant, Decimal(str(amounts[month_index])), payment_type, month_start + timedelta(days=2, hours=9))
            for index, (merchant, payment_type, low, high) in enumerate(variable):
                amount = Decimal(str(round(random.uniform(low, high), 2)))
                happened = month_start + timedelta(days=4 + index, hours=10 + index % 8, minutes=index * 2)
                self._create(user, merchant, amount, payment_type, happened)

        # Explicit alert scenarios in the current month.
        duplicate_time = month_starts[-1] + timedelta(days=22, hours=18)
        self._create(user, "SP Group", Decimal("102.00"), "Bill", duplicate_time)
        self._create(user, "SP Group", Decimal("101.50"), "Bill", duplicate_time + timedelta(minutes=3))
        self._create(user, "SP Group", Decimal("350.00"), "Bill", month_starts[-1] + timedelta(days=23, hours=9))
        self._create(user, "Orchard Bespoke Tech", Decimal("1250.00"), "Others", month_starts[-1] + timedelta(days=24, hours=14))

        # Raise current Entertainment spending relative to the previous month.
        for day in range(20, 25):
            self._create(user, "Cathay", Decimal("42.00"), "Entertainment", month_starts[-1] + timedelta(days=day, hours=20))

        bills = refresh_recurring_bills(user)
        count = Transaction.objects.filter(user=user).count()
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {count} transactions, {bills.count()} recurring bills, and {user.alerts.count()} alerts."
        ))
        self.stdout.write("Demo login: demo / demo12345")

    @staticmethod
    def _shift_month(value, offset):
        month_index = value.year * 12 + value.month - 1 + offset
        year, month_zero = divmod(month_index, 12)
        return value.replace(year=year, month=month_zero + 1, day=1, hour=0, minute=0)

    @staticmethod
    def _create(user, merchant, amount, payment_type, happened):
        result = categorise_transaction(merchant, payment_type, "Demo transaction")
        item = Transaction.objects.create(
            user=user,
            merchant_name=merchant,
            amount=amount,
            transaction_date=happened,
            payment_type=payment_type,
            note="Demo transaction",
            predicted_category=result.category,
            final_category=result.category,
            confidence_score=result.confidence,
            category_explanation=result.explanation,
        )
        generate_alerts(item)
        return item
