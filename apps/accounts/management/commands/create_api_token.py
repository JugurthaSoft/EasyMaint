"""
Jeton d'accès à l'API pour un compte (capteur, passerelle, logiciel d'appareil, ERP).

    python manage.py create_api_token capteurs
    python manage.py create_api_token capteurs --renew   # invalide l'ancien jeton

Le jeton s'utilise dans l'en-tête HTTP : `Authorization: Token <jeton>`.
Le compte n'a que les droits de son rôle (par exemple « Technicien » pour envoyer des mesures).
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from rest_framework.authtoken.models import Token

from apps.core.models import AuditLog
from apps.core.services import log_action
from apps.core.tenancy import reset_current_tenant, set_current_tenant


class Command(BaseCommand):
    help = "Crée (ou affiche, ou renouvelle) le jeton API d'un utilisateur."

    def add_arguments(self, parser):
        parser.add_argument("username", help="Identifiant du compte")
        parser.add_argument("--renew", action="store_true", help="Remplace le jeton existant")

    def handle(self, *args, username, renew, **options):
        user = get_user_model().objects.filter(username=username).first()
        if user is None:
            raise CommandError(f"Utilisateur « {username} » introuvable.")
        if user.tenant_id is None or not user.is_active:
            raise CommandError("Le compte doit être actif et rattaché à une entreprise.")
        if renew:
            Token.objects.filter(user=user).delete()
        token, created = Token.objects.get_or_create(user=user)
        context = set_current_tenant(user.tenant)
        try:
            if created:
                log_action(AuditLog.Action.CREATE, user=None, username="système",
                           changes={"Jeton API": ["", user.username]})
        finally:
            reset_current_tenant(context)
        state = "créé" if created else "existant"
        self.stdout.write(self.style.SUCCESS(f"Jeton {state} pour {user.username} : {token.key}"))
        self.stdout.write("En-tête à utiliser : Authorization: Token " + token.key)
