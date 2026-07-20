from django.conf import settings
from django.db import models

from payments.models import Transaction


class Alert(models.Model):
    class AlertType(models.TextChoices):
        DUPLICATE = "duplicate", "Possible duplicate payment"
        UNUSUAL_AMOUNT = "unusual_amount", "Unusual bill amount"
        UNFAMILIAR_HIGH_VALUE = "unfamiliar_high_value", "Unfamiliar high-value merchant"
        HIGH_CATEGORY = "high_category", "High category spending"

    class Severity(models.TextChoices):
        LOW = "Low", "Low"
        MEDIUM = "Medium", "Medium"
        HIGH = "High", "High"

    class Status(models.TextChoices):
        ACTIVE = "Active", "Active"
        REVIEWED = "Reviewed", "Reviewed"
        DISMISSED = "Dismissed", "Dismissed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="alerts")
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name="alerts")
    alert_type = models.CharField(max_length=40, choices=AlertType.choices)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    title = models.CharField(max_length=150)
    message = models.TextField()
    explanation = models.TextField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title
