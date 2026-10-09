from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from payments.services.ml_categorisation import evaluate_model


class Command(BaseCommand):
    help = "Re-evaluate the saved MoneyVis SVM on its reproducible 20% holdout."

    def handle(self, *args, **options):
        csv_path = Path(settings.BASE_DIR) / "data" / "moneyvis_singapore_quality_checked.csv"
        model_path = Path(settings.BASE_DIR) / "models" / "transaction_classifier.joblib"
        try:
            metrics = evaluate_model(csv_path, model_path, test_size=0.20)
        except (FileNotFoundError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write("Saved model evaluation")
        self.stdout.write(f"Accuracy:  {metrics['accuracy']:.4f}")
        self.stdout.write(f"Precision: {metrics['precision']:.4f}")
        self.stdout.write(f"Recall:    {metrics['recall']:.4f}")
        self.stdout.write(f"F1-score:  {metrics['f1']:.4f}")
        self.stdout.write("Labels: " + ", ".join(metrics["labels"]))
        self.stdout.write("Confusion matrix:")
        self.stdout.write(str(metrics["confusion_matrix"]))
