"""
Création d'une entreprise et de son premier administrateur.

    python manage.py create_tenant --name "Ma Société" --code ma-societe --admin admin
(le mot de passe est demandé de manière masquée s'il n'est pas fourni)
"""
import getpass

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.services import create_tenant
from apps.core.models import Tenant


class Command(BaseCommand):
    help = "Crée une entreprise, ses rôles prédéfinis et son administrateur."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="Raison sociale")
        parser.add_argument("--code", required=True, help="Code court (lettres, chiffres, tirets)")
        parser.add_argument("--admin", required=True, help="Identifiant de l'administrateur")
        parser.add_argument("--password", help="Mot de passe (sinon demandé)")
        parser.add_argument("--email", default="")

    def handle(self, *args, **options):
        if Tenant.objects.filter(code=options["code"]).exists():
            raise CommandError(f"Une entreprise avec le code « {options['code']} » existe déjà.")
        password = options.get("password")
        if not password:
            password = getpass.getpass("Mot de passe de l'administrateur : ")
            if password != getpass.getpass("Confirmation : "):
                raise CommandError("Les mots de passe ne correspondent pas.")
        try:
            password_validation.validate_password(password)
        except ValidationError as error:
            raise CommandError(" ".join(error.messages)) from error
        tenant, user = create_tenant(
            name=options["name"], code=options["code"], admin_username=options["admin"],
            admin_password=password, admin_email=options["email"],
        )
        self.stdout.write(self.style.SUCCESS(f"Entreprise « {tenant} » créée, administrateur « {user.username} »."))
