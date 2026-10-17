from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory

from .authentication import ApiKeyAuthentication
from .models import ApiClient, Tenant


class ApiKeyAuthenticationTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Tenant A", slug="tenant-a")
        self.raw_key, prefix, key_hash = ApiClient.generate_key()
        self.client_record = ApiClient.objects.create(
            tenant=self.tenant,
            name="test",
            key_prefix=prefix,
            key_hash=key_hash,
        )
        self.factory = APIRequestFactory()

    def test_key_authentication_scopes_request_to_tenant_and_never_stores_raw_key(self):
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"Api-Key {self.raw_key}")
        client, _ = ApiKeyAuthentication().authenticate(request)
        self.assertEqual(client.pk, self.client_record.pk)
        self.assertEqual(request.tenant.pk, self.tenant.pk)
        self.assertNotEqual(self.client_record.key_hash, self.raw_key)

    def test_invalid_or_inactive_key_is_rejected(self):
        request = self.factory.get("/", HTTP_AUTHORIZATION="Api-Key invalid")
        with self.assertRaises(AuthenticationFailed):
            ApiKeyAuthentication().authenticate(request)
        self.client_record.is_active = False
        self.client_record.save(update_fields=["is_active"])
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"Api-Key {self.raw_key}")
        with self.assertRaises(AuthenticationFailed):
            ApiKeyAuthentication().authenticate(request)

    @override_settings(SECRET_KEY="test-key")
    def test_core_key_is_encrypted_and_round_trips(self):
        tenant = Tenant.objects.create(name="Encrypted", slug="encrypted")
        tenant.set_rag_core_api_key("rag_secret_value")
        self.assertNotIn("rag_secret_value", tenant.rag_core_api_key_encrypted)
        self.assertEqual(tenant.get_rag_core_api_key(), "rag_secret_value")

    def test_rotating_a_key_revokes_the_previous_client(self):
        output = StringIO()
        call_command("rotate_api_client", client_id=self.client_record.pk, stdout=output)
        self.client_record.refresh_from_db()
        replacement = ApiClient.objects.get(tenant=self.tenant, is_active=True)
        self.assertFalse(self.client_record.is_active)
        self.assertNotEqual(replacement.key_hash, self.client_record.key_hash)
        self.assertIn("API key (shown once): aib_", output.getvalue())
