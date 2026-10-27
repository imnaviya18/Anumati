"""URL routes for in-app notifications."""
from django.urls import path
from apps.notifications.api.views import NotificationListView, NotificationMarkReadView

urlpatterns = [
    path("", NotificationListView.as_view(), name="notifications-list"),
    path("<uuid:alert_id>/read/", NotificationMarkReadView.as_view(), name="notifications-mark-read"),
]
