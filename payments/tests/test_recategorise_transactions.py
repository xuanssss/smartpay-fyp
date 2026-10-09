from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from payments.models import Category, Transaction


class RecategoriseTransactionsCommandTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="bulk-test", password="test-password-123"
        )
        self.dining = Category.objects.get(name="Dining")
        self.other = Category.objects.get(name="Other")

    def make_transaction(
        self,
        merchant,
        description,
        *,
        corrected=False,
        category=None,
        happened=None,
    ):
        category = category or self.other
        return Transaction.objects.create(
            user=self.user,
            merchant_name=merchant,
            amount=Decimal("18.20"),
            transaction_date=happened or timezone.now(),
            payment_type=Transaction.PaymentType.OTHERS,
            bank_transaction_type=Transaction.BankTransactionType.DEBIT_CARD,
            transaction_description=description,
            predicted_category=category,
            final_category=self.dining if corrected else category,
            confidence_score=0.25,
            category_explanation="Old prediction.",
            categorisation_source=(
                Transaction.CategorisationSource.USER_CORRECTION
                if corrected
                else Transaction.CategorisationSource.ML
            ),
            user_corrected=corrected,
        )

    def test_updates_predictions_and_preserves_corrected_final_category(self):
        ride = self.make_transaction("Grab", "GRAB AIRPORT RIDE")
        corrected = self.make_transaction(
            "Amazon",
            "MOBILE PHONE PURCHASE",
            corrected=True,
            happened=timezone.now() - timedelta(days=1),
        )

        output = StringIO()
        call_command("recategorise_transactions", stdout=output)

        ride.refresh_from_db()
        corrected.refresh_from_db()
        self.assertEqual(ride.predicted_category.name, "Private Hire & Taxis")
        self.assertEqual(ride.final_category.name, "Private Hire & Taxis")
        self.assertEqual(
            ride.categorisation_source,
            Transaction.CategorisationSource.COMBINED,
        )
        self.assertEqual(corrected.predicted_category.name, "Online Shopping")
        self.assertEqual(corrected.final_category, self.dining)
        self.assertEqual(
            corrected.categorisation_source,
            Transaction.CategorisationSource.USER_CORRECTION,
        )
        self.assertIn("Updated 2 of 2 transactions", output.getvalue())
        self.assertIn("preserved 1 user-corrected final categories", output.getvalue())

    def test_dry_run_does_not_save_changes(self):
        payment = self.make_transaction("Grab", "GRAB AIRPORT RIDE")

        output = StringIO()
        call_command("recategorise_transactions", dry_run=True, stdout=output)

        payment.refresh_from_db()
        self.assertEqual(payment.predicted_category, self.other)
        self.assertEqual(payment.final_category, self.other)
        self.assertEqual(payment.category_explanation, "Old prediction.")
        self.assertIn("Would update 1 of 1 transactions", output.getvalue())
