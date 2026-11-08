"""
Administration technique de la plateforme (réservée au super-administrateur).
Les utilisateurs de l'entreprise passent par l'interface EasyMaint, pas par cet écran.
"""
from django.contrib import admin

from .models import AuditLog, Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "currency_code", "is_active", "created_at")
    search_fields = ("name", "code")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("at", "tenant", "username", "action", "object_type", "object_repr", "ip_address")
    list_filter = ("action", "tenant")
    search_fields = ("username", "object_repr")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
