from getpass import getpass

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import Tenant


class Command(BaseCommand):
    help = "Set or rotate a tenant's encrypted RAG Core API credential."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-slug", required=True)

    def handle(self, *args, **options):
        try:
            tenant = Tenant.objects.get(slug=options["tenant_slug"])
        except Tenant.DoesNotExist as exc:
            raise CommandError("Tenant not found.") from exc
        raw_key = getpass("New RAG Core API key: ")
        if not raw_key:
            raise CommandError("The API key cannot be empty.")
        tenant.set_rag_core_api_key(raw_key)
        tenant.save(update_fields=["rag_core_api_key_encrypted"])
        self.stdout.write(self.style.SUCCESS(f"Updated encrypted RAG Core credential for '{tenant.slug}'."))
