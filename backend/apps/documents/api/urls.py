"""URL routes for documents and quarantine pipeline."""
from django.urls import path
from apps.documents.api.views import (
    DocumentDownloadGrantView,
    DocumentHumanReviewView,
    DocumentQuarantineUploadView,
)

urlpatterns = [
    path("", DocumentQuarantineUploadView.as_view(), name="documents-list-upload"),
    path("<uuid:doc_id>/download-grant/", DocumentDownloadGrantView.as_view(), name="documents-download-grant"),
    path("<uuid:doc_id>/review/", DocumentHumanReviewView.as_view(), name="documents-human-review"),
]
