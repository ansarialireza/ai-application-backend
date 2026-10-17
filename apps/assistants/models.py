import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.accounts.models import Tenant


class Assistant(models.Model):
    PROVIDER_OPENAI_COMPATIBLE = "openai_compatible"
    PROVIDER_CHOICES = [(PROVIDER_OPENAI_COMPATIBLE, "OpenAI-compatible Chat Completions")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="assistants")
    display_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES, default=PROVIDER_OPENAI_COMPATIBLE)
    model = models.CharField(max_length=128)
    system_instructions = models.TextField(blank=True)
    temperature = models.FloatField(default=0.2, validators=[MinValueValidator(0), MaxValueValidator(2)])
    max_output_tokens = models.PositiveIntegerField(default=1024)
    rag_enabled = models.BooleanField(default=False)
    core_knowledge_base_id = models.PositiveBigIntegerField(null=True, blank=True)
    retrieval_top_k = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(1), MaxValueValidator(20)])
    similarity_threshold = models.FloatField(default=0.0, validators=[MinValueValidator(-1), MaxValueValidator(1)])
    insufficient_context_instructions = models.CharField(
        max_length=500,
        default="State that the available sources do not contain enough information to answer.",
    )
    is_public = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["tenant", "updated_at"])]

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.rag_enabled and not self.core_knowledge_base_id:
            raise ValidationError({"core_knowledge_base_id": "A Core knowledge-base ID is required when RAG is enabled."})
        if self.max_output_tokens > settings.MAX_OUTPUT_TOKENS:
            raise ValidationError({"max_output_tokens": f"Must be at most {settings.MAX_OUTPUT_TOKENS}."})

    def __str__(self):
        return self.display_name


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="conversations")
    assistant = models.ForeignKey(Assistant, on_delete=models.CASCADE, related_name="conversations")
    title = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["tenant", "updated_at"])]

    def __str__(self):
        return self.title or str(self.id)


class Message(models.Model):
    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_CHOICES = [(ROLE_USER, "User"), (ROLE_ASSISTANT, "Assistant")]

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["conversation", "created_at"])]


class ExecutionRecord(models.Model):
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [(STATUS_SUCCEEDED, "Succeeded"), (STATUS_FAILED, "Failed")]

    request_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="executions")
    assistant = models.ForeignKey(Assistant, null=True, on_delete=models.SET_NULL, related_name="executions")
    assistant_id_snapshot = models.UUIDField()
    assistant_name = models.CharField(max_length=255)
    provider = models.CharField(max_length=32)
    model = models.CharField(max_length=128)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField()
    duration_ms = models.PositiveIntegerField()
    prompt_tokens = models.PositiveIntegerField(null=True, blank=True)
    completion_tokens = models.PositiveIntegerField(null=True, blank=True)
    error_category = models.CharField(max_length=64, blank=True)
    retrieval_used = models.BooleanField(default=False)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["tenant", "started_at"])]
