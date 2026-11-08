from django import forms
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .capabilities import ALL_CAPABILITIES, CAPABILITY_GROUPS, CAPABILITY_LABELS
from .models import Role, User


class LockoutMixin:
    """Refuse la connexion pendant un blocage temporaire, avant même de tester le mot de passe."""

    def clean(self):
        from apps.core.services import client_ip

        from .lockout import locked_for, minutes

        delay = locked_for(self.cleaned_data.get("username", ""), client_ip(self.request))
        if delay:
            raise ValidationError(
                _("Trop de tentatives de connexion échouées. Réessayez dans %(n)s minute(s) ou contactez votre administrateur.")
                % {"n": minutes(delay)}, code="locked",
            )
        return super().clean()


class AdminLoginForm(LockoutMixin, AdminAuthenticationForm):
    """Connexion à l'administration de la plateforme, avec le même blocage."""


class LoginForm(LockoutMixin, AuthenticationForm):
    error_messages = {
        "invalid_login": _("Identifiant ou mot de passe incorrect."),
        "inactive": _("Ce compte est désactivé."),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = _("Identifiant")
        self.fields["username"].widget.attrs.update({"autofocus": True, "autocomplete": "username"})
        self.fields["password"].label = _("Mot de passe")

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.tenant_id is not None and not user.tenant.is_active:
            raise ValidationError(_("L'accès de votre entreprise est suspendu."), code="inactive")


class _UserBaseForm(forms.ModelForm):
    def __init__(self, *args, acting_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.acting_user = acting_user
        self.fields["role"].queryset = Role.objects.all()
        self.fields["role"].required = True
        self.fields["role"].empty_label = _("Choisir un rôle…")
        for name in ("first_name", "last_name"):
            self.fields[name].required = True


class UserCreateForm(_UserBaseForm):
    password1 = forms.CharField(label=_("Mot de passe"), widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label=_("Confirmation du mot de passe"), widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "job_title", "role", "email", "phone"]
        labels = {"username": _("Identifiant"), "first_name": _("Prénom"), "last_name": _("Nom"), "email": _("E-mail")}

    def clean_password2(self):
        p1, p2 = self.cleaned_data.get("password1"), self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError(_("Les deux mots de passe ne correspondent pas."))
        return p2

    def _post_clean(self):
        super()._post_clean()
        password = self.cleaned_data.get("password2")
        if password:
            try:
                password_validation.validate_password(password, self.instance)
            except ValidationError as error:
                self.add_error("password2", error)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class UserUpdateForm(_UserBaseForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "job_title", "role", "email", "phone", "is_active"]
        labels = {"first_name": _("Prénom"), "last_name": _("Nom"), "email": _("E-mail"), "is_active": _("Compte actif")}

    def clean(self):
        cleaned = super().clean()
        if self.acting_user is not None and self.instance.pk == self.acting_user.pk:
            if not cleaned.get("is_active", True):
                raise ValidationError(_("Vous ne pouvez pas désactiver votre propre compte."))
            role = cleaned.get("role")
            if role is not None and "settings.manage" not in role.capabilities:
                raise ValidationError(_("Vous ne pouvez pas vous retirer le droit de gérer les utilisateurs."))
        return cleaned


class RoleForm(forms.ModelForm):
    capabilities = forms.MultipleChoiceField(
        label=_("Capacités"), choices=[(c, CAPABILITY_LABELS[c]) for c in ALL_CAPABILITIES],
        required=False, widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Role
        fields = ["name", "capabilities"]
        labels = {"name": _("Nom du rôle")}

    def __init__(self, *args, acting_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.acting_user = acting_user

    def capability_groups(self):
        """Capacités regroupées par module, avec leur état coché, pour l'affichage."""
        selected = set(self["capabilities"].value() or [])
        return [
            (group, [(code, label, code in selected) for code, label in items])
            for group, items in CAPABILITY_GROUPS
        ]

    def clean_capabilities(self):
        capabilities = self.cleaned_data["capabilities"]
        if self.instance.code == "admin" and "settings.manage" not in capabilities:
            raise ValidationError(_("Le rôle Administrateur doit conserver la gestion des utilisateurs."))
        if (
            self.acting_user is not None and self.instance.pk
            and self.acting_user.role_id == self.instance.pk and "settings.manage" not in capabilities
        ):
            raise ValidationError(_("Vous perdriez vous-même l'accès à cet écran."))
        return capabilities
