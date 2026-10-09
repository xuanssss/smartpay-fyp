import uuid
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Category, CatalogueItem, PaymentMethod, Transaction


class BootstrapFormMixin:
    def apply_bootstrap(self):
        for field in self.fields.values():
            if isinstance(field.widget, forms.HiddenInput):
                continue
            field.widget.attrs["class"] = "form-select" if isinstance(field.widget, forms.Select) else "form-control"


class CataloguePurchaseForm(BootstrapFormMixin, forms.Form):
    quantity = forms.IntegerField(min_value=1, initial=1, widget=forms.NumberInput(attrs={"step": 1}))
    amount = forms.DecimalField(
        min_value=Decimal("0.01"), max_digits=10, decimal_places=2,
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
    )
    payment_method = forms.ModelChoiceField(queryset=PaymentMethod.objects.none(), empty_label="Select a payment method")
    submission_token = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, user, item: CatalogueItem, **kwargs):
        super().__init__(*args, **kwargs)
        self.item = item
        methods = PaymentMethod.objects.filter(user=user, is_active=True)
        self.fields["payment_method"].queryset = methods
        default = methods.filter(is_default=True).first()
        if default and not self.is_bound:
            self.initial["payment_method"] = default.pk
        self.initial.setdefault("submission_token", uuid.uuid4())
        if item.allows_quantity:
            self.fields.pop("amount")
            self.fields["quantity"].min_value = item.minimum_quantity
            self.fields["quantity"].max_value = item.maximum_quantity
            self.fields["quantity"].widget.attrs.update({
                "min": item.minimum_quantity, "max": item.maximum_quantity,
            })
            self.initial.setdefault("quantity", item.minimum_quantity)
        else:
            self.fields.pop("quantity")
            self.initial.setdefault("amount", item.unit_price)
            self.fields["amount"].label = "Payment amount"
        self.apply_bootstrap()

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if not self.item.allows_quantity:
            return 1
        if not self.item.minimum_quantity <= quantity <= self.item.maximum_quantity:
            raise ValidationError(
                f"Choose a quantity from {self.item.minimum_quantity} to {self.item.maximum_quantity}."
            )
        return quantity

    def total_amount(self):
        if self.item.allows_quantity:
            return self.item.unit_price * self.cleaned_data["quantity"]
        return self.cleaned_data["amount"]


class PayAnotherMerchantForm(BootstrapFormMixin, forms.ModelForm):
    amount = forms.DecimalField(
        min_value=Decimal("0.01"), max_digits=12, decimal_places=2,
        widget=forms.NumberInput(attrs={"min": "0.01", "step": "0.01", "placeholder": "0.00"}),
    )
    payment_method = forms.ModelChoiceField(queryset=PaymentMethod.objects.none(), empty_label="Select a payment method")
    submission_token = forms.UUIDField(widget=forms.HiddenInput)

    class Meta:
        model = Transaction
        fields = (
            "merchant_name",
            "transaction_description",
            "amount",
            "transaction_date",
            "payment_method",
        )
        labels = {
            "transaction_description": "What are you paying for?",
        }
        widgets = {
            "merchant_name": forms.TextInput(attrs={"placeholder": "Merchant or service provider"}),
            "transaction_description": forms.TextInput(attrs={"placeholder": "e.g. Airport ride or repair service"}),
            "transaction_date": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        methods = PaymentMethod.objects.filter(user=user, is_active=True)
        self.fields["payment_method"].queryset = methods
        default = methods.filter(is_default=True).first()
        if default and not self.is_bound:
            self.initial["payment_method"] = default.pk
        self.fields["transaction_date"].input_formats = ["%Y-%m-%dT%H:%M"]
        if not self.is_bound:
            self.initial.setdefault("transaction_date", timezone.localtime().strftime("%Y-%m-%dT%H:%M"))
            self.initial.setdefault("submission_token", uuid.uuid4())
        self.apply_bootstrap()


class PaymentMethodForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = PaymentMethod
        fields = ("method_type", "display_name", "last_four", "expiry_month", "expiry_year", "is_default")
        labels = {
            "last_four": "Last four digits",
            "expiry_month": "Expiry month",
            "expiry_year": "Expiry year",
            "is_default": "Use as default",
        }
        widgets = {
            "last_four": forms.TextInput(attrs={"maxlength": 4, "inputmode": "numeric", "placeholder": "4821"}),
            "expiry_month": forms.NumberInput(attrs={"min": 1, "max": 12, "placeholder": "12"}),
            "expiry_year": forms.NumberInput(attrs={"placeholder": str(timezone.localdate().year + 2)}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["method_type"].choices = [
            (value, "Bank Account" if value == PaymentMethod.MethodType.BANK else label)
            for value, label in PaymentMethod.MethodType.choices
        ]
        self.apply_bootstrap()
        self.fields["is_default"].widget.attrs["class"] = "form-check-input"

    def clean(self):
        cleaned = super().clean()
        method_type = cleaned.get("method_type")
        if method_type in PaymentMethod.CARD_TYPES:
            last_four = (cleaned.get("last_four") or "").strip()
            if len(last_four) != 4 or not last_four.isdigit():
                self.add_error("last_four", "Enter exactly four digits. Do not enter a full card number.")
            month = cleaned.get("expiry_month")
            year = cleaned.get("expiry_year")
            if month is None or not 1 <= month <= 12:
                self.add_error("expiry_month", "Enter a month from 1 to 12.")
            if year is None or year < timezone.localdate().year:
                self.add_error("expiry_year", "Enter the current year or a future year.")
        else:
            cleaned["last_four"] = ""
            cleaned["expiry_month"] = None
            cleaned["expiry_year"] = None
        return cleaned


class CategoryCorrectionForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ("final_category",)
        labels = {"final_category": "Choose the correct category"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["final_category"].queryset = Category.objects.filter(is_active=True).order_by("name")
        self.apply_bootstrap()
