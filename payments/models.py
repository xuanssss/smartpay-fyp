from django.conf import settings
from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=80, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class MerchantRule(models.Model):
    keyword = models.CharField(max_length=120, unique=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="merchant_rules")
    confidence_score = models.FloatField(default=0.85)
    explanation_template = models.TextField()

    def __str__(self):
        return f"{self.keyword} → {self.category}"


class Transaction(models.Model):
    class PaymentType(models.TextChoices):
        FOOD = "Food", "Food"
        TRANSPORT = "Transport", "Transport"
        SHOPPING = "Shopping", "Shopping"
        BILL = "Bill", "Bill"
        SUBSCRIPTION = "Subscription", "Subscription"
        EDUCATION = "Education", "Education"
        HEALTHCARE = "Healthcare", "Healthcare"
        HOUSING = "Housing", "Housing"
        ENTERTAINMENT = "Entertainment", "Entertainment"
        OTHERS = "Others", "Others"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="transactions")
    merchant_name = models.CharField(max_length=150)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_date = models.DateTimeField()
    payment_type = models.CharField(max_length=30, choices=PaymentType.choices)
    note = models.TextField(blank=True)
    predicted_category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="predicted_transactions")
    final_category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="final_transactions")
    confidence_score = models.FloatField()
    category_explanation = models.TextField()
    user_corrected = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-transaction_date", "-id"]
        indexes = [
            models.Index(fields=["user", "transaction_date"]),
            models.Index(fields=["user", "merchant_name"]),
        ]

    @property
    def confidence_label(self):
        # TODO-FYP-TWEAK: Adjust confidence thresholds after evaluating the classifier.
        if self.confidence_score >= 0.85:
            return "High"
        if self.confidence_score >= 0.60:
            return "Medium"
        return "Low"

    def __str__(self):
        return f"{self.merchant_name} - S${self.amount}"
