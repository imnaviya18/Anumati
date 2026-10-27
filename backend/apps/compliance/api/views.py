"""API views for obligations, evidence submissions, document validity registry, and renewals (Sheet 03 D1-F5)."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.selectors import (
    scope_obligations_queryset,
    scope_validity_records_queryset,
)
from apps.compliance.models import EvidenceSubmission, Obligation
from apps.compliance.services import (
    submit_obligation_evidence,
    verify_obligation_evidence,
)
from apps.documents.models import DocumentValidityRecord, DocumentVersion


class ObligationListView(APIView):
    """List scoped continuing obligations (Sheet 03 D1, Sheet 07 Q2)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            qs = scope_obligations_queryset(
                request.user,
                Obligation.objects.select_related(
                    "institution", "case"
                ).prefetch_related("submissions"),
            )
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        return Response(
            [
                {
                    "id": str(ob.id),
                    "institution_code": ob.institution.permanent_id,
                    "case_number": ob.case.case_number if ob.case else None,
                    "obligation_code": ob.obligation_code,
                    "condition_text": ob.condition_text,
                    "state": ob.state,
                    "due_at": ob.due_at.isoformat(),
                    "submissions": [
                        {
                            "id": str(sub.id),
                            "document_version_id": str(sub.document_version_id),
                            "reviewed_at": sub.reviewed_at,
                        }
                        for sub in ob.submissions.all()
                    ],
                    "is_submission_late": ob.is_submission_late,
                    "is_verification_late": ob.is_verification_late,
                }
                for ob in qs[:100]
            ]
        )


class ObligationSubmitVerifyView(APIView):
    """Submit or verify evidence for a continuing obligation (Sheet 03 E1-E4)."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, obligation_id: str, action_name: str) -> Response:
        ob = get_object_or_404(Obligation, id=obligation_id)
        try:
            if action_name == "submit":
                doc = get_object_or_404(
                    DocumentVersion, id=request.data.get("document_version_id")
                )
                sub = submit_obligation_evidence(
                    actor=request.user, obligation_id=ob.id, document_version_id=doc.id
                )
                ob.refresh_from_db()
                return Response(
                    {
                        "submission_id": str(sub.id),
                        "obligation_state": ob.state,
                        "was_submitted_after_due": sub.was_submitted_after_due,
                    },
                    status=status.HTTP_201_CREATED,
                )
            if action_name == "verify":
                sub = get_object_or_404(
                    EvidenceSubmission,
                    id=request.data.get("submission_id"),
                    obligation=ob,
                )
                updated = verify_obligation_evidence(
                    actor=request.user,
                    submission_id=sub.id,
                    fulfilled=request.data.get("is_fulfilled") is True,
                    finding_notes=str(request.data.get("finding_notes", "")),
                )
                return Response(
                    {
                        "obligation_id": str(updated.id),
                        "state": updated.state,
                        "is_submission_late": updated.is_submission_late,
                        "is_verification_late": updated.is_verification_late,
                    }
                )
            return Response(
                {"detail": "Unknown action."}, status=status.HTTP_400_BAD_REQUEST
            )
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class DocumentValidityListView(APIView):
    """List scoped document validity records (Sheet 03 F1-F5)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from rest_framework import serializers
        from apps.access.selectors import scope_documents_queryset
        from apps.compliance.services import register_accepted_validity_document

        class Input(serializers.Serializer):
            document_version_id = serializers.UUIDField()
            valid_from = serializers.DateField()
            valid_until = serializers.DateField()
        data = Input(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        doc = get_object_or_404(scope_documents_queryset(request.user), pk=values["document_version_id"])
        record = register_accepted_validity_document(actor=request.user, institution=doc.institution,
            document_type=doc.document_type, accepted_version_id=doc.id,
            valid_from=values["valid_from"], valid_until=values["valid_until"])
        return Response({"id":str(record.id), "state":record.state}, status=201)

    def get(self, request: Request) -> Response:
        try:
            qs = scope_validity_records_queryset(
                request.user,
                DocumentValidityRecord.objects.select_related(
                    "institution", "accepted_version", "pending_renewal_version"
                ),
            )
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        return Response(
            [
                {
                    "id": str(vr.id),
                    "institution_code": vr.institution.permanent_id,
                    "document_type": vr.document_type,
                    "state": vr.state,
                    "valid_from": vr.valid_from.isoformat(),
                    "valid_until": vr.valid_until.isoformat(),
                    "accepted_version_id": str(vr.accepted_version_id),
                    "pending_renewal_version_id": (
                        str(vr.pending_renewal_version_id)
                        if vr.pending_renewal_version_id
                        else None
                    ),
                }
                for vr in qs[:100]
            ]
        )


class RenewalActionView(APIView):
    def post(self, request, validity_id, action_name):
        from datetime import date
        from apps.compliance.services import (
            submit_document_renewal,
            review_and_decide_document_renewal,
        )
        from apps.access.selectors import scope_validity_records_queryset

        record = get_object_or_404(
            scope_validity_records_queryset(request.user), id=validity_id
        )
        if action_name == "submit":
            updated = submit_document_renewal(
                actor=request.user,
                validity_record_id=record.id,
                new_document_version_id=request.data.get("document_version_id"),
            )
        elif action_name == "review":
            accept = request.data.get("accept")
            if not isinstance(accept, bool):
                raise ValidationError("accept must be a boolean.")
            updated = review_and_decide_document_renewal(
                actor=request.user,
                validity_record_id=record.id,
                accept=accept,
                new_valid_from=date.fromisoformat(
                    str(request.data.get("valid_from", ""))
                )
                if accept
                else None,
                new_valid_until=date.fromisoformat(
                    str(request.data.get("valid_until", ""))
                )
                if accept
                else None,
                finding_notes=str(request.data.get("notes", "")),
            )
        else:
            raise ValidationError("Unknown renewal action.")
        return Response({"id": str(updated.id), "state": updated.state})
