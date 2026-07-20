from django.contrib import admin
from .models import Category, MerchantRule, Transaction

admin.site.register(Category)
admin.site.register(MerchantRule)
admin.site.register(Transaction)
