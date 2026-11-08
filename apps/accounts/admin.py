from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from .forms import AdminLoginForm
from .models import Role, User

# Même blocage après plusieurs échecs que la page de connexion d'EasyMaint.
admin.site.login_form = AdminLoginForm


class PlatformUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username",)


class PlatformUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = PlatformUserChangeForm
    add_form = PlatformUserCreationForm
    list_display = ("username", "first_name", "last_name", "tenant", "role", "is_active")
    list_filter = ("tenant", "is_active", "is_superuser")
    fieldsets = BaseUserAdmin.fieldsets + (("EasyMaint", {"fields": ("tenant", "role", "phone", "job_title")}),)


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "tenant", "is_system")
    list_filter = ("tenant",)
    readonly_fields = ("tenant",)

    def get_queryset(self, request):
        return Role.all_tenants.select_related("tenant")
