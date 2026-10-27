"""API views for guarded Competent Authority decisions (Sheet 06 K1-K6, L1-L3)."""
from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cases.models import ApplicationCase
from apps.decisions.services import (
    IdempotencyConflictError,
    StaleCaseVersionError,
    execute_guarded_decision_command,
)
from apps.routing.services import TransitionViolationError


class GuardedDecisionCommandView(APIView):
    """Execute guarded Competent Authority decision command (Sheet 06 K1-K6, L1-L3)."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, case_id: str) -> Response:
        case = get_object_or_404(ApplicationCase, id=case_id)
        try:
            res = execute_guarded_decision_command(
                actor=request.user,
                case_id=case.id,
                action="DECIDE_" + str(request.data.get("outcome", "")),
                outcome=str(request.data.get("outcome", "")),
                expected_version=int(request.data.get("expected_version", 0)),
                idempotency_key=str(request.data.get("idempotency_key", "")),
                delegated_power_ref=str(request.data.get("delegated_power_ref", "")),
                reasons=str(request.data.get("reasons", "")),
                reviewed_evidence_version_ids=request.data.get("reviewed_evidence_version_ids") or [],
                refer_back_stage_type=str(request.data.get("refer_back_stage_type", "")),
                obligations_spec=request.data.get("obligations_specs") or [],
            )
            return Response(res.body, status=res.status_code)
        except (StaleCaseVersionError, IdempotencyConflictError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except (TransitionViolationError, ValidationError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
