from django.db import migrations


MERCHANT_CATEGORY_BY_KEYWORD = {
    "grab ride": "Travel",
    "grab taxi": "Travel",
    "grab transport": "Travel",
    "grab food": "Dine Out",
    "grab eat": "Dine Out",
    "grab delivery": "Dine Out",
    "foodpanda": "Dine Out",
    "deliveroo": "Dine Out",
    "mcdonald's": "Dine Out",
    "koufu": "Dine Out",
    "starbucks": "Dine Out",
    "comfortdelgro": "Travel",
    "gojek": "Travel",
    "mrt": "Travel",
    "simplygo": "Travel",
    "shopee": "Other Shopping",
    "lazada": "Other Shopping",
    "amazon": "Amazon",
    "fairprice": "Groceries",
    "sp group": "Bills",
    "geneco": "Bills",
    "singtel": "Bills",
    "starhub": "Bills",
    "m1": "Bills",
    "netflix": "Entertainment",
    "spotify": "Entertainment",
    "disney+": "Entertainment",
    "youtube premium": "Entertainment",
    "smu": "Services",
    "coursera": "Services",
    "udemy": "Services",
    "guardian": "Health",
    "watsons": "Health",
    "rent": "Services/Home Improvement",
    "landlord": "Services/Home Improvement",
    "cathay": "Entertainment",
    "golden village": "Entertainment",
}


def catalogue_target(item):
    slug = item.slug
    browse_slug = item.browse_category.slug
    if browse_slug == "food-drinks":
        return "Dine Out"
    if browse_slug == "transport":
        return "Travel"
    if browse_slug == "groceries":
        return "Groceries"
    if browse_slug == "bills":
        return "Bills"
    if browse_slug == "subscriptions":
        return "Services" if "cloud-storage" in slug else "Entertainment"
    if browse_slug == "education":
        return "Amazon" if "university-textbook" in slug else "Services"
    if browse_slug == "healthcare":
        return "Health"
    if browse_slug == "home":
        return "Services/Home Improvement"
    if browse_slug == "entertainment":
        return "Entertainment"
    if browse_slug == "shopping":
        if "t-shirt" in slug or "running-shoes" in slug:
            return "Clothes"
        if "mobile-phone" in slug:
            return "Amazon"
        if "household-organiser" in slug:
            return "Home Improvement"
        return "Other Shopping"
    return "Others"


def align_existing_configuration(apps, schema_editor):
    Category = apps.get_model("payments", "Category")
    MerchantRule = apps.get_model("payments", "MerchantRule")
    CatalogueItem = apps.get_model("payments", "CatalogueItem")
    categories = {category.name: category for category in Category.objects.filter(is_active=True)}

    for rule in MerchantRule.objects.all():
        category_name = MERCHANT_CATEGORY_BY_KEYWORD.get(rule.keyword.casefold().strip())
        if category_name in categories:
            rule.category = categories[category_name]
            rule.save(update_fields=["category"])

    for item in CatalogueItem.objects.select_related("browse_category").all():
        # Rent is outside the purchase-only taxonomy and is removed from the
        # active catalogue without deleting historical records.
        if item.slug == "home-monthly-rent":
            item.is_active = False
            item.save(update_fields=["is_active"])
            continue
        category_name = catalogue_target(item)
        if category_name in categories:
            item.ground_truth_category = categories[category_name]
            item.save(update_fields=["ground_truth_category"])


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0003_category_is_active"),
    ]

    operations = [
        migrations.RunPython(align_existing_configuration, migrations.RunPython.noop),
    ]
