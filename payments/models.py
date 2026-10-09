from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction as db_transaction
from django.db.models import Q


class Category(models.Model):
    name = models.CharField(max_length=80, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class MerchantRule(models.Model):
    """Legacy data model retained for migration compatibility; runtime categorisation ignores it."""

    keyword = models.CharField(max_length=120, unique=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="merchant_rules")
    confidence_score = models.FloatField(default=0.85)
    explanation_template = models.TextField()

    def __str__(self):
        return f"{self.keyword} → {self.category}"


class BrowseCategory(models.Model):
    """A navigation category only; it is never a financial prediction."""

    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=90, unique=True)
    description = models.TextField(blank=True)
    icon_name = models.CharField(max_length=40, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name


class CatalogueItem(models.Model):
    """A simulated product/service offered inside the payment prototype.

    ``browse_category`` controls navigation only. ``ground_truth_category`` is
    reserved for offline evaluation. Neither field is passed directly to the
    normal categorisation result.
    """

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    browse_category = models.ForeignKey(BrowseCategory, on_delete=models.PROTECT, related_name="items")
    merchant_name = models.CharField(max_length=150)
    transaction_description = models.CharField(max_length=240)
    short_description = models.CharField(max_length=180, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)])
    icon_name = models.CharField(max_length=40, blank=True)
    allows_quantity = models.BooleanField(default=True)
    minimum_quantity = models.PositiveIntegerField(default=1)
    maximum_quantity = models.PositiveIntegerField(default=10)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    # Evaluation label only. Never copy this value into predicted_category.
    ground_truth_category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="catalogue_ground_truth_items"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["browse_category__display_order", "display_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["browse_category", "name"], name="unique_item_name_per_browse_category")
        ]

    def clean(self):
        if self.minimum_quantity < 1:
            raise ValidationError({"minimum_quantity": "Minimum quantity must be at least 1."})
        if self.maximum_quantity < self.minimum_quantity:
            raise ValidationError({"maximum_quantity": "Maximum quantity must not be below the minimum."})

    def __str__(self):
        return self.name


class PaymentMethod(models.Model):
    class MethodType(models.TextChoices):
        VISA = "Visa", "Visa"
        MASTERCARD = "Mastercard", "Mastercard"
        APPLE_PAY = "Apple Pay", "Apple Pay"
        GOOGLE_PAY = "Google Pay", "Google Pay"
        PAYNOW = "PayNow", "PayNow"
        GRABPAY = "GrabPay", "GrabPay"
        BANK = "Simulated Bank Account", "Simulated Bank Account"

    CARD_TYPES = {MethodType.VISA, MethodType.MASTERCARD}

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payment_methods")
    method_type = models.CharField(max_length=40, choices=MethodType.choices)
    display_name = models.CharField(max_length=80)
    last_four = models.CharField(max_length=4, blank=True)
    expiry_month = models.PositiveSmallIntegerField(null=True, blank=True)
    expiry_year = models.PositiveSmallIntegerField(null=True, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_simulated = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_default", "display_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"], condition=Q(is_default=True, is_active=True),
                name="one_active_default_payment_method_per_user",
            )
        ]

    @property
    def is_card(self):
        return self.method_type in self.CARD_TYPES

    @property
    def safe_display(self):
        return f"{self.display_name} •••• {self.last_four}" if self.is_card and self.last_four else self.display_name

    def save(self, *args, **kwargs):
        with db_transaction.atomic():
            if self.is_active and not self.pk and not PaymentMethod.objects.filter(user=self.user, is_active=True).exists():
                self.is_default = True
            if self.is_default and self.is_active:
                PaymentMethod.objects.filter(user=self.user, is_active=True, is_default=True).exclude(pk=self.pk).update(is_default=False)
            super().save(*args, **kwargs)

    def deactivate(self):
        was_default = self.is_default
        self.is_active = False
        self.is_default = False
        self.save(update_fields=["is_active", "is_default", "updated_at"])
        if was_default:
            replacement = PaymentMethod.objects.filter(user=self.user, is_active=True).order_by("created_at").first()
            if replacement:
                replacement.is_default = True
                replacement.save(update_fields=["is_default", "updated_at"])

    def __str__(self):
        return self.safe_display


class Transaction(models.Model):
    class BankTransactionType(models.TextChoices):
        DEBIT_CARD = "DEB", "Debit card or wallet"
        DIRECT_DEBIT = "DD", "Direct debit"
        FASTER_PAYMENT = "FPO", "Faster payment / PayNow"
        PAYMENT = "PAY", "Bank payment"
        STANDING_ORDER = "SO", "Standing order"
        CASHPOINT = "CPT", "Cashpoint"
        TRANSFER = "TFR", "Transfer"
        BILL_PAYMENT = "BP", "Bill payment"

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

    class CategorisationSource(models.TextChoices):
        # MERCHANT and COMBINED are used by the narrow domain-rule layer.
        # The other rule/fallback values are retained for historical records.
        EXACT_ITEM = "Exact item rule", "Exact item rule"
        MERCHANT = "Merchant rule", "Merchant rule"
        COMBINED = "Combined keyword rule", "Combined keyword rule"
        ML = "Machine-learning model", "Machine-learning model"
        PAYMENT_TYPE = "Payment-type fallback", "Payment-type fallback"
        OTHERS = "Others fallback", "Others fallback"
        USER_CORRECTION = "User correction", "User correction"
        LEGACY = "Legacy transaction", "Legacy transaction"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="transactions")
    merchant_name = models.CharField(max_length=150)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_date = models.DateTimeField()
    payment_type = models.CharField(max_length=30, choices=PaymentType.choices)
    # Structured ML feature derived from the selected simulated payment method.
    bank_transaction_type = models.CharField(
        max_length=3,
        choices=BankTransactionType.choices,
        default=BankTransactionType.DEBIT_CARD,
    )
    note = models.TextField(blank=True)
    catalogue_item = models.ForeignKey(
        CatalogueItem, on_delete=models.SET_NULL, null=True, blank=True, related_name="purchase_transactions"
    )
    item_name = models.CharField(max_length=120, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    payment_method = models.ForeignKey(
        PaymentMethod, on_delete=models.SET_NULL, null=True, blank=True, related_name="transactions"
    )
    transaction_description = models.TextField(blank=True)
    categorisation_source = models.CharField(
        max_length=40, choices=CategorisationSource.choices, default=CategorisationSource.LEGACY
    )
    ground_truth_category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="ground_truth_transactions"
    )
    submission_token = models.UUIDField(null=True, blank=True, unique=True)
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
