"""URL routes for outbox operations and failed-job replay."""
from django.urls import path
from apps.outbox.api.views import OutboxFailedQueueReplayView, OutboxOperationsMetricsView

urlpatterns = [
    path("metrics/", OutboxOperationsMetricsView.as_view(), name="outbox-metrics"),
    path("failed/", OutboxFailedQueueReplayView.as_view(), name="outbox-failed-list"),
    path("failed/<uuid:event_id>/replay/", OutboxFailedQueueReplayView.as_view(), name="outbox-failed-replay"),
]
