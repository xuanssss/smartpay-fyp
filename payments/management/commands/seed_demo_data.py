import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.utils import timezone
from django.utils.text import slugify

from alerts.services.alert_generation import generate_alerts
from analytics.models import MonthlyBudget
from payments.models import (
    BrowseCategory,
    CatalogueItem,
    Category,
    PaymentMethod,
    Transaction,
)
from payments.services.catalog import payment_type_for_item
from payments.services.categorisation import categorise_transaction
from payments.services.payment_processing import bank_transaction_type_for_payment
from payments.taxonomy import PURCHASE_CATEGORY_DESCRIPTIONS


# Financial categories use the reviewed purchase-only application taxonomy.
CATEGORIES = PURCHASE_CATEGORY_DESCRIPTIONS


# A browse category is navigation only and is intentionally separate from the
# financial Category prediction.
BROWSE_CATEGORIES = [
    ("Food", "food-drinks", "Meals and drinks", "🍜"),
    ("Transport", "transport", "Trips and transport value", "🚆"),
    ("Groceries", "groceries", "Everyday grocery items", "🛒"),
    ("Bills", "bills", "Household and communication bills", "💡"),
    ("Subscriptions", "subscriptions", "Digital memberships", "▣"),
    ("Education", "education", "Courses and learning costs", "▤"),
    ("Healthcare", "healthcare", "Health products and services", "✚"),
    ("Housing", "home", "Housing and household services", "⌂"),
    ("Entertainment", "entertainment", "Movies, events, and games", "☆"),
    ("Shopping", "shopping", "Retail and personal items", "◫"),
    ("Other", "other", "Miscellaneous payments and services", ""),
]


# name, merchant, raw transaction description, price, financial ground truth,
# allows quantity, icon. There are five items in every browse category.
CATALOGUE_ITEMS = {
    "food-drinks": [
        ("Chicken Rice", "Koufu", "CHICKEN RICE MEAL", "5.80", "Dining", True, "🍚"),
        ("Nasi Lemak", "Koufu", "NASI LEMAK MEAL", "6.20", "Dining", True, "🍛"),
        ("Kaya Toast Set", "Koufu", "KAYA TOAST BREAKFAST", "4.90", "Dining", True, "🍞"),
        ("Bubble Tea", "Foodpanda", "BUBBLE TEA DELIVERY", "4.50", "Dining", True, "🧋"),
        ("Iced Latte", "Starbucks", "ICED LATTE DRINK", "7.30", "Dining", True, "☕"),
    ],
    "transport": [
        ("MRT Trip", "SimplyGo", "MRT TRIP", "2.20", "Public Transport", True, "🚆"),
        ("Bus Trip", "SimplyGo", "BUS TRIP", "1.80", "Public Transport", True, "🚌"),
        ("Taxi Ride", "ComfortDelGro", "TAXI RIDE", "18.00", "Private Hire & Taxis", False, "🚕"),
        ("Private-hire Ride", "Gojek", "PRIVATE-HIRE RIDE", "16.00", "Private Hire & Taxis", False, "🚗"),
        ("Transport Top-up", "SimplyGo", "TRANSPORT TOP-UP", "20.00", "Public Transport", False, "＋"),
    ],
    "groceries": [
        ("Fresh Eggs", "FairPrice", "FRESH EGGS GROCERIES", "3.80", "Groceries", True, "🥚"),
        ("Fresh Milk", "FairPrice", "FRESH MILK GROCERIES", "3.20", "Groceries", True, "🥛"),
        ("Wholemeal Bread", "FairPrice", "WHOLEMEAL BREAD GROCERIES", "2.90", "Groceries", True, "🍞"),
        ("Cooking Oil", "FairPrice", "COOKING OIL GROCERIES", "7.90", "Groceries", True, "◉"),
        ("Laundry Detergent", "FairPrice", "LAUNDRY DETERGENT HOUSEHOLD", "12.80", "Groceries", True, "◇"),
    ],
    "bills": [
        ("Electricity Bill", "SP Group", "MONTHLY ELECTRICITY BILL", "98.00", "Bills", False, "⚡"),
        ("Water Bill", "SP Group", "MONTHLY WATER BILL", "36.00", "Bills", False, "💧"),
        ("Mobile Phone Bill", "Singtel", "MONTHLY MOBILE PHONE BILL", "48.00", "Bills", False, "▯"),
        ("Internet Bill", "StarHub", "MONTHLY INTERNET BILL", "52.00", "Bills", False, "◎"),
        ("Green Energy Bill", "Geneco", "MONTHLY ELECTRICITY BILL", "92.00", "Bills", False, "♻"),
    ],
    "subscriptions": [
        ("Streaming Subscription", "Netflix", "MONTHLY STREAMING SUBSCRIPTION", "15.98", "Entertainment", False, "▶"),
        ("Music Subscription", "Spotify", "MONTHLY MUSIC SUBSCRIPTION", "10.98", "Entertainment", False, "♫"),
        ("Family Streaming", "Disney+", "MONTHLY STREAMING SUBSCRIPTION", "14.98", "Entertainment", False, "★"),
        ("Video Premium", "YouTube Premium", "MONTHLY VIDEO SUBSCRIPTION", "13.98", "Entertainment", False, "▷"),
        ("Cloud Storage", "CloudBox", "MONTHLY CLOUD STORAGE SUBSCRIPTION", "4.48", "Services", False, "☁"),
    ],
    "education": [
        ("Online Course", "Coursera", "ONLINE COURSE", "59.00", "Services", True, "▤"),
        ("Skills Course", "Udemy", "ONLINE COURSE", "24.90", "Services", True, "◆"),
        ("University Textbook", "Amazon", "UNIVERSITY TEXTBOOK", "68.00", "Online Shopping", True, "▥"),
        ("Tuition Fee", "SMU", "SEMESTER TUITION FEE", "500.00", "Services", False, "▦"),
        ("Examination Fee", "SMU", "EXAMINATION FEE", "120.00", "Services", False, "✓"),
    ],
    "healthcare": [
        ("Daily Vitamins", "Guardian", "DAILY VITAMINS", "18.90", "Healthcare", True, "✚"),
        ("Cold Medication", "Watsons", "COLD MEDICATION", "12.50", "Healthcare", True, "✣"),
        ("Medical Consultation", "Neighbourhood Clinic", "MEDICAL CONSULTATION", "45.00", "Healthcare", False, "⚕"),
        ("Dental Appointment", "Bright Dental", "DENTAL APPOINTMENT", "85.00", "Healthcare", False, "◌"),
        ("Health Screening", "Wellness Centre", "HEALTH SCREENING", "120.00", "Healthcare", False, "♡"),
    ],
    "home": [
        ("Home Cleaning Plan", "CleanHome", "MONTHLY HOME CLEANING SERVICE", "32.00", "Home Improvement", False, "⌂"),
        ("Aircon Servicing", "CoolCare", "AIRCON SERVICING", "72.00", "Home Improvement", False, "⌁"),
        ("Plumbing Repair", "HomeFix Services", "HOME REPAIR PLUMBING", "90.00", "Home Improvement", False, "⚒"),
        ("Lighting Repair", "HomeFix Services", "HOME REPAIR LIGHTING", "65.00", "Home Improvement", False, "✦"),
        ("Household Organiser", "IKEA Singapore", "HOUSEHOLD ITEM ORGANISER", "32.00", "Home Improvement", True, "◇"),
    ],
    "entertainment": [
        ("Cinema Ticket", "Golden Village", "CINEMA TICKET", "15.00", "Entertainment", True, "🎬"),
        ("Movie Snack Set", "Cathay", "CINEMA SNACK SET", "10.50", "Entertainment", True, "🍿"),
        ("Concert Ticket", "City Events", "CONCERT TICKET", "88.00", "Entertainment", True, "♫"),
        ("Game Purchase", "Game Store", "DIGITAL GAME PURCHASE", "35.00", "Entertainment", True, "◈"),
        ("Attraction Ticket", "Sentosa Fun", "ATTRACTION TICKET", "42.00", "Entertainment", True, "☆"),
    ],
    "shopping": [
        ("Basic T-shirt", "Shopee", "COTTON T-SHIRT", "18.90", "Clothing", True, "▱"),
        ("Running Shoes", "Lazada", "RUNNING SHOES", "69.00", "Clothing", True, "♢"),
        ("Mobile Phone", "Amazon", "MOBILE PHONE", "699.00", "Online Shopping", True, "▯"),
        ("Wireless Headphones", "Shopee", "WIRELESS HEADPHONES", "49.90", "Online Shopping", True, "◉"),
        ("Household Organiser", "Lazada", "HOUSEHOLD ITEM ORGANISER", "16.50", "Home Improvement", True, "▦"),
    ],
    "other": [
        ("Parcel Postage", "SingPost", "PARCEL POSTAGE SERVICE", "4.80", "Services", True, ""),
        ("Printing Service", "Print Hub", "DOCUMENT PRINTING SERVICE", "2.50", "Services", True, ""),
        ("Laundry Service", "WashLab", "LAUNDRY SERVICE", "12.00", "Services", True, ""),
        ("Gift Card", "City Gifts", "GENERAL PURPOSE GIFT CARD", "25.00", "Other", False, ""),
        ("Donation", "Community Fund", "CHARITABLE DONATION", "10.00", "Other", False, ""),
    ],
}


class Command(BaseCommand):
    help = "Create the persistent catalogue, demo methods, and four months of demonstration transactions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--if-missing",
            action="store_true",
            help="Seed only when the demo user does not exist (safe for repeated deployments).",
        )

    @db_transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        if options["if_missing"] and User.objects.filter(username="demo").exists():
            self.stdout.write("Demo data already exists; seed skipped.")
            return

        random.seed(42)
        Category.objects.update(is_active=False)
        categories = {
            name: Category.objects.update_or_create(
                name=name,
                defaults={"description": description, "is_active": True},
            )[0]
            for name, description in CATEGORIES.items()
        }
        browse_categories = {}
        BrowseCategory.objects.update(is_active=False)
        for order, (name, slug, description, _icon) in enumerate(BROWSE_CATEGORIES):
            browse_categories[slug] = BrowseCategory.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "description": description,
                    "icon_name": "",
                    "display_order": order,
                    "is_active": True,
                },
            )[0]

        CatalogueItem.objects.update(is_active=False)
        catalogue = {}
        for browse_slug, item_rows in CATALOGUE_ITEMS.items():
            for order, (name, merchant, description, price, ground_truth, allows_quantity, _icon) in enumerate(item_rows):
                item_slug = f"{browse_slug}-{slugify(name)}"
                catalogue[item_slug] = CatalogueItem.objects.update_or_create(
                    slug=item_slug,
                    defaults={
                        "name": name,
                        "browse_category": browse_categories[browse_slug],
                        "merchant_name": merchant,
                        "transaction_description": description,
                        "short_description": description.title(),
                        "unit_price": Decimal(price),
                        "icon_name": "",
                        "allows_quantity": allows_quantity,
                        "minimum_quantity": 1,
                        "maximum_quantity": 8,
                        "is_active": True,
                        "display_order": order,
                        "ground_truth_category": categories[ground_truth],
                    },
                )[0]

        user, _ = User.objects.get_or_create(username="demo", defaults={"email": "demo@example.com"})
        user.email = "demo@example.com"
        user.set_password("demo12345")
        user.save()
        user.transactions.all().delete()
        user.payment_methods.all().delete()
        user.monthly_budgets.all().delete()

        visa = PaymentMethod.objects.create(
            user=user,
            method_type=PaymentMethod.MethodType.VISA,
            display_name="Visa",
            last_four="4821",
            expiry_month=12,
            expiry_year=timezone.localdate().year + 3,
            is_default=True,
        )
        PaymentMethod.objects.create(
            user=user, method_type=PaymentMethod.MethodType.APPLE_PAY,
            display_name="Apple Pay",
        )
        PaymentMethod.objects.create(
            user=user, method_type=PaymentMethod.MethodType.PAYNOW,
            display_name="PayNow",
        )

        now = timezone.localtime().replace(second=0, microsecond=0)
        month_starts = [self._shift_month(now, offset) for offset in (-3, -2, -1, 0)]
        monthly_service_slugs = [
            "subscriptions-streaming-subscription",
            "bills-electricity-bill",
            "bills-mobile-phone-bill",
            "home-home-cleaning-plan",
        ]
        monthly_service_amounts = {
            "subscriptions-streaming-subscription": ["15.98", "15.98", "15.98", "15.98"],
            "bills-electricity-bill": ["96.20", "101.40", "99.80", "102.00"],
            "bills-mobile-phone-bill": ["48.00", "48.00", "48.00", "48.00"],
            "home-home-cleaning-plan": ["32.00", "32.00", "32.00", "32.00"],
        }
        ordinary_slugs = [
            "food-drinks-chicken-rice", "food-drinks-bubble-tea", "food-drinks-iced-latte",
            "transport-mrt-trip", "transport-bus-trip", "transport-private-hire-ride",
            "groceries-fresh-eggs", "groceries-fresh-milk", "groceries-wholemeal-bread",
            "healthcare-daily-vitamins", "education-online-course",
            "entertainment-cinema-ticket", "shopping-basic-t-shirt", "shopping-wireless-headphones",
        ]

        for month_index, month_start in enumerate(month_starts):
            is_current_month = month_index == len(month_starts) - 1
            for service_index, item_slug in enumerate(monthly_service_slugs):
                happened = (
                    self._current_month_time(month_start, now, service_index)
                    if is_current_month
                    else month_start + timedelta(days=2 + service_index, hours=9)
                )
                self._create(
                    user, visa, catalogue[item_slug],
                    Decimal(monthly_service_amounts[item_slug][month_index]),
                    happened,
                )
            for index, item_slug in enumerate(ordinary_slugs):
                item = catalogue[item_slug]
                quantity = 1 + ((index + month_index) % 2 if item.allows_quantity and index % 4 == 0 else 0)
                amount = item.unit_price * quantity if item.allows_quantity else item.unit_price
                happened = (
                    self._current_month_time(month_start, now, 4 + index)
                    if is_current_month
                    else month_start + timedelta(days=7 + index, hours=10 + index % 8, minutes=index * 2)
                )
                self._create(user, visa, item, amount, happened, quantity=quantity)

        # Explicit current-month awareness scenarios.
        duplicate_time = self._current_month_time(month_starts[-1], now, 20)
        electricity = catalogue["bills-electricity-bill"]
        self._create(user, visa, electricity, Decimal("102.00"), duplicate_time)
        self._create(user, visa, electricity, Decimal("101.50"), duplicate_time + timedelta(minutes=3))
        self._create(
            user, visa, electricity, Decimal("350.00"),
            self._current_month_time(month_starts[-1], now, 22),
        )
        self._create(
            user, visa, None, Decimal("180.00"),
            self._current_month_time(month_starts[-1], now, 23),
            merchant="Orchard Bespoke Tech",
            payment_type=Transaction.PaymentType.OTHERS,
            description="CUSTOM TECHNOLOGY SERVICE",
        )
        self._create(
            user, visa, None, Decimal("34.80"),
            self._current_month_time(month_starts[-1], now, 24),
            merchant="Grab",
            payment_type=Transaction.PaymentType.OTHERS,
            description="GRAB AIRPORT RIDE",
        )

        # Increase current entertainment spending relative to the prior month.
        cinema = catalogue["entertainment-cinema-ticket"]
        for offset in range(5):
            self._create(
                user, visa, cinema, Decimal("45.00"),
                self._current_month_time(month_starts[-1], now, 25 + offset),
                quantity=3,
            )

        MonthlyBudget.objects.update_or_create(
            user=user,
            month=month_starts[0].date(),
            defaults={"amount": Decimal("3000.00")},
        )

        count = Transaction.objects.filter(user=user).count()
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(browse_categories)} browse categories, {len(catalogue)} items, 3 payment methods, "
            f"{count} transactions, and {user.alerts.count()} alerts."
        ))
        self.stdout.write("Demo login: demo / demo12345")

    @staticmethod
    def _shift_month(value, offset):
        month_index = value.year * 12 + value.month - 1 + offset
        year, month_zero = divmod(month_index, 12)
        return value.replace(year=year, month=month_zero + 1, day=1, hour=0, minute=0)

    @staticmethod
    def _current_month_time(month_start, now, slot, total_slots=36):
        """Spread demo payments before now, never into the future."""
        elapsed = now - month_start
        return month_start + elapsed * ((slot + 1) / (total_slots + 1))

    @staticmethod
    def _create(
        user, payment_method, item, amount, happened, quantity=1,
        merchant="", payment_type=Transaction.PaymentType.OTHERS, description="",
    ):
        if item:
            merchant = item.merchant_name
            payment_type = payment_type_for_item(item)
            item_name = item.name
            description = f"{item.merchant_name} {item.name} {item.transaction_description}".upper()
        else:
            item_name = ""
        bank_transaction_type = bank_transaction_type_for_payment(
            payment_method, payment_type
        )
        result = categorise_transaction(
            merchant,
            payment_type,
            "Seeded demo transaction",
            item_name=item_name,
            transaction_description=description,
            amount=amount,
            transaction_date=happened,
            transaction_type=bank_transaction_type,
        )
        transaction = Transaction.objects.create(
            user=user,
            catalogue_item=item,
            item_name=item_name,
            quantity=quantity,
            unit_price=item.unit_price if item and item.allows_quantity else None,
            merchant_name=merchant,
            amount=amount,
            transaction_date=happened,
            payment_type=payment_type,
            bank_transaction_type=bank_transaction_type,
            payment_method=payment_method,
            transaction_description=description,
            note="Seeded demo transaction",
            predicted_category=result.category,
            final_category=result.category,
            confidence_score=result.confidence,
            category_explanation=result.explanation,
            categorisation_source=result.source,
            # Evaluation label only; this was not passed into the classifier.
            ground_truth_category=item.ground_truth_category if item else None,
        )
        generate_alerts(transaction)
        return transaction
