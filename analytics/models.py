from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class MonthlyBudget(models.Model):
    """A budget change that applies from its month until a later change."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="monthly_budgets")
    month = models.DateField(help_text="Stored as the first day of the selected month.")
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-month"]
        constraints = [
            models.UniqueConstraint(fields=["user", "month"], name="unique_monthly_budget_per_user"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="monthly_budget_amount_positive"),
        ]

    def save(self, *args, **kwargs):
        if self.month:
            self.month = self.month.replace(day=1)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user} · {self.month:%B %Y} · S${self.amount}"


class PerformanceLog(models.Model):
    class Operation(models.TextChoices):
        CATEGORISATION = "categorisation", "Categorisation"
        DASHBOARD_LOADING = "dashboard_loading", "Dashboard loading"
        ALERT_GENERATION = "alert_generation", "Alert generation"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="performance_logs")
    operation_name = models.CharField(max_length=40, choices=Operation.choices)
    duration_ms = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
