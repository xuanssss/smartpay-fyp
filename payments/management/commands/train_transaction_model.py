from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from payments.services.ml_categorisation import train_model


class Command(BaseCommand):
    help = "Train and save the MoneyVis structured-feature SVM with an 80/20 split."

    def handle(self, *args, **options):
        csv_path = Path(settings.BASE_DIR) / "data" / "moneyvis_singapore_quality_checked.csv"
        model_path = Path(settings.BASE_DIR) / "models" / "transaction_classifier.joblib"
        metrics = train_model(csv_path, model_path, test_size=0.20)
        self.stdout.write(self.style.SUCCESS(f"Model saved to {model_path}"))
        self._print_metrics(metrics)

    def _print_metrics(self, metrics):
        self.stdout.write(f"Accuracy:  {metrics['accuracy']:.4f}")
        self.stdout.write(f"Precision: {metrics['precision']:.4f}")
        self.stdout.write(f"Recall:    {metrics['recall']:.4f}")
        self.stdout.write(f"F1-score:  {metrics['f1']:.4f}")
        self.stdout.write(
            f"Split:      {metrics['training_rows']:,} training / "
            f"{metrics['test_rows']:,} test rows"
        )
        self.stdout.write(f"Features:   {metrics['feature_count']:,}")
        self.stdout.write("Feature blocks: " + ", ".join(
            f"{name}={count:,}"
            for name, count in metrics["feature_block_counts"].items()
        ))
        self.stdout.write("Labels: " + ", ".join(metrics["labels"]))
        self.stdout.write("Confusion matrix:")
        self.stdout.write(str(metrics["confusion_matrix"]))
