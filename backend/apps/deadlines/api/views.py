from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from apps.access.services import resolve_actor_scope
from apps.access.selectors import scope_cases_queryset
from apps.deadlines.models import DeadlineRecord
from apps.escalation.models import EscalationTask
from apps.deadlines.services import extend_or_hold_deadline, close_escalation_task


def scoped_records(user, model):
    scope = resolve_actor_scope(user)
    qs = model.objects.all()
    if scope.roles & {"COMPETENT_AUTHORITY", "OVERSIGHT_AUDITOR"}:
        return qs
    return qs.filter(
        Q(case__in=scope_cases_queryset(user))
        | Q(region_id__in=scope.region_ids)
        | Q(institution_id__in=scope.institution_ids)
    ).distinct()


class DeadlineOperationsView(APIView):
    def get(self, request):
        deadlines = scoped_records(request.user, DeadlineRecord).select_related("case").order_by("due_at")[
            :200
        ]
        escalations = scoped_records(request.user, EscalationTask).select_related("case", "owner").order_by(
            "-created_at"
        )[:200]
        return Response(
            {
                "deadlines": [
                    {
                        "id": str(d.id),
                        "source_type": d.source_type,
                        "clock_type": d.clock_type,
                        "due_at": d.due_at,
                        "revision": d.current_revision,
                        "state": d.state,
                    }
                    for d in deadlines
                ],
                "escalations": [
                    {
                        "id": str(e.id),
                        "reason": e.trigger_reason,
                        "case_id": str(e.case_id) if e.case_id else None,
                        "case_number": e.case.case_number if e.case else None,
                        "owner": e.owner.username,
                        "created_at": e.created_at,
                        "closure_reason": e.closure_reason,
                        "level": e.escalation_level,
                        "state": e.state,
                        "owner_id": e.owner_id,
                    }
                    for e in escalations
                ],
            }
        )

    def post(self, request, record_id, action):
        scope = resolve_actor_scope(request.user)
        if not scope.roles & {
            "COMPETENT_AUTHORITY",
            "REGIONAL_OFFICER",
            "BUREAU_OFFICER",
        }:
            raise PermissionDenied("Regulatory authority is required.")
        reason = str(request.data.get("reason", ""))
        if action == "close-escalation":
            item = get_object_or_404(
                scoped_records(request.user, EscalationTask), id=record_id
            )
            result = close_escalation_task(
                actor=request.user, escalation_id=item.id, closure_reason=reason
            )
        elif action in {"extend", "hold"}:
            item = get_object_or_404(
                scoped_records(request.user, DeadlineRecord), id=record_id
            )
            due = parse_datetime(str(request.data.get("due_at", "")))
            if not due or timezone.is_naive(due):
                raise ValidationError("A timezone-aware due date is required.")
            result = extend_or_hold_deadline(
                actor=request.user,
                deadline_id=item.id,
                new_due_at=due,
                reason=reason,
                action_type="HOLD" if action == "hold" else "EXTENSION",
            )
        else:
            raise ValidationError("Unknown deadline action.")
        return Response({"id": str(result.id), "state": result.state})
