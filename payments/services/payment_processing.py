from time import perf_counter

from django.db import IntegrityError, transaction as db_transaction
from django.utils import timezone

from alerts.services.alert_generation import generate_alerts
from analytics.models import PerformanceLog
from payments.models import PaymentMethod, Transaction
from .catalog import payment_type_for_item
from .categorisation import categorise_transaction


def bank_transaction_type_for_payment(payment_method, payment_type):
    """Translate app payment context into a MoneyVis-compatible transaction code."""
    if payment_method.method_type == PaymentMethod.MethodType.PAYNOW:
        return Transaction.BankTransactionType.FASTER_PAYMENT
    if payment_method.method_type == PaymentMethod.MethodType.BANK:
        if payment_type == Transaction.PaymentType.BILL:
            return Transaction.BankTransactionType.DIRECT_DEBIT
        if payment_type == Transaction.PaymentType.HOUSING:
            return Transaction.BankTransactionType.STANDING_ORDER
        return Transaction.BankTransactionType.BILL_PAYMENT
    return Transaction.BankTransactionType.DEBIT_CARD


def _validate_method(user, payment_method):
    if not payment_method or payment_method.user_id != user.id or not payment_method.is_active:
        raise ValueError("Select one of your active payment methods.")


def _existing_submission(user, token):
    return Transaction.objects.filter(user=user, submission_token=token).first()


def _finish_new_transaction(transaction, started):
    PerformanceLog.objects.create(
        user=transaction.user,
        operation_name=PerformanceLog.Operation.CATEGORISATION,
        duration_ms=(perf_counter() - started) * 1000,
    )
    generate_alerts(transaction)


def create_catalogue_purchase(*, user, item, quantity, amount, payment_method, submission_token):
    """Create one catalogue transaction; browse/ground truth never choose its prediction."""
    _validate_method(user, payment_method)
    existing = _existing_submission(user, submission_token)
    if existing:
        return existing, False

    started = perf_counter()
    payment_type = payment_type_for_item(item)
    happened = timezone.now()
    bank_transaction_type = bank_transaction_type_for_payment(payment_method, payment_type)
    raw_description = f"{item.merchant_name} {item.name} {item.transaction_description}".upper()
    result = categorise_transaction(
        item.merchant_name,
        payment_type,
        item_name=item.name,
        transaction_description=raw_description,
        amount=amount,
        transaction_date=happened,
        transaction_type=bank_transaction_type,
    )
    try:
        with db_transaction.atomic():
            payment = Transaction.objects.create(
                user=user,
                catalogue_item=item,
                item_name=item.name,
                quantity=quantity,
                unit_price=item.unit_price if item.allows_quantity else None,
                merchant_name=item.merchant_name,
                amount=amount,
                transaction_date=happened,
                payment_type=payment_type,
                bank_transaction_type=bank_transaction_type,
                payment_method=payment_method,
                transaction_description=raw_description,
                predicted_category=result.category,
                final_category=result.category,
                confidence_score=result.confidence,
                category_explanation=result.explanation,
                categorisation_source=result.source,
                # Stored for evaluation only; it was not passed to categorise_transaction().
                ground_truth_category=item.ground_truth_category,
                submission_token=submission_token,
            )
    except IntegrityError:
        duplicate = _existing_submission(user, submission_token)
        if duplicate:
            return duplicate, False
        raise
    _finish_new_transaction(payment, started)
    return payment, True


def create_merchant_payment(*, user, cleaned_data):
    payment_method = cleaned_data["payment_method"]
    submission_token = cleaned_data["submission_token"]
    _validate_method(user, payment_method)
    existing = _existing_submission(user, submission_token)
    if existing:
        return existing, False

    started = perf_counter()
    description = cleaned_data["transaction_description"].strip()
    payment_type = Transaction.PaymentType.OTHERS
    note = ""
    bank_transaction_type = bank_transaction_type_for_payment(
        payment_method, payment_type
    )
    result = categorise_transaction(
        cleaned_data["merchant_name"],
        payment_type,
        note,
        transaction_description=description,
        amount=cleaned_data["amount"],
        transaction_date=cleaned_data["transaction_date"],
        transaction_type=bank_transaction_type,
    )
    try:
        with db_transaction.atomic():
            payment = Transaction.objects.create(
                user=user,
                merchant_name=cleaned_data["merchant_name"],
                amount=cleaned_data["amount"],
                transaction_date=cleaned_data["transaction_date"],
                payment_type=payment_type,
                bank_transaction_type=bank_transaction_type,
                note=note,
                payment_method=payment_method,
                transaction_description=description,
                predicted_category=result.category,
                final_category=result.category,
                confidence_score=result.confidence,
                category_explanation=result.explanation,
                categorisation_source=result.source,
                submission_token=submission_token,
            )
    except IntegrityError:
        duplicate = _existing_submission(user, submission_token)
        if duplicate:
            return duplicate, False
        raise
    _finish_new_transaction(payment, started)
    return payment, True
