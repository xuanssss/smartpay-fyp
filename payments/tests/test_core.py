from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from alerts.models import Alert
from alerts.services.alert_generation import generate_alerts
from analytics.services.dashboard import get_monthly_total
from payments.models import Category, MerchantRule, Transaction
from payments.services.categorisation import categorise_transaction


class CoreServiceTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("tester", password="test-password-123")
        cls.categories = {
            name: Category.objects.create(name=name)
            for name in [
                "Food & Dining", "Transport", "Shopping", "Utilities", "Subscriptions",
                "Education", "Healthcare", "Housing / Rent", "Entertainment", "Others",
            ]
        }
        MerchantRule.objects.create(
            keyword="Netflix",
            category=cls.categories["Subscriptions"],
            confidence_score=0.95,
            explanation_template="Merchant name matches a known subscription provider.",
        )

    def make_transaction(self, merchant="Test Merchant", amount="10.00", happened=None, category="Others"):
        happened = happened or timezone.now()
        selected = self.categories[category]
        return Transaction.objects.create(
            user=self.user,
            merchant_name=merchant,
            amount=Decimal(amount),
            transaction_date=happened,
            payment_type="Others",
            predicted_category=selected,
            final_category=selected,
            confidence_score=0.40,
            category_explanation="Test explanation.",
        )

    def test_exact_merchant_rule_categorisation(self):
        result = categorise_transaction("Netflix", "Subscription", "Monthly plan")
        self.assertEqual(result.category.name, "Subscriptions")
        self.assertEqual(result.confidence, 0.95)
        self.assertIn("subscription provider", result.explanation)

    def test_duplicate_payment_alert_rule(self):
        happened = timezone.now()
        self.make_transaction("SP Group", "100.00", happened)
        second = self.make_transaction("SP Group", "102.00", happened + timedelta(minutes=3))
        generate_alerts(second)
        self.assertTrue(second.alerts.filter(alert_type=Alert.AlertType.DUPLICATE).exists())

    def test_unfamiliar_high_value_merchant_alert_rule(self):
        for index in range(3):
            self.make_transaction(f"Known {index}", "20.00", timezone.now() - timedelta(days=index + 1))
        high_value = self.make_transaction("Brand New Merchant", "100.00")
        generate_alerts(high_value)
        self.assertTrue(high_value.alerts.filter(alert_type=Alert.AlertType.UNFAMILIAR_HIGH_VALUE).exists())

    def test_dashboard_monthly_total(self):
        now = timezone.now()
        self.make_transaction(amount="10.25", happened=now)
        self.make_transaction(amount="24.75", happened=now - timedelta(days=1))
        self.assertEqual(get_monthly_total(self.user, now), Decimal("35.00"))

    def test_category_correction_keeps_prediction(self):
        payment = self.make_transaction(category="Others")
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("change_category", args=[payment.pk]),
            {"final_category": self.categories["Food & Dining"].pk},
        )
        self.assertRedirects(response, reverse("transaction_detail", args=[payment.pk]))
        payment.refresh_from_db()
        self.assertEqual(payment.predicted_category, self.categories["Others"])
        self.assertEqual(payment.final_category, self.categories["Food & Dining"])
        self.assertTrue(payment.user_corrected)
