from django.conf import settings
from django.db import models

from payments.models import Category


class RecurringBill(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recurring_bills")
    merchant_name = models.CharField(max_length=150)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="recurring_bills")
    average_amount = models.DecimalField(max_digits=12, decimal_places=2)
    frequency_label = models.CharField(max_length=40, default="Monthly")
    transaction_count = models.PositiveIntegerField()
    last_detected_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "merchant_name"], name="unique_recurring_merchant_per_user")]
        ordering = ["-average_amount"]

    def __str__(self):
        return f"{self.merchant_name} ({self.frequency_label})"


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
