from django import forms

from .models import MonthlyBudget


class MonthlyBudgetForm(forms.ModelForm):
    class Meta:
        model = MonthlyBudget
        fields = ("month", "amount")
        labels = {"month": "Budget month", "amount": "Monthly budget"}
        widgets = {
            "month": forms.DateInput(format="%Y-%m", attrs={"type": "month", "class": "form-control"}),
            "amount": forms.NumberInput(
                attrs={"min": "0.01", "step": "0.01", "class": "form-control", "placeholder": "0.00"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["month"].input_formats = ["%Y-%m"]

    def clean_month(self):
        return self.cleaned_data["month"].replace(day=1)
