import hashlib
import secrets

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import models
from django.utils import timezone


def _credential_cipher():
    key = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    import base64

    return Fernet(base64.urlsafe_b64encode(key))


class Tenant(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    rag_core_api_key_encrypted = models.TextField(blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def set_rag_core_api_key(self, raw_key: str) -> None:
        if not raw_key or len(raw_key) > 512:
            raise ValidationError("A valid RAG Core API key is required.")
        self.rag_core_api_key_encrypted = _credential_cipher().encrypt(raw_key.encode()).decode()

    def get_rag_core_api_key(self) -> str:
        if not self.rag_core_api_key_encrypted:
            raise ImproperlyConfigured("No RAG Core API key is configured for this tenant.")
        try:
            return _credential_cipher().decrypt(self.rag_core_api_key_encrypted.encode()).decode()
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise ImproperlyConfigured("The tenant's RAG Core credential cannot be decrypted.") from exc

    def __str__(self):
        return self.name


class ApiClient(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="api_clients")
    name = models.CharField(max_length=255)
    key_prefix = models.CharField(max_length=16)
    key_hash = models.CharField(max_length=64, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @staticmethod
    def hash_key(raw_key: str) -> str:
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    @classmethod
    def generate_key(cls) -> tuple[str, str, str]:
        raw_key = f"aib_{secrets.token_urlsafe(32)}"
        return raw_key, raw_key[:8], cls.hash_key(raw_key)

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def mark_used(self):
        ApiClient.objects.filter(pk=self.pk).update(last_used_at=timezone.now())

    def __str__(self):
        return f"{self.name} ({self.tenant.slug})"
