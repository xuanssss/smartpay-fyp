from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from .models import Alert


@login_required
def alert_list(request):
    alerts = Alert.objects.filter(user=request.user).select_related("transaction")
    return render(request, "alerts/alert_list.html", {"alerts": alerts})


@login_required
def update_alert_status(request, pk, status):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    alert = get_object_or_404(Alert, pk=pk, user=request.user)
    allowed = {Alert.Status.REVIEWED, Alert.Status.DISMISSED}
    if status not in allowed:
        messages.error(request, "That alert status is not available.")
    else:
        alert.status = status
        alert.save(update_fields=["status"])
        messages.success(request, f"Alert marked as {status.lower()}.")
    return redirect("alert_list")
