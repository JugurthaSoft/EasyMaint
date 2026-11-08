from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from . import blocks as registry
from .models import DashboardLayout


@login_required
def home(request):
    """Accueil : blocs choisis par l'utilisateur (ou présentation de son rôle), chacun selon ses droits."""
    user = request.user
    if user.tenant_id is None:
        # Super-administrateur de la plateforme : pas de données d'entreprise.
        return redirect("admin:index")
    keys, customized = registry.layout(user)
    blocks, context = registry.build(request, keys)
    context.update({
        "today": timezone.localdate(), "blocks": blocks, "customized": customized,
        "needs_chart": any(block.chart for block in blocks), "has_any_block": bool(registry.available(user)),
    })
    return render(request, "dashboard/home.html", context)


@login_required
def customize(request):
    """Choix et ordre des blocs de l'accueil, propres à l'utilisateur."""
    user = request.user
    if user.tenant_id is None:
        return redirect("admin:index")
    allowed = {block.key: block for block in registry.available(user)}
    if request.method == "POST":
        if request.POST.get("reset"):
            DashboardLayout.objects.filter(user=user).delete()
            messages.success(request, _("Présentation par défaut de votre rôle rétablie."))
            return redirect("dashboard:home")
        shown = set(request.POST.getlist("show"))
        order = [key for key in request.POST.getlist("order") if key in allowed]
        chosen = [key for key in dict.fromkeys(order) if key in shown]
        DashboardLayout.objects.update_or_create(user=user, defaults={"blocks": chosen, "created_by": user})
        messages.success(request, _("Accueil personnalisé : %(n)s bloc(s) affiché(s).") % {"n": len(chosen)})
        return redirect("dashboard:home")
    keys, _customized = registry.layout(user)
    rows = [(allowed[key], True) for key in keys] + [(block, False) for key, block in allowed.items() if key not in keys]
    return render(request, "dashboard/customize.html", {"rows": rows})


