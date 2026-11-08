"""
Déclencheurs des notifications. Les modules métier n'en savent rien : ce module écoute leurs
enregistrements (signaux Django) et n'est relié qu'aux modules installés.

- OT affecté à un technicien           → le technicien
- nouvelle demande d'intervention      → les personnes qui analysent les demandes
- nouvelle alerte conditionnelle       → les personnes qui gèrent le conditionnel
- pièce demandée au magasin pour un OT → les magasiniers
- OT terminé                           → les personnes qui valident les OT
"""
from django.apps import apps as django_apps
from django.db.models.signals import m2m_changed, post_save, pre_save
from django.utils.translation import gettext as _

from .models import Notification
from .services import notify, users_with

K = Notification.Kind


def _url(obj):
    try:
        return obj.get_absolute_url()
    except Exception:
        return ""


def on_request_saved(sender, instance, created, raw=False, **kwargs):
    if not created or raw:
        return
    notify(users_with(instance.tenant, "requests.manage"), tenant=instance.tenant, kind=K.REQUEST,
           title=_("Nouvelle demande %(n)s · %(eq)s") % {"n": instance.number, "eq": instance.equipment.code},
           body=instance.description, url=_url(instance))


def on_technicians_changed(sender, instance, action, reverse, pk_set, **kwargs):
    if action != "post_add" or reverse or not pk_set:
        return
    from apps.workforce.models import Technician

    if instance.status not in instance.OPEN_STATUSES:
        return
    users = [t.user for t in Technician.all_tenants.filter(pk__in=pk_set, tenant=instance.tenant, user__isnull=False).select_related("user")]
    notify(users, tenant=instance.tenant, kind=K.ASSIGNED,
           title=_("OT affecté : %(n)s") % {"n": instance.number},
           body=f"{instance.equipment.code} · {instance.title}", url=_url(instance))


def remember_status(sender, instance, raw=False, **kwargs):
    if raw or not instance.pk:
        instance._previous_status = None
        return
    instance._previous_status = sender.all_tenants.filter(pk=instance.pk).values_list("status", flat=True).first()


def on_work_order_saved(sender, instance, created, raw=False, **kwargs):
    if raw or instance.status != sender.Status.DONE or getattr(instance, "_previous_status", None) == sender.Status.DONE:
        return
    notify(users_with(instance.tenant, "workorders.validate"), tenant=instance.tenant, kind=K.TO_VALIDATE,
           title=_("OT terminé à valider : %(n)s") % {"n": instance.number},
           body=f"{instance.equipment.code} · {instance.title}", url=_url(instance))


def on_alert_saved(sender, instance, created, raw=False, **kwargs):
    if not created or raw:
        return
    notify(users_with(instance.tenant, "condition.manage"), tenant=instance.tenant, kind=K.ALERT,
           title=_("Alerte %(level)s · %(point)s") % {"level": instance.get_level_display(), "point": instance.point},
           body=instance.parameter.name, url=_url(instance))


def on_part_requested(sender, instance, created, raw=False, **kwargs):
    if not created or raw or instance.from_plan:
        return
    from apps.core.formatting import smart_number

    notify(users_with(instance.tenant, "stock.move"), tenant=instance.tenant, kind=K.PART,
           title=_("Pièce demandée pour %(n)s") % {"n": instance.work_order.number},
           body=f"{instance.item.reference} · {instance.item.designation} × {smart_number(instance.quantity)}",
           url=_part_url())


def _part_url():
    from django.urls import NoReverseMatch, reverse

    try:
        return reverse("inventory:request_queue")
    except NoReverseMatch:
        return ""


def connect():
    if django_apps.is_installed("apps.workorders"):
        from apps.workorders.models import WorkOrder, WorkRequest

        post_save.connect(on_request_saved, sender=WorkRequest, dispatch_uid="notif_request")
        m2m_changed.connect(on_technicians_changed, sender=WorkOrder.technicians.through, dispatch_uid="notif_assigned")
        pre_save.connect(remember_status, sender=WorkOrder, dispatch_uid="notif_wo_status")
        post_save.connect(on_work_order_saved, sender=WorkOrder, dispatch_uid="notif_wo_done")
    if django_apps.is_installed("apps.condition"):
        from apps.condition.models import Alert

        post_save.connect(on_alert_saved, sender=Alert, dispatch_uid="notif_alert")
    if django_apps.is_installed("apps.inventory"):
        from apps.inventory.models import WorkOrderPart

        post_save.connect(on_part_requested, sender=WorkOrderPart, dispatch_uid="notif_part")
