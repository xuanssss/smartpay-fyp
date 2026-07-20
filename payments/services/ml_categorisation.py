from pathlib import Path

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline


REQUIRED_COLUMNS = {"merchant_name", "payment_type", "note", "category"}


def _load_data(csv_path):
    frame = pd.read_csv(csv_path).fillna("")
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"Dataset is missing columns: {', '.join(sorted(missing))}")
    frame["text"] = frame["merchant_name"] + " " + frame["payment_type"] + " " + frame["note"]
    return frame


def _pipeline():
    # TODO-FYP-TWEAK: Replace Logistic Regression or tune TF-IDF settings for the final ML experiment.
    return Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), lowercase=True, min_df=1)),
        ("classifier", LogisticRegression(max_iter=1000, random_state=42)),
    ])


def _metrics(y_true, y_pred, labels):
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="weighted", zero_division=0
    )
    return {
        "accuracy": accuracy_score(y_true, y_pred),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "labels": labels,
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=labels),
    }


def train_model(csv_path, model_path, test_size=0.25):
    frame = _load_data(csv_path)
    counts = frame["category"].value_counts()
    stratify = frame["category"] if counts.min() >= 2 else None
    x_train, x_test, y_train, y_test = train_test_split(
        frame["text"], frame["category"], test_size=test_size, random_state=42, stratify=stratify
    )
    evaluation_model = _pipeline()
    evaluation_model.fit(x_train, y_train)
    labels = sorted(frame["category"].unique())
    metrics = _metrics(y_test, evaluation_model.predict(x_test), labels)

    model_path = Path(model_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    # Save the model fitted only on the training partition so the evaluation
    # command can measure it against the same reproducible, unseen test split.
    joblib.dump(evaluation_model, model_path)
    return metrics


def predict_category(merchant_name, payment_type="Others", note="", model_path=None):
    if model_path is None or not Path(model_path).exists():
        return None
    model = joblib.load(model_path)
    text = f"{merchant_name} {payment_type} {note}"
    category = model.predict([text])[0]
    confidence = float(model.predict_proba([text])[0].max())
    return {"category": category, "confidence": confidence}


def evaluate_model(csv_path, model_path, test_size=0.25):
    if not Path(model_path).exists():
        raise FileNotFoundError("Trained model not found. Run train_transaction_model first.")
    frame = _load_data(csv_path)
    counts = frame["category"].value_counts()
    stratify = frame["category"] if counts.min() >= 2 else None
    _, x_test, _, y_test = train_test_split(
        frame["text"], frame["category"], test_size=test_size, random_state=42, stratify=stratify
    )
    model = joblib.load(model_path)
    labels = sorted(frame["category"].unique())
    return _metrics(y_test, model.predict(x_test), labels)
