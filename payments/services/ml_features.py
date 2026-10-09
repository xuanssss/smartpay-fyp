"""Reusable feature engineering for MoneyVis training and app inference.

The fitted transformer is stored inside the model pipeline.  The Django app
therefore cannot accidentally rebuild a different TF-IDF vocabulary, lexicon,
amount percentile boundary, or one-hot category at prediction time.
"""

from collections import Counter
import re
import unicodedata

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.utils.validation import check_is_fitted


# Frozen ECB euro reference rates for 1 August 2025. Both are quoted per EUR,
# so SGD per GBP is (SGD per EUR) / (GBP per EUR).
FX_REFERENCE_DATE = "2025-08-01"
ECB_EUR_TO_GBP = 0.86650
ECB_EUR_TO_SGD = 1.4811
GBP_TO_SGD_RATE = ECB_EUR_TO_SGD / ECB_EUR_TO_GBP
FX_SOURCE_URL = (
    "https://www.ecb.europa.eu/stats/exchange/eurofxref/shared/pdf/2025/08/"
    "20250801.pdf"
)

MODEL_INPUT_COLUMNS = (
    "description_clean",
    "transaction_type",
    "amount_sgd",
    "transaction_date",
)
AMOUNT_PERCENTILES = np.array([0.10, 0.25, 0.50, 0.75, 0.90])
AMOUNT_BUCKET_LABELS = np.array(
    ["le_p10", "p10_p25", "p25_p50", "p50_p75", "p75_p90", "gt_p90"],
    dtype=object,
)
DAY_BUCKET_LABELS = np.array(
    ["days_01_05", "days_06_10", "days_11_20", "days_21_25", "days_26_end"],
    dtype=object,
)
TOKEN_PATTERN = re.compile(r"\b\w+\b", flags=re.UNICODE)


def clean_transaction_description(value) -> str:
    """Apply the same description cleaning used by data preprocessing."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.replace("&", " and ")
    text = re.sub(r"\b\d{5,}\b", " refnum ", text)
    text = re.sub(r"[^a-z0-9'+./ -]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def build_prediction_frame(*, description, transaction_type, amount_sgd, transaction_date):
    """Create the single-row schema consumed by the fitted model pipeline."""
    cleaned_description = clean_transaction_description(description)
    if not cleaned_description:
        raise ValueError("A non-empty transaction description is required")
    transaction_type = str(transaction_type or "").strip().upper()
    if not transaction_type:
        raise ValueError("A transaction type is required")
    amount_sgd = float(amount_sgd)
    if not np.isfinite(amount_sgd) or amount_sgd <= 0:
        raise ValueError("The SGD transaction amount must be finite and positive")
    transaction_date = pd.to_datetime(transaction_date, errors="coerce")
    if pd.isna(transaction_date):
        raise ValueError("A valid transaction date is required")
    return pd.DataFrame(
        [{
            "description_clean": cleaned_description,
            "transaction_type": transaction_type,
            "amount_sgd": amount_sgd,
            "transaction_date": transaction_date,
        }],
        columns=MODEL_INPUT_COLUMNS,
    )


def _as_text_array(values) -> np.ndarray:
    if isinstance(values, pd.DataFrame):
        values = values.iloc[:, 0]
    if isinstance(values, pd.Series):
        return values.fillna("").astype(str).to_numpy()
    array = np.asarray(values, dtype=object)
    if array.ndim == 2:
        array = array[:, 0]
    return pd.Series(array).fillna("").astype(str).to_numpy()


def _description_terms(text: str) -> tuple[list[str], list[str]]:
    tokens = TOKEN_PATTERN.findall(str(text).casefold())
    bigrams = [f"{left} {right}" for left, right in zip(tokens, tokens[1:])]
    return tokens, bigrams


class CategoryLexiconTransformer(BaseEstimator, TransformerMixin):
    """Learn category unigram/bigram lexicons from training labels only."""

    def __init__(self, min_unigram_count=5, min_bigram_count=3, max_terms_per_category=120):
        self.min_unigram_count = min_unigram_count
        self.min_bigram_count = min_bigram_count
        self.max_terms_per_category = max_terms_per_category

    def fit(self, X, y):
        if y is None:
            raise ValueError("Category labels are required when learning lexicons")
        texts = _as_text_array(X)
        labels = np.asarray(y, dtype=object)
        if len(texts) != len(labels):
            raise ValueError("Descriptions and category labels have different lengths")

        self.categories_ = np.array(sorted(pd.unique(labels)), dtype=object)
        self.lexicons_ = {}
        self.lexicon_rankings_ = {}
        for category in self.categories_:
            unigram_counts = Counter()
            bigram_counts = Counter()
            for text in texts[labels == category]:
                tokens, bigrams = _description_terms(text)
                unigram_counts.update(tokens)
                bigram_counts.update(bigrams)
            eligible = [
                (term, count)
                for term, count in unigram_counts.items()
                if count >= self.min_unigram_count
            ]
            eligible.extend(
                (term, count)
                for term, count in bigram_counts.items()
                if count >= self.min_bigram_count
            )
            ranking = sorted(eligible, key=lambda item: (-item[1], item[0]))[
                : self.max_terms_per_category
            ]
            self.lexicon_rankings_[category] = ranking
            self.lexicons_[category] = {term for term, _ in ranking}
        return self

    def transform(self, X):
        check_is_fitted(self, ["categories_", "lexicons_"])
        texts = _as_text_array(X)
        values = np.zeros((len(texts), len(self.categories_)), dtype=np.float64)
        for row_index, text in enumerate(texts):
            tokens, bigrams = _description_terms(text)
            denominator = max(len(tokens), 1)
            term_counts = Counter(tokens + bigrams)
            for category_index, category in enumerate(self.categories_):
                match_count = sum(term_counts[term] for term in self.lexicons_[category])
                values[row_index, category_index] = match_count / denominator
        return sparse.csr_matrix(values)

    def get_feature_names_out(self, input_features=None):
        check_is_fitted(self, ["categories_"])
        return np.array(
            [f"lexicon_match__{category}" for category in self.categories_],
            dtype=object,
        )


def _as_numeric_array(values) -> np.ndarray:
    if isinstance(values, pd.DataFrame):
        values = values.iloc[:, 0]
    return pd.to_numeric(np.asarray(values).reshape(-1), errors="coerce").astype(float)


class TrainingPercentileAmountBucketizer(BaseEstimator, TransformerMixin):
    """Learn global SGD amount boundaries from training rows only."""

    def fit(self, X, y=None):
        amounts_sgd = _as_numeric_array(X)
        if not np.isfinite(amounts_sgd).all() or (amounts_sgd <= 0).any():
            raise ValueError("Training amounts must be finite and positive")
        self.thresholds_sgd_ = np.quantile(
            amounts_sgd, AMOUNT_PERCENTILES, method="linear"
        )
        return self

    def transform(self, X):
        check_is_fitted(self, ["thresholds_sgd_"])
        amounts_sgd = _as_numeric_array(X)
        if not np.isfinite(amounts_sgd).all() or (amounts_sgd <= 0).any():
            raise ValueError("Amounts must be finite and positive")
        bucket_indices = np.searchsorted(self.thresholds_sgd_, amounts_sgd, side="right")
        return AMOUNT_BUCKET_LABELS[bucket_indices].reshape(-1, 1)

    def get_feature_names_out(self, input_features=None):
        return np.array(["amount_bucket"], dtype=object)


class DayOfMonthBucketizer(BaseEstimator, TransformerMixin):
    def fit(self, X, y=None):
        self.is_fitted_ = True
        return self

    def transform(self, X):
        check_is_fitted(self, ["is_fitted_"])
        if isinstance(X, pd.DataFrame):
            X = X.iloc[:, 0]
        dates = pd.to_datetime(np.asarray(X).reshape(-1), errors="coerce")
        if dates.isna().any():
            raise ValueError("An invalid transaction date cannot be bucketed")
        days = np.asarray(dates.day)
        bucket_indices = np.select(
            [days <= 5, days <= 10, days <= 20, days <= 25],
            [0, 1, 2, 3],
            default=4,
        ).astype(int)
        return DAY_BUCKET_LABELS[bucket_indices].reshape(-1, 1)

    def get_feature_names_out(self, input_features=None):
        return np.array(["day_bucket"], dtype=object)


def build_feature_engineering() -> ColumnTransformer:
    """Build Section 4.5 as one train-fitted sparse transformer."""
    amount_pipeline = Pipeline([
        ("bucketizer", TrainingPercentileAmountBucketizer()),
        ("onehot", OneHotEncoder(handle_unknown="ignore")),
    ])
    day_pipeline = Pipeline([
        ("bucketizer", DayOfMonthBucketizer()),
        ("onehot", OneHotEncoder(handle_unknown="ignore")),
    ])
    return ColumnTransformer(
        transformers=[
            (
                "word_tfidf",
                TfidfVectorizer(
                    analyzer="word",
                    ngram_range=(1, 2),
                    min_df=2,
                    max_df=0.995,
                    sublinear_tf=True,
                    strip_accents="unicode",
                    max_features=30_000,
                    lowercase=True,
                    token_pattern=r"(?u)\b\w+\b",
                ),
                "description_clean",
            ),
            (
                "character_tfidf",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(3, 5),
                    max_features=40_000,
                    lowercase=True,
                    strip_accents="unicode",
                ),
                "description_clean",
            ),
            ("category_lexicon", CategoryLexiconTransformer(), "description_clean"),
            (
                "transaction_type",
                OneHotEncoder(handle_unknown="ignore"),
                ["transaction_type"],
            ),
            ("amount_bucket", amount_pipeline, ["amount_sgd"]),
            ("day_bucket", day_pipeline, ["transaction_date"]),
        ],
        remainder="drop",
        sparse_threshold=1.0,
        verbose_feature_names_out=True,
    )
