from dataclasses import dataclass
import re

from payments.models import Transaction
from .ml_features import clean_transaction_description


@dataclass(frozen=True)
class DomainRuleMatch:
    category_name: str
    confidence: float
    explanation: str
    source: str


# HUMAN REVIEW: Keep this mapping small. Add only merchants whose business
# context is stable enough to justify deterministic categorisation; never add
# transaction dates, amounts, reference numbers, or individual records.
EXACT_MERCHANT_RULES = {
    "amazon": ("Online Shopping", "a recognised online marketplace"),
    "shopee": ("Online Shopping", "a recognised online marketplace"),
    "lazada": ("Online Shopping", "a recognised online marketplace"),
    "fairprice": ("Groceries", "a recognised grocery merchant"),
    "ntuc fairprice": ("Groceries", "a recognised grocery merchant"),
    "sheng siong": ("Groceries", "a recognised grocery merchant"),
    "comfortdelgro": ("Private Hire & Taxis", "a recognised taxi provider"),
    "simplygo": ("Public Transport", "a recognised public-transport provider"),
    "mrt": ("Public Transport", "a recognised public-transport provider"),
    "smrt": ("Public Transport", "a recognised public-transport provider"),
    "sbs transit": ("Public Transport", "a recognised public-transport provider"),
    "sp group": ("Bills", "a recognised utility provider"),
}

RIDE_CONTEXT = re.compile(
    r"\b(?:ride|taxi|transport|trip|airport|pick\s*up|pickup|drop\s*off|dropoff)\b"
)
FOOD_CONTEXT = re.compile(r"\b(?:food|meal|eat|eats|delivery|takeaway)\b")
MULTI_SERVICE_MERCHANTS = {"grab", "gojek"}

# Rule scores are explicit rule-strength indicators, not learned probabilities.
EXACT_RULE_CONFIDENCE = 0.97
CONTEXT_RULE_CONFIDENCE = 0.96


def match_high_confidence_rule(
    *, merchant_name, item_name="", transaction_description=""
):
    """Return a reusable high-confidence domain rule or None.

    Multi-service merchants require contextual wording. A bare "Grab" or
    "Gojek" is intentionally left to the SVM because it is ambiguous.
    """
    merchant = clean_transaction_description(merchant_name)
    combined = clean_transaction_description(
        " ".join(filter(None, (merchant_name, item_name, transaction_description)))
    )

    # Only the merchant field identifies a multi-service provider. Context
    # elsewhere then disambiguates the service; a generic use of words such as
    # "grab" in an item description must not activate this rule.
    multi_service_match = any(
        re.search(rf"\b{re.escape(name)}\b", merchant)
        for name in MULTI_SERVICE_MERCHANTS
    )
    if multi_service_match:
        if FOOD_CONTEXT.search(combined):
            return DomainRuleMatch(
                category_name="Dining",
                confidence=CONTEXT_RULE_CONFIDENCE,
                explanation=(
                    "A multi-service merchant was accompanied by explicit "
                    "food or delivery wording."
                ),
                source=Transaction.CategorisationSource.COMBINED,
            )
        if RIDE_CONTEXT.search(combined):
            return DomainRuleMatch(
                category_name="Private Hire & Taxis",
                confidence=CONTEXT_RULE_CONFIDENCE,
                explanation=(
                    "A multi-service merchant was accompanied by explicit "
                    "ride, taxi, transport, or airport wording."
                ),
                source=Transaction.CategorisationSource.COMBINED,
            )
        return None

    exact_rule = EXACT_MERCHANT_RULES.get(merchant)
    if exact_rule:
        category_name, reason = exact_rule
        return DomainRuleMatch(
            category_name=category_name,
            confidence=EXACT_RULE_CONFIDENCE,
            explanation=f"The merchant is {reason}.",
            source=Transaction.CategorisationSource.MERCHANT,
        )
    return None
