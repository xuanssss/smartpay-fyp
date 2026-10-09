"""Training, evaluation, and inference for the structured transaction SVM."""

from hashlib import sha256
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import scipy
import sklearn
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    precision_recall_fscore_support,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.svm import SVC

from .ml_features import (
    GBP_TO_SGD_RATE,
    MODEL_INPUT_COLUMNS,
    build_feature_engineering,
    build_prediction_frame,
    clean_transaction_description,
)


RANDOM_SEED = 42
TEST_SIZE = 0.20
TARGET_COLUMN = "category"
AUDIT_COLUMN = "source_row_id"
SOURCE_REQUIRED_COLUMNS = {
    AUDIT_COLUMN,
    "transaction_date",
    "transaction_type",
    "description_clean",
    "absolute_amount",
    TARGET_COLUMN,
}
MODEL_FORMAT_VERSION = 2


def _library_versions():
    return {
        "joblib": joblib.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scikit_learn": sklearn.__version__,
        "scipy": scipy.__version__,
    }


def _dataset_hash(csv_path):
    return sha256(Path(csv_path).read_bytes()).hexdigest()


def _load_data(csv_path):
    frame = pd.read_csv(csv_path)
    missing = SOURCE_REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"Dataset is missing columns: {', '.join(sorted(missing))}")
    if frame[list(SOURCE_REQUIRED_COLUMNS)].isna().any().any():
        raise ValueError("Dataset contains missing required values")
    if frame[AUDIT_COLUMN].duplicated().any():
        raise ValueError("source_row_id must be unique")

    frame = frame.copy()
    frame["description_clean"] = frame["description_clean"].map(clean_transaction_description)
    frame["transaction_type"] = frame["transaction_type"].astype(str).str.strip().str.upper()
    amounts_gbp = pd.to_numeric(frame["absolute_amount"], errors="coerce")
    frame["amount_sgd"] = amounts_gbp * GBP_TO_SGD_RATE
    frame["transaction_date"] = pd.to_datetime(frame["transaction_date"], errors="coerce")
    if frame["description_clean"].eq("").any():
        raise ValueError("Dataset contains an empty cleaned description")
    if frame["transaction_type"].eq("").any():
        raise ValueError("Dataset contains an empty transaction type")
    if frame["amount_sgd"].isna().any() or frame["amount_sgd"].le(0).any():
        raise ValueError("Dataset contains an invalid or non-positive amount")
    if frame["transaction_date"].isna().any():
        raise ValueError("Dataset contains an invalid transaction date")
    return frame


def _pipeline():
    return Pipeline([
        ("features", build_feature_engineering()),
        (
            "classifier",
            SVC(
                kernel="linear",
                C=1.0,
                class_weight="balanced",
                probability=True,
                random_state=RANDOM_SEED,
            ),
        ),
    ])


def _split_data(frame, test_size=TEST_SIZE):
    counts = frame[TARGET_COLUMN].value_counts()
    if counts.min() < 2:
        raise ValueError("Every category needs at least two rows for a stratified split")
    return train_test_split(
        frame.loc[:, MODEL_INPUT_COLUMNS],
        frame[TARGET_COLUMN],
        frame[AUDIT_COLUMN],
        test_size=test_size,
        random_state=RANDOM_SEED,
        stratify=frame[TARGET_COLUMN],
    )


def _metrics(y_true, y_pred, labels):
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, average="macro", zero_division=0
    )
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "labels": list(labels),
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=labels),
        "classification_report": classification_report(
            y_true, y_pred, labels=labels, output_dict=True, zero_division=0
        ),
    }


def _feature_metadata(fitted_pipeline):
    features = fitted_pipeline.named_steps["features"]
    block_counts = {
        name: output_slice.stop - output_slice.start
        for name, output_slice in features.output_indices_.items()
        if name != "remainder"
    }
    amount_bucketizer = (
        features.named_transformers_["amount_bucket"].named_steps["bucketizer"]
    )
    return {
        "feature_count": int(sum(block_counts.values())),
        "feature_block_counts": block_counts,
        "amount_percentiles_sgd": amount_bucketizer.thresholds_sgd_.tolist(),
    }


def train_model(csv_path, model_path, test_size=TEST_SIZE):
    """Fit on the 80% training partition, evaluate on the untouched 20%, and persist."""
    frame = _load_data(csv_path)
    x_train, x_test, y_train, y_test, id_train, id_test = _split_data(frame, test_size)
    model = _pipeline()
    model.fit(x_train, y_train)
    labels = sorted(frame[TARGET_COLUMN].unique())
    metrics = _metrics(y_test, model.predict(x_test), labels)
    metrics.update({
        "training_rows": len(x_train),
        "test_rows": len(x_test),
        "training_ids": id_train.tolist(),
        "test_ids": id_test.tolist(),
        **_feature_metadata(model),
    })

    bundle = {
        "format_version": MODEL_FORMAT_VERSION,
        "pipeline": model,
        "metadata": {
            "dataset_sha256": _dataset_hash(csv_path),
            "test_size": test_size,
            "random_seed": RANDOM_SEED,
            "model_input_columns": list(MODEL_INPUT_COLUMNS),
            "labels": labels,
            "training_rows": len(x_train),
            "test_rows": len(x_test),
            "feature_count": metrics["feature_count"],
            "feature_block_counts": metrics["feature_block_counts"],
            "amount_percentiles_sgd": metrics["amount_percentiles_sgd"],
            "classifier": "SVC(kernel='linear', C=1.0, class_weight='balanced')",
            "library_versions": _library_versions(),
        },
    }
    model_path = Path(model_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, model_path)
    return metrics


def _load_model_bundle(model_path):
    bundle = joblib.load(model_path)
    if not isinstance(bundle, dict) or bundle.get("format_version") != MODEL_FORMAT_VERSION:
        raise ValueError("The saved classifier uses an obsolete model format; retrain it")
    return bundle


def predict_category(*, description, transaction_type, amount_sgd, transaction_date, model_path):
    if model_path is None or not Path(model_path).exists():
        return None
    bundle = _load_model_bundle(model_path)
    row = build_prediction_frame(
        description=description,
        transaction_type=transaction_type,
        amount_sgd=amount_sgd,
        transaction_date=transaction_date,
    )
    model = bundle["pipeline"]
    category = str(model.predict(row)[0])
    probabilities = model.predict_proba(row)[0]
    class_index = int(np.where(model.classes_ == category)[0][0])
    return {
        "category": category,
        "confidence": float(probabilities[class_index]),
        "description_clean": row.iloc[0]["description_clean"],
        "transaction_type": row.iloc[0]["transaction_type"],
    }


def evaluate_model(csv_path, model_path, test_size=TEST_SIZE):
    if not Path(model_path).exists():
        raise FileNotFoundError("Trained model not found. Run train_transaction_model first.")
    frame = _load_data(csv_path)
    bundle = _load_model_bundle(model_path)
    metadata = bundle["metadata"]
    if metadata["dataset_sha256"] != _dataset_hash(csv_path):
        raise ValueError("The saved model was trained from a different dataset version")
    saved_versions = metadata.get("library_versions")
    current_versions = _library_versions()
    if saved_versions != current_versions:
        raise ValueError(
            "The saved model dependency versions do not match this environment. "
            f"Saved: {saved_versions}; current: {current_versions}"
        )
    if float(metadata["test_size"]) != float(test_size):
        raise ValueError("The requested split does not match the saved model")
    _, x_test, _, y_test, _, _ = _split_data(frame, test_size)
    labels = metadata["labels"]
    return _metrics(y_test, bundle["pipeline"].predict(x_test), labels)
