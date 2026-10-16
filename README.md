# AI Application Backend

An independent, tenant-scoped Django REST service for generic assistant configuration, conversations, AI execution, and optional grounding through the RAG Core HTTP API. It does not import or access the Core's database, models, or files.

## Technical assessment of the existing RAG Core

The sibling [`../rag_core`](../rag_core) project is a Django REST Framework service with tenant-owned knowledge bases and API-key authentication. Its actual retrieval contract is:

- `POST /api/v1/search/`
- Header: `Authorization: Api-Key <RAG-Core-client-key>`
- JSON: `{"knowledge_base_id": 123, "query": "...", "top_k": 5, "similarity_threshold": 0.0}`
- Success: `{"results": [{"chunk_id": 1, "document_id": 1, "content": "...", "score": 0.8, "chunk_index": 0, "start_char": 0, "end_char": 5, "document_title": "..."}]}`
- A missing or foreign-tenant knowledge base is returned as 404. The Core's API-key authentication scopes retrieval by tenant.

The Core also exposes tenant-scoped knowledge-base CRUD and document upload/list/delete APIs. Its ingestion code accepts PDF, DOCX, TXT, and Markdown. Ingestion and retrieval are synchronous. The search endpoint returns source text and metadata but does not return citation-verification guarantees. The inspected Core has no automated test files. Its Django check could not run in the available Core virtual environment because Django is not installed there. The Core worktree already had unrelated changes; this backend leaves those untouched.

## Architecture

- The backend is a separate Django 5.2/DRF project, with its own SQLite development option, PostgreSQL deployment option, migrations, API keys, tenant records, models, docs, and tests.
- Every backend client credential is random and stored only as a SHA-256 hash. The management command displays it once. `Api-Key` authentication scopes all private assistant, conversation, and execution queries to that client's tenant.
- Each backend tenant can hold a Fernet-encrypted RAG Core API key. The encryption key is derived from Django `SECRET_KEY`; changing that secret makes existing encrypted Core keys unreadable, so retain and back up the production secret.
- The initial provider adapter implements OpenAI-compatible Chat Completions, with a configurable base URL, normalized usage, timeouts, sanitized errors, and SSE delta parsing. No provider key is stored on an assistant or exposed through the API.
- RAG uses only the Core's public search endpoint and the credential associated with the authenticated backend tenant. The Core remains authoritative for KB authorization.
- Retrieved content is bounded and explicitly treated as untrusted evidence, not instructions. No-context answers receive the assistant's configured insufficient-context instruction. Returned sources are metadata only; citations are not independently verified.
- Conversations are tenant/assistant scoped and retain user/assistant messages. Only the most recent configured history window is sent to the model. Execution records retain provider/model, status, duration, available token usage, failure category, and retrieval use; prompts and message bodies are not copied to execution records.
- Anonymous access is limited to `POST /api/v1/public/assistants/{assistant_uuid}/generate/`, and works only for an assistant explicitly marked `is_public=true`. It has a configurable DRF IP throttle. Private configuration, conversation, and execution endpoints remain API-key protected.

## Requirements and local setup

Python 3.12 is recommended. SQLite is the default for local development; PostgreSQL is recommended for shared/production use.

```powershell
cd ai_application_backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `DJANGO_SECRET_KEY` to a unique random secret, `AI_PROVIDER_API_KEY` to a real provider key, and the RAG variables below when using retrieval. Do not commit `.env`. The sibling Core is a separately configured process/project; its default development port is 8000.

```powershell
python manage.py check
python manage.py migrate
python manage.py create_api_client --tenant-name "Example tenant" --tenant-slug example
python manage.py runserver 8001
```

The client creation command prompts without echoing for the Core API key; leave it blank if RAG is not being used. It prints the new backend API key once. To rotate the Core key later:

```powershell
python manage.py set_rag_core_api_key --tenant-slug example
```

To revoke and rotate a backend API client, issue a replacement and disable the old key atomically:

```powershell
python manage.py rotate_api_client --client-id 1
```

For the local Core, keep `RAG_CORE_BASE_URL=http://127.0.0.1:8000`. When this backend runs in Docker on Windows/macOS and the Core runs directly on the host, use `RAG_CORE_BASE_URL=http://host.docker.internal:8000`. If both projects run in separate Compose projects, configure a shared Docker network or use a routable Core URL; do not assume the `api` service name is shared.

### Environment variables

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Django signing and tenant Core-key encryption secret; must be stable and private |
| `DEBUG`, `ALLOWED_HOSTS` | Django runtime configuration |
| `DATABASE_URL` | Django database URL; defaults to project-local SQLite |
| `RAG_CORE_BASE_URL` | Core origin, without the API path |
| `RAG_CONNECT_TIMEOUT_SECONDS`, `RAG_READ_TIMEOUT_SECONDS` | Explicit Core HTTP timeouts |
| `AI_PROVIDER_API_BASE_URL`, `AI_PROVIDER_API_KEY` | OpenAI-compatible provider origin and secret |
| `AI_PROVIDER_TIMEOUT_SECONDS` | Provider HTTP timeout |
| `PUBLIC_EXECUTION_RATE` | DRF throttle for anonymous public generation, e.g. `10/minute` |
| `MAX_INPUT_CHARS`, `MAX_HISTORY_MESSAGES`, `MAX_OUTPUT_TOKENS` | Request, history, and output limits |
| `MAX_HISTORY_CHARS`, `MAX_RAG_CONTEXT_CHARS` | Total conversation-history and retrieved-context character limits |

For OpenRouter, set `AI_PROVIDER_API_BASE_URL=https://openrouter.ai/api/v1`, keep the OpenRouter key only in the backend's server-side `AI_PROVIDER_API_KEY`, and set each assistant's `model` to an identifier currently listed by OpenRouter (free-model availability changes). The key is used only in the provider adapter's bearer header and is never part of assistant configuration or API responses. `PUBLIC_EXECUTION_RATE` uses Django REST Framework's `ScopedRateThrottle` `num/period` format for anonymous public-assistant calls (default `10/minute`); it is an application ingress limit, not an OpenRouter quota.

## API

All application endpoints are versioned under `/api/v1/`. Private endpoints require `Authorization: Api-Key <backend-client-key>`. Errors use `{"error":{"code":"...","message":"...","details":...}}`; external-service errors include whether a retry is appropriate in `details.retryable`.

| Method and route | Auth | Purpose |
|---|---|---|
| `GET, POST /api/v1/assistants/` | API key | List this tenant's assistants / create a generic assistant profile |
| `GET, PATCH, DELETE /api/v1/assistants/{uuid}/` | API key | Read or manage an assistant in the caller's tenant |
| `POST /api/v1/assistants/{uuid}/generate/` | API key | Stateless generation; RAG runs when configured on the assistant |
| `POST /api/v1/assistants/{uuid}/generate/stream/` | API key | Stream deltas as Server-Sent Events |
| `GET, POST /api/v1/conversations/` | API key | List or create conversations for this tenant |
| `GET /api/v1/conversations/{uuid}/` | API key | Read conversation metadata |
| `GET, POST /api/v1/conversations/{uuid}/messages/` | API key | Read up to the latest 100 messages, or add a user question and execute the assistant |
| `GET /api/v1/executions/` | API key | List this tenant's execution metadata |
| `GET /api/v1/executions/{request_uuid}/` | API key | Read one execution record |
| `POST /api/v1/public/assistants/{uuid}/generate/` | Anonymous, explicit public flag, throttled | Execute only a public assistant |
| `GET /health/` | Public | Liveness response |
| `GET /api/schema/`, `GET /api/docs/` | Public | OpenAPI JSON and Swagger UI |

Assistant create example:

```powershell
$headers = @{ Authorization = "Api-Key $env:AI_BACKEND_API_KEY" }
$assistant = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8001/api/v1/assistants/ `
  -Headers $headers -ContentType "application/json" -Body (@{
    display_name = "Knowledge assistant"
    model = "your-chat-model"
    system_instructions = "Answer clearly and concisely."
    rag_enabled = $true
    core_knowledge_base_id = 123
    retrieval_top_k = 5
  } | ConvertTo-Json)
```

Generate:

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/api/v1/assistants/$($assistant.id)/generate/" `
  -Headers $headers -ContentType "application/json" -Body '{"question":"What does the source say?"}'
```

Conversation flow:

```powershell
$conversation = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8001/api/v1/conversations/ `
  -Headers $headers -ContentType "application/json" -Body (@{ assistant_id = $assistant.id } | ConvertTo-Json)
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/api/v1/conversations/$($conversation.id)/messages/" `
  -Headers $headers -ContentType "application/json" -Body '{"question":"Continue our discussion"}'
```

Generation returns `answer`, `sources` (Core chunk/document metadata, not source text), `usage` (nullable counts if unknown), and `execution_id`. Streaming returns SSE `delta`, `done`, and sanitized `error` events. Non-streaming execution records expose `request_id`, provider/model, status, duration, available usage, error category, and whether RAG was configured for the request.

`assistant` UUIDs are backend identifiers and are distinct from numeric RAG Core knowledge-base IDs. The configured Core credential for each tenant is what authorizes its KB reference; a foreign or inaccessible KB is rejected by the Core.

## Run with Docker Compose

Copy `.env.example` to `.env`, set a strong `DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD`, and configure provider/Core credentials. Compose starts its own PostgreSQL database and the backend on port 8001; it does not change or join the Core's Compose services.

```powershell
docker compose up --build
```

## Tests and database checks

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --check
python manage.py test apps core
```

The automated suite mocks external HTTP boundaries. It verifies provider normalization/errors/stream parsing, the real Core request path/schema/auth header, empty and malformed retrieval, RAG prompt boundaries, execution usage, tenant isolation, API authentication, public assistant gating, conversations, and schema generation. These tests do not claim external-service verification.

## Known limits

- Only one real adapter is included: OpenAI-compatible Chat Completions. Other vendors are not claimed as supported; compatibility depends on their actual API behavior.
- The running RAG Core answered its health request with HTTP 200 and rejected a deliberately invalid search key with HTTP 401. A successful authorized retrieval could not be exercised: no tenant-scoped Core API key was available, and the existing Core container's source bind mount is unavailable, preventing safe provisioning of a disposable client there. The available Core embedding credential is not a retrieval API key.
- No AI chat-provider key was configured, so real model calls were not attempted. The public OpenRouter catalog on 2026-10-16 listed `liquid/lfm-2.5-2.6b:free` as a text-to-text free model supporting this adapter's `temperature` and `max_tokens` parameters; the catalog candidate was not invoked. OpenAI-compatible calls, errors, and streaming were validated against mocked HTTP responses only. Supply a valid provider key and a usable tenant Core API key to verify the complete live RAG-plus-generation flow.
- Public throttling uses Django REST Framework's default local-memory cache unless deployment configures a shared cache, so multi-process production deployments should also enforce edge/API-gateway rate limits.
- The Core itself has no tests and could not pass framework checks here because Django is missing from its existing virtual environment. No Core files or schema were changed.
- No end-user account system is invented: trusted application clients are the private API principal. Public assistant execution is explicitly separate and does not grant conversation-history access.
- Execution records intentionally omit prompt/body logging and exact cost estimates. Streamed responses report content deltas; usage remains unavailable unless returned by the provider.
