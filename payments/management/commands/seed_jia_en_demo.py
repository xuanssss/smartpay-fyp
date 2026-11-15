import calendar
import os
import random
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction
from django.db.models import Sum
from django.utils import timezone

from alerts.models import Alert
from alerts.services.alert_generation import generate_alerts
from analytics.models import MonthlyBudget
from analytics.services.dashboard import (
    get_budget_summary,
    get_category_breakdown,
    get_category_changes,
)
from payments.models import Category, PaymentMethod, Transaction
from payments.services.categorisation import categorise_transaction
from payments.services.payment_processing import bank_transaction_type_for_payment


USERNAME = "jia_en_demo"
EMAIL = "jia.en.demo@example.com"
PASSWORD_ENVIRONMENT_VARIABLE = "JIA_EN_DEMO_PASSWORD"
AS_OF_ENVIRONMENT_VARIABLE = "JIA_EN_DEMO_AS_OF"
DEMO_NOTE = "Synthetic Jia En presentation data — no real payment."
RANDOM_SEED = 20261115
BUDGET_AMOUNT = Decimal("3000.00")
SUBMISSION_NAMESPACE = uuid.UUID("9c9821b2-1a54-4d41-bc28-e4efc5f6369a")


@dataclass(frozen=True)
class DemoPayment:
    key: str
    merchant: str
    description: str
    amount: Decimal
    happened: datetime
    category_name: str
    payment_type: str
    payment_method: str = "visa"


def _month_start(value, offset=0):
    value = value.replace(day=1)
    month_index = value.year * 12 + value.month - 1 + offset
    year, zero_based_month = divmod(month_index, 12)
    return date(year, zero_based_month + 1, 1)


def _aware(month, day, hour, minute=0):
    last_day = calendar.monthrange(month.year, month.month)[1]
    naive = datetime(month.year, month.month, min(day, last_day), hour, minute)
    return timezone.make_aware(naive, timezone.get_current_timezone())


def _money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _varied_amount(rng, base, adjustments):
    return _money(Decimal(str(base)) + Decimal(str(rng.choice(adjustments))))


def build_demo_plan(as_of):
    """Return deterministic synthetic payments for eleven prior months and this month."""
    rng = random.Random(RANDOM_SEED)
    plan = []

    # Values are ordered May–October 2026 first to preserve the original
    # presentation snapshot, followed by December 2025–April 2026. The final
    # plan is sorted chronologically before it is saved.
    completed_month_offsets = tuple(range(-6, 0)) + tuple(range(-11, -6))
    electricity_amounts = (
        "98.00", "103.00", "101.00", "106.00", "97.00", "102.00",
        "96.00", "99.00", "104.00", "100.00", "105.00",
    )
    singtel_amounts = (
        "39.60", "39.90", "40.10", "39.80", "40.20", "39.90",
        "39.50", "39.50", "39.60", "39.60", "39.60",
    )
    starhub_amounts = (
        "51.90", "52.40", "52.90", "52.70", "53.10", "52.90",
        "51.50", "51.50", "51.90", "51.90", "51.90",
    )
    rent_amounts = (
        "1400.00", "1400.00", "1420.00", "1420.00", "1440.00", "1440.00",
        "1380.00", "1380.00", "1390.00", "1390.00", "1400.00",
    )
    insurance_amounts = (
        "128.60", "128.60", "131.40", "131.40", "135.20", "135.20",
        "125.80", "125.80", "128.60", "128.60", "128.60",
    )
    water_amounts = (
        "34.80", "36.10", "35.40", "37.20", "36.60", "37.40",
        "35.10", "34.60", "36.40", "35.80", "36.20",
    )
    completed_month_one_offs = (
        ("Uniqlo", "UNIQLO WORK WARDROBE", "168.00", "Clothing", Transaction.PaymentType.SHOPPING),
        ("Hotel Boss", "SINGAPORE WEEKEND STAYCATION", "286.00", "Travel & Holidays", Transaction.PaymentType.OTHERS),
        ("Coursera", "ONLINE PROFESSIONAL COURSE", "129.00", "Services", Transaction.PaymentType.EDUCATION),
        ("City Events", "LIVE CONCERT TICKET", "198.00", "Entertainment", Transaction.PaymentType.ENTERTAINMENT),
        ("Decathlon", "RUNNING SHOES AND FITNESS GEAR", "145.00", "Fitness", Transaction.PaymentType.HEALTHCARE),
        ("IKEA Singapore", "HOME OFFICE CHAIR", "229.00", "Home Improvement", Transaction.PaymentType.HOUSING),
        ("Shopee", "YEAR END GIFTS AND HOME ITEMS", "185.00", "Online Shopping", Transaction.PaymentType.SHOPPING),
        ("AirAsia", "CHINESE NEW YEAR FLIGHT BOOKING", "248.00", "Travel & Holidays", Transaction.PaymentType.OTHERS),
        ("Udemy", "ONLINE SKILLS COURSE", "89.00", "Services", Transaction.PaymentType.EDUCATION),
        ("City Events", "LIVE MUSIC EVENT TICKET", "168.00", "Entertainment", Transaction.PaymentType.ENTERTAINMENT),
        ("Decathlon", "RUNNING SHOES", "129.00", "Fitness", Transaction.PaymentType.HEALTHCARE),
    )
    monthly_counts = {
        "dining": (9, 11, 8, 12, 10, 10, 10, 9, 11, 8, 10),
        "groceries": (4, 4, 5, 4, 4, 4, 4, 5, 4, 4, 5),
        "public_transport": (6, 7, 6, 7, 6, 7, 6, 7, 6, 7, 6),
        "private_hire": (2, 2, 1, 2, 2, 2, 2, 2, 1, 2, 2),
        "shopping": (2, 2, 2, 3, 2, 2, 2, 2, 2, 3, 2),
        "healthcare": (1,) * 11,
        "entertainment": (1,) * 11,
    }

    dining = (
        ("Koufu", "Nasi Lemak", "KOUFU NASI LEMAK MEAL", "6.20"),
        ("Kopitiam", "Chicken Rice", "KOPITIAM CHICKEN RICE MEAL", "5.80"),
        ("McDonald's", "Value Meal", "MCDONALDS VALUE MEAL", "8.90"),
        ("Local Hawker Stall", "Mixed Rice", "HAWKER MIXED RICE LUNCH", "5.60"),
        ("Ya Kun Kaya Toast", "Kaya Toast Set", "KAYA TOAST BREAKFAST SET", "5.70"),
        ("Toast Box", "Kopi and Toast", "KOPI AND TOAST BREAKFAST", "6.80"),
        ("Starbucks", "Iced Latte", "ICED LATTE DRINK", "7.30"),
        ("Foodpanda", "Dinner Delivery", "FOOD DELIVERY DINNER", "17.80"),
    )
    groceries = (
        ("NTUC FairPrice", "Weekly groceries", "WEEKLY SUPERMARKET GROCERIES", "38.45"),
        ("Sheng Siong", "Fresh groceries", "FRESH FOOD AND GROCERIES", "31.80"),
        ("NTUC FairPrice", "Household groceries", "HOUSEHOLD AND GROCERY ITEMS", "46.25"),
        ("Sheng Siong", "Fruit and vegetables", "FRUIT VEGETABLES GROCERIES", "27.65"),
    )
    public_transport = (
        ("SimplyGo", "MRT journey", "SIMPLYGO MRT JOURNEY", "2.20"),
        ("SimplyGo", "Bus journey", "SIMPLYGO BUS JOURNEY", "1.89"),
        ("SimplyGo", "MRT journey", "SIMPLYGO MRT JOURNEY", "2.05"),
    )
    private_hire = (
        ("Grab", "Ride home", "GRAB RIDE HOME", "16.40"),
        ("Grab", "Late evening ride", "GRAB TAXI RIDE", "22.80"),
        ("Gojek", "Weekend ride", "GOJEK TRANSPORT RIDE", "14.90"),
    )
    shopping = (
        ("Shopee", "Home accessories", "SHOPEE ONLINE HOME ACCESSORIES", "34.90", "Online Shopping"),
        ("Uniqlo", "Work clothes", "UNIQLO WORK CLOTHES", "48.00", "Clothing"),
        ("Watsons", "Personal care", "WATSONS PERSONAL CARE ITEMS", "23.80", "Shopping"),
        ("Shopee", "Phone accessories", "SHOPEE ONLINE PHONE ACCESSORIES", "26.50", "Online Shopping"),
    )

    def add(
        key,
        month,
        day,
        hour,
        merchant,
        description,
        amount,
        category_name,
        payment_type,
        payment_method="visa",
        minute=0,
    ):
        plan.append(DemoPayment(
            key=key,
            merchant=merchant,
            description=description,
            amount=_money(amount),
            happened=_aware(month, day, hour, minute),
            category_name=category_name,
            payment_type=payment_type,
            payment_method=payment_method,
        ))

    for month_number, offset in enumerate(completed_month_offsets):
        month = _month_start(as_of, offset)
        prefix = month.strftime("%Y-%m")
        add(
            f"{prefix}-super-energy", month, 2, 8, "Super Energy",
            "SUPER ENERGY MONTHLY ELECTRICITY BILL",
            electricity_amounts[month_number], "Bills", Transaction.PaymentType.BILL, "bank",
        )
        add(
            f"{prefix}-singtel", month, 4, 9, "Singtel",
            "SINGTEL MONTHLY MOBILE PHONE BILL",
            singtel_amounts[month_number], "Bills", Transaction.PaymentType.BILL, "bank",
        )
        add(
            f"{prefix}-netflix", month, 6, 7, "Netflix",
            "NETFLIX MONTHLY STREAMING SUBSCRIPTION",
            "15.98", "Entertainment", Transaction.PaymentType.SUBSCRIPTION,
        )
        add(
            f"{prefix}-spotify", month, 7, 7, "Spotify",
            "SPOTIFY MONTHLY MUSIC SUBSCRIPTION",
            "10.98", "Entertainment", Transaction.PaymentType.SUBSCRIPTION,
        )
        add(
            f"{prefix}-fitness-first", month, 9, 18, "Fitness First",
            "FITNESS FIRST MONTHLY GYM MEMBERSHIP",
            "72.00", "Fitness", Transaction.PaymentType.HEALTHCARE,
        )
        add(
            f"{prefix}-starhub", month, 11, 9, "StarHub",
            "STARHUB MONTHLY HOME INTERNET BILL",
            starhub_amounts[month_number], "Bills", Transaction.PaymentType.BILL, "bank",
        )

        group_specs = (
            ("dining", dining, "Dining", Transaction.PaymentType.FOOD, ("-0.40", "-0.20", "0", "0.30", "0.50"), 1),
            ("groceries", groceries, "Groceries", Transaction.PaymentType.SHOPPING, ("-4.20", "-2.10", "0", "1.85", "3.40"), 4),
            ("public_transport", public_transport, "Public Transport", Transaction.PaymentType.TRANSPORT, ("-0.10", "0", "0.10", "0.20"), 7),
            ("private_hire", private_hire, "Private Hire & Taxis", Transaction.PaymentType.TRANSPORT, ("-2.10", "-0.80", "0", "1.30", "2.60"), 10),
        )
        for group_name, templates, category_name, payment_type, adjustments, day_seed in group_specs:
            for index in range(monthly_counts[group_name][month_number]):
                merchant, item_name, description, base_amount = templates[(index + month_number) % len(templates)]
                if group_name == "public_transport" and month_number == 5:
                    # Keep the latest completed month's first-half commuting
                    # comparable with the current partial month.
                    day = (2, 5, 8, 11, 14, 21, 27)[index]
                else:
                    day = 1 + ((index * 7 + month_number * 3 + day_seed) % calendar.monthrange(month.year, month.month)[1])
                add(
                    f"{prefix}-{group_name}-{index + 1}", month, day, 7 + (index * 3) % 15,
                    merchant, f"{description} · {item_name.upper()}",
                    _varied_amount(rng, base_amount, adjustments),
                    category_name, payment_type, "paynow" if group_name == "dining" else "visa",
                    minute=(index * 11 + month_number) % 60,
                )

        for index in range(monthly_counts["shopping"][month_number]):
            merchant, item_name, description, base_amount, category_name = shopping[(index + month_number) % len(shopping)]
            day = 1 + ((index * 11 + month_number * 5 + 13) % calendar.monthrange(month.year, month.month)[1])
            add(
                f"{prefix}-shopping-{index + 1}", month, day, 12 + index * 3,
                merchant, f"{description} · {item_name.upper()}",
                _varied_amount(rng, base_amount, ("-3.00", "-1.20", "0", "2.90", "5.00")),
                category_name, Transaction.PaymentType.SHOPPING,
                minute=(month_number * 7 + index * 13) % 60,
            )

        add(
            f"{prefix}-healthcare", month, 16 + month_number, 18, "Guardian",
            "GUARDIAN VITAMINS AND PERSONAL HEALTH ITEMS",
            _varied_amount(rng, "18.90", ("-2.20", "-0.80", "0", "1.50", "3.10")),
            "Healthcare", Transaction.PaymentType.HEALTHCARE,
        )
        add(
            f"{prefix}-cinema", month, 20 + month_number, 20, "Golden Village",
            "GOLDEN VILLAGE CINEMA TICKET",
            _varied_amount(rng, "15.00", ("0", "0", "3.00", "7.00")),
            "Entertainment", Transaction.PaymentType.ENTERTAINMENT,
        )
        add(
            f"{prefix}-water", month, 3, 8, "Super Water",
            "MONTHLY HOUSEHOLD WATER BILL", water_amounts[month_number],
            "Bills", Transaction.PaymentType.BILL, "bank",
        )
        add(
            f"{prefix}-extra-dining-1", month, 5, 19, "Kopitiam",
            "DINNER WITH COLLEAGUES", _money(Decimal("14.80") + month_number),
            "Dining", Transaction.PaymentType.FOOD, "paynow",
        )
        add(
            f"{prefix}-extra-groceries", month, 10, 18, "NTUC FairPrice",
            "FORTNIGHTLY SUPERMARKET GROCERIES", _money(Decimal("58.80") + month_number),
            "Groceries", Transaction.PaymentType.SHOPPING,
        )
        add(
            f"{prefix}-extra-dining-2", month, 15, 20, "Foodpanda",
            "WEEKEND FOOD DELIVERY", _money(Decimal("21.40") + month_number),
            "Dining", Transaction.PaymentType.FOOD,
        )
        add(
            f"{prefix}-haircut", month, 18, 18, "K Cuts",
            "HAIRCUT AND PERSONAL SERVICE", _money(Decimal("40.00") + month_number),
            "Services", Transaction.PaymentType.OTHERS,
        )
        add(
            f"{prefix}-insurance", month, 20, 9, "Income Insurance",
            "MONTHLY HEALTH INSURANCE PREMIUM", insurance_amounts[month_number],
            "Insurance", Transaction.PaymentType.BILL, "bank",
        )
        merchant, description, amount, category_name, payment_type = completed_month_one_offs[month_number]
        add(
            f"{prefix}-monthly-one-off", month, 22, 19, merchant, description,
            amount, category_name, payment_type,
        )
        add(
            f"{prefix}-dental", month, 24, 17, "Bright Dental",
            "DENTAL CHECKUP AND CLEANING", _money(Decimal("75.00") + month_number),
            "Healthcare", Transaction.PaymentType.HEALTHCARE,
        )
        add(
            f"{prefix}-rent", month, 25, 9, "HDB Room Rental",
            "MONTHLY SHARED ROOM RENT", rent_amounts[month_number],
            "Housing", Transaction.PaymentType.HOUSING, "bank",
        )

    current = _month_start(as_of)
    prefix = current.strftime("%Y-%m")
    current_rows = (
        ("netflix", 1, 7, 0, "Netflix", "NETFLIX MONTHLY STREAMING SUBSCRIPTION", "15.98", "Entertainment", Transaction.PaymentType.SUBSCRIPTION, "visa"),
        ("spotify", 1, 7, 5, "Spotify", "SPOTIFY MONTHLY MUSIC SUBSCRIPTION", "10.98", "Entertainment", Transaction.PaymentType.SUBSCRIPTION, "visa"),
        ("mrt-1", 2, 8, 12, "SimplyGo", "SIMPLYGO MRT JOURNEY", "2.20", "Public Transport", Transaction.PaymentType.TRANSPORT, "visa"),
        ("fairprice", 3, 19, 10, "NTUC FairPrice", "WEEKLY SUPERMARKET GROCERIES", "32.75", "Groceries", Transaction.PaymentType.SHOPPING, "visa"),
        ("koufu", 4, 12, 20, "Koufu", "KOUFU NASI LEMAK MEAL", "6.20", "Dining", Transaction.PaymentType.FOOD, "paynow"),
        ("grab-1", 4, 22, 15, "Grab", "GRAB RIDE HOME", "18.40", "Private Hire & Taxis", Transaction.PaymentType.TRANSPORT, "visa"),
        ("fitness-first", 5, 18, 0, "Fitness First", "FITNESS FIRST MONTHLY GYM MEMBERSHIP", "72.00", "Fitness", Transaction.PaymentType.HEALTHCARE, "visa"),
        ("hawker", 5, 12, 35, "Local Hawker Stall", "HAWKER MIXED RICE LUNCH", "5.80", "Dining", Transaction.PaymentType.FOOD, "paynow"),
        ("mrt-2", 6, 8, 8, "SimplyGo", "SIMPLYGO MRT JOURNEY", "2.05", "Public Transport", Transaction.PaymentType.TRANSPORT, "visa"),
        ("shopee-1", 6, 20, 20, "Shopee", "SHOPEE ONLINE WIRELESS HEADPHONES", "49.90", "Online Shopping", Transaction.PaymentType.SHOPPING, "visa"),
        ("singtel-first", 7, 9, 0, "Singtel", "SINGTEL MONTHLY MOBILE PHONE BILL", "39.90", "Bills", Transaction.PaymentType.BILL, "bank"),
        ("singtel-duplicate", 7, 9, 2, "Singtel", "SINGTEL MONTHLY MOBILE PHONE BILL", "39.90", "Bills", Transaction.PaymentType.BILL, "bank"),
        ("mcdonalds", 8, 19, 5, "McDonald's", "MCDONALDS DINNER VALUE MEAL", "9.80", "Dining", Transaction.PaymentType.FOOD, "paynow"),
        ("sheng-siong", 8, 20, 15, "Sheng Siong", "FRESH FOOD AND GROCERIES", "28.45", "Groceries", Transaction.PaymentType.SHOPPING, "visa"),
        ("cinema", 9, 20, 30, "Golden Village", "GOLDEN VILLAGE CINEMA TICKET", "15.00", "Entertainment", Transaction.PaymentType.ENTERTAINMENT, "visa"),
        ("bus-1", 9, 8, 5, "SimplyGo", "SIMPLYGO BUS JOURNEY", "1.89", "Public Transport", Transaction.PaymentType.TRANSPORT, "visa"),
        ("super-energy-high", 10, 8, 15, "Super Energy", "SUPER ENERGY MONTHLY ELECTRICITY BILL", "350.00", "Bills", Transaction.PaymentType.BILL, "bank"),
        ("uniqlo", 11, 19, 25, "Uniqlo", "UNIQLO WORK CLOTHES", "88.90", "Clothing", Transaction.PaymentType.SHOPPING, "visa"),
        ("cafe", 11, 12, 10, "The Coffee Bean", "CAFE LUNCH AND COFFEE", "18.60", "Dining", Transaction.PaymentType.FOOD, "paynow"),
        ("starhub", 12, 9, 0, "StarHub", "STARHUB MONTHLY HOME INTERNET BILL", "52.90", "Bills", Transaction.PaymentType.BILL, "bank"),
        ("grab-2", 13, 22, 20, "Grab", "GRAB TAXI RIDE HOME", "21.40", "Private Hire & Taxis", Transaction.PaymentType.TRANSPORT, "visa"),
        ("kopitiam", 13, 12, 40, "Kopitiam", "KOPITIAM CHICKEN RICE MEAL", "6.20", "Dining", Transaction.PaymentType.FOOD, "paynow"),
        ("mrt-3", 14, 8, 10, "SimplyGo", "SIMPLYGO MRT JOURNEY", "2.20", "Public Transport", Transaction.PaymentType.TRANSPORT, "visa"),
        ("guardian", 14, 18, 45, "Guardian", "GUARDIAN DAILY VITAMINS", "18.90", "Healthcare", Transaction.PaymentType.HEALTHCARE, "visa"),
        ("foodpanda", 15, 19, 30, "Foodpanda", "FOOD DELIVERY DINNER FOR TWO", "24.80", "Dining", Transaction.PaymentType.FOOD, "visa"),
        ("bus-2", 15, 8, 0, "SimplyGo", "SIMPLYGO BUS JOURNEY", "1.89", "Public Transport", Transaction.PaymentType.TRANSPORT, "visa"),
        ("decathlon", 15, 17, 15, "Decathlon", "FITNESS TRAINING ACCESSORIES", "42.90", "Fitness", Transaction.PaymentType.HEALTHCARE, "visa"),
        ("shopee-2", 15, 21, 0, "Shopee", "SHOPEE ONLINE WORK BAG", "36.80", "Online Shopping", Transaction.PaymentType.SHOPPING, "visa"),
        ("water", 3, 8, 20, "Super Water", "MONTHLY HOUSEHOLD WATER BILL", "37.40", "Bills", Transaction.PaymentType.BILL, "bank"),
        ("extra-dining-1", 5, 19, 10, "Kopitiam", "DINNER WITH COLLEAGUES", "19.80", "Dining", Transaction.PaymentType.FOOD, "paynow"),
        ("haircut", 6, 18, 30, "K Cuts", "HAIRCUT AND PERSONAL SERVICE", "45.00", "Services", Transaction.PaymentType.OTHERS, "visa"),
        ("extra-groceries", 10, 18, 30, "NTUC FairPrice", "FORTNIGHTLY SUPERMARKET GROCERIES", "63.80", "Groceries", Transaction.PaymentType.SHOPPING, "visa"),
        ("work-blazer", 13, 19, 40, "Uniqlo", "UNIQLO WORK BLAZER", "98.00", "Clothing", Transaction.PaymentType.SHOPPING, "visa"),
        ("dental", 14, 17, 30, "Bright Dental", "DENTAL CHECKUP AND CLEANING", "78.00", "Healthcare", Transaction.PaymentType.HEALTHCARE, "visa"),
        ("extra-dining-2", 15, 20, 15, "Foodpanda", "WEEKEND FOOD DELIVERY", "26.40", "Dining", Transaction.PaymentType.FOOD, "visa"),
        ("household", 15, 16, 10, "IKEA Singapore", "HOUSEHOLD STORAGE ITEMS", "49.00", "Home Improvement", Transaction.PaymentType.HOUSING, "visa"),
    )
    for row in current_rows:
        key, day, hour, minute, merchant, description, amount, category_name, payment_type, method = row
        if day <= as_of.day:
            add(
                f"{prefix}-{key}", current, day, hour, merchant, description, amount,
                category_name, payment_type, method, minute,
            )
    return sorted(plan, key=lambda item: (item.happened, item.key))


class Command(BaseCommand):
    help = (
        "Create the isolated, deterministic Jia En presentation account with "
        "eleven complete months plus current-month synthetic spending."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete and recreate data owned only by the Jia En demo account.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Build and verify the scenario inside a rolled-back database transaction.",
        )
        parser.add_argument(
            "--verify-only",
            action="store_true",
            help="Verify and print the already-saved Jia En scenario without changing it.",
        )
        parser.add_argument(
            "--as-of",
            default=os.environ.get(AS_OF_ENVIRONMENT_VARIABLE),
            help=(
                "Presentation date in YYYY-MM-DD format. Defaults to today or "
                f"the {AS_OF_ENVIRONMENT_VARIABLE} environment variable."
            ),
        )
        parser.add_argument(
            "--password",
            default=None,
            help=(
                "Demo password. Prefer the JIA_EN_DEMO_PASSWORD environment "
                "variable so the value is not stored in shell history."
            ),
        )

    @db_transaction.atomic
    def handle(self, *args, **options):
        as_of = self._parse_as_of(options["as_of"])
        if as_of > timezone.localdate():
            raise CommandError("--as-of cannot be in the future.")
        if as_of.day < 15:
            raise CommandError("--as-of must be on or after the 15th so every presentation scenario exists.")

        if options["verify_only"]:
            if options["reset"] or options["dry_run"]:
                raise CommandError("--verify-only cannot be combined with --reset or --dry-run.")
            User = get_user_model()
            try:
                user = User.objects.get(username=USERNAME)
            except User.DoesNotExist as exc:
                raise CommandError("The Jia En demo account does not exist. Run the seed command first.") from exc
            summary = self._verify_and_summarise(user, as_of)
            self._print_summary(user, as_of, summary)
            self.stdout.write(self.style.SUCCESS("Saved Jia En demo data passed every verification check."))
            return

        password = options["password"] or os.environ.get(PASSWORD_ENVIRONMENT_VARIABLE)
        if not password:
            raise CommandError(
                f"Set {PASSWORD_ENVIRONMENT_VARIABLE} to a strong, presentation-only password."
            )

        plan = build_demo_plan(as_of)
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=USERNAME,
            defaults={"email": EMAIL, "first_name": "Jia En", "last_name": "Tan"},
        )
        user.email = EMAIL
        user.first_name = "Jia En"
        user.last_name = "Tan"
        try:
            validate_password(password, user=user)
        except ValidationError as exc:
            raise CommandError("The configured demo password is not strong enough: " + " ".join(exc.messages)) from exc
        user.set_password(password)
        user.save()

        scenario_exists = user.transactions.filter(note__startswith=DEMO_NOTE).exists()
        if scenario_exists and not options["reset"] and not options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(
                    "Jia En demo data already exists; password/profile refreshed and seeding skipped. "
                    "Use --reset to recreate it."
                )
            )
            return
        if not created and user.transactions.exists() and not scenario_exists and not options["reset"] and not options["dry_run"]:
            raise CommandError(
                f"The {USERNAME} account contains non-demo transactions. Re-run with --reset only if this is the dedicated demo account."
            )

        # Every deletion is constrained through the dedicated demo user.
        user.alerts.all().delete()
        user.transactions.all().delete()
        user.payment_methods.all().delete()
        user.monthly_budgets.all().delete()
        user.performance_logs.all().delete()

        payment_methods = self._create_payment_methods(user, as_of)
        first_month = _month_start(as_of, -11)
        MonthlyBudget.objects.create(user=user, month=first_month, amount=BUDGET_AMOUNT)

        categories = {
            category.name: category
            for category in Category.objects.filter(is_active=True)
        }
        missing_categories = sorted({item.category_name for item in plan} - set(categories))
        if missing_categories:
            raise CommandError("Required active categories are missing: " + ", ".join(missing_categories))

        created_transactions = {}
        for item in plan:
            created_transactions[item.key] = self._create_transaction(
                user=user,
                payment_methods=payment_methods,
                categories=categories,
                item=item,
                as_of=as_of,
            )

        current_prefix = _month_start(as_of).strftime("%Y-%m")
        high_bill = created_transactions[f"{current_prefix}-super-energy-high"]
        duplicate = created_transactions[f"{current_prefix}-singtel-duplicate"]
        self._generate_timestamped_alerts(high_bill)
        self._generate_timestamped_alerts(duplicate)

        summary = self._verify_and_summarise(user, as_of)
        self._print_summary(user, as_of, summary)

        if options["dry_run"]:
            db_transaction.set_rollback(True)
            self.stdout.write(self.style.WARNING("Dry run complete; no database changes were saved."))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Jia En demo is ready. Login with username '{USERNAME}' and the configured password."
            ))

    @staticmethod
    def _parse_as_of(raw_value):
        if not raw_value:
            return timezone.localdate()
        try:
            return date.fromisoformat(raw_value)
        except ValueError as exc:
            raise CommandError("--as-of must use YYYY-MM-DD format.") from exc

    @staticmethod
    def _create_payment_methods(user, as_of):
        return {
            "visa": PaymentMethod.objects.create(
                user=user,
                method_type=PaymentMethod.MethodType.VISA,
                display_name="Jia En's Visa",
                last_four="4821",
                expiry_month=12,
                expiry_year=as_of.year + 3,
                is_default=True,
            ),
            "paynow": PaymentMethod.objects.create(
                user=user,
                method_type=PaymentMethod.MethodType.PAYNOW,
                display_name="Jia En's PayNow",
            ),
            "bank": PaymentMethod.objects.create(
                user=user,
                method_type=PaymentMethod.MethodType.BANK,
                display_name="Jia En's simulated bank account",
            ),
        }

    @staticmethod
    def _create_transaction(*, user, payment_methods, categories, item, as_of):
        method = payment_methods[item.payment_method]
        bank_transaction_type = bank_transaction_type_for_payment(method, item.payment_type)
        result = categorise_transaction(
            item.merchant,
            item.payment_type,
            DEMO_NOTE,
            transaction_description=item.description,
            amount=item.amount,
            transaction_date=item.happened,
            transaction_type=bank_transaction_type,
        )
        intended_category = categories[item.category_name]
        corrected = result.category.pk != intended_category.pk
        return Transaction.objects.create(
            user=user,
            merchant_name=item.merchant,
            amount=item.amount,
            transaction_date=item.happened,
            payment_type=item.payment_type,
            bank_transaction_type=bank_transaction_type,
            note=DEMO_NOTE,
            payment_method=method,
            transaction_description=item.description,
            predicted_category=result.category,
            final_category=intended_category,
            confidence_score=result.confidence,
            category_explanation=result.explanation,
            categorisation_source=(
                Transaction.CategorisationSource.USER_CORRECTION
                if corrected else result.source
            ),
            ground_truth_category=intended_category,
            user_corrected=corrected,
            submission_token=uuid.uuid5(
                SUBMISSION_NAMESPACE, f"{USERNAME}:{as_of.isoformat()}:{item.key}"
            ),
        )

    @staticmethod
    def _generate_timestamped_alerts(transaction):
        alerts = generate_alerts(transaction)
        for index, alert in enumerate(alerts):
            Alert.objects.filter(pk=alert.pk).update(
                created_at=transaction.transaction_date + timedelta(minutes=1, seconds=index)
            )
        return alerts

    @staticmethod
    def _verify_and_summarise(user, as_of):
        current_month = _month_start(as_of)
        expected_months = [_month_start(as_of, offset) for offset in range(-11, 1)]
        monthly = []
        for month in expected_months:
            next_month = _month_start(month, 1)
            queryset = user.transactions.filter(
                transaction_date__date__gte=month,
                transaction_date__date__lt=next_month,
            )
            count = queryset.count()
            total = queryset.aggregate(value=Sum("amount"))["value"] or Decimal("0.00")
            if month < current_month and not 20 <= count <= 45:
                raise CommandError(f"Verification failed: {month:%B %Y} has {count} transactions, not 20–45.")
            monthly.append({"month": month, "count": count, "total": total})

        historical_electricity = list(
            user.transactions.filter(
                merchant_name="Super Energy",
                transaction_date__date__lt=current_month,
            ).order_by("transaction_date").values_list("amount", flat=True)
        )
        expected_electricity = [
            Decimal(value) for value in (
                "96.00", "99.00", "104.00", "100.00", "105.00",
                "98.00", "103.00", "101.00", "106.00", "97.00", "102.00",
            )
        ]
        if historical_electricity != expected_electricity:
            raise CommandError("Verification failed: historical Super Energy amounts do not match the scenario.")

        high_bill = user.transactions.get(
            merchant_name="Super Energy",
            amount=Decimal("350.00"),
            transaction_date__date__gte=current_month,
        )
        if high_bill.predicted_category.name != "Bills" or high_bill.final_category.name != "Bills":
            raise CommandError("Verification failed: the S$350 Super Energy prediction/final category is not Bills.")
        unusual_alert = high_bill.alerts.filter(
            alert_type=Alert.AlertType.UNUSUAL_AMOUNT,
            status=Alert.Status.ACTIVE,
        ).first()
        if unusual_alert is None:
            raise CommandError("Verification failed: the unusual-bill alert was not generated.")

        duplicate_payments = list(
            user.transactions.filter(
                merchant_name="Singtel",
                amount=Decimal("39.90"),
                transaction_date__date__gte=current_month,
            ).order_by("transaction_date")
        )
        if len(duplicate_payments) != 2:
            raise CommandError("Verification failed: the two current Singtel payments are missing.")
        if duplicate_payments[1].transaction_date - duplicate_payments[0].transaction_date != timedelta(minutes=2):
            raise CommandError("Verification failed: the Singtel payments are not two minutes apart.")
        duplicate_alert = duplicate_payments[1].alerts.filter(
            alert_type=Alert.AlertType.DUPLICATE,
            status=Alert.Status.ACTIVE,
        ).first()
        if duplicate_alert is None:
            raise CommandError("Verification failed: the duplicate-payment alert was not generated.")

        budget_summary = get_budget_summary(user, current_month, today=as_of)
        if not budget_summary["budget"] or budget_summary["budget"].amount != BUDGET_AMOUNT:
            raise CommandError("Verification failed: the S$3,000 monthly budget is missing.")
        if not user.transactions.filter(pk=high_bill.pk, final_category__name="Bills").exists():
            raise CommandError("Verification failed: the S$350 bill is absent from Bills aggregation.")

        category_breakdown = get_category_breakdown(user, current_month, today=as_of)
        breakdown_total = sum((row["total"] for row in category_breakdown), Decimal("0.00"))
        if breakdown_total != budget_summary["total"]:
            raise CommandError("Verification failed: dashboard category totals do not reconcile.")
        category_changes = get_category_changes(user, current_month, today=as_of, same_period=True)
        increases = [row for row in category_changes if row["difference"] > 0]
        if not {"Bills", "Dining"}.issubset({row["name"] for row in increases}):
            raise CommandError("Verification failed: the planned Bills and Dining increases are not present.")

        return {
            "monthly": monthly,
            "budget": budget_summary,
            "category_breakdown": category_breakdown,
            "category_increases": increases,
            "alerts": list(user.alerts.select_related("transaction").order_by("created_at", "id")),
            "high_bill": high_bill,
            "duplicate": duplicate_payments[1],
        }

    def _print_summary(self, user, as_of, summary):
        self.stdout.write("\nMonthly totals")
        for row in summary["monthly"]:
            self.stdout.write(
                f"  {row['month']:%b %Y}: {row['count']:2d} transactions · S${row['total']:,.2f}"
            )

        self.stdout.write(f"\nCurrent-month category totals through {as_of:%d %b %Y}")
        for row in summary["category_breakdown"]:
            self.stdout.write(
                f"  {row['final_category__name']}: S${row['total']:,.2f} ({row['count']} transactions)"
            )

        self.stdout.write("\nCategories above the same point last month")
        for row in summary["category_increases"]:
            percent = "new" if row["percent"] is None else f"{row['percent']:+.1f}%"
            self.stdout.write(
                f"  {row['name']}: S${row['current_total']:,.2f} vs "
                f"S${row['previous_total']:,.2f} ({percent})"
            )

        self.stdout.write("\nActive alerts generated by the existing alert service")
        for alert in summary["alerts"]:
            self.stdout.write(
                f"  {alert.get_alert_type_display()}: {alert.transaction.merchant_name} "
                f"S${alert.transaction.amount:,.2f} · {alert.status}"
            )
        self.stdout.write(
            f"\nStored classifier result for Super Energy S$350.00: "
            f"{summary['high_bill'].predicted_category.name} · "
            f"{summary['high_bill'].get_categorisation_source_display()} · "
            f"confidence {summary['high_bill'].confidence_score:.4f}"
        )
        self.stdout.write(
            f"Budget: S${BUDGET_AMOUNT:,.2f} · Current spending: "
            f"S${summary['budget']['total']:,.2f} · "
            f"{summary['budget']['used_percent']:.1f}% used"
        )
