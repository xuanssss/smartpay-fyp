from .models import Alert


def active_alert_count(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"navbar_active_alert_count": 0}
    return {"navbar_active_alert_count": Alert.objects.filter(user=request.user, status=Alert.Status.ACTIVE).count()}
