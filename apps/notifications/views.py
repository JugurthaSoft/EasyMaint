from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import services
from .models import Notification


@login_required
def notification_list(request):
    queryset = Notification.objects.filter(user=request.user)
    if request.GET.get("filtre") == "non-lues":
        queryset = queryset.filter(read_at__isnull=True)
    page = Paginator(queryset, 30).get_page(request.GET.get("page"))
    return render(request, "notifications/list.html", {
        "page_obj": page, "notifications": page.object_list, "filter": request.GET.get("filtre", ""),
        "unread_total": services.unread(request.user).count(),
    })


@login_required
def notification_open(request, pk):
    """Marque la notification comme lue puis ouvre l'élément concerné."""
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at", "updated_at"])
    target = notification.url
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(target)
    return redirect("notifications:list")


@login_required
@require_POST
def notification_read_all(request):
    services.mark_read(request.user)
    return redirect(request.POST.get("next") if url_has_allowed_host_and_scheme(
        request.POST.get("next", ""), allowed_hosts={request.get_host()}) else "notifications:list")
