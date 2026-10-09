from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import joblib
import numpy as np
from django.test import SimpleTestCase, TestCase

from payments.models import MerchantRule, PaymentMethod, Transaction
from payments.services.categorisation import categorise_transaction
from payments.services.ml_categorisation import MODEL_FORMAT_VERSION, predict_category
from payments.services.ml_features import MODEL_INPUT_COLUMNS, build_prediction_frame
from payments.services.payment_processing import bank_transaction_type_for_payment


class RecordingModel:
    classes_ = np.array(["Dining", "Other"], dtype=object)

    def __init__(self):
        self.received_columns = None
        self.received_row = None

    def predict(self, frame):
        self.received_columns = tuple(frame.columns)
        self.received_row = frame.iloc[0].to_dict()
        return np.array(["Dining"], dtype=object)

    def predict_proba(self, frame):
        return np.array([[0.82, 0.18]])


class StructuredModelInputTests(SimpleTestCase):
    def test_prediction_frame_applies_training_description_cleaning(self):
        frame = build_prediction_frame(
            description="CAFÉ & SHOP 123456",
            transaction_type=" deb ",
            amount_sgd=Decimal("12.50"),
            transaction_date=datetime(2026, 9, 4, 12, 30),
        )

        self.assertTupleEqual(tuple(frame.columns), MODEL_INPUT_COLUMNS)
        self.assertEqual(frame.iloc[0]["description_clean"], "caf and shop refnum")
        self.assertEqual(frame.iloc[0]["transaction_type"], "DEB")
        self.assertEqual(frame.iloc[0]["amount_sgd"], 12.5)

    def test_saved_pipeline_receives_all_four_structured_features(self):
        with TemporaryDirectory() as temporary_directory:
            model_path = Path(temporary_directory) / "model.joblib"
            joblib.dump(
                {
                    "format_version": MODEL_FORMAT_VERSION,
                    "pipeline": RecordingModel(),
                    "metadata": {},
                },
                model_path,
            )
            result = predict_category(
                description="Koufu chicken rice",
                transaction_type="DEB",
                amount_sgd=6.50,
                transaction_date="2026-09-04",
                model_path=model_path,
            )

        self.assertEqual(result["category"], "Dining")
        self.assertAlmostEqual(result["confidence"], 0.82)
        self.assertEqual(result["description_clean"], "koufu chicken rice")
        self.assertEqual(result["transaction_type"], "DEB")

    def test_payment_method_is_mapped_to_moneyvis_transaction_type(self):
        paynow = PaymentMethod(method_type=PaymentMethod.MethodType.PAYNOW)
        bank = PaymentMethod(method_type=PaymentMethod.MethodType.BANK)
        card = PaymentMethod(method_type=PaymentMethod.MethodType.VISA)

        self.assertEqual(
            bank_transaction_type_for_payment(paynow, Transaction.PaymentType.OTHERS),
            Transaction.BankTransactionType.FASTER_PAYMENT,
        )
        self.assertEqual(
            bank_transaction_type_for_payment(bank, Transaction.PaymentType.BILL),
            Transaction.BankTransactionType.DIRECT_DEBIT,
        )
        self.assertEqual(
            bank_transaction_type_for_payment(bank, Transaction.PaymentType.HOUSING),
            Transaction.BankTransactionType.STANDING_ORDER,
        )
        self.assertEqual(
            bank_transaction_type_for_payment(card, Transaction.PaymentType.SHOPPING),
            Transaction.BankTransactionType.DEBIT_CARD,
        )


class CategorisationModelBridgeTests(TestCase):
    @patch("payments.services.categorisation.Path.exists", return_value=True)
    @patch("payments.services.categorisation.ml_predict_category")
    def test_unmatched_transaction_passes_structured_app_values_to_svm(
        self, model_prediction, _model_exists
    ):
        from payments.models import Category

        housing = Category.objects.get(name="Housing", is_active=True)
        other = Category.objects.get(name="Other", is_active=True)
        MerchantRule.objects.create(
            keyword="Unmapped Housing Provider",
            category=other,
            confidence_score=0.99,
            explanation_template="This legacy rule must be ignored.",
        )
        model_prediction.return_value = {"category": housing.name, "confidence": 0.97}

        result = categorise_transaction(
            "Unmapped Housing Provider",
            Transaction.PaymentType.HOUSING,
            transaction_description="monthly rent",
            amount=Decimal("1850.00"),
            transaction_date="2026-09-26",
            transaction_type=Transaction.BankTransactionType.STANDING_ORDER,
        )

        self.assertEqual(result.category, housing)
        self.assertEqual(result.source, Transaction.CategorisationSource.ML)
        self.assertEqual(result.confidence, 0.97)
        model_prediction.assert_called_once_with(
            description="Unmapped Housing Provider monthly rent",
            transaction_type=Transaction.BankTransactionType.STANDING_ORDER,
            amount_sgd=Decimal("1850.00"),
            transaction_date="2026-09-26",
            model_path=model_prediction.call_args.kwargs["model_path"],
        )

    @patch("payments.services.categorisation.ml_predict_category")
    def test_stable_online_marketplace_rule_precedes_svm(self, model_prediction):
        result = categorise_transaction(
            "Amazon",
            item_name="Mobile Phone",
            transaction_description="MOBILE PHONE PURCHASE",
        )
        self.assertEqual(result.category.name, "Online Shopping")
        self.assertEqual(result.source, Transaction.CategorisationSource.MERCHANT)
        self.assertEqual(result.confidence, 0.97)
        model_prediction.assert_not_called()

    @patch("payments.services.categorisation.ml_predict_category")
    def test_grab_ride_context_uses_reusable_context_rule(self, model_prediction):
        result = categorise_transaction(
            "Grab Singapore",
            transaction_description="Airport ride",
        )
        self.assertEqual(result.category.name, "Private Hire & Taxis")
        self.assertEqual(result.source, Transaction.CategorisationSource.COMBINED)
        self.assertEqual(result.confidence, 0.96)
        model_prediction.assert_not_called()

    @patch("payments.services.categorisation.ml_predict_category")
    def test_grab_food_context_maps_to_dining(self, model_prediction):
        result = categorise_transaction(
            "Grab",
            transaction_description="Food delivery order",
        )
        self.assertEqual(result.category.name, "Dining")
        self.assertEqual(result.source, Transaction.CategorisationSource.COMBINED)
        model_prediction.assert_not_called()

    @patch("payments.services.categorisation.Path.exists", return_value=True)
    @patch("payments.services.categorisation.ml_predict_category")
    def test_bare_grab_is_ambiguous_and_falls_through_to_svm(
        self, model_prediction, _model_exists
    ):
        model_prediction.return_value = {"category": "Services", "confidence": 0.61}
        result = categorise_transaction(
            "Grab",
            amount=Decimal("18.20"),
            transaction_date="2026-09-26",
            transaction_type=Transaction.BankTransactionType.DEBIT_CARD,
        )
        self.assertEqual(result.category.name, "Services")
        self.assertEqual(result.source, Transaction.CategorisationSource.ML)
        model_prediction.assert_called_once()

    @patch("payments.services.categorisation.Path.exists", return_value=True)
    @patch("payments.services.categorisation.ml_predict_category")
    def test_context_words_without_supported_merchant_do_not_trigger_rule(
        self, model_prediction, _model_exists
    ):
        model_prediction.return_value = {"category": "Shopping", "confidence": 0.74}
        result = categorise_transaction(
            "Airport Souvenirs",
            transaction_description="Gift shop purchase",
            amount=Decimal("22.00"),
            transaction_date="2026-09-26",
            transaction_type=Transaction.BankTransactionType.DEBIT_CARD,
        )
        self.assertEqual(result.category.name, "Shopping")
        self.assertEqual(result.source, Transaction.CategorisationSource.ML)
        model_prediction.assert_called_once()
