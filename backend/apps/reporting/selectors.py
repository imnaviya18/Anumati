"""Selectors for role-based dashboards and the exact 6 statutory reports (Sheet 01 Block 07, Sheet 04 J6, PS Sections B & F)."""
from __future__ import annotations

from datetime import timedelta
from typing import Any
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.utils import timezone

from apps.access.selectors import (
    scope_cases_queryset,
    scope_obligations_queryset,
    scope_validity_records_queryset,
)
from apps.access.services import resolve_actor_scope
from apps.cases.models import ApplicationCase, CaseStatus, StageInstance, StageStatus
from apps.compliance.models import Obligation
from apps.deadlines.models import DeadlineRecord, DeadlineState
from apps.documents.models import DocumentValidityRecord
from apps.escalation.models import EscalationState, EscalationTask
from apps.evc.models import EvcCoordination
from apps.organisation.models import Region


ALLOWED_REPORT_CODES = frozenset(
    {
        "application_pendency",
        "evc_status",
        "undertaking_compliance",
        "document_validity",
        "overdue_cases",
        "region_wise_processing_performance",
    }
)


def select_role_dashboard_snapshot(
    user: Any,
    *,
    region_code: str | None = None,
    academic_cycle: str | None = None,
    bureau_code: str | None = None,
) -> dict[str, Any]:
    """Build role-scoped dashboard snapshot with 'data_as_of' timestamp, status by region/stage/institution/officer, ageing, workload, bottlenecks, and timeline alerts (PS Section B, Sheet 01 Block 07, Sheet 04 J6)."""
    now = timezone.now()
    scope = resolve_actor_scope(user, now)

    cases_qs = scope_cases_queryset(
        user,
        ApplicationCase.objects.select_related("institution", "region", "responsible_bureau"),
    )
    if region_code:
        cases_qs = cases_qs.filter(region__code=region_code)
    if academic_cycle:
        cases_qs = cases_qs.filter(academic_cycle=academic_cycle)

    if bureau_code:
        cases_qs = cases_qs.filter(responsible_bureau__code=bureau_code)

    pending_filter = ~Q(status__in=[CaseStatus.CLOSED, CaseStatus.APPROVED_EOA, CaseStatus.APPROVED_LOA, CaseStatus.REJECTED_LOR, CaseStatus.DEFICIENCY_LETTER_LOD])
    by_bureau = list(cases_qs.values("responsible_bureau__code", "responsible_bureau__name").annotate(count=Count("id"), pending_count=Count("id", filter=pending_filter)).order_by("responsible_bureau__code"))
    by_status = list(cases_qs.values("status").annotate(count=Count("id")).order_by("status"))
    by_region = list(
        cases_qs.values("region__code", "region__name")
        .annotate(count=Count("id"), pending_count=Count("id", filter=pending_filter))
        .order_by("region__code")
    )
    by_stage = list(
        cases_qs.exclude(current_stage_type="")
        .values("current_stage_type")
        .annotate(count=Count("id"))
        .order_by("current_stage_type")
    )
    by_institution = list(
        cases_qs.values("institution__permanent_id", "institution__name", "status")
        .annotate(count=Count("id"))
        .order_by("institution__permanent_id")[:100]
    )

    active_stages_qs = StageInstance.objects.filter(
        case__in=cases_qs,
        status__in=[StageStatus.PENDING, StageStatus.IN_PROGRESS, StageStatus.RETURNED_FOR_DEFICIENCY],
    ).select_related("assigned_officer", "assigned_committee")

    workload_by_officer = list(
        active_stages_qs.exclude(assigned_officer__isnull=True)
        .values("assigned_officer__username", "stage_type")
        .annotate(active_cases=Count("id"))
        .order_by("-active_cases")
    )
    workload_by_committee = list(
        active_stages_qs.exclude(assigned_committee__isnull=True)
        .values("assigned_committee__code", "stage_type")
        .annotate(active_cases=Count("id"))
        .order_by("-active_cases")
    )

    bottlenecks = list(
        active_stages_qs.values("stage_type", "status")
        .annotate(pending_count=Count("id"))
        .order_by("-pending_count")
    )

    visible_inst_ids = cases_qs.values_list("institution_id", flat=True)
    deadlines_qs = DeadlineRecord.objects.filter(
        Q(case__in=cases_qs) | Q(case__isnull=True, institution_id__in=visible_inst_ids),
        state=DeadlineState.ACTIVE,
    )
    overdue_count = deadlines_qs.filter(due_at__lt=now).count()
    approaching_count = deadlines_qs.filter(due_at__gte=now, due_at__lte=now + timedelta(hours=72)).count()

    open_escalations_count = EscalationTask.objects.filter(
        Q(case__in=cases_qs) | Q(case__isnull=True, institution_id__in=visible_inst_ids),
        state__in=[EscalationState.OPEN, EscalationState.ESCALATED_NEXT_LEVEL],
    ).count()

    ageing = []
    for label, lower, upper in [("0–7 days", 0, 7), ("8–30 days", 8, 30), ("31–90 days", 31, 90), ("Over 90 days", 91, None)]:
        pending = cases_qs.exclude(status__in=[CaseStatus.CLOSED, CaseStatus.APPROVED_EOA, CaseStatus.APPROVED_LOA, CaseStatus.REJECTED_LOR, CaseStatus.DEFICIENCY_LETTER_LOD])
        pending = pending.filter(created_at__lte=now - timedelta(days=lower))
        if upper is not None:
            pending = pending.filter(created_at__gt=now - timedelta(days=upper + 1))
        ageing.append({"band":label,"count":pending.count()})
    return {
        "data_as_of": now.isoformat(),
        "status_by_bureau": by_bureau,
        "ageing": ageing,
        "unassigned_stages": active_stages_qs.filter(assigned_officer__isnull=True, assigned_committee__isnull=True).count(),
        "polling_interval_seconds": 30,
        "actor_roles": sorted(scope.roles),
        "total_visible_cases": cases_qs.count(),
        "status_by_case_status": by_status,
        "status_by_region": by_region,
        "status_by_stage": by_stage,
        "status_by_institution": by_institution,
        "workload_by_officer": workload_by_officer,
        "workload_by_committee": workload_by_committee,
        "bottlenecks": bottlenecks,
        "timeline_alerts": {
            "approaching_72h_count": approaching_count,
            "overdue_count": overdue_count,
            "open_escalations_count": open_escalations_count,
        },
    }


def generate_statutory_report(
    user: Any,
    *,
    report_code: str,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate one of the exact 6 statutory reports with strict permission/scope filtering (PS Section F.3, Sheet 01 Block 07, Sheet 04 J6)."""
    if report_code not in ALLOWED_REPORT_CODES:
        raise ValidationError(
            f"Unsupported report_code '{report_code}'. Allowed reports: {sorted(ALLOWED_REPORT_CODES)}"
        )

    now = timezone.now()
    resolve_actor_scope(user, now)
    flt = filters or {}
    region_code = flt.get("region_code")
    academic_cycle = flt.get("academic_cycle")
    institution_code = flt.get("institution_code")

    if report_code == "application_pendency":
        qs = scope_cases_queryset(
            user,
            ApplicationCase.objects.select_related(
                "institution", "region", "responsible_bureau", "pinned_policy_version"
            ),
        )
        if region_code:
            qs = qs.filter(region__code=region_code)
        if academic_cycle:
            qs = qs.filter(academic_cycle=academic_cycle)
        if institution_code:
            qs = qs.filter(institution__permanent_id=institution_code)

        columns = [
            "case_number",
            "institution_code",
            "institution_name",
            "region_code",
            "academic_cycle",
            "application_category",
            "selected_route_code",
            "status",
            "current_stage_type",
            "age_days",
        ]
        rows = []
        for c in qs:
            ref_time = c.submitted_at or c.created_at
            age_days = max(0, (now - ref_time).days) if ref_time else 0
            rows.append(
                {
                    "case_number": c.case_number,
                    "institution_code": c.institution.permanent_id,
                    "institution_name": c.institution.name,
                    "region_code": c.region.code,
                    "academic_cycle": c.academic_cycle,
                    "application_category": c.application_category,
                    "selected_route_code": c.selected_route_code,
                    "status": c.status,
                    "current_stage_type": c.current_stage_type,
                    "age_days": age_days,
                }
            )
        return {"report_code": report_code, "data_as_of": now.isoformat(), "columns": columns, "rows": rows}

    if report_code == "evc_status":
        visible_cases = scope_cases_queryset(user)
        qs = EvcCoordination.objects.select_related(
            "case", "case__institution", "case__region", "committee", "scheduling_deadline", "completion_deadline"
        ).filter(case__in=visible_cases)
        if region_code:
            qs = qs.filter(case__region__code=region_code)
        if institution_code:
            qs = qs.filter(case__institution__permanent_id=institution_code)

        columns = [
            "case_number",
            "institution_code",
            "region_code",
            "mode",
            "status",
            "is_new_institution_rule",
            "committee_code",
            "scheduled_start",
            "report_submitted_at",
        ]
        rows = [
            {
                "case_number": ev.case.case_number,
                "institution_code": ev.case.institution.permanent_id,
                "region_code": ev.case.region.code,
                "mode": ev.mode,
                "status": ev.status,
                "is_new_institution_rule": ev.is_new_institution_rule,
                "committee_code": ev.committee.code if ev.committee else "",
                "scheduled_start": ev.scheduled_start.isoformat() if ev.scheduled_start else "",
                "report_submitted_at": ev.report_submitted_at.isoformat() if ev.report_submitted_at else "",
            }
            for ev in qs
        ]
        return {"report_code": report_code, "data_as_of": now.isoformat(), "columns": columns, "rows": rows}

    if report_code == "undertaking_compliance":
        qs = scope_obligations_queryset(
            user,
            Obligation.objects.select_related("institution", "institution__region", "case"),
        )
        if region_code:
            qs = qs.filter(institution__region__code=region_code)
        if institution_code:
            qs = qs.filter(institution__permanent_id=institution_code)

        columns = [
            "obligation_code",
            "institution_code",
            "region_code",
            "case_number",
            "state",
            "due_at",
            "last_submitted_at",
            "is_submission_late",
            "verified_at",
            "is_verification_late",
        ]
        rows = [
            {
                "obligation_code": ob.obligation_code,
                "institution_code": ob.institution.permanent_id,
                "region_code": ob.institution.region.code,
                "case_number": ob.case.case_number if ob.case else "",
                "state": ob.state,
                "due_at": ob.due_at.isoformat(),
                "last_submitted_at": ob.last_submitted_at.isoformat() if ob.last_submitted_at else "",
                "is_submission_late": ob.is_submission_late,
                "verified_at": ob.verified_at.isoformat() if ob.verified_at else "",
                "is_verification_late": ob.is_verification_late,
            }
            for ob in qs
        ]
        return {"report_code": report_code, "data_as_of": now.isoformat(), "columns": columns, "rows": rows}

    if report_code == "document_validity":
        qs = scope_validity_records_queryset(
            user,
            DocumentValidityRecord.objects.select_related(
                "institution", "institution__region", "accepted_version", "pending_renewal_version"
            ),
        )
        if region_code:
            qs = qs.filter(institution__region__code=region_code)
        if institution_code:
            qs = qs.filter(institution__permanent_id=institution_code)

        columns = [
            "document_type",
            "institution_code",
            "region_code",
            "state",
            "valid_from",
            "valid_until",
            "accepted_version_number",
            "has_pending_renewal",
        ]
        rows = [
            {
                "document_type": vr.document_type,
                "institution_code": vr.institution.permanent_id,
                "region_code": vr.institution.region.code,
                "state": vr.state,
                "valid_from": vr.valid_from.isoformat(),
                "valid_until": vr.valid_until.isoformat(),
                "accepted_version_number": vr.accepted_version.version_number,
                "has_pending_renewal": vr.pending_renewal_version_id is not None,
            }
            for vr in qs
        ]
        return {"report_code": report_code, "data_as_of": now.isoformat(), "columns": columns, "rows": rows}

    if report_code == "overdue_cases":
        visible_cases = scope_cases_queryset(user)
        qs = DeadlineRecord.objects.select_related("case", "institution", "region").filter(
            case__in=visible_cases,
            state=DeadlineState.ACTIVE,
            due_at__lt=now,
        )
        if region_code:
            qs = qs.filter(region__code=region_code)
        if institution_code:
            qs = qs.filter(institution__permanent_id=institution_code)

        columns = [
            "case_number",
            "institution_code",
            "region_code",
            "clock_type",
            "owner_role",
            "due_at",
            "overdue_hours",
            "current_revision",
        ]
        rows = [
            {
                "case_number": dl.case.case_number if dl.case else "",
                "institution_code": dl.institution.permanent_id,
                "region_code": dl.region.code,
                "clock_type": dl.clock_type,
                "owner_role": dl.owner_role,
                "due_at": dl.due_at.isoformat(),
                "overdue_hours": round((now - dl.due_at).total_seconds() / 3600.0, 2),
                "current_revision": dl.current_revision,
            }
            for dl in qs
        ]
        return {"report_code": report_code, "data_as_of": now.isoformat(), "columns": columns, "rows": rows}

    # 6. region_wise_processing_performance
    visible_cases = scope_cases_queryset(user)
    regions_qs = Region.objects.filter(is_active=True)
    if region_code:
        regions_qs = regions_qs.filter(code=region_code)

    columns = [
        "region_code",
        "region_name",
        "total_cases",
        "in_progress_cases",
        "completed_or_disposed_cases",
        "overdue_active_deadlines",
    ]
    rows = []
    for reg in regions_qs:
        reg_cases = visible_cases.filter(region=reg)
        total = reg_cases.count()
        completed_or_disposed = reg_cases.filter(
            status__in=[
                CaseStatus.APPROVED_LOA,
                CaseStatus.APPROVED_EOA,
                CaseStatus.DEFICIENCY_LETTER_LOD,
                CaseStatus.REJECTED_LOR,
                CaseStatus.CLOSED,
            ]
        ).count()
        in_prog = total - completed_or_disposed
        overdue_dl = DeadlineRecord.objects.filter(
            case__in=reg_cases,
            state=DeadlineState.ACTIVE,
            due_at__lt=now,
        ).count()
        rows.append(
            {
                "region_code": reg.code,
                "region_name": reg.name,
                "total_cases": total,
                "in_progress_cases": in_prog,
                "completed_or_disposed_cases": completed_or_disposed,
                "overdue_active_deadlines": overdue_dl,
            }
        )
    return {"report_code": report_code, "data_as_of": now.isoformat(), "columns": columns, "rows": rows}
