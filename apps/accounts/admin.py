from django.contrib import admin

from .models import ApiClient, Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "created_at")
    readonly_fields = ("rag_core_api_key_encrypted",)


@admin.register(ApiClient)
class ApiClientAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "key_prefix", "is_active", "created_at", "last_used_at")
    readonly_fields = ("key_prefix", "key_hash", "created_at", "last_used_at")
    list_filter = ("is_active", "tenant")
