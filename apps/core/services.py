"""Services du socle : numérotation des documents et journalisation des actions."""
import logging

from django.conf import settings
from django.core.files import File
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.translation import gettext

from .models import AuditLog, DocumentSequence
from .tenancy import get_current_tenant

logger = logging.getLogger("easymaint")

DOCUMENT_PREFIXES = {
    "OT": "OT",    # ordre de travail
    "DI": "DI",    # demande d'intervention
    "DA": "DA",    # demande d'achat
    "BC": "BC",    # bon de commande
    "MVT": "MVT",  # mouvement de stock
    "INV": "INV",  # inventaire physique
}


def next_document_number(doc_type, *, year=None):
    """
    Renvoie le prochain numéro unique d'un type de document pour l'entreprise courante,
    au format PREFIXE-AAAA-000123. Sûr en accès concurrent : la ligne de séquence est
    verrouillée (SELECT ... FOR UPDATE) le temps de l'incrément.
    """
    if doc_type not in DOCUMENT_PREFIXES:
        raise ValueError(f"Type de document inconnu : {doc_type}")
    tenant = get_current_tenant()
    if tenant is None:
        raise RuntimeError(gettext("Aucune entreprise courante pour la numérotation."))
    year = year or timezone.localdate().year
    with transaction.atomic():
        DocumentSequence.objects.get_or_create(tenant=tenant, doc_type=doc_type, year=year)
        sequence = DocumentSequence.objects.select_for_update().get(tenant=tenant, doc_type=doc_type, year=year)
        sequence.last_number += 1
        sequence.save(update_fields=["last_number", "updated_at"])
        number = sequence.last_number
    return f"{DOCUMENT_PREFIXES[doc_type]}-{year}-{number:06d}"


def client_ip(request):
    if request is None:
        return None
    # L'en-tête X-Forwarded-For peut être inventé par n'importe quel client : on ne le lit que
    # derrière un proxy de confiance (Caddy en SaaS), et on prend l'adresse ajoutée par ce proxy.
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded and getattr(settings, "EASYMAINT_BEHIND_PROXY", False):
        return forwarded.split(",")[-1].strip() or None
    return request.META.get("REMOTE_ADDR")


def _display(value):
    """Valeur lisible pour le journal (objets liés par leur libellé, dates au format français)."""
    if value is None or (isinstance(value, str) and value == ""):
        return ""
    if isinstance(value, File):  # fichier envoyé ou FieldFile : on ne garde que le nom
        return value.name.rsplit("/", 1)[-1] if value.name else ""
    if isinstance(value, bool):
        return "oui" if value else "non"
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y %H:%M") if hasattr(value, "hour") else value.strftime("%d/%m/%Y")
    if isinstance(value, (list, tuple, set, QuerySet)):
        return ", ".join(str(item) for item in value)
    return str(value)


def form_changes(form):
    """Différences avant / après d'un ModelForm valide, prêtes pour le journal."""
    changes = {}
    for name in form.changed_data:
        field = form.fields[name]
        before = form.initial.get(name)
        if hasattr(field, "queryset") and before not in (None, ""):
            try:
                if isinstance(before, (list, tuple)):
                    before = list(field.queryset.model._base_manager.filter(pk__in=before))
                else:
                    before = field.queryset.model._base_manager.filter(pk=before).first()
            except (TypeError, ValueError):
                pass
        if hasattr(field, "choices") and not hasattr(field, "queryset"):
            choices = dict(field.choices)
            before_label = choices.get(before, before)
            after_label = choices.get(form.cleaned_data.get(name), form.cleaned_data.get(name))
        else:
            before_label, after_label = before, form.cleaned_data.get(name)
        changes[str(field.label or name)] = [_display(before_label), _display(after_label)]
    return changes


def log_action(action, *, user=None, request=None, obj=None, changes=None, username=""):
    """Ajoute une entrée au journal d'audit. Ne fait jamais échouer l'action métier."""
    try:
        if request is not None and user is None and getattr(request, "user", None) is not None:
            if request.user.is_authenticated:
                user = request.user
        tenant = None
        if obj is not None and getattr(obj, "tenant_id", None):
            tenant = obj.tenant
        elif user is not None and getattr(user, "tenant_id", None):
            tenant = user.tenant
        else:
            tenant = get_current_tenant()
        AuditLog.objects.create(
            tenant=tenant,
            user=user,
            username=(user.get_username() if user is not None else username)[:150],
            action=action,
            object_type=obj._meta.label if obj is not None else "",
            object_id=str(obj.pk) if obj is not None else "",
            object_repr=str(obj)[:255] if obj is not None else "",
            changes=changes or {},
            ip_address=client_ip(request),
        )
    except Exception:  # le journal ne doit pas bloquer l'utilisateur, mais l'incident est tracé
        logger.exception("Échec d'écriture dans le journal d'audit")
