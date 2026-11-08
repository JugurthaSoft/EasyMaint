from django.db.models import Count, Q
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, ListView, TemplateView, UpdateView

from apps.accounts.permissions import CapabilityRequiredMixin
from apps.core.mixins import AuditedFormMixin

from .forms import ContractorForm, SkillForm, TeamForm, TechnicianForm
from .models import Contractor, Skill, Team, Technician


class TechnicianListView(CapabilityRequiredMixin, ListView):
    required_capability = "workforce.view"
    template_name = "workforce/technician_list.html"
    context_object_name = "technicians"

    def get_queryset(self):
        queryset = Technician.objects.select_related("team", "user").prefetch_related("skills")
        if self.request.GET.get("inactifs") != "1":
            queryset = queryset.filter(is_active=True)
        query = self.request.GET.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(first_name__icontains=query) | Q(last_name__icontains=query)
                | Q(employee_number__icontains=query) | Q(specialty__icontains=query)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["teams"] = Team.objects.select_related("leader").annotate(n=Count("members", filter=Q(members__is_active=True)))
        return context


class _Form(AuditedFormMixin, CapabilityRequiredMixin):
    required_capability = "workforce.manage"
    template_name = "assets/simple_form.html"
    back_url_name = "workforce:technician_list"

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "page_title": self.page_title, "back_url_name": self.back_url_name}

    def get_success_url(self):
        return reverse(self.back_url_name)


class TechnicianCreateView(_Form, CreateView):
    form_class = TechnicianForm
    page_title = _("Nouveau technicien")
    success_message = _("Technicien « %(name)s » créé.")


class TechnicianUpdateView(_Form, UpdateView):
    form_class = TechnicianForm
    page_title = _("Modifier le technicien")
    success_message = _("Technicien « %(name)s » mis à jour.")

    def get_queryset(self):
        return Technician.objects.all()


class TeamCreateView(_Form, CreateView):
    form_class = TeamForm
    page_title = _("Nouvelle équipe")
    success_message = _("Équipe « %(name)s » créée.")


class TeamUpdateView(_Form, UpdateView):
    form_class = TeamForm
    page_title = _("Modifier l'équipe")
    success_message = _("Équipe « %(name)s » mise à jour.")

    def get_queryset(self):
        return Team.objects.all()


class ReferentialView(CapabilityRequiredMixin, TemplateView):
    required_capability = "workforce.view"
    template_name = "workforce/referentials.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["skills"] = Skill.objects.annotate(n=Count("technicians"))
        context["contractors"] = Contractor.objects.all()
        return context


class SkillCreateView(_Form, CreateView):
    form_class = SkillForm
    page_title = _("Nouvelle compétence")
    success_message = _("Compétence « %(name)s » créée.")
    back_url_name = "workforce:referentials"


class SkillUpdateView(_Form, UpdateView):
    form_class = SkillForm
    page_title = _("Modifier la compétence")
    success_message = _("Compétence « %(name)s » mise à jour.")
    back_url_name = "workforce:referentials"

    def get_queryset(self):
        return Skill.objects.all()


class ContractorCreateView(_Form, CreateView):
    form_class = ContractorForm
    page_title = _("Nouveau sous-traitant")
    success_message = _("Sous-traitant « %(name)s » créé.")
    back_url_name = "workforce:referentials"


class ContractorUpdateView(_Form, UpdateView):
    form_class = ContractorForm
    page_title = _("Modifier le sous-traitant")
    success_message = _("Sous-traitant « %(name)s » mis à jour.")
    back_url_name = "workforce:referentials"

    def get_queryset(self):
        return Contractor.objects.all()
