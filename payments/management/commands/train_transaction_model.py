from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from payments.services.ml_categorisation import train_model


class Command(BaseCommand):
    help = "Train and save the sample transaction categorisation model."

    def handle(self, *args, **options):
        csv_path = Path(settings.BASE_DIR) / "data" / "sample_transactions.csv"
        model_path = Path(settings.BASE_DIR) / "models" / "transaction_classifier.joblib"
        metrics = train_model(csv_path, model_path)
        self.stdout.write(self.style.SUCCESS(f"Model saved to {model_path}"))
        self._print_metrics(metrics)

    def _print_metrics(self, metrics):
        self.stdout.write(f"Accuracy:  {metrics['accuracy']:.4f}")
        self.stdout.write(f"Precision: {metrics['precision']:.4f}")
        self.stdout.write(f"Recall:    {metrics['recall']:.4f}")
        self.stdout.write(f"F1-score:  {metrics['f1']:.4f}")
        self.stdout.write("Labels: " + ", ".join(metrics["labels"]))
        self.stdout.write("Confusion matrix:")
        self.stdout.write(str(metrics["confusion_matrix"]))
