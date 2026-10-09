from django.db.models import Q

from payments.models import BrowseCategory, CatalogueItem, Transaction


# TODO-FYP-TWEAK: Keep these browse groups small. They organise the catalogue
# only and are never supplied to the financial categorisation result.
CATALOGUE_GROUPS = (
    {
        "slug": "food",
        "label": "Food",
        "category_slugs": ("food-drinks", "groceries"),
    },
    {
        "slug": "travel",
        "label": "Transport",
        "category_slugs": ("transport",),
    },
    {
        "slug": "essentials",
        "label": "Bills",
        "category_slugs": ("bills", "subscriptions", "home"),
    },
    {
        "slug": "shopping",
        "label": "Shopping",
        "category_slugs": ("shopping",),
    },
    {
        "slug": "lifestyle",
        "label": "Lifestyle",
        "category_slugs": ("education", "healthcare", "entertainment"),
    },
    {
        "slug": "other",
        "label": "Other",
        "category_slugs": ("other",),
    },
)


def get_browse_groups(active_category_slugs=None):
    """Return the small set of UI groups that contain active catalogue data."""
    active_slugs = set(active_category_slugs or ())
    if not active_slugs:
        return [dict(group) for group in CATALOGUE_GROUPS]
    return [
        dict(group)
        for group in CATALOGUE_GROUPS
        if active_slugs.intersection(group["category_slugs"])
    ]


def get_browse_group_for_slug(category_slug):
    """Find the simple UI group for a catalogue item's stored category."""
    return next(
        (dict(group) for group in CATALOGUE_GROUPS if category_slug in group["category_slugs"]),
        {"slug": "other", "label": "Other"},
    )


def get_catalogue(category="all", query=""):
    """Return simple browse groups and matching active catalogue items."""
    categories = BrowseCategory.objects.filter(is_active=True)
    active_slugs = tuple(categories.values_list("slug", flat=True))
    groups = get_browse_groups(active_slugs)
    group_map = {group["slug"]: group for group in groups}

    selected = category
    selected_slugs = None
    if category in group_map:
        selected_slugs = group_map[category]["category_slugs"]
    elif category != "all" and categories.filter(slug=category).exists():
        # Retain old bookmarked category URLs without exposing them in the UI.
        selected_slugs = (category,)
    elif category != "all":
        selected = "all"

    items = CatalogueItem.objects.filter(is_active=True, browse_category__is_active=True).select_related("browse_category")
    if selected_slugs:
        items = items.filter(browse_category__slug__in=selected_slugs)
    search = (query or "").strip()
    if search:
        items = items.filter(
            Q(name__icontains=search)
            | Q(merchant_name__icontains=search)
            | Q(short_description__icontains=search)
            | Q(transaction_description__icontains=search)
            | Q(browse_category__name__icontains=search)
        )
    return groups, selected, items


def payment_type_for_item(item):
    """Provide contextual input only; this does not determine the predicted category."""
    mapping = {
        "food": Transaction.PaymentType.FOOD,
        "food-drinks": Transaction.PaymentType.FOOD,
        "groceries": Transaction.PaymentType.SHOPPING,
        "transport": Transaction.PaymentType.TRANSPORT,
        "shopping": Transaction.PaymentType.SHOPPING,
        "bills": Transaction.PaymentType.BILL,
        "subscriptions": Transaction.PaymentType.SUBSCRIPTION,
        "education": Transaction.PaymentType.EDUCATION,
        "healthcare": Transaction.PaymentType.HEALTHCARE,
        "housing": Transaction.PaymentType.HOUSING,
        "home": Transaction.PaymentType.HOUSING,
        "entertainment": Transaction.PaymentType.ENTERTAINMENT,
        "other": Transaction.PaymentType.OTHERS,
    }
    return mapping.get(item.browse_category.slug, Transaction.PaymentType.OTHERS)
