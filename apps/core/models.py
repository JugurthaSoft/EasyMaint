"""Modèles du socle : entreprise, base multi-entreprise, numérotation, journal, pièces jointes."""
import os
import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from .tenancy import get_current_tenant


class Tenant(models.Model):
    """Une entreprise cliente. En installation locale, il n'y en a qu'une."""

    name = models.CharField(_("raison sociale"), max_length=200)
    code = models.SlugField(
        _("code"), max_length=50, unique=True,
        help_text=_("Identifiant court, utilisé comme sous-domaine en mode SaaS."),
    )
    currency_code = models.CharField(_("devise"), max_length=3, default="TND")
    currency_decimals = models.PositiveSmallIntegerField(_("décimales de la devise"), default=3)
    time_zone = models.CharField(_("fuseau horaire"), max_length=64, default="Africa/Tunis")
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(_("créée le"), auto_now_add=True)

    class Meta:
        verbose_name = _("entreprise")
        verbose_name_plural = _("entreprises")
        ordering = ["name"]

    def __str__(self):
        return self.name


class TenantManager(models.Manager):
    """Manager par défaut : ne voit que les données de l'entreprise courante."""

    def get_queryset(self):
        queryset = super().get_queryset()
        tenant = get_current_tenant()
        if tenant is None:
            return queryset.none()
        return queryset.filter(tenant=tenant)


class TenantScopedModel(models.Model):
    """
    Base de toutes les tables métier.

    - `objects` : filtré sur l'entreprise courante (à utiliser partout).
    - `all_tenants` : non filtré, réservé aux usages explicitement transverses
      (administration de la plateforme, commandes de maintenance).
    """

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, editable=False, related_name="+")
    created_at = models.DateTimeField(_("créé le"), auto_now_add=True)
    updated_at = models.DateTimeField(_("modifié le"), auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        editable=False, related_name="+", verbose_name=_("créé par"),
    )

    objects = TenantManager()
    all_tenants = models.Manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.tenant_id:
            tenant = get_current_tenant()
            if tenant is None:
                raise ValidationError(gettext("Enregistrement impossible : aucune entreprise courante."))
            self.tenant = tenant
        super().save(*args, **kwargs)

    def full_clean(self, *args, **kwargs):
        # L'entreprise doit être connue AVANT la validation pour que les contraintes
        # d'unicité « par entreprise » (code unique dans l'entreprise...) soient vérifiées.
        if not self.tenant_id and get_current_tenant() is not None:
            self.tenant = get_current_tenant()
        return super().full_clean(*args, **kwargs)

    def validate_constraints(self, exclude=None):
        # Les formulaires n'exposent jamais le champ « tenant » : Django l'exclurait de la
        # validation et ignorerait alors toutes les contraintes (tenant, code). On l'y réintègre.
        if exclude:
            exclude = set(exclude) - {"tenant"}
        return super().validate_constraints(exclude=exclude)

    def check_same_tenant(self, **related):
        """Lève une erreur si un objet lié appartient à une autre entreprise."""
        tenant_id = self.tenant_id or getattr(get_current_tenant(), "pk", None)
        errors = {}
        for field_name, obj in related.items():
            if obj is not None and getattr(obj, "tenant_id", tenant_id) != tenant_id:
                errors[field_name] = _("Cet élément appartient à une autre entreprise.")
        if errors:
            raise ValidationError(errors)


class DocumentSequence(TenantScopedModel):
    """Compteur de numérotation par entreprise, type de document et année (OT-2026-000123)."""

    doc_type = models.CharField(_("type de document"), max_length=10)
    year = models.PositiveSmallIntegerField(_("année"))
    last_number = models.PositiveIntegerField(_("dernier numéro"), default=0)

    class Meta:
        verbose_name = _("séquence de numérotation")
        constraints = [
            models.UniqueConstraint(fields=["tenant", "doc_type", "year"], name="uniq_sequence_per_tenant_type_year"),
        ]

    def __str__(self):
        return f"{self.doc_type}-{self.year} : {self.last_number}"


class AuditLog(models.Model):
    """
    Journal d'audit non modifiable : connexions et modifications des données.
    N'hérite pas de TenantScopedModel : une tentative de connexion échouée n'a pas d'entreprise.
    """

    class Action(models.TextChoices):
        LOGIN = "login", _("Connexion")
        LOGIN_FAILED = "login_failed", _("Échec de connexion")
        LOGOUT = "logout", _("Déconnexion")
        CREATE = "create", _("Création")
        UPDATE = "update", _("Modification")
        DELETE = "delete", _("Suppression")
        EXPORT = "export", _("Export")

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    username = models.CharField(_("identifiant"), max_length=150, blank=True)
    action = models.CharField(_("action"), max_length=20, choices=Action.choices)
    object_type = models.CharField(_("type d'objet"), max_length=100, blank=True)
    object_id = models.CharField(_("identifiant de l'objet"), max_length=64, blank=True)
    object_repr = models.CharField(_("objet"), max_length=255, blank=True)
    changes = models.JSONField(_("modifications"), default=dict, blank=True)
    ip_address = models.GenericIPAddressField(_("adresse IP"), null=True, blank=True)
    at = models.DateTimeField(_("date"), default=timezone.now, db_index=True)

    class Meta:
        verbose_name = _("entrée du journal")
        verbose_name_plural = _("journal d'audit")
        ordering = ["-at"]
        indexes = [
            models.Index(fields=["tenant", "object_type", "object_id"], name="audit_object_idx"),
            models.Index(fields=["action", "at"], name="audit_action_at_idx"),
        ]

    def __str__(self):
        return f"{self.at:%d/%m/%Y %H:%M} {self.username} {self.get_action_display()} {self.object_repr}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(gettext("Le journal d'audit ne peut pas être modifié."))
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(gettext("Le journal d'audit ne peut pas être supprimé."))


ALLOWED_ATTACHMENT_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".dwg", ".dxf",
    ".doc", ".docx", ".xls", ".xlsx", ".txt", ".csv", ".zip",
}


def attachment_upload_to(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    today = timezone.now()
    return f"tenant_{instance.tenant_id}/fichiers/{today:%Y/%m}/{uuid.uuid4().hex}{ext}"


def validate_attachment(uploaded_file):
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise ValidationError(_("Type de fichier non autorisé (%(ext)s)."), params={"ext": ext or "?"})
    max_bytes = settings.EASYMAINT_MAX_ATTACHMENT_MB * 1024 * 1024
    if uploaded_file.size > max_bytes:
        raise ValidationError(
            _("Fichier trop volumineux (maximum %(max)s Mo)."), params={"max": settings.EASYMAINT_MAX_ATTACHMENT_MB},
        )


class Attachment(TenantScopedModel):
    """Fichier joint à n'importe quel objet (équipement, OT, article...)."""

    class Category(models.TextChoices):
        TECHNICAL = "technical", _("Documentation technique")
        PLAN = "plan", _("Plan ou schéma")
        PHOTO = "photo", _("Photo")
        PHOTO_BEFORE = "photo_before", _("Photo avant intervention")
        PHOTO_AFTER = "photo_after", _("Photo après intervention")
        REPORT = "report", _("Rapport")
        OTHER = "other", _("Autre")

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
    file = models.FileField(_("fichier"), upload_to=attachment_upload_to, validators=[validate_attachment])
    original_name = models.CharField(_("nom du fichier"), max_length=255)
    title = models.CharField(_("titre"), max_length=200, blank=True)
    category = models.CharField(_("catégorie"), max_length=20, choices=Category.choices, default=Category.TECHNICAL)
    size = models.PositiveBigIntegerField(_("taille (octets)"), default=0)

    class Meta:
        verbose_name = _("pièce jointe")
        verbose_name_plural = _("pièces jointes")
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["tenant", "content_type", "object_id"], name="attachment_object_idx")]

    def __str__(self):
        return self.title or self.original_name

    @property
    def display_name(self):
        return self.title or self.original_name
