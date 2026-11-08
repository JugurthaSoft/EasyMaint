from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from apps.core.models import AuditLog
from apps.core.services import form_changes, log_action

from .forms import LoginForm, RoleForm, UserCreateForm, UserUpdateForm
from .models import Role, User
from .permissions import CapabilityRequiredMixin


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class LogoutView(auth_views.LogoutView):
    next_page = reverse_lazy("accounts:login")


class ProfileView(LoginRequiredMixin, View):
    template_name = "accounts/profile.html"

    def get(self, request):
        return render(request, self.template_name, {"form": PasswordChangeForm(request.user)})

    def post(self, request):
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            log_action(AuditLog.Action.UPDATE, request=request, obj=user, changes={_("Mot de passe"): ["", _("modifié")]})
            messages.success(request, _("Votre mot de passe a été modifié."))
            return redirect("accounts:profile")
        return render(request, self.template_name, {"form": form})


# --- Utilisateurs de l'entreprise -------------------------------------------------

class TenantUserMixin(CapabilityRequiredMixin):
    required_capability = "settings.manage"

    def get_queryset(self):
        # User n'est pas un modèle « multi-entreprise » par manager : on filtre explicitement.
        return User.objects.filter(tenant=self.request.tenant).select_related("role")


class UserListView(TenantUserMixin, ListView):
    template_name = "accounts/user_list.html"
    context_object_name = "users"
    paginate_by = 50

    def get_queryset(self):
        queryset = super().get_queryset()
        query = self.request.GET.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(username__icontains=query) | Q(first_name__icontains=query)
                | Q(last_name__icontains=query) | Q(job_title__icontains=query)
            )
        status = self.request.GET.get("statut")
        if status == "actifs":
            queryset = queryset.filter(is_active=True)
        elif status == "inactifs":
            queryset = queryset.filter(is_active=False)
        return queryset


class UserCreateView(TenantUserMixin, CreateView):
    form_class = UserCreateForm
    template_name = "accounts/user_form.html"

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "acting_user": self.request.user}

    def form_valid(self, form):
        form.instance.tenant = self.request.tenant
        response = super().form_valid(form)
        log_action(AuditLog.Action.CREATE, request=self.request, obj=self.object)
        messages.success(self.request, _("Utilisateur %(name)s créé.") % {"name": self.object})
        return response

    def get_success_url(self):
        return reverse("accounts:user_list")


class UserUpdateView(TenantUserMixin, UpdateView):
    form_class = UserUpdateForm
    template_name = "accounts/user_form.html"
    context_object_name = "managed_user"

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "acting_user": self.request.user}

    def form_valid(self, form):
        changes = form_changes(form)
        response = super().form_valid(form)
        if changes:
            log_action(AuditLog.Action.UPDATE, request=self.request, obj=self.object, changes=changes)
        messages.success(self.request, _("Utilisateur %(name)s mis à jour.") % {"name": self.object})
        return response

    def get_success_url(self):
        return reverse("accounts:user_list")


class UserSetPasswordView(TenantUserMixin, View):
    template_name = "accounts/user_password.html"

    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def get_user(self, pk):
        return get_object_or_404(self.get_queryset(), pk=pk)

    def get(self, request, pk):
        managed = self.get_user(pk)
        return render(request, self.template_name, {"managed_user": managed, "form": SetPasswordForm(managed)})

    def post(self, request, pk):
        managed = self.get_user(pk)
        form = SetPasswordForm(managed, request.POST)
        if form.is_valid():
            form.save()
            log_action(AuditLog.Action.UPDATE, request=request, obj=managed, changes={_("Mot de passe"): ["", _("réinitialisé")]})
            messages.success(request, _("Mot de passe de %(name)s réinitialisé.") % {"name": managed})
            return redirect("accounts:user_list")
        return render(request, self.template_name, {"managed_user": managed, "form": form})


# --- Rôles -----------------------------------------------------------------------

class RoleListView(CapabilityRequiredMixin, ListView):
    required_capability = "settings.manage"
    template_name = "accounts/role_list.html"
    context_object_name = "roles"

    def get_queryset(self):
        return Role.objects.annotate(user_count=Count("users"))


class RoleCreateView(CapabilityRequiredMixin, CreateView):
    required_capability = "settings.manage"
    form_class = RoleForm
    template_name = "accounts/role_form.html"

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "acting_user": self.request.user}

    @transaction.atomic
    def form_valid(self, form):
        base = slugify(form.cleaned_data["name"])[:40] or "role"
        code, suffix = base, 2
        while Role.objects.filter(code=code).exists():
            code, suffix = f"{base}-{suffix}", suffix + 1
        form.instance.code = code
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        log_action(AuditLog.Action.CREATE, request=self.request, obj=self.object)
        messages.success(self.request, _("Rôle « %(name)s » créé.") % {"name": self.object})
        return response

    def get_success_url(self):
        return reverse("accounts:role_list")


class RoleUpdateView(CapabilityRequiredMixin, UpdateView):
    required_capability = "settings.manage"
    form_class = RoleForm
    template_name = "accounts/role_form.html"
    context_object_name = "role"

    def get_queryset(self):
        return Role.objects.all()

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "acting_user": self.request.user}

    def form_valid(self, form):
        before = set(self.get_object().capabilities)
        response = super().form_valid(form)
        after = set(self.object.capabilities)
        changes = {}
        if before != after:
            changes[_("Capacités ajoutées")] = ["", ", ".join(sorted(after - before))]
            changes[_("Capacités retirées")] = ["", ", ".join(sorted(before - after))]
        if "name" in form.changed_data:
            changes[_("Nom")] = [form.initial.get("name", ""), self.object.name]
        if changes:
            log_action(AuditLog.Action.UPDATE, request=self.request, obj=self.object, changes=changes)
        messages.success(self.request, _("Rôle « %(name)s » mis à jour.") % {"name": self.object})
        return response

    def get_success_url(self):
        return reverse("accounts:role_list")


# --- Journal d'activité ----------------------------------------------------------

class AuditListView(CapabilityRequiredMixin, ListView):
    required_capability = "audit.view"
    template_name = "accounts/audit_list.html"
    context_object_name = "entries"
    paginate_by = 50

    def get_queryset(self):
        queryset = AuditLog.objects.filter(tenant=self.request.tenant).select_related("user")
        action = self.request.GET.get("action")
        if action in AuditLog.Action.values:
            queryset = queryset.filter(action=action)
        query = self.request.GET.get("q", "").strip()
        if query:
            queryset = queryset.filter(Q(username__icontains=query) | Q(object_repr__icontains=query))
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["actions"] = AuditLog.Action.choices
        return context
