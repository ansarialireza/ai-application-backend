from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AssistantViewSet, ConversationViewSet, ExecutionRecordViewSet, PublicGenerationView

router = DefaultRouter()
router.register("assistants", AssistantViewSet, basename="assistant")
router.register("conversations", ConversationViewSet, basename="conversation")
router.register("executions", ExecutionRecordViewSet, basename="execution")

urlpatterns = [
    path("public/assistants/<uuid:assistant_id>/generate/", PublicGenerationView.as_view(), name="public-generate"),
    path("", include(router.urls)),
]
