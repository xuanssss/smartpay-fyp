"""Reviewed purchase-only application taxonomy.

The preprocessing pipeline maps the source workbook's labels into these names
while retaining ``source_category`` for traceability. Browse categories remain
a separate UI concern and must not replace these model targets.
"""

PURCHASE_CATEGORY_DESCRIPTIONS = {
    "Accommodation": "Hotels and other paid accommodation.",
    "Bills": "Utilities, telecommunications, and other household bills.",
    "Clothing": "Clothing, footwear, and apparel purchases.",
    "Dining": "Restaurants, cafes, food courts, takeaway, and food delivery.",
    "Entertainment": "Cinema, events, attractions, games, and leisure purchases.",
    "Fitness": "Gym, exercise, and fitness-service purchases.",
    "Groceries": "Supermarket, market, and grocery purchases.",
    "Healthcare": "Clinic, pharmacy, dental, and other health purchases.",
    "Home Improvement": "Home goods, hardware, appliances, maintenance, and repair.",
    "Housing": "Mortgage, rent, and other housing payments.",
    "Insurance": "Insurance premiums and policy payments.",
    "Online Shopping": "General purchases through online marketplaces and shops.",
    "Other": "Valid debit purchases without a more specific category.",
    "Private Hire & Taxis": "Taxi and ride-hailing journeys.",
    "Public Transport": "Train, metro, bus, and public-transport fares or top-ups.",
    "Services": "Personal, professional, postal, digital, and general services.",
    "Shopping": "General in-store retail purchases outside more specific categories.",
    "Travel & Holidays": "Flights, tours, bookings, and other holiday purchases.",
}

PURCHASE_CATEGORY_NAMES = tuple(PURCHASE_CATEGORY_DESCRIPTIONS)
