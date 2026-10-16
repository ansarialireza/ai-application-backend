from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import ApiClient


class Command(BaseCommand):
    help = "Revoke a backend API client key and issue a replacement."

    def add_arguments(self, parser):
        parser.add_argument("--client-id", required=True, type=int)

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            old_client = ApiClient.objects.select_for_update().get(pk=options["client_id"])
        except ApiClient.DoesNotExist as exc:
            raise CommandError("API client not found.") from exc
        raw_key, prefix, key_hash = ApiClient.generate_key()
        old_client.is_active = False
        old_client.save(update_fields=["is_active"])
        new_client = ApiClient.objects.create(
            tenant=old_client.tenant,
            name=old_client.name,
            key_prefix=prefix,
            key_hash=key_hash,
        )
        self.stdout.write(self.style.SUCCESS(f"Client key rotated; new client ID: {new_client.pk}."))
        self.stdout.write(f"API key (shown once): {raw_key}")
