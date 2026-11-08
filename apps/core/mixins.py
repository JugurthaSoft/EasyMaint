"""Mixins de vues partagés par les modules."""
from django.contrib import messages

from .models import AuditLog
from .services import form_changes, log_action


class AuditedFormMixin:
    """Création / modification via formulaire : renseigne l'auteur, journalise, affiche un message."""

    success_message = ""

    def form_valid(self, form):
        is_new = form.instance.pk is None
        changes = {} if is_new else form_changes(form)
        if is_new and hasattr(form.instance, "created_by_id"):
            form.instance.created_by = self.request.user
        response = super().form_valid(form)
        if is_new:
            log_action(AuditLog.Action.CREATE, request=self.request, obj=self.object)
        elif changes:
            log_action(AuditLog.Action.UPDATE, request=self.request, obj=self.object, changes=changes)
        if self.success_message:
            messages.success(self.request, self.success_message % {"name": self.object})
        return response
