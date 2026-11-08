"""
Interventions : demandes d'intervention (DI), ordres de travail (OT), pointages,
pièces, frais, check-lists, arrêts machine et codes de défaillance.

Les changements d'état passent exclusivement par apps.workorders.services.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.assets.models import Equipment
from apps.core.models import TenantScopedModel
from apps.workforce.models import Contractor, Team, Technician


class Priority(models.IntegerChoices):
    URGENT = 1, _("P1 · Urgente")
    HIGH = 2, _("P2 · Haute")
    NORMAL = 3, _("P3 · Normale")
    LOW = 4, _("P4 · Basse")


PRIORITY_BADGES = {1: "b-red", 2: "b-orange", 3: "b-gray", 4: "b-gray"}


class FailureCode(TenantScopedModel):
    """Référentiel des modes de défaillance, causes et remèdes."""

    class Kind(models.TextChoices):
        MODE = "mode", _("Mode de défaillance")
        CAUSE = "cause", _("Cause")
        REMEDY = "remedy", _("Remède")

    kind = models.CharField(_("type"), max_length=10, choices=Kind.choices)
    code = models.CharField(_("code"), max_length=30)
    name = models.CharField(_("libellé"), max_length=150)
    is_active = models.BooleanField(_("actif"), default=True)

    class Meta:
        verbose_name = _("code de défaillance")
        verbose_name_plural = _("codes de défaillance")
        ordering = ["kind", "name"]
        constraints = [models.UniqueConstraint(fields=["tenant", "kind", "code"], name="uniq_failure_code_per_tenant")]

    def __str__(self):
        return self.name


class WorkOrder(TenantScopedModel):
    class Kind(models.TextChoices):
        CORRECTIVE = "corrective", _("Correctif")
        PREVENTIVE = "preventive", _("Préventif")
        CONDITIONAL = "conditional", _("Conditionnel")
        IMPROVEMENT = "improvement", _("Amélioratif")

    class Status(models.TextChoices):
        TO_PLAN = "to_plan", _("À planifier")
        ASSIGNED = "assigned", _("Affecté")
        IN_PROGRESS = "in_progress", _("En cours")
        WAITING_PARTS = "waiting_parts", _("En attente de pièces")
        WAITING_EXTERNAL = "waiting_external", _("En attente d'intervention externe")
        DONE = "done", _("Terminé")
        VALIDATED = "validated", _("Validé")
        CANCELLED = "cancelled", _("Annulé")

    OPEN_STATUSES = ("to_plan", "assigned", "in_progress", "waiting_parts", "waiting_external")
    STATUS_BADGES = {
        "to_plan": "b-purple", "assigned": "b-blue", "in_progress": "b-blue", "waiting_parts": "b-orange",
        "waiting_external": "b-orange", "done": "b-green", "validated": "b-green", "cancelled": "b-muted",
    }
    KIND_BADGES = {"corrective": "b-red", "preventive": "b-blue", "conditional": "b-purple", "improvement": "b-gray"}

    number = models.CharField(_("numéro"), max_length=20, editable=False)
    kind = models.CharField(_("type"), max_length=20, choices=Kind.choices, default=Kind.CORRECTIVE)
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name="work_orders", verbose_name=_("équipement"))
    title = models.CharField(_("intitulé"), max_length=200)
    description = models.TextField(_("description"), blank=True)
    priority = models.PositiveSmallIntegerField(_("priorité"), choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(_("statut"), max_length=20, choices=Status.choices, default=Status.TO_PLAN)
    production_stopped = models.BooleanField(_("arrêt de production"), default=False)
    planned_date = models.DateField(_("date prévue"), null=True, blank=True)
    due_date = models.DateField(_("échéance"), null=True, blank=True)
    original_due_date = models.DateField(
        _("échéance d'origine"), null=True, blank=True,
        help_text=_("Conservée lors d'un report, pour mesurer le respect du planning."),
    )
    preventive_plan = models.ForeignKey(
        "preventive.PreventivePlan", on_delete=models.SET_NULL, null=True, blank=True, related_name="work_orders",
        verbose_name=_("plan préventif"),
    )
    estimated_hours = models.DecimalField(_("temps estimé (h)"), max_digits=6, decimal_places=2, null=True, blank=True)
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="work_orders", verbose_name=_("équipe"))
    technicians = models.ManyToManyField(Technician, blank=True, related_name="work_orders", verbose_name=_("techniciens"))
    contractor = models.ForeignKey(
        Contractor, on_delete=models.SET_NULL, null=True, blank=True, related_name="work_orders", verbose_name=_("sous-traitant"),
    )
    started_at = models.DateTimeField(_("début réel"), null=True, blank=True)
    finished_at = models.DateTimeField(_("fin réelle"), null=True, blank=True)
    diagnosis = models.TextField(_("diagnostic"), blank=True)
    failure_mode = models.ForeignKey(
        FailureCode, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name=_("mode de défaillance"),
    )
    failure_cause = models.ForeignKey(
        FailureCode, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name=_("cause"),
    )
    work_done = models.TextField(_("travaux réalisés"), blank=True)
    waiting_reason = models.CharField(_("motif d'attente"), max_length=255, blank=True)
    cancel_reason = models.CharField(_("motif d'annulation"), max_length=255, blank=True)
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name=_("validé par"),
    )
    validated_at = models.DateTimeField(_("validé le"), null=True, blank=True)
    labour_cost = models.DecimalField(_("main-d'œuvre"), max_digits=14, decimal_places=3, default=0)
    parts_cost = models.DecimalField(_("pièces"), max_digits=14, decimal_places=3, default=0)
    external_cost = models.DecimalField(_("prestations externes"), max_digits=14, decimal_places=3, default=0)
    other_cost = models.DecimalField(_("autres dépenses"), max_digits=14, decimal_places=3, default=0)
    total_cost = models.DecimalField(_("coût total"), max_digits=14, decimal_places=3, default=0)

    class Meta:
        verbose_name = _("ordre de travail")
        verbose_name_plural = _("ordres de travail")
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["tenant", "number"], name="uniq_work_order_number_per_tenant")]
        indexes = [
            models.Index(fields=["tenant", "status"], name="wo_status_idx"),
            models.Index(fields=["tenant", "equipment"], name="wo_equipment_idx"),
            # Listes, retards, coûts et indicateurs (filtres les plus fréquents)
            models.Index(fields=["tenant", "-created_at"], name="wo_created_idx"),
            models.Index(fields=["tenant", "kind", "status"], name="wo_kind_status_idx"),
            models.Index(fields=["tenant", "due_date"], name="wo_due_idx"),
            models.Index(fields=["tenant", "finished_at"], name="wo_finished_idx"),
        ]

    def __str__(self):
        return f"{self.number} · {self.title}"

    def get_absolute_url(self):
        return reverse("workorders:wo_detail", args=[self.pk])

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    @property
    def is_postponed(self):
        return bool(self.original_due_date and self.due_date and self.original_due_date != self.due_date)

    @property
    def is_late(self):
        return self.is_open and self.due_date is not None and self.due_date < timezone.localdate()

    @property
    def status_badge(self):
        return self.STATUS_BADGES.get(self.status, "b-gray")

    @property
    def kind_badge(self):
        return self.KIND_BADGES.get(self.kind, "b-gray")

    @property
    def priority_badge(self):
        return PRIORITY_BADGES.get(self.priority, "b-gray")

    def clean(self):
        self.check_same_tenant(
            equipment=self.equipment if self.equipment_id else None, team=self.team, contractor=self.contractor,
            failure_mode=self.failure_mode, failure_cause=self.failure_cause,
        )


class WorkRequest(TenantScopedModel):
    """Demande d'intervention : déclarée par un opérateur, analysée par la maintenance."""

    class Status(models.TextChoices):
        NEW = "new", _("Nouvelle")
        ACCEPTED = "accepted", _("Acceptée")
        REJECTED = "rejected", _("Refusée")

    STATUS_BADGES = {"new": "b-purple", "accepted": "b-green", "rejected": "b-gray"}

    number = models.CharField(_("numéro"), max_length=20, editable=False)
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name="work_requests", verbose_name=_("équipement"))
    description = models.TextField(_("description du problème"))
    priority = models.PositiveSmallIntegerField(_("priorité"), choices=Priority.choices, default=Priority.NORMAL)
    production_stopped = models.BooleanField(_("la production est arrêtée"), default=False)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name=_("demandeur"),
    )
    requested_at = models.DateTimeField(_("déclarée le"), default=timezone.now)
    status = models.CharField(_("statut"), max_length=20, choices=Status.choices, default=Status.NEW)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name=_("traitée par"),
    )
    decided_at = models.DateTimeField(_("traitée le"), null=True, blank=True)
    decision_note = models.CharField(_("commentaire de décision"), max_length=255, blank=True)
    work_order = models.OneToOneField(
        WorkOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="request", verbose_name=_("ordre de travail"),
    )

    class Meta:
        verbose_name = _("demande d'intervention")
        verbose_name_plural = _("demandes d'intervention")
        ordering = ["-requested_at"]
        constraints = [models.UniqueConstraint(fields=["tenant", "number"], name="uniq_work_request_number_per_tenant")]
        indexes = [models.Index(fields=["tenant", "status"], name="wr_status_idx")]

    def __str__(self):
        return f"{self.number} · {self.equipment.code}"

    def get_absolute_url(self):
        return reverse("workorders:request_detail", args=[self.pk])

    @property
    def status_badge(self):
        return self.STATUS_BADGES.get(self.status, "b-gray")

    @property
    def priority_badge(self):
        return PRIORITY_BADGES.get(self.priority, "b-gray")


class StatusLog(TenantScopedModel):
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="status_logs")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    at = models.DateTimeField(default=timezone.now)
    comment = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["at", "pk"]

    def __str__(self):
        return f"{self.work_order.number} : {self.from_status} → {self.to_status}"

    @property
    def to_label(self):
        return WorkOrder.Status(self.to_status).label if self.to_status in WorkOrder.Status.values else self.to_status


class TimeEntry(TenantScopedModel):
    """Temps passé par un technicien sur un OT. `ended_at` vide = chronomètre en marche."""

    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="time_entries")
    technician = models.ForeignKey(Technician, on_delete=models.PROTECT, related_name="time_entries", verbose_name=_("technicien"))
    started_at = models.DateTimeField(_("début"))
    ended_at = models.DateTimeField(_("fin"), null=True, blank=True)
    hours = models.DecimalField(_("heures"), max_digits=7, decimal_places=2, default=0)
    is_overtime = models.BooleanField(_("heures supplémentaires"), default=False)
    hourly_rate = models.DecimalField(_("taux appliqué"), max_digits=10, decimal_places=3, default=0)
    note = models.CharField(_("commentaire"), max_length=200, blank=True)

    class Meta:
        verbose_name = _("pointage")
        verbose_name_plural = _("pointages")
        ordering = ["started_at"]

    def __str__(self):
        return f"{self.technician} · {self.hours} h"

    @property
    def is_running(self):
        return self.ended_at is None

    @property
    def cost(self):
        return (self.hours or Decimal("0")) * (self.hourly_rate or Decimal("0"))


class PartUsage(TenantScopedModel):
    """
    Pièce utilisée. En phase 3 la pièce est saisie librement ; la phase 5 la reliera
    à un article du magasin (sortie de stock automatique).
    """

    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="parts")
    reference = models.CharField(_("référence"), max_length=60, blank=True)
    designation = models.CharField(_("désignation"), max_length=200)
    quantity = models.DecimalField(_("quantité"), max_digits=12, decimal_places=3, default=1)
    unit_cost = models.DecimalField(_("coût unitaire"), max_digits=14, decimal_places=3, default=0)

    class Meta:
        verbose_name = _("pièce utilisée")
        verbose_name_plural = _("pièces utilisées")
        ordering = ["pk"]

    def __str__(self):
        return self.designation

    @property
    def cost(self):
        return (self.quantity or Decimal("0")) * (self.unit_cost or Decimal("0"))


class Expense(TenantScopedModel):
    class Nature(models.TextChoices):
        EXTERNAL = "external", _("Prestation externe")
        RENTAL = "rental", _("Location de matériel")
        OTHER = "other", _("Autre dépense")

    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="expenses")
    nature = models.CharField(_("nature"), max_length=20, choices=Nature.choices, default=Nature.EXTERNAL)
    label = models.CharField(_("libellé"), max_length=200)
    supplier = models.CharField(_("fournisseur"), max_length=150, blank=True)
    amount = models.DecimalField(_("montant"), max_digits=14, decimal_places=3)

    class Meta:
        verbose_name = _("dépense")
        verbose_name_plural = _("dépenses")
        ordering = ["pk"]

    def __str__(self):
        return self.label


class ChecklistItem(TenantScopedModel):
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="checklist")
    position = models.PositiveSmallIntegerField(default=0)
    label = models.CharField(_("point de contrôle"), max_length=255)
    is_done = models.BooleanField(_("fait"), default=False)
    comment = models.CharField(_("commentaire"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("point de contrôle")
        verbose_name_plural = _("check-list")
        ordering = ["position", "pk"]

    def __str__(self):
        return self.label


class Downtime(TenantScopedModel):
    """Arrêt d'un équipement. Base des calculs de MTBF, MTTR et disponibilité (phase 6)."""

    class Origin(models.TextChoices):
        FAILURE = "failure", _("Panne")
        PREVENTIVE = "preventive", _("Maintenance planifiée")
        OTHER = "other", _("Autre")

    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name="downtimes", verbose_name=_("équipement"))
    work_order = models.ForeignKey(WorkOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="downtimes")
    work_request = models.ForeignKey(WorkRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name="downtimes")
    started_at = models.DateTimeField(_("début de l'arrêt"))
    ended_at = models.DateTimeField(_("fin de l'arrêt"), null=True, blank=True)
    production_stopped = models.BooleanField(_("arrêt de production"), default=True)
    origin = models.CharField(_("origine"), max_length=20, choices=Origin.choices, default=Origin.FAILURE)

    class Meta:
        verbose_name = _("arrêt machine")
        verbose_name_plural = _("arrêts machine")
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["equipment", "started_at"], name="downtime_equipment_idx")]

    def __str__(self):
        return f"{self.equipment.code} · {self.started_at:%d/%m/%Y %H:%M}"

    @property
    def duration_hours(self):
        end = self.ended_at or timezone.now()
        return Decimal(str(round((end - self.started_at).total_seconds() / 3600, 2)))
