from django.contrib import admin

from .models import Assistant, Conversation, ExecutionRecord, Message


@admin.register(Assistant)
class AssistantAdmin(admin.ModelAdmin):
    list_display = ("display_name", "tenant", "provider", "model", "rag_enabled", "is_public")
    list_filter = ("tenant", "provider", "rag_enabled", "is_public")


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ("role", "content", "created_at")
    can_delete = False


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "assistant", "title", "updated_at")
    list_filter = ("tenant",)
    inlines = [MessageInline]


@admin.register(ExecutionRecord)
class ExecutionRecordAdmin(admin.ModelAdmin):
    list_display = ("request_id", "tenant", "assistant_name", "status", "provider", "model", "started_at")
    list_filter = ("tenant", "status", "provider", "retrieval_used")
    readonly_fields = [field.name for field in ExecutionRecord._meta.fields]
