"""API views for quarantined file upload, short-lived download grants, and human acceptance (Sheet 03 E1-E3, Sheet 07 P2, Q2)."""
from __future__ import annotations

import base64
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.selectors import scope_documents_queryset
from apps.cases.models import ApplicationCase
from apps.documents.models import DocumentVersion
from apps.documents.services import (
    issue_short_lived_download_grant,
    receive_quarantined_upload,
    redeem_download_grant,
    review_and_accept_document_version,
)
from apps.organisation.models import Institution


class DocumentQuarantineUploadView(APIView):
    """Upload a document to quarantine and optionally run signature/type/size scan (Sheet 03 E1, Sheet 07 P2)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            qs = scope_documents_queryset(
                request.user,
                DocumentVersion.objects.select_related("institution", "case"),
            )
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        if request.query_params.get("case_id"):
            qs = qs.filter(case_id=request.query_params["case_id"])
        return Response(
            [
                {
                    "id": str(d.id),
                    "institution_id": str(d.institution_id),
                    "case_id": str(d.case_id) if d.case_id else None,
                    "document_type": d.document_type,
                    "original_filename": d.original_filename,
                    "version_number": d.version_number,
                    "sha256_checksum": d.sha256_digest,
                    "lifecycle_state": d.quarantine_status,
                    "acceptance_status": d.acceptance_status,
                    "review_finding": d.review_finding,
                }
                for d in qs[:100]
            ]
        )

    def post(self, request: Request) -> Response:
        try:
            inst = get_object_or_404(Institution, id=request.data.get("institution_id"))
            case = (
                get_object_or_404(ApplicationCase, id=request.data.get("case_id"))
                if request.data.get("case_id")
                else None
            )
            raw_b64 = str(request.data.get("content_base64", ""))
            content_bytes = base64.b64decode(raw_b64, validate=True) if raw_b64 else b""
            doc = receive_quarantined_upload(
                actor=request.user,
                institution=inst,
                case=case,
                document_type=str(request.data.get("document_type", "")),
                original_filename=str(request.data.get("original_filename", "")),
                content_type=str(request.data.get("declared_mime_type", "application/pdf")),
                file_bytes=content_bytes,
            )
            return Response(
                {
                    "id": str(doc.id),
                    "version_number": doc.version_number,
                    "sha256_checksum": doc.sha256_digest,
                    "lifecycle_state": doc.quarantine_status,
                    "scan_detail": doc.scan_Finding,
                },
                status=status.HTTP_201_CREATED,
            )
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class DocumentDownloadGrantView(APIView):
    """Issue or redeem a short-lived download grant after scope and scan verification (Sheet 07 P2, Q2)."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, doc_id: str) -> Response:
        doc = get_object_or_404(DocumentVersion, id=doc_id)
        try:
            grant = issue_short_lived_download_grant(actor=request.user, document_version_id=doc.id)
            return Response(
                {
                    "grant_token": grant.token,
                    "expires_at": grant.expires_at.isoformat(),
                }
            )
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

    def get(self, request: Request, doc_id: str) -> Response | HttpResponse:
        token = request.query_params.get("token", "")
        from apps.documents.models import DownloadGrant
        get_object_or_404(DownloadGrant, token=token, document_version_id=doc_id, issued_to=request.user)
        try:
            doc, content = redeem_download_grant(actor=request.user, token=token)
            if str(doc.id) != str(doc_id):
                return Response({"detail": "Grant does not match document."}, status=status.HTTP_403_FORBIDDEN)
            resp = HttpResponse(content, content_type=doc.content_type)
            from django.utils.http import content_disposition_header
            resp["Content-Disposition"] = content_disposition_header(True, doc.original_filename)
            return resp
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)


class DocumentHumanReviewView(APIView):
    """Record explicit human reviewer acceptance or rejection of a CLEAN_SCANNED document (Sheet 03 E3, Sheet 07 P2)."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, doc_id: str) -> Response:
        doc = get_object_or_404(DocumentVersion, id=doc_id)
        try:
            updated = review_and_accept_document_version(
                actor=request.user,
                document_version_id=doc.id,
                accept=request.data.get("accept") is True,
                finding=str(request.data.get("notes", "")),
            )
            return Response(
                {
                    "id": str(updated.id),
                    "lifecycle_state": updated.quarantine_status,
                    "review_notes": updated.review_finding,
                }
            )
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
