from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from payments.models import Category, Transaction
from .domain_rules import match_high_confidence_rule
from .ml_categorisation import predict_category as ml_predict_category


class CategorisationUnavailable(RuntimeError):
    """Raised when the hybrid categorisation service cannot make a prediction."""


@dataclass(frozen=True)
class CategorisationResult:
    category: Category
    confidence: float
    explanation: str
    source: str

    @property
    def confidence_label(self):
        if self.confidence >= 0.85:
            return "High"
        if self.confidence >= 0.60:
            return "Medium"
        return "Low"


def categorise_transaction(
    merchant_name,
    payment_type="Others",
    note="",
    item_name="",
    transaction_description="",
    *,
    amount=None,
    transaction_date=None,
    transaction_type=None,
):
    """Apply a narrow high-confidence rule layer, then the fitted SVM."""
    del payment_type, note

    rule_match = match_high_confidence_rule(
        merchant_name=merchant_name,
        item_name=item_name,
        transaction_description=transaction_description,
    )
    if rule_match:
        category = Category.objects.filter(
            name=rule_match.category_name, is_active=True
        ).first()
        if category:
            return CategorisationResult(
                category=category,
                confidence=rule_match.confidence,
                explanation=rule_match.explanation,
                source=rule_match.source,
            )

    model_path = Path(settings.BASE_DIR) / "models" / "transaction_classifier.joblib"
    if not model_path.exists():
        raise CategorisationUnavailable(
            "The SVM categorisation model is unavailable. Run "
            "'python manage.py train_transaction_model' first."
        )
    missing_inputs = [
        name
        for name, value in (
            ("amount", amount),
            ("transaction_date", transaction_date),
            ("transaction_type", transaction_type),
        )
        if value is None or value == ""
    ]
    if missing_inputs:
        raise CategorisationUnavailable(
            "SVM categorisation requires: " + ", ".join(missing_inputs)
        )

    model_description = " ".join(
        filter(None, (merchant_name, item_name, transaction_description))
    )
    prediction = ml_predict_category(
        description=model_description,
        transaction_type=transaction_type,
        amount_sgd=amount,
        transaction_date=transaction_date,
        model_path=model_path,
    )
    if not prediction:
        raise CategorisationUnavailable("The SVM did not return a prediction.")

    category = Category.objects.filter(
        name=prediction["category"], is_active=True
    ).first()
    if category is None:
        raise CategorisationUnavailable(
            f"The SVM predicted inactive or unknown category: {prediction['category']}"
        )

    return CategorisationResult(
        category=category,
        confidence=float(prediction["confidence"]),
        explanation=(
            "The SVM compared the cleaned description, transaction type, "
            "relative amount, and day-of-month with its training data."
        ),
        source=Transaction.CategorisationSource.ML,
    )
