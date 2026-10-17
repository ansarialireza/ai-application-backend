from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from rest_framework.test import APITestCase

from apps.accounts.models import ApiClient, Tenant
from core.providers.base import GenerationResult
from .models import Assistant, Conversation, ExecutionRecord, Message


class StubProvider:
    supports_streaming = True

    def generate(self, model, messages, temperature, max_tokens):
        self.messages = messages
        return GenerationResult("Grounded answer", 12, 7)

    def stream(self, model, messages, temperature, max_tokens):
        yield "hello"
        yield " world"


class AssistantApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="One", slug="one")
        self.client_key, prefix, key_hash = ApiClient.generate_key()
        ApiClient.objects.create(
            tenant=self.tenant,
            name="integration client",
            key_prefix=prefix,
            key_hash=key_hash,
        )
        self.other_tenant = Tenant.objects.create(name="Two", slug="two")
        self.assistant = Assistant.objects.create(
            tenant=self.tenant,
            display_name="General",
            model="test-model",
        )

    def auth(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Api-Key {self.client_key}")

    def test_private_api_requires_api_key(self):
        response = self.client.get("/api/v1/assistants/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["error"]["code"], "not_authenticated")

    def test_assistants_are_tenant_scoped(self):
        other = Assistant.objects.create(tenant=self.other_tenant, display_name="Other", model="test")
        self.auth()
        response = self.client.get("/api/v1/assistants/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertNotEqual(str(response.data["results"][0]["id"]), str(other.id))
        self.assertEqual(self.client.get(f"/api/v1/assistants/{other.id}/").status_code, 404)

    def test_assistant_generation_records_usage_and_does_not_return_prompt(self):
        self.auth()
        with patch("core.execution.get_provider", return_value=StubProvider()):
            response = self.client.post(
                f"/api/v1/assistants/{self.assistant.id}/generate/",
                {"question": "What is the answer?"},
                format="json",
            )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["answer"], "Grounded answer")
        self.assertEqual(response.data["usage"], {"prompt_tokens": 12, "completion_tokens": 7})
        record = ExecutionRecord.objects.get()
        self.assertEqual(record.status, ExecutionRecord.STATUS_SUCCEEDED)
        self.assertEqual(record.prompt_tokens, 12)
        self.assertNotIn("question", response.data)

    def test_public_execution_requires_explicit_public_setting(self):
        url = f"/api/v1/public/assistants/{self.assistant.id}/generate/"
        self.assertEqual(self.client.post(url, {"question": "hello"}, format="json").status_code, 404)
        self.assistant.is_public = True
        self.assistant.save(update_fields=["is_public"])
        with patch("core.execution.get_provider", return_value=StubProvider()):
            response = self.client.post(url, {"question": "hello"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

    def test_public_execution_uses_application_rate_limit(self):
        self.assistant.is_public = True
        self.assistant.save(update_fields=["is_public"])
        limit = int(settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["public_execute"].split("/", 1)[0])
        url = f"/api/v1/public/assistants/{self.assistant.id}/generate/"
        cache.clear()
        with patch("core.execution.get_provider", return_value=StubProvider()) as provider:
            responses = [
                self.client.post(url, {"question": "Test"}, format="json")
                for _ in range(limit + 1)
            ]
        self.assertTrue(all(response.status_code == 200 for response in responses[:limit]))
        self.assertEqual(responses[-1].status_code, 429)
        self.assertEqual(provider.call_count, limit)

    def test_conversation_creation_message_order_and_history(self):
        self.auth()
        created = self.client.post(
            "/api/v1/conversations/",
            {"assistant_id": str(self.assistant.id)},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        conversation_id = created.data["id"]
        with patch("core.execution.get_provider", return_value=StubProvider()):
            response = self.client.post(
                f"/api/v1/conversations/{conversation_id}/messages/",
                {"question": "Question"},
                format="json",
            )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            list(Message.objects.filter(conversation_id=conversation_id).values_list("role", flat=True)),
            ["user", "assistant"],
        )
        history = self.client.get(f"/api/v1/conversations/{conversation_id}/messages/")
        self.assertEqual(history.status_code, 200)
        self.assertEqual([row["role"] for row in history.data], ["user", "assistant"])

    def test_cross_tenant_conversation_is_hidden(self):
        other_assistant = Assistant.objects.create(
            tenant=self.other_tenant,
            display_name="Other",
            model="test",
        )
        other_conversation = Conversation.objects.create(
            tenant=self.other_tenant,
            assistant=other_assistant,
        )
        self.auth()
        response = self.client.get(f"/api/v1/conversations/{other_conversation.id}/")
        self.assertEqual(response.status_code, 404)

    def test_invalid_generation_input_has_predictable_error(self):
        self.auth()
        response = self.client.post(
            f"/api/v1/assistants/{self.assistant.id}/generate/",
            {"question": " "},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.data)

    def test_stream_endpoint_returns_sse_events(self):
        self.auth()
        with patch("apps.assistants.views.stream_assistant", return_value=iter(["A", "B"])):
            response = self.client.post(
                f"/api/v1/assistants/{self.assistant.id}/generate/stream/",
                {"question": "Stream this"},
                format="json",
            )
            body = b"".join(response.streaming_content).decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn('"type": "delta", "content": "A"', body)
        self.assertIn('"type": "delta", "content": "B"', body)
        self.assertIn('"type":"done"', body)

    def test_schema_is_available(self):
        response = self.client.get("/api/schema/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("/api/v1/assistants/", response.data["paths"])
        generate = response.data["paths"]["/api/v1/assistants/{id}/generate/"]["post"]
        self.assertIn("requestBody", generate)
