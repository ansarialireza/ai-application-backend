from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed

from .models import ApiClient


class ApiKeyAuthentication(authentication.BaseAuthentication):
    keyword = "Api-Key"

    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header:
            return None
        parts = header.split()
        if len(parts) != 2 or parts[0].lower() != self.keyword.lower():
            raise AuthenticationFailed("Authorization header must use the Api-Key scheme.")
        try:
            client = ApiClient.objects.select_related("tenant").get(
                key_hash=ApiClient.hash_key(parts[1]), is_active=True
            )
        except ApiClient.DoesNotExist as exc:
            raise AuthenticationFailed("Invalid API key.") from exc
        client.mark_used()
        request.tenant = client.tenant
        return client, None

    def authenticate_header(self, request):
        return self.keyword
