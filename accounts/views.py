from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from analytics.services.dashboard import (
    get_alert_summary,
    get_category_breakdown,
    get_monthly_total,
    get_recurring_bills,
)
from .forms import RegistrationForm


def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("home")
    return render(request, "registration/register.html", {"form": form})


@login_required
def home(request):
    month = timezone.localdate().replace(day=1)
    breakdown = get_category_breakdown(request.user, month)
    context = {
        "monthly_total": get_monthly_total(request.user, month),
        "top_category": breakdown[0] if breakdown else None,
        "alert_summary": get_alert_summary(request.user),
        "recurring_count": len(get_recurring_bills(request.user)),
    }
    return render(request, "home.html", context)
