import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from alerts.models import Alert
from alerts.services.alert_generation import generate_alerts
from analytics.models import PerformanceLog
from analytics.services.dashboard import get_monthly_total
from payments.models import (
    BrowseCategory,
    CatalogueItem,
    Category,
    PaymentMethod,
    Transaction,
)
from payments.services.catalog import get_catalogue
from payments.services.categorisation import categorise_transaction
from payments.taxonomy import PURCHASE_CATEGORY_NAMES


class CataloguePaymentFlowTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("tester", password="test-password-123")
        self.other_user = User.objects.create_user("other", password="test-password-123")
        self.categories = {
            name: Category.objects.get(name=name, is_active=True)
            for name in PURCHASE_CATEGORY_NAMES
        }
        self.food_browse = BrowseCategory.objects.create(
            name="Food", slug="food-drinks", icon_name="F", display_order=1
        )
        self.bill_browse = BrowseCategory.objects.create(
            name="Bills", slug="bills", icon_name="B", display_order=2
        )
        self.housing_browse = BrowseCategory.objects.create(
            name="Housing", slug="home", icon_name="H", display_order=3
        )
        self.food_item = CatalogueItem.objects.create(
            name="Chicken Rice",
            slug="food-chicken-rice",
            browse_category=self.food_browse,
            merchant_name="Koufu",
            transaction_description="KOUFU CHICKEN RICE PURCHASE",
            short_description="A local rice meal",
            unit_price=Decimal("6.50"),
            allows_quantity=True,
            minimum_quantity=1,
            maximum_quantity=5,
            ground_truth_category=self.categories["Dining"],
        )
        self.bill_item = CatalogueItem.objects.create(
            name="Electricity Bill",
            slug="bills-electricity",
            browse_category=self.bill_browse,
            merchant_name="SP Group",
            transaction_description="MONTHLY ELECTRICITY BILL",
            short_description="Monthly electricity service",
            unit_price=Decimal("90.00"),
            allows_quantity=False,
            ground_truth_category=self.categories["Bills"],
        )
        # Deliberately conflicting navigation and evaluation labels. Raw wording
        # must still produce Dining.
        self.mismatch_item = CatalogueItem.objects.create(
            name="Chicken Rice Set",
            slug="housing-chicken-rice",
            browse_category=self.housing_browse,
            merchant_name="Koufu",
            transaction_description="KOUFU CHICKEN RICE PURCHASE",
            short_description="Deliberate evaluation mismatch",
            unit_price=Decimal("7.00"),
            allows_quantity=True,
            ground_truth_category=self.categories["Other"],
        )
        self.method = PaymentMethod.objects.create(
            user=self.user,
            method_type=PaymentMethod.MethodType.VISA,
            display_name="Test Visa",
            last_four="4821",
            expiry_month=12,
            expiry_year=timezone.localdate().year + 2,
        )
        self.other_method = PaymentMethod.objects.create(
            user=self.other_user,
            method_type=PaymentMethod.MethodType.PAYNOW,
            display_name="Someone else's PayNow",
        )
        self.client.force_login(self.user)

    def purchase(self, item=None, token=None, quantity=1, amount=None, method=None):
        item = item or self.food_item
        data = {
            "submission_token": str(token or uuid.uuid4()),
            "payment_method": (method or self.method).pk,
        }
        if item.allows_quantity:
            data["quantity"] = quantity
        else:
            data["amount"] = amount if amount is not None else "90.00"
        return self.client.post(reverse("catalogue_item_detail", args=[item.slug]), data)

    def make_legacy_transaction(self, merchant="Legacy Merchant", amount="10.00", happened=None, category="Other"):
        selected = self.categories[category]
        return Transaction.objects.create(
            user=self.user,
            merchant_name=merchant,
            amount=Decimal(amount),
            transaction_date=happened or timezone.now(),
            payment_type=Transaction.PaymentType.OTHERS,
            predicted_category=selected,
            final_category=selected,
            confidence_score=0.40,
            category_explanation="Legacy explanation.",
        )

    def test_01_category_filter_displays_correct_items(self):
        _, selected, items = get_catalogue("bills")
        self.assertEqual(selected, "bills")
        self.assertQuerySetEqual(items, [self.bill_item])

    def test_02_search_matches_item_merchant_description_and_category(self):
        _, _, item_results = get_catalogue(query="rice")
        self.assertIn(self.food_item, item_results)
        _, _, merchant_results = get_catalogue(query="sp gro")
        self.assertQuerySetEqual(merchant_results, [self.bill_item])
        _, _, combined = get_catalogue("bills", "monthly")
        self.assertQuerySetEqual(combined, [self.bill_item])

    def test_03_selecting_item_opens_correct_detail(self):
        response = self.client.get(reverse("catalogue_item_detail", args=[self.food_item.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["item"], self.food_item)
        self.assertContains(response, "Chicken Rice")
        self.assertContains(response, "Back to Food")
        self.assertContains(response, '<p class="page-kicker">Food</p>', html=True)
        self.assertNotContains(response, "Food & groceries")

    def test_03b_bill_detail_uses_same_label_as_pay_page(self):
        response = self.client.get(
            reverse("catalogue_item_detail", args=[self.bill_item.slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Back to Bills")
        self.assertContains(response, '<p class="page-kicker">Bills</p>', html=True)
        self.assertNotContains(response, "Bills & home")

    def test_04_quantity_changes_server_calculated_total(self):
        response = self.purchase(quantity=3)
        payment = Transaction.objects.get()
        self.assertRedirects(response, reverse("transaction_detail", args=[payment.pk]))
        self.assertEqual(payment.quantity, 3)
        self.assertEqual(payment.unit_price, Decimal("6.50"))
        self.assertEqual(payment.amount, Decimal("19.50"))

    def test_05_invalid_quantity_is_rejected(self):
        response = self.purchase(quantity=6)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose a quantity from 1 to 5")
        self.assertEqual(Transaction.objects.count(), 0)

    def test_06_variable_bill_amount_must_be_positive(self):
        response = self.purchase(item=self.bill_item, amount="0.00")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ensure this value is greater than or equal to 0.01")
        self.assertEqual(Transaction.objects.count(), 0)

    def test_07_purchase_requires_active_payment_method(self):
        self.method.deactivate()
        response = self.client.post(
            reverse("catalogue_item_detail", args=[self.food_item.slug]),
            {"quantity": 1, "payment_method": self.method.pk, "submission_token": str(uuid.uuid4())},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add a payment method first")
        self.assertEqual(Transaction.objects.count(), 0)

    def test_08_user_can_only_view_and_select_own_methods(self):
        response = self.client.get(reverse("payment_method_list"))
        self.assertContains(response, self.method.display_name)
        self.assertNotContains(response, self.other_method.display_name)
        response = self.client.get(reverse("catalogue_item_detail", args=[self.food_item.slug]))
        self.assertNotIn(self.other_method, response.context["form"].fields["payment_method"].queryset)
        forbidden = self.client.post(reverse("set_default_payment_method", args=[self.other_method.pk]))
        self.assertEqual(forbidden.status_code, 404)

    def test_09_user_has_only_one_active_default_method(self):
        second = PaymentMethod.objects.create(
            user=self.user,
            method_type=PaymentMethod.MethodType.PAYNOW,
            display_name="Test PayNow",
            is_default=True,
        )
        self.method.refresh_from_db()
        self.assertFalse(self.method.is_default)
        self.assertTrue(second.is_default)
        self.assertEqual(self.user.payment_methods.filter(is_active=True, is_default=True).count(), 1)

    def test_10_purchase_creates_exactly_one_transaction(self):
        self.purchase()
        self.assertEqual(Transaction.objects.count(), 1)

    def test_11_repeated_form_submission_is_idempotent(self):
        token = uuid.uuid4()
        first = self.purchase(token=token)
        second = self.purchase(token=token)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(Transaction.objects.filter(submission_token=token).count(), 1)

    def test_12_browse_category_is_not_copied_to_prediction(self):
        self.purchase(item=self.mismatch_item)
        payment = Transaction.objects.get()
        self.assertEqual(self.mismatch_item.browse_category.name, "Housing")
        self.assertEqual(payment.predicted_category.name, "Dining")

    def test_13_ground_truth_is_not_copied_to_prediction(self):
        self.purchase(item=self.mismatch_item)
        payment = Transaction.objects.get()
        self.assertEqual(payment.ground_truth_category.name, "Other")
        self.assertEqual(payment.predicted_category.name, "Dining")

    def test_14_catalogue_purchase_runs_categorisation(self):
        self.purchase()
        payment = Transaction.objects.get()
        self.assertEqual(payment.predicted_category.name, "Dining")
        self.assertEqual(payment.categorisation_source, Transaction.CategorisationSource.ML)
        self.assertTrue(payment.category_explanation)
        self.assertTrue(PerformanceLog.objects.filter(operation_name="categorisation").exists())

    def test_15_pay_another_merchant_creates_and_categorises(self):
        form_response = self.client.get(reverse("pay_another_merchant"))
        self.assertNotIn("payment_type", form_response.context["form"].fields)
        self.assertNotIn("note", form_response.context["form"].fields)
        self.assertNotContains(form_response, "Service context")
        self.assertNotContains(form_response, "Optional note")

        response = self.client.post(reverse("pay_another_merchant"), {
            "merchant_name": "Netflix",
            "transaction_description": "Monthly video plan",
            "amount": "15.98",
            "transaction_date": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
            "payment_method": self.method.pk,
            "submission_token": str(uuid.uuid4()),
        })
        payment = Transaction.objects.get()
        self.assertRedirects(response, reverse("transaction_detail", args=[payment.pk]))
        self.assertTrue(payment.predicted_category.is_active)
        self.assertEqual(payment.final_category, payment.predicted_category)
        self.assertEqual(
            payment.categorisation_source, Transaction.CategorisationSource.ML
        )
        self.assertEqual(payment.transaction_description, "Monthly video plan")
        self.assertEqual(payment.payment_type, Transaction.PaymentType.OTHERS)
        self.assertEqual(payment.note, "")
        self.assertEqual(payment.bank_transaction_type, Transaction.BankTransactionType.DEBIT_CARD)

    def test_16_payment_method_is_stored_with_transaction(self):
        self.purchase()
        self.assertEqual(Transaction.objects.get().payment_method, self.method)

    def test_17_dashboard_monthly_total_still_works(self):
        self.purchase(quantity=2)
        self.make_legacy_transaction(amount="7.00")
        self.assertEqual(get_monthly_total(self.user, timezone.now()), Decimal("20.00"))

    def test_18_existing_alert_rules_still_work(self):
        happened = timezone.now()
        self.make_legacy_transaction("SP Group", "100.00", happened, "Bills")
        duplicate = self.make_legacy_transaction("SP Group", "102.00", happened + timedelta(minutes=3), "Bills")
        generate_alerts(duplicate)
        self.assertTrue(duplicate.alerts.filter(alert_type=Alert.AlertType.DUPLICATE).exists())

        for index in range(3):
            self.make_legacy_transaction(f"Known {index}", "20.00", happened - timedelta(days=index + 1))
        high_value = self.make_legacy_transaction("Brand New Merchant", "200.00", happened)
        generate_alerts(high_value)
        self.assertTrue(high_value.alerts.filter(alert_type=Alert.AlertType.UNFAMILIAR_HIGH_VALUE).exists())

    def test_19_category_correction_preserves_prediction(self):
        payment = self.make_legacy_transaction(category="Other")
        response = self.client.post(
            reverse("change_category", args=[payment.pk]),
            {"final_category": self.categories["Dining"].pk},
        )
        self.assertRedirects(response, reverse("transaction_detail", args=[payment.pk]))
        payment.refresh_from_db()
        self.assertEqual(payment.predicted_category, self.categories["Other"])
        self.assertEqual(payment.final_category, self.categories["Dining"])
        self.assertTrue(payment.user_corrected)
        self.assertEqual(payment.categorisation_source, Transaction.CategorisationSource.USER_CORRECTION)

    def test_20_legacy_transaction_without_new_links_displays(self):
        payment = self.make_legacy_transaction()
        response = self.client.get(reverse("transaction_detail", args=[payment.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Legacy Merchant")
        self.assertContains(response, "Not recorded (legacy payment)")

    def test_21_online_marketplace_example_uses_curated_merchant_rule(self):
        result = categorise_transaction(
            merchant_name="Amazon",
            payment_type=Transaction.PaymentType.SHOPPING,
            item_name="Mobile Phone",
            transaction_description="MOBILE PHONE PURCHASE",
            amount=Decimal("699.00"),
            transaction_date=timezone.now(),
            transaction_type=Transaction.BankTransactionType.DEBIT_CARD,
        )
        self.assertEqual(result.category.name, "Online Shopping")
        self.assertTrue(result.category.is_active)
        self.assertEqual(
            result.source, Transaction.CategorisationSource.MERCHANT
        )

    def test_22_payment_page_defaults_to_a_simple_food_group(self):
        response = self.client.get(reverse("create_payment"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_category"], "food")
        self.assertQuerySetEqual(response.context["items"], [self.food_item])
        self.assertContains(response, 'class="payment-sidebar"')
        self.assertContains(response, "Pay another merchant")
        self.assertContains(response, ">Services<")
        self.assertContains(response, '<h2 id="catalogue-heading">Food</h2>')
        self.assertContains(response, "Select")
        self.assertNotContains(response, 'role="search"')
        self.assertNotContains(response, ">Housing<")

    def test_23_simple_group_can_contain_multiple_catalogue_categories(self):
        _, selected, items = get_catalogue("essentials")
        self.assertEqual(selected, "essentials")
        self.assertSetEqual(set(items), {self.bill_item, self.mismatch_item})

    def test_24_other_group_displays_miscellaneous_items(self):
        response = self.client.get(reverse("create_payment"), {"category": "other"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Parcel Postage")
        self.assertContains(response, "Gift Card")
        self.assertNotContains(response, "Chicken Rice")

    @patch("payments.services.categorisation.ml_predict_category")
    def test_25_other_browse_group_is_not_used_as_prediction(self, model_prediction):
        model_prediction.return_value = {"category": "Services", "confidence": 0.91}
        item = CatalogueItem.objects.get(slug="other-printing-service")
        self.purchase(item=item)
        payment = Transaction.objects.get()
        self.assertEqual(item.browse_category.name, "Other")
        self.assertEqual(payment.predicted_category.name, "Services")
        self.assertEqual(
            payment.categorisation_source, Transaction.CategorisationSource.ML
        )
        model_prediction.assert_called_once()
        self.assertNotIn(
            item.browse_category.name,
            model_prediction.call_args.kwargs["description"],
        )

    @patch("payments.services.categorisation.Path.exists", return_value=False)
    def test_26_missing_svm_stops_payment_without_rule_fallback(self, _model_exists):
        response = self.purchase()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SVM categorisation model is unavailable")
        self.assertEqual(Transaction.objects.count(), 0)
