from getpass import getpass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from apps.accounts.models import ApiClient, Tenant


class Command(BaseCommand):
    help = "Create a tenant and one-time API client credential."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-name", required=True)
        parser.add_argument("--tenant-slug")
        parser.add_argument("--client-name", default="default")

    @transaction.atomic
    def handle(self, *args, **options):
        slug = options["tenant_slug"] or slugify(options["tenant_name"])
        if not slug:
            raise CommandError("A non-empty tenant slug is required.")
        if Tenant.objects.filter(slug=slug).exists():
            raise CommandError(f"Tenant '{slug}' already exists; credentials were not changed.")
        raw_core_key = getpass("RAG Core API key (leave empty if RAG is unused): ")
        tenant = Tenant.objects.create(name=options["tenant_name"], slug=slug)
        if raw_core_key:
            tenant.set_rag_core_api_key(raw_core_key)
            tenant.save(update_fields=["rag_core_api_key_encrypted"])
        raw_key, prefix, key_hash = ApiClient.generate_key()
        ApiClient.objects.create(
            tenant=tenant,
            name=options["client_name"],
            key_prefix=prefix,
            key_hash=key_hash,
        )
        self.stdout.write(self.style.SUCCESS(f"Tenant '{slug}' and API client created."))
        self.stdout.write(f"API key (shown once): {raw_key}")
