import math

import httpx
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .exceptions import ServiceError


class RagError(ServiceError):
    code = "rag_core_error"


class RagAuthenticationError(RagError):
    code = "rag_core_authentication_failed"


class RagKnowledgeBaseError(RagError):
    code = "rag_knowledge_base_unavailable"
    status_code = 422


class RagTimeout(RagError):
    code = "rag_core_timeout"
    status_code = 504
    retryable = True


class RagUnavailable(RagError):
    code = "rag_core_unavailable"
    status_code = 503
    retryable = True


class RagResponseError(RagError):
    code = "rag_core_invalid_response"


class RagCoreClient:
    def retrieve(self, tenant, knowledge_base_id: int, query: str, top_k: int, similarity_threshold: float):
        try:
            api_key = tenant.get_rag_core_api_key()
        except ImproperlyConfigured as exc:
            raise RagAuthenticationError("No usable RAG Core credential is configured for this tenant.") from exc
        timeout = httpx.Timeout(
            connect=settings.RAG_CONNECT_TIMEOUT_SECONDS,
            read=settings.RAG_READ_TIMEOUT_SECONDS,
            write=settings.RAG_READ_TIMEOUT_SECONDS,
            pool=settings.RAG_CONNECT_TIMEOUT_SECONDS,
        )
        try:
            response = httpx.post(
                f"{settings.RAG_CORE_BASE_URL}/api/v1/search/",
                headers={"Authorization": f"Api-Key {api_key}"},
                json={
                    "knowledge_base_id": knowledge_base_id,
                    "query": query,
                    "top_k": top_k,
                    "similarity_threshold": similarity_threshold,
                },
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise RagTimeout("The RAG Core request timed out.") from exc
        except httpx.HTTPError as exc:
            raise RagUnavailable("The RAG Core could not be reached.") from exc

        if response.status_code in (401, 403):
            raise RagAuthenticationError("The RAG Core rejected this tenant's credential.")
        if response.status_code == 404:
            raise RagKnowledgeBaseError("The configured knowledge base is unavailable to this tenant.")
        if response.status_code >= 500:
            raise RagUnavailable("The RAG Core is temporarily unavailable.")
        if response.is_error:
            raise RagResponseError(f"The RAG Core rejected the retrieval request (HTTP {response.status_code}).")
        try:
            payload = response.json()
            results = payload["results"]
            if not isinstance(results, list):
                raise TypeError
            validated = []
            for item in results:
                if not isinstance(item, dict):
                    raise TypeError
                content = item["content"]
                if not isinstance(content, str):
                    raise TypeError
                document_id = item.get("document_id")
                chunk_id = item.get("chunk_id")
                chunk_index = item.get("chunk_index")
                for identifier in (document_id, chunk_id, chunk_index):
                    if identifier is not None and (
                        isinstance(identifier, bool) or not isinstance(identifier, int)
                    ):
                        raise TypeError
                score = item.get("score")
                if score is not None and (
                    isinstance(score, bool)
                    or not isinstance(score, (int, float))
                    or not math.isfinite(score)
                ):
                    raise TypeError
                title = item.get("document_title", "")
                if not isinstance(title, str):
                    raise TypeError
                validated.append({
                    "content": content[:12000],
                    "document_id": document_id,
                    "document_title": title[:255],
                    "chunk_id": chunk_id,
                    "chunk_index": chunk_index,
                    "score": score,
                })
            return validated[:top_k]
        except (ValueError, TypeError, KeyError) as exc:
            raise RagResponseError("The RAG Core returned an invalid retrieval response.") from exc
