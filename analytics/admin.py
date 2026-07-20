from django.contrib import admin
from .models import PerformanceLog, RecurringBill

admin.site.register(RecurringBill)
admin.site.register(PerformanceLog)
