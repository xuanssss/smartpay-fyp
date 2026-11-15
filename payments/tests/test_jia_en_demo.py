from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from alerts.models import Alert
from analytics.models import MonthlyBudget
from analytics.services.dashboard import (
    get_budget_summary,
    get_category_breakdown,
    get_category_changes,
    get_monthly_review_data,
    get_smart_insights,
)
from payments.management.commands.seed_jia_en_demo import DEMO_NOTE, USERNAME
from payments.models import Category, Transaction


AS_OF = date(2026, 11, 15)
TEST_PASSWORD = "River-Quartz-7391!"


class JiaEnDemoScenarioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.command_output = StringIO()
        call_command(
            "seed_jia_en_demo",
            as_of=AS_OF.isoformat(),
            password=TEST_PASSWORD,
            stdout=cls.command_output,
        )
        cls.user = get_user_model().objects.get(username=USERNAME)

    def test_account_budget_month_coverage_and_realistic_counts(self):
        self.assertTrue(self.user.check_password(TEST_PASSWORD))
        self.assertEqual(self.user.first_name, "Jia En")
        self.assertEqual(self.user.last_name, "Tan")
        self.assertEqual(self.user.payment_methods.count(), 3)
        self.assertEqual(
            MonthlyBudget.objects.get(user=self.user).amount,
            Decimal("3000.00"),
        )

        expected_months = [date(2025, 12, 1)] + [
            date(2026, month_number, 1) for month_number in range(1, 12)
        ]
        expected_counts = [41, 42, 41, 41, 42, 40, 43, 39, 45, 41, 42, 36]
        actual_counts = []
        for month in expected_months:
            next_month = (
                date(month.year + 1, 1, 1)
                if month.month == 12
                else date(month.year, month.month + 1, 1)
            )
            actual_counts.append(self.user.transactions.filter(
                transaction_date__date__gte=month,
                transaction_date__date__lt=next_month,
            ).count())
        self.assertEqual(actual_counts, expected_counts)
        self.assertFalse(
            self.user.transactions.filter(transaction_date__date__gt=AS_OF).exists()
        )
        self.assertTrue(
            self.user.transactions.filter(note__startswith=DEMO_NOTE).exists()
        )

    def test_electricity_history_and_real_unusual_amount_rule(self):
        historical = list(
            self.user.transactions.filter(
                merchant_name="Super Energy",
                transaction_date__date__lt=date(2026, 11, 1),
            ).order_by("transaction_date").values_list("amount", flat=True)
        )
        self.assertEqual(
            historical,
            [
                Decimal("96.00"),
                Decimal("99.00"),
                Decimal("104.00"),
                Decimal("100.00"),
                Decimal("105.00"),
                Decimal("98.00"),
                Decimal("103.00"),
                Decimal("101.00"),
                Decimal("106.00"),
                Decimal("97.00"),
                Decimal("102.00"),
            ],
        )

        high_bill = self.user.transactions.get(
            merchant_name="Super Energy", amount=Decimal("350.00")
        )
        self.assertEqual(high_bill.predicted_category.name, "Bills")
        self.assertEqual(high_bill.final_category.name, "Bills")
        self.assertEqual(
            high_bill.categorisation_source,
            Transaction.CategorisationSource.ML,
        )
        self.assertGreater(high_bill.confidence_score, 0)
        self.assertIn("SVM", high_bill.category_explanation)
        self.assertFalse(high_bill.user_corrected)

        alert = high_bill.alerts.get(alert_type=Alert.AlertType.UNUSUAL_AMOUNT)
        self.assertEqual(alert.status, Alert.Status.ACTIVE)
        self.assertEqual(alert.severity, Alert.Severity.MEDIUM)
        self.assertIn("higher than your usual amount", alert.message)
        self.assertIn("two standard deviations", alert.explanation)

    def test_duplicate_singtel_payments_use_distinct_submissions_and_real_rule(self):
        payments = list(
            self.user.transactions.filter(
                merchant_name="Singtel",
                amount=Decimal("39.90"),
                transaction_date__date__gte=date(2026, 11, 1),
            ).order_by("transaction_date")
        )
        self.assertEqual(len(payments), 2)
        self.assertEqual(
            payments[1].transaction_date - payments[0].transaction_date,
            timedelta(minutes=2),
        )
        self.assertNotEqual(payments[0].submission_token, payments[1].submission_token)

        alert = payments[1].alerts.get(alert_type=Alert.AlertType.DUPLICATE)
        self.assertEqual(alert.status, Alert.Status.ACTIVE)
        self.assertIn("within 5 minutes", alert.message)
        self.assertIn("amounts were very similar", alert.explanation)

    def test_dashboard_totals_categories_and_same_period_increases_reconcile(self):
        month = date(2026, 11, 1)
        budget = get_budget_summary(self.user, month, today=AS_OF)
        breakdown = get_category_breakdown(self.user, month, today=AS_OF)
        changes = get_category_changes(self.user, month, today=AS_OF)

        self.assertEqual(budget["budget"].amount, Decimal("3000.00"))
        self.assertEqual(budget["total"], Decimal("1434.09"))
        self.assertEqual(budget["used_percent"], 47.8)
        self.assertEqual(
            sum((row["total"] for row in breakdown), Decimal("0.00")),
            budget["total"],
        )
        category_totals = {
            row["final_category__name"]: row["total"] for row in breakdown
        }
        self.assertEqual(category_totals["Bills"], Decimal("520.10"))
        self.assertEqual(category_totals["Dining"], Decimal("117.60"))
        self.assertEqual(category_totals["Groceries"], Decimal("125.00"))
        increases = {row["name"]: row for row in changes if row["difference"] > 0}
        self.assertEqual(increases["Bills"]["previous_total"], Decimal("232.20"))
        self.assertEqual(increases["Bills"]["percent"], 124.0)
        self.assertEqual(increases["Dining"]["percent"], 66.6)
        self.assertEqual(increases["Groceries"]["percent"], 1.1)
        self.assertNotIn("Public Transport", increases)

        review = get_monthly_review_data(self.user, month, today=AS_OF)
        self.assertEqual(
            [milestone["key"] for milestone in review["milestones"]],
            ["biggest-day", "busiest-day", "period-comparison", "month-total"],
        )
        self.assertEqual(review["milestones"][2]["label"], "Spending increased")
        self.assertEqual(len(review["trend"]["values"]), 12)
        self.assertEqual(review["trend"]["values"][0], 2629.59)
        self.assertEqual(review["trend"]["values"][-1], 1434.09)
        self.assertTrue(all(value > 0 for value in review["trend"]["values"]))
        insights = get_smart_insights(self.user, month, budget)
        self.assertEqual(len(insights), 3)
        self.assertNotIn("Spending increased", [insight["title"] for insight in insights])

    def test_login_and_presentation_pages_render_from_saved_data(self):
        self.assertTrue(self.client.login(username=USERNAME, password=TEST_PASSWORD))
        high_bill = self.user.transactions.get(
            merchant_name="Super Energy", amount=Decimal("350.00")
        )
        pages = (
            reverse("alert_list"),
            reverse("transaction_history"),
            reverse("transaction_detail", args=[high_bill.pk]),
            reverse("dashboard") + "?month=2026-11",
            reverse("dashboard_analysis") + "?month=2026-11",
        )
        for page in pages:
            with self.subTest(page=page):
                self.assertEqual(self.client.get(page).status_code, 200)

        detail = self.client.get(reverse("transaction_detail", args=[high_bill.pk]))
        self.assertContains(detail, "Super Energy")
        self.assertContains(detail, "Machine-learning model")
        self.assertContains(detail, "Predicted category")
        self.assertContains(detail, "Final category")
        self.assertContains(detail, "Change category")

        alerts = self.client.get(reverse("alert_list"))
        self.assertContains(alerts, "Unusual bill amount")
        self.assertContains(alerts, "Possible duplicate payment")
        self.assertContains(alerts, "For awareness only")

        verification_output = StringIO()
        call_command(
            "seed_jia_en_demo",
            as_of=AS_OF.isoformat(),
            verify_only=True,
            stdout=verification_output,
        )
        self.assertIn(
            "Saved Jia En demo data passed every verification check",
            verification_output.getvalue(),
        )

    def test_rerun_is_idempotent_and_reset_does_not_touch_other_users(self):
        original_count = self.user.transactions.count()
        original_alert_count = self.user.alerts.count()
        output = StringIO()
        call_command(
            "seed_jia_en_demo",
            as_of=AS_OF.isoformat(),
            password=TEST_PASSWORD,
            stdout=output,
        )
        self.assertEqual(self.user.transactions.count(), original_count)
        self.assertEqual(self.user.alerts.count(), original_alert_count)
        self.assertIn("seeding skipped", output.getvalue())

        other_user = get_user_model().objects.create_user(
            username="unrelated-user", password="Unrelated-Test-4281!"
        )
        dining = Category.objects.get(name="Dining")
        unrelated = Transaction.objects.create(
            user=other_user,
            merchant_name="Unrelated Merchant",
            amount=Decimal("12.00"),
            transaction_date=self.user.transactions.first().transaction_date,
            payment_type=Transaction.PaymentType.FOOD,
            predicted_category=dining,
            final_category=dining,
            confidence_score=0.9,
            category_explanation="Unrelated test data.",
        )

        call_command(
            "seed_jia_en_demo",
            as_of=AS_OF.isoformat(),
            password=TEST_PASSWORD,
            reset=True,
            stdout=StringIO(),
        )
        self.assertEqual(self.user.transactions.count(), original_count)
        self.assertEqual(self.user.alerts.count(), original_alert_count)
        self.assertTrue(Transaction.objects.filter(pk=unrelated.pk).exists())


class JiaEnDemoDryRunTests(TestCase):
    def test_dry_run_rolls_back_every_change(self):
        output = StringIO()
        call_command(
            "seed_jia_en_demo",
            as_of=AS_OF.isoformat(),
            password=TEST_PASSWORD,
            dry_run=True,
            stdout=output,
        )
        self.assertFalse(get_user_model().objects.filter(username=USERNAME).exists())
        self.assertIn("Dry run complete", output.getvalue())
