from django import forms
from django.utils import timezone

from .models import Category, Transaction


class BootstrapFormMixin:
    def apply_bootstrap(self):
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-select" if isinstance(field.widget, forms.Select) else "form-control"


class PaymentForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ("merchant_name", "amount", "transaction_date", "payment_type", "note")
        widgets = {
            "merchant_name": forms.TextInput(attrs={"placeholder": "e.g. SP Group"}),
            "amount": forms.NumberInput(attrs={"min": "0.01", "step": "0.01", "placeholder": "0.00"}),
            "transaction_date": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "note": forms.Textarea(attrs={"rows": 3, "placeholder": "Optional note"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["transaction_date"].input_formats = ["%Y-%m-%dT%H:%M"]
        if not self.is_bound:
            self.initial["transaction_date"] = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
        self.apply_bootstrap()


class CategoryCorrectionForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ("final_category",)
        labels = {"final_category": "Choose the correct category"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["final_category"].queryset = Category.objects.order_by("name")
        self.apply_bootstrap()
