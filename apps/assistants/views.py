import json
import logging

from django.conf import settings
from django.db import transaction
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiResponse, OpenApiTypes, extend_schema

from core.execution import execute_assistant, stream_assistant
from core.exceptions import ServiceError
from .models import Assistant, Conversation, ExecutionRecord, Message
from .serializers import (
    AssistantSerializer,
    ConversationCreateSerializer,
    ConversationSerializer,
    ConversationGenerationResponseSerializer,
    ExecutionRecordSerializer,
    GenerationResponseSerializer,
    GenerationRequestSerializer,
    MessageSerializer,
)

logger = logging.getLogger(__name__)


class AssistantViewSet(viewsets.ModelViewSet):
    queryset = Assistant.objects.all()
    serializer_class = AssistantSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Assistant.objects.filter(tenant=self.request.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @extend_schema(request=GenerationRequestSerializer, responses=GenerationResponseSerializer)
    @action(detail=True, methods=["post"])
    def generate(self, request, pk=None):
        assistant = self.get_object()
        serializer = GenerationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = execute_assistant(assistant, request.tenant, serializer.validated_data["question"])
        return Response(result, status=status.HTTP_200_OK)

    @extend_schema(
        request=GenerationRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.STR,
                description="Server-Sent Events: delta, done, and sanitized error events.",
            )
        },
    )
    @action(detail=True, methods=["post"], url_path="generate/stream")
    def stream(self, request, pk=None):
        assistant = self.get_object()
        serializer = GenerationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.validated_data["question"]

        def events():
            try:
                for text in stream_assistant(assistant, request.tenant, question):
                    yield f"data: {json.dumps({'type': 'delta', 'content': text})}\n\n"
                yield 'data: {"type":"done"}\n\n'
            except ServiceError as exc:
                yield f"data: {json.dumps({'type': 'error', 'error': {'code': exc.code, 'message': str(exc)}})}\n\n"
            except Exception:
                logger.exception("Streaming response failed")
                yield 'data: {"type":"error","error":{"code":"internal_error","message":"An internal error occurred."}}\n\n'

        return StreamingHttpResponse(events(), content_type="text/event-stream")


class ConversationViewSet(viewsets.ModelViewSet):
    queryset = Conversation.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return Conversation.objects.filter(tenant=self.request.tenant).select_related("assistant")

    def get_serializer_class(self):
        if self.action == "create":
            return ConversationCreateSerializer
        return ConversationSerializer

    def perform_create(self, serializer):
        conversation = serializer.save(tenant=self.request.tenant)
        if not conversation.title:
            conversation.title = conversation.assistant.display_name
            conversation.save(update_fields=["title"])

    @extend_schema(
        methods=["GET"],
        responses=MessageSerializer(many=True),
    )
    @extend_schema(
        methods=["POST"],
        request=GenerationRequestSerializer,
        responses=ConversationGenerationResponseSerializer,
    )
    @action(detail=True, methods=["get", "post"])
    def messages(self, request, pk=None):
        if request.method == "GET":
            conversation = self.get_object()
            messages = list(conversation.messages.order_by("-created_at", "-id")[:100])
            messages.reverse()
            return Response(MessageSerializer(messages, many=True).data)

        serializer = GenerationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.validated_data["question"]
        failure = None
        result = None

        with transaction.atomic():
            try:
                conversation = (
                    Conversation.objects.select_for_update()
                    .select_related("assistant")
                    .get(pk=pk, tenant=request.tenant)
                )
            except (Conversation.DoesNotExist, ValueError) as exc:
                raise NotFound("Conversation not found.") from exc
            history = list(
                conversation.messages.order_by("-created_at", "-id")
                .values("role", "content")[: settings.MAX_HISTORY_MESSAGES]
            )
            history.reverse()
            Message.objects.create(
                conversation=conversation,
                role=Message.ROLE_USER,
                content=question,
            )
            conversation.updated_at = timezone.now()
            conversation.save(update_fields=["updated_at"])
            try:
                result = execute_assistant(
                    conversation.assistant,
                    request.tenant,
                    question,
                    history=history,
                )
                Message.objects.create(
                    conversation=conversation,
                    role=Message.ROLE_ASSISTANT,
                    content=result["answer"],
                )
                conversation.updated_at = timezone.now()
                conversation.save(update_fields=["updated_at"])
            except Exception as exc:
                failure = exc

        if failure is not None:
            raise failure
        return Response(
            {
                "conversation_id": conversation.id,
                **result,
            },
            status=status.HTTP_200_OK,
        )


class PublicGenerationView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_execute"

    @extend_schema(request=GenerationRequestSerializer, responses=GenerationResponseSerializer)
    def post(self, request, assistant_id):
        assistant = get_object_or_404(Assistant, pk=assistant_id, is_public=True)
        serializer = GenerationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = execute_assistant(
            assistant,
            assistant.tenant,
            serializer.validated_data["question"],
        )
        return Response(result, status=status.HTTP_200_OK)


class ExecutionRecordViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ExecutionRecord.objects.all()
    serializer_class = ExecutionRecordSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "request_id"

    def get_queryset(self):
        return ExecutionRecord.objects.filter(tenant=self.request.tenant)
