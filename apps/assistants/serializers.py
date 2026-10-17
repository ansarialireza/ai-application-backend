import math

from django.conf import settings
from rest_framework import serializers

from .models import Assistant, Conversation, ExecutionRecord, Message


class AssistantSerializer(serializers.ModelSerializer):
    description = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    system_instructions = serializers.CharField(required=False, allow_blank=True, max_length=8000)

    class Meta:
        model = Assistant
        fields = [
            "id", "display_name", "description", "provider", "model", "system_instructions",
            "temperature", "max_output_tokens", "rag_enabled", "core_knowledge_base_id",
            "retrieval_top_k", "similarity_threshold", "insufficient_context_instructions",
            "is_public", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        instance = self.instance
        rag_enabled = attrs.get("rag_enabled", instance.rag_enabled if instance else False)
        kb_id = attrs.get(
            "core_knowledge_base_id",
            instance.core_knowledge_base_id if instance else None,
        )
        if rag_enabled and not kb_id:
            raise serializers.ValidationError({"core_knowledge_base_id": "Required when RAG is enabled."})
        token_limit = attrs.get("max_output_tokens", instance.max_output_tokens if instance else 1024)
        if not 1 <= token_limit <= settings.MAX_OUTPUT_TOKENS:
            raise serializers.ValidationError(
                {"max_output_tokens": f"Must be between 1 and {settings.MAX_OUTPUT_TOKENS}."}
            )
        provider = attrs.get("provider", instance.provider if instance else Assistant.PROVIDER_OPENAI_COMPATIBLE)
        if provider != Assistant.PROVIDER_OPENAI_COMPATIBLE:
            raise serializers.ValidationError({"provider": "This provider is not supported."})
        temperature = attrs.get("temperature", instance.temperature if instance else 0.2)
        threshold = attrs.get(
            "similarity_threshold",
            instance.similarity_threshold if instance else 0.0,
        )
        if not math.isfinite(temperature):
            raise serializers.ValidationError({"temperature": "Must be a finite number."})
        if not math.isfinite(threshold):
            raise serializers.ValidationError({"similarity_threshold": "Must be a finite number."})
        return attrs


class ConversationCreateSerializer(serializers.ModelSerializer):
    assistant_id = serializers.PrimaryKeyRelatedField(
        source="assistant",
        queryset=Assistant.objects.none(),
        write_only=True,
    )

    class Meta:
        model = Conversation
        fields = ["id", "assistant_id", "title", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and hasattr(request, "tenant"):
            self.fields["assistant_id"].queryset = Assistant.objects.filter(tenant=request.tenant)


class ConversationSerializer(serializers.ModelSerializer):
    assistant_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Conversation
        fields = ["id", "assistant_id", "title", "created_at", "updated_at"]
        read_only_fields = fields


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "role", "content", "created_at"]
        read_only_fields = fields


class GenerationRequestSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=settings.MAX_INPUT_CHARS, trim_whitespace=True)

    def validate_question(self, value):
        if len(value) > settings.MAX_INPUT_CHARS:
            raise serializers.ValidationError(f"Must be at most {settings.MAX_INPUT_CHARS} characters.")
        return value


class SourceReferenceSerializer(serializers.Serializer):
    chunk_id = serializers.IntegerField(required=False, allow_null=True)
    document_id = serializers.IntegerField(required=False, allow_null=True)
    document_title = serializers.CharField()
    chunk_index = serializers.IntegerField(required=False, allow_null=True)
    score = serializers.FloatField(required=False, allow_null=True)


class UsageSerializer(serializers.Serializer):
    prompt_tokens = serializers.IntegerField(allow_null=True)
    completion_tokens = serializers.IntegerField(allow_null=True)


class GenerationResponseSerializer(serializers.Serializer):
    answer = serializers.CharField()
    sources = SourceReferenceSerializer(many=True)
    usage = UsageSerializer()
    execution_id = serializers.UUIDField()


class ConversationGenerationResponseSerializer(GenerationResponseSerializer):
    conversation_id = serializers.UUIDField()


class ExecutionRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExecutionRecord
        fields = [
            "request_id", "assistant_id_snapshot", "assistant_name", "provider", "model",
            "status", "started_at", "completed_at", "duration_ms", "prompt_tokens",
            "completion_tokens", "error_category", "retrieval_used",
        ]
        read_only_fields = fields
