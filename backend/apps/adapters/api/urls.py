"""URL routes for adapters API."""
from django.urls import path

from .views import adapter_status_view

urlpatterns = [
    path("status/", adapter_status_view, name="adapter-status"),
]
