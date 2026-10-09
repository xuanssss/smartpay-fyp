from django.db import migrations, models


def add_housing_category(apps, schema_editor):
    Category = apps.get_model("payments", "Category")
    Category.objects.update_or_create(
        name="Housing",
        defaults={
            "description": "Mortgage, rent, and other housing payments.",
            "is_active": True,
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0006_add_other_catalogue_group"),
    ]

    operations = [
        migrations.AddField(
            model_name="transaction",
            name="bank_transaction_type",
            field=models.CharField(
                choices=[
                    ("DEB", "Debit card or wallet"),
                    ("DD", "Direct debit"),
                    ("FPO", "Faster payment / PayNow"),
                    ("PAY", "Bank payment"),
                    ("SO", "Standing order"),
                    ("CPT", "Cashpoint"),
                    ("TFR", "Transfer"),
                    ("BP", "Bill payment"),
                ],
                default="DEB",
                max_length=3,
            ),
        ),
        migrations.RunPython(add_housing_category, migrations.RunPython.noop),
    ]
