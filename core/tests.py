from unittest.mock import Mock, patch

import httpx
from django.test import SimpleTestCase, TestCase, override_settings

from apps.accounts.models import Tenant
from apps.assistants.models import Assistant, ExecutionRecord
from core.execution import execute_assistant
from core.providers.base import (
    GenerationResult,
    ProviderNotConfigured,
    ProviderRejected,
    ProviderTimeout,
)
from core.providers.openai_compatible import OpenAICompatibleProvider
from core.rag_client import (
    RagAuthenticationError,
    RagCoreClient,
    RagKnowledgeBaseError,
    RagResponseError,
    RagTimeout,
)


def mock_response(status_code=200, payload=None):
    response = Mock()
    response.status_code = status_code
    response.is_error = status_code >= 400
    response.json.return_value = payload or {}
    return response


class ProviderTests(SimpleTestCase):
    @override_settings(AI_PROVIDER_API_BASE_URL="https://provider.test/v1", AI_PROVIDER_API_KEY="secret")
    @patch("core.providers.openai_compatible.httpx.post")
    def test_success_normalizes_content_and_usage(self, post):
        post.return_value = mock_response(200, {
            "choices": [{"message": {"content": "Hello"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4},
        })
        result = OpenAICompatibleProvider().generate("model", [{"role": "user", "content": "Hi"}], 0.2, 100)
        self.assertEqual(result, GenerationResult("Hello", 3, 4))
        self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], 100)

    @override_settings(AI_PROVIDER_API_KEY="")
    def test_missing_key_is_explicit(self):
        with self.assertRaises(ProviderNotConfigured):
            OpenAICompatibleProvider().generate("model", [], 0.2, 10)

    @override_settings(AI_PROVIDER_API_KEY="secret")
    @patch("core.providers.openai_compatible.httpx.post")
    def test_timeout_and_provider_error_are_normalized(self, post):
        post.side_effect = httpx.TimeoutException("private")
        with self.assertRaises(ProviderTimeout):
            OpenAICompatibleProvider().generate("model", [], 0.2, 10)
        post.side_effect = None
        post.return_value = mock_response(429, {})
        with self.assertRaises(ProviderRejected) as raised:
            OpenAICompatibleProvider().generate("model", [], 0.2, 10)
        self.assertTrue(raised.exception.retryable)

    @override_settings(AI_PROVIDER_API_KEY="secret")
    @patch("core.providers.openai_compatible.httpx.post")
    def test_malformed_completion_fails_instead_of_faking_success(self, post):
        post.return_value = mock_response(200, {"choices": []})
        with self.assertRaises(Exception) as raised:
            OpenAICompatibleProvider().generate("model", [], 0.2, 10)
        self.assertEqual(raised.exception.code, "provider_invalid_response")

    @override_settings(AI_PROVIDER_API_KEY="secret")
    @patch("core.providers.openai_compatible.httpx.stream")
    def test_streaming_normalizes_delta_events(self, stream):
        response = Mock()
        response.is_error = False
        response.iter_lines.return_value = [
            'data: {"choices":[{"delta":{"content":"A"}}]}',
            'data: {"choices":[{"delta":{"content":"B"}}]}',
            "data: [DONE]",
        ]
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        stream.return_value = context
        self.assertEqual(list(OpenAICompatibleProvider().stream("m", [], 0.2, 10)), ["A", "B"])


class RagClientTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="RAG", slug="rag")
        self.tenant.set_rag_core_api_key("core-key")
        self.tenant.save(update_fields=["rag_core_api_key_encrypted"])

    @patch("core.rag_client.httpx.post")
    def test_uses_actual_search_api_contract_and_returns_source_metadata(self, post):
        post.return_value = mock_response(200, {
            "results": [{
                "chunk_id": 3,
                "document_id": 8,
                "content": "source text",
                "score": 0.8,
                "chunk_index": 1,
                "start_char": 0,
                "end_char": 11,
                "document_title": "manual.pdf",
            }],
        })
        result = RagCoreClient().retrieve(self.tenant, 99, "question", 5, 0.25)
        request = post.call_args
        self.assertTrue(request.args[0].endswith("/api/v1/search/"))
        self.assertEqual(request.kwargs["headers"]["Authorization"], "Api-Key core-key")
        self.assertEqual(request.kwargs["json"], {
            "knowledge_base_id": 99,
            "query": "question",
            "top_k": 5,
            "similarity_threshold": 0.25,
        })
        self.assertEqual(result[0]["document_title"], "manual.pdf")

    @patch("core.rag_client.httpx.post")
    def test_empty_results_are_valid(self, post):
        post.return_value = mock_response(200, {"results": []})
        self.assertEqual(RagCoreClient().retrieve(self.tenant, 1, "no match", 5, 0), [])

    @patch("core.rag_client.httpx.post")
    def test_core_auth_and_inaccessible_kb_errors_are_explicit(self, post):
        post.return_value = mock_response(401)
        with self.assertRaises(RagAuthenticationError):
            RagCoreClient().retrieve(self.tenant, 1, "q", 5, 0)
        post.return_value = mock_response(404)
        with self.assertRaises(RagKnowledgeBaseError):
            RagCoreClient().retrieve(self.tenant, 999, "q", 5, 0)

    @patch("core.rag_client.httpx.post")
    def test_malformed_responses_timeout_and_connection_errors(self, post):
        post.return_value = mock_response(200, {"results": [{"content": 42}]})
        with self.assertRaises(RagResponseError):
            RagCoreClient().retrieve(self.tenant, 1, "q", 5, 0)
        post.side_effect = httpx.TimeoutException("secret")
        with self.assertRaises(RagTimeout) as raised:
            RagCoreClient().retrieve(self.tenant, 1, "q", 5, 0)
        self.assertTrue(raised.exception.retryable)
        post.side_effect = httpx.ConnectError("offline")
        with self.assertRaises(Exception) as raised:
            RagCoreClient().retrieve(self.tenant, 1, "q", 5, 0)
        self.assertEqual(raised.exception.code, "rag_core_unavailable")

    def test_missing_core_credential_fails_closed(self):
        tenant = Tenant.objects.create(name="No key", slug="no-key")
        with self.assertRaises(RagAuthenticationError):
            RagCoreClient().retrieve(tenant, 1, "q", 5, 0)


class ExecutionTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Exec", slug="exec")
        self.assistant = Assistant.objects.create(
            tenant=self.tenant,
            display_name="Grounded",
            model="model",
            rag_enabled=True,
            core_knowledge_base_id=15,
        )

    def test_rag_prompt_marks_retrieved_text_as_untrusted_and_records_usage(self):
        provider = Mock()
        provider.generate.return_value = GenerationResult("Supported answer", 5, 6)
        rag_client = Mock()
        rag_client.retrieve.return_value = [{
            "content": "document says hello",
            "document_id": 4,
            "document_title": "source.txt",
            "chunk_id": 7,
            "chunk_index": 0,
            "score": 0.9,
        }]
        result = execute_assistant(
            self.assistant,
            self.tenant,
            "Question?",
            provider=provider,
            rag_client=rag_client,
        )
        prompt = provider.generate.call_args.args[1]
        self.assertIn("untrusted", prompt[1]["content"])
        self.assertIn("document says hello", prompt[-1]["content"])
        self.assertEqual(result["sources"][0]["document_title"], "source.txt")
        self.assertNotIn("content", result["sources"][0])
        record = ExecutionRecord.objects.get()
        self.assertTrue(record.retrieval_used)
        self.assertEqual((record.prompt_tokens, record.completion_tokens), (5, 6))

    def test_rag_with_no_sources_instructs_insufficient_context(self):
        self.assistant.rag_enabled = True
        self.assistant.core_knowledge_base_id = 15
        provider = Mock()
        provider.generate.return_value = GenerationResult("I don't know")
        result = execute_assistant(
            self.assistant,
            self.tenant,
            "Question?",
            provider=provider,
            rag_client=Mock(retrieve=Mock(return_value=[])),
        )
        self.assertEqual(result["sources"], [])
        self.assertIn("No relevant source material", provider.generate.call_args.args[1][-1]["content"])

    def test_disabled_rag_does_not_call_core(self):
        self.assistant.rag_enabled = False
        provider = Mock()
        provider.generate.return_value = GenerationResult("Answer")
        rag = Mock()
        execute_assistant(self.assistant, self.tenant, "Question", provider=provider, rag_client=rag)
        rag.retrieve.assert_not_called()

    def test_provider_failure_is_recorded_without_prompt_contents(self):
        provider = Mock()
        provider.generate.side_effect = ProviderRejected("Provider rejected request.")
        with self.assertRaises(ProviderRejected):
            execute_assistant(
                self.assistant,
                self.tenant,
                "sensitive question text",
                provider=provider,
                rag_client=Mock(retrieve=Mock(return_value=[])),
            )
        record = ExecutionRecord.objects.get()
        self.assertEqual(record.status, ExecutionRecord.STATUS_FAILED)
        self.assertEqual(record.error_category, "provider_rejected")
        self.assertFalse(hasattr(record, "prompt"))
