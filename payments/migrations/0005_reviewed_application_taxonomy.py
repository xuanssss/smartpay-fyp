from django.db import migrations


FINAL_CATEGORY_DESCRIPTIONS = {
    "Accommodation": "Hotels and other paid accommodation.",
    "Bills": "Utilities, telecommunications, and other household bills.",
    "Clothing": "Clothing, footwear, and apparel purchases.",
    "Dining": "Restaurants, cafes, food courts, takeaway, and food delivery.",
    "Entertainment": "Cinema, events, attractions, games, and leisure purchases.",
    "Fitness": "Gym, exercise, and fitness-service purchases.",
    "Groceries": "Supermarket, market, and grocery purchases.",
    "Healthcare": "Clinic, pharmacy, dental, and other health purchases.",
    "Home Improvement": "Home goods, hardware, appliances, maintenance, and repair.",
    "Insurance": "Insurance premiums and policy payments.",
    "Online Shopping": "General purchases through online marketplaces and shops.",
    "Other": "Valid debit purchases without a more specific category.",
    "Private Hire & Taxis": "Taxi and ride-hailing journeys.",
    "Public Transport": "Train, metro, bus, and public-transport fares or top-ups.",
    "Services": "Personal, professional, postal, digital, and general services.",
    "Shopping": "General in-store retail purchases outside more specific categories.",
    "Travel & Holidays": "Flights, tours, bookings, and other holiday purchases.",
}


DIRECT_LEGACY_MAPPING = {
    "Amazon": "Online Shopping",
    "Bills": "Bills",
    "Clothes": "Clothing",
    "Dine Out": "Dining",
    "Entertainment": "Entertainment",
    "Fitness": "Fitness",
    "Food Shopping": "Groceries",
    "Groceries": "Groceries",
    "Health": "Healthcare",
    "Home Improvement": "Home Improvement",
    "Hotels": "Accommodation",
    "Insurance": "Insurance",
    "Purchase of uk.eg.org": "Services",
    "Services": "Services",
    "Services/Home Improvement": "Home Improvement",
}


def contains(text, terms):
    return any(term in text for term in terms)


def mapped_name(old_name, text=""):
    text = (text or "").casefold()
    if old_name in FINAL_CATEGORY_DESCRIPTIONS:
        return old_name
    if old_name in DIRECT_LEGACY_MAPPING:
        return DIRECT_LEGACY_MAPPING[old_name]
    if old_name == "Other Shopping":
        if contains(text, ("amazon", "shopee", "lazada", "etsy", "online", "marketplace")):
            return "Online Shopping"
        if contains(text, ("t-shirt", "shirt", "shoes", "clothing", "apparel")):
            return "Clothing"
        return "Shopping"
    if old_name == "Travel":
        if contains(text, ("comfortdelgro", "gojek", "grab ride", "grab taxi", "taxi", "private-hire")):
            return "Private Hire & Taxis"
        if contains(text, ("simplygo", "mrt", "sbs transit", "smrt", "ez link", "bus", "train", "rail")):
            return "Public Transport"
        return "Travel & Holidays"
    if old_name == "Others":
        if contains(text, ("domain", "godaddy", "vodien", "exabytes", "singpost", "post office")):
            return "Services"
        return "Other"
    return "Other"


def activate_and_remap(apps, schema_editor):
    Category = apps.get_model("payments", "Category")
    MerchantRule = apps.get_model("payments", "MerchantRule")
    CatalogueItem = apps.get_model("payments", "CatalogueItem")
    Transaction = apps.get_model("payments", "Transaction")

    Category.objects.update(is_active=False)
    categories = {
        name: Category.objects.update_or_create(
            name=name,
            defaults={"description": description, "is_active": True},
        )[0]
        for name, description in FINAL_CATEGORY_DESCRIPTIONS.items()
    }

    for rule in MerchantRule.objects.select_related("category"):
        target = mapped_name(rule.category.name, rule.keyword)
        rule.category = categories[target]
        rule.save(update_fields=["category"])

    for item in CatalogueItem.objects.select_related("ground_truth_category"):
        text = f"{item.merchant_name} {item.name} {item.transaction_description}"
        target = mapped_name(item.ground_truth_category.name, text)
        item.ground_truth_category = categories[target]
        item.save(update_fields=["ground_truth_category"])

    category_fields = ("predicted_category", "final_category", "ground_truth_category")
    for transaction in Transaction.objects.select_related(*category_fields):
        text = " ".join(
            filter(
                None,
                (
                    transaction.merchant_name,
                    transaction.item_name,
                    transaction.transaction_description,
                    transaction.note,
                ),
            )
        )
        changed_fields = []
        for field in category_fields:
            old_category = getattr(transaction, field)
            if old_category is None:
                continue
            target = categories[mapped_name(old_category.name, text)]
            if old_category.pk != target.pk:
                setattr(transaction, field, target)
                changed_fields.append(field)
        if changed_fields:
            transaction.save(update_fields=changed_fields)


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0004_align_existing_purchase_taxonomy"),
    ]

    operations = [
        migrations.RunPython(activate_and_remap, migrations.RunPython.noop),
    ]
