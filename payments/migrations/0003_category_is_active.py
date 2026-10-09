from django.db import migrations, models


PURCHASE_CATEGORY_DESCRIPTIONS = {
    "Amazon": "Purchases made through Amazon.",
    "Bills": "Utility, telecommunications, and other household service bills.",
    "Clothes": "Clothing and apparel purchases.",
    "Dine Out": "Restaurants, cafes, food courts, and takeaway purchases.",
    "Entertainment": "Cinema, events, attractions, games, and leisure purchases.",
    "Fitness": "Gym, exercise, and fitness-service purchases.",
    "Food Shopping": "Food purchases labelled as Food Shopping in the source dataset.",
    "Groceries": "Supermarket and grocery purchases.",
    "Health": "Clinic, pharmacy, dental, and other health purchases.",
    "Home Improvement": "Home goods, hardware, appliances, and improvement purchases.",
    "Hotels": "Hotel and accommodation purchases.",
    "Insurance": "Insurance premium payments.",
    "Other Shopping": "Retail purchases outside the more specific shopping categories.",
    "Others": "Debit purchases without a stronger retained source category.",
    "Purchase of uk.eg.org": "Domain-name or web-domain purchases using the source label.",
    "Services": "Personal and general service purchases.",
    "Services/Home Improvement": "Home maintenance and repair service purchases.",
    "Travel": "Public transport, taxi, ride-hailing, and travel purchases.",
}


def activate_source_purchase_categories(apps, schema_editor):
    Category = apps.get_model("payments", "Category")
    Category.objects.update(is_active=False)
    for name, description in PURCHASE_CATEGORY_DESCRIPTIONS.items():
        Category.objects.update_or_create(
            name=name,
            defaults={"description": description, "is_active": True},
        )


def reactivate_all_categories(apps, schema_editor):
    Category = apps.get_model("payments", "Category")
    Category.objects.update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0002_browsecategory_transaction_categorisation_source_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="category",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(
            activate_source_purchase_categories,
            reactivate_all_categories,
        ),
    ]
