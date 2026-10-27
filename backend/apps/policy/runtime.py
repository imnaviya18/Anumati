"""Declarative calendar and deadline evaluation; no executable policy expressions."""

from datetime import timedelta
from django.core.exceptions import ValidationError


def due_after_days(start, days, policy, trigger="STAGE"):
    days = int(days)
    if days < 0 or days > 3660:
        raise ValidationError("Deadline day count is outside the supported range.")
    config = (policy.deadline_triggers or {}).get(trigger, {}) if policy else {}
    mode = config.get("day_count", "calendar")
    if mode == "calendar":
        return start + timedelta(days=days)
    if mode != "business":
        raise ValidationError("Unsupported calendar day-count mode.")
    holidays = set(policy.calendar_holidays or [])
    weekdays = set(config.get("working_weekdays", [0, 1, 2, 3, 4]))
    if not weekdays or not weekdays.issubset(set(range(7))):
        raise ValidationError("Invalid working weekdays.")
    result = start
    for _ in range(days):
        for _attempt in range(4000):
            result += timedelta(days=1)
            if (
                result.weekday() in weekdays
                and result.date().isoformat() not in holidays
            ):
                break
        else:
            raise ValidationError(
                "Calendar has no working date in the supported horizon."
            )
    return result


def create_stage_deadline(case, stage, now):
    from apps.deadlines.models import DeadlineRecord, ClockType

    policy = case.pinned_policy_version
    if not policy:
        raise ValidationError("A pinned policy is required for stage deadlines.")
    days = (policy.stage_timelines or {}).get(stage.stage_type)
    if days is None:
        if not policy.is_demonstration:
            raise ValidationError("Authoritative policy is missing a stage timeline.")
        days = 15
    config = (policy.deadline_triggers or {}).get("STAGE", {})
    return DeadlineRecord.objects.create(
        source_type="STAGE",
        source_id=stage.id,
        case=case,
        institution=case.institution,
        region=case.region,
        clock_type=ClockType.OFFICER_REVIEW,
        due_at=due_after_days(now, days, policy),
        calendar_version=policy.calendar_version,
        owner_role=config.get("owner_role", "REGIONAL_OFFICER"),
        reminder_offsets_hours=config.get("reminder_offsets_hours", [72, 24, 0]),
    )
