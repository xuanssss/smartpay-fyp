from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction

from payments.models import Transaction
from payments.services.categorisation import categorise_transaction


class Command(BaseCommand):
    help = (
        "Reapply the current hybrid rule/SVM categoriser to every saved "
        "transaction while preserving user-corrected final categories."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Calculate every result and print the summary without saving changes.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        transactions = Transaction.objects.select_related(
            "predicted_category", "final_category"
        ).order_by("pk")
        total = transactions.count()
        changed = 0
        corrected_final_categories_preserved = 0
        source_counts = Counter()

        with db_transaction.atomic():
            for payment in transactions.iterator():
                try:
                    result = categorise_transaction(
                        merchant_name=payment.merchant_name,
                        payment_type=payment.payment_type,
                        note=payment.note,
                        item_name=payment.item_name,
                        transaction_description=payment.transaction_description,
                        amount=payment.amount,
                        transaction_date=payment.transaction_date,
                        transaction_type=payment.bank_transaction_type,
                    )
                except Exception as exc:
                    raise CommandError(
                        f"Transaction {payment.pk} could not be categorised: {exc}"
                    ) from exc

                source_counts[result.source] += 1
                original_values = (
                    payment.predicted_category_id,
                    payment.final_category_id,
                    payment.confidence_score,
                    payment.category_explanation,
                    payment.categorisation_source,
                )

                payment.predicted_category = result.category
                payment.confidence_score = result.confidence
                payment.category_explanation = result.explanation
                if payment.user_corrected:
                    corrected_final_categories_preserved += 1
                    payment.categorisation_source = (
                        Transaction.CategorisationSource.USER_CORRECTION
                    )
                else:
                    payment.final_category = result.category
                    payment.categorisation_source = result.source

                updated_values = (
                    payment.predicted_category_id,
                    payment.final_category_id,
                    payment.confidence_score,
                    payment.category_explanation,
                    payment.categorisation_source,
                )
                if updated_values != original_values:
                    changed += 1

                if not dry_run:
                    payment.save(
                        update_fields=[
                            "predicted_category",
                            "final_category",
                            "confidence_score",
                            "category_explanation",
                            "categorisation_source",
                            "updated_at",
                        ]
                    )

            if dry_run:
                db_transaction.set_rollback(True)

        action = "Would update" if dry_run else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {changed} of {total} transactions; "
                f"preserved {corrected_final_categories_preserved} "
                "user-corrected final categories."
            )
        )
        for source, count in sorted(source_counts.items()):
            self.stdout.write(f"{source}: {count}")
