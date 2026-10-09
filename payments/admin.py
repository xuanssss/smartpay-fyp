from django.contrib import admin
from .models import BrowseCategory, CatalogueItem, Category, PaymentMethod, Transaction

admin.site.register(Category)
admin.site.register(Transaction)
admin.site.register(BrowseCategory)
admin.site.register(CatalogueItem)
admin.site.register(PaymentMethod)
