from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from payments.models import Category, MerchantRule
from .ml_categorisation import predict_category as ml_predict_category


@dataclass(frozen=True)
class CategorisationResult:
    category: Category
    confidence: float
    explanation: str
    source: str


PAYMENT_TYPE_CATEGORIES = {
    "Food": "Food & Dining",
    "Transport": "Transport",
    "Shopping": "Shopping",
    "Bill": "Utilities",
    "Subscription": "Subscriptions",
    "Education": "Education",
    "Healthcare": "Healthcare",
    "Housing": "Housing / Rent",
    "Entertainment": "Entertainment",
}


def _normalise(value):
    return " ".join((value or "").casefold().replace("’", "'").split())


def categorise_transaction(merchant_name, payment_type="Others", note=""):
    merchant = _normalise(merchant_name)
    searchable = _normalise(f"{merchant_name} {payment_type} {note}")

    rules = MerchantRule.objects.select_related("category").order_by("-confidence_score", "-keyword")
    exact_matches = [rule for rule in rules if merchant == _normalise(rule.keyword)]
    if exact_matches:
        rule = exact_matches[0]
        # TODO-FYP-TWEAK: Exact-rule confidence stays within the documented 0.90–0.99 band.
        confidence = max(0.90, min(rule.confidence_score, 0.99))
        return CategorisationResult(rule.category, confidence, rule.explanation_template, "exact_rule")

    keyword_matches = [rule for rule in rules if _normalise(rule.keyword) in searchable]
    if keyword_matches:
        rule = keyword_matches[0]
        # TODO-FYP-TWEAK: Keyword confidence is capped below exact-rule confidence.
        confidence = min(rule.confidence_score, 0.89)
        return CategorisationResult(rule.category, confidence, rule.explanation_template, "keyword_rule")

    model_path = Path(settings.BASE_DIR) / "models" / "transaction_classifier.joblib"
    if model_path.exists():
        prediction = ml_predict_category(merchant_name, payment_type, note, model_path=model_path)
        if prediction:
            category = Category.objects.filter(name=prediction["category"]).first()
            if category:
                return CategorisationResult(
                    category,
                    max(0.40, min(float(prediction["confidence"]), 0.89)),
                    "The trained categorisation model found similar wording in the sample transaction data.",
                    "ml",
                )

    fallback_name = PAYMENT_TYPE_CATEGORIES.get(payment_type)
    if fallback_name:
        category = Category.objects.get(name=fallback_name)
        # TODO-FYP-TWEAK: Payment-type fallback confidence defaults to 0.60.
        return CategorisationResult(
            category, 0.60,
            f"No strong merchant rule was found, so the selected payment type ({payment_type}) was used.",
            "payment_type",
        )

    others = Category.objects.get(name="Others")
    return CategorisationResult(
        others, 0.40,
        "No strong merchant rule was found, so this transaction was placed under Others.",
        "unknown",
    )
