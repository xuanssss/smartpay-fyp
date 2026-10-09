from decimal import Decimal

from django.db import migrations


OTHER_ITEMS = (
    ("other-parcel-postage", "Parcel Postage", "SingPost", "PARCEL POSTAGE SERVICE", "4.80", "Services", True),
    ("other-printing-service", "Printing Service", "Print Hub", "DOCUMENT PRINTING SERVICE", "2.50", "Services", True),
    ("other-laundry-service", "Laundry Service", "WashLab", "LAUNDRY SERVICE", "12.00", "Services", True),
    ("other-gift-card", "Gift Card", "City Gifts", "GENERAL PURPOSE GIFT CARD", "25.00", "Other", False),
    ("other-donation", "Donation", "Community Fund", "CHARITABLE DONATION", "10.00", "Other", False),
)


def add_other_catalogue_group(apps, schema_editor):
    BrowseCategory = apps.get_model("payments", "BrowseCategory")
    CatalogueItem = apps.get_model("payments", "CatalogueItem")
    Category = apps.get_model("payments", "Category")

    # Emoji artwork is no longer used by the payment catalogue.
    BrowseCategory.objects.update(icon_name="")
    CatalogueItem.objects.update(icon_name="")

    other_group, _ = BrowseCategory.objects.update_or_create(
        slug="other",
        defaults={
            "name": "Other",
            "description": "Miscellaneous payments and services",
            "icon_name": "",
            "display_order": 10,
            "is_active": True,
        },
    )

    categories = {
        category.name: category
        for category in Category.objects.filter(name__in=("Services", "Other"), is_active=True)
    }
    for order, (slug, name, merchant, description, price, category_name, allows_quantity) in enumerate(OTHER_ITEMS):
        CatalogueItem.objects.update_or_create(
            slug=slug,
            defaults={
                "name": name,
                "browse_category": other_group,
                "merchant_name": merchant,
                "transaction_description": description,
                "short_description": "",
                "unit_price": Decimal(price),
                "icon_name": "",
                "allows_quantity": allows_quantity,
                "minimum_quantity": 1,
                "maximum_quantity": 8,
                "is_active": True,
                "display_order": order,
                "ground_truth_category": categories[category_name],
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0005_reviewed_application_taxonomy"),
    ]

    operations = [
        migrations.RunPython(add_other_catalogue_group, migrations.RunPython.noop),
    ]
