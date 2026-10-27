"""Create explicitly synthetic local data, never production rules or real institutions."""

import json
import os
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from apps.access.models import RoleAssignment, CaseAssignment
from apps.organisation.models import (
    Region,
    Bureau,
    Institution,
    Committee,
    CommitteeMembership,
)
from apps.policy.models import PolicyVersion
from apps.policy.services import (
    draft_policy_version,
    validate_policy_version,
    run_policy_dry_run,
    approve_and_activate_policy_version,
    approve_policy_version,
)
from apps.cases.services import submit_or_import_application
from apps.cases.models import ApplicationCase
from apps.communications.models import CommunicationTemplate
from apps.audit.services import record_audit_event


class Command(BaseCommand):
    help = "Seed synthetic institutions and demonstration policies in an explicitly enabled local environment."

    @transaction.atomic
    def handle(self, *args, **options):
        if (
            not settings.DEBUG
            or not settings.ALLOW_DEMONSTRATION_POLICIES
            or os.environ.get("ALLOW_SYNTHETIC_SEED") != "true"
        ):
            raise CommandError(
                "Synthetic seeding requires DEBUG, demonstration policies and ALLOW_SYNTHETIC_SEED=true."
            )
        password = os.environ.get("DEMO_PASSWORD")
        if not password:
            raise CommandError("Set DEMO_PASSWORD for local synthetic accounts.")
        region, _ = Region.objects.get_or_create(
            code="DEMO-NORTH",
            defaults={
                "name": "Synthetic Northern Region",
                "headquarters_city": "Demonstration City",
            },
        )
        bureau, _ = Bureau.objects.get_or_create(
            code="DEMO-APPROVAL", defaults={"name": "Synthetic Approval Bureau"}
        )
        institution, _ = Institution.objects.get_or_create(
            permanent_id="DEMO-INST-001",
            defaults={
                "name": "Synthetic Institute of Technology — Demo Only",
                "region": region,
                "state": "Demonstration State",
            },
        )
        other, _ = Institution.objects.get_or_create(
            permanent_id="DEMO-INST-002",
            defaults={
                "name": "Synthetic New Technical Institute — Demo Only",
                "region": region,
                "state": "Demonstration State",
                "is_new_institution": True,
            },
        )
        users = {}
        for name, role in [
            ("admin", "TECHNICAL_ADMIN"),
            ("institution", "INSTITUTION_USER"),
            ("officer", "REGIONAL_OFFICER"),
            ("evc", "EVC_MEMBER"),
            ("authority", "COMPETENT_AUTHORITY"),
            ("policy", "POLICY_ADMIN"),
            ("auditor", "OVERSIGHT_AUDITOR"),
        ]:
            user, created = get_user_model().objects.get_or_create(
                username=f"demo_{name}", defaults={"email": f"{name}@example.test"}
            )
            if created:
                user.set_password(password)
                user.save()
            users[name] = user
            defaults = {
                "region": region if name == "officer" else None,
                "institution": institution if name == "institution" else None,
                "delegated_powers": [
                    "GRANT_EOA",
                    "GRANT_LOA",
                    "ISSUE_LOD",
                    "REJECT_LOR",
                    "REFER_BACK",
                ]
                if name == "authority"
                else [],
                "assigned_reason": "Synthetic local demonstration account",
            }
            RoleAssignment.objects.get_or_create(
                user=user, role=role, institution=defaults.pop("institution"), defaults=defaults
            )
        RoleAssignment.objects.get_or_create(
            user=users["institution"],
            role="INSTITUTION_USER",
            institution=other,
            defaults={"assigned_reason": "Synthetic second institution"},
        )
        committee, _ = Committee.objects.get_or_create(
            code="DEMO-EVC",
            defaults={
                "name": "Synthetic EVC Committee",
                "committee_type": "EVC",
                "region": region,
                "quorum_count": 1,
            },
        )
        CommitteeMembership.objects.get_or_create(
            committee=committee, user=users["evc"]
        )
        policy = PolicyVersion.objects.filter(
            policy_code="DEMO-ONLY-2026", version_number=1
        ).first()
        if not policy:
            policy = draft_policy_version(
                actor=users["policy"],
                policy_code="DEMO-ONLY-2026",
                version_number=1,
                academic_cycle="2026-27",
                is_demonstration=True,
                provenance={
                    "label": "SYNTHETIC DEMONSTRATION ONLY — NOT AICTE RULES",
                    "sources": ["Illustrative local workflow test data"],
                },
                route_rules=[
                    {
                        "route_code": "DEMO_EOA_SCRUTINY",
                        "conditions": {"application_category": "EOA"},
                        "stages": ["SCRUTINY"],
                    },
                    {
                        "route_code": "DEMO_NEW_SCRUTINY_EVC",
                        "conditions": {"application_category": "NEW_INSTITUTION"},
                        "stages": ["SCRUTINY", "EVC"],
                    },
                ],
                stage_timelines={"SCRUTINY": 5, "RE_SCRUTINY": 3, "EVC": 7, "SAC": 7},
                evc_rules={
                    "new_institution": {
                        "scheduling_sla_days": 3,
                        "completion_sla_days": 7,
                    },
                    "existing_institution": {
                        "scheduling_sla_days": 5,
                        "completion_sla_days": 10,
                    },
                },
                deadline_triggers={
                    "STAGE": {
                        "anchor": "stage_started_at",
                        "day_count": "business",
                        "working_weekdays": [0, 1, 2, 3, 4],
                        "owner_role": "REGIONAL_OFFICER",
                        "reminder_offsets_hours": [72, 24, 0],
                    }
                },
                escalation_hierarchies={
                    "levels": [
                        {
                            "level": 1,
                            "overdue_hours": 0,
                            "target_role": "REGIONAL_OFFICER",
                        },
                        {
                            "level": 2,
                            "overdue_hours": 24,
                            "target_role": "COMPETENT_AUTHORITY",
                        },
                    ]
                },
                exception_rules={
                    "missing_route": "POLICY_REVIEW_REQUIRED",
                    "ambiguous_route": "POLICY_REVIEW_REQUIRED",
                },
                regression_cases=[
                    {
                        "name": "Demo EOA",
                        "application_category": "EOA",
                        "institution_category": "PRIVATE_SELF_FINANCING",
                        "expected_route_code": "DEMO_EOA_SCRUTINY",
                    },
                    {
                        "name": "Demo new institute",
                        "application_category": "NEW_INSTITUTION",
                        "institution_category": "PRIVATE_SELF_FINANCING",
                        "is_new_institution": True,
                        "expected_route_code": "DEMO_NEW_SCRUTINY_EVC",
                    },
                    {
                        "name": "Unknown category",
                        "application_category": "UNKNOWN",
                        "expect_review_required": True,
                    },
                ],
            )
            validate_policy_version(actor=users["policy"], policy=policy)
            run_policy_dry_run(actor=users["policy"], policy=policy)
            approve_policy_version(actor=users["authority"], policy=policy, reason="Synthetic demonstration regression approved")
            approve_and_activate_policy_version(actor=users["authority"], policy=policy)
        draft_path = Path(
            os.environ.get(
                "APH_DRAFT_PATH",
                str(
                    Path(settings.BASE_DIR).parent
                    / "docs/policy/aph_2024_2027_draft.json"
                ),
            )
        )
        if draft_path.exists():
            draft = json.loads(draft_path.read_text())
            if not PolicyVersion.objects.filter(
                policy_code=draft["policy_code"], version_number=draft["version_number"]
            ).exists():
                draft_policy_version(actor=users["policy"], **draft)
        else:
            raise CommandError(
                "The researched APH draft file is required; set APH_DRAFT_PATH."
            )
        for inst, category, source in [
            (institution, "EOA", "DEMO-SOURCE-001"),
            (other, "NEW_INSTITUTION", "DEMO-SOURCE-002"),
        ]:
            if not ApplicationCase.objects.filter(source_id=source).exists():
                case = submit_or_import_application(
                    actor=users["institution"],
                    institution=inst,
                    academic_cycle="2026-27",
                    application_category=category,
                    source_id=source,
                    responsible_bureau=bureau,
                )
                stage = case.stage_instances.first()
                stage.assigned_officer = users["officer"]
                stage.save()
                CaseAssignment.objects.create(
                    case=case,
                    stage_instance=stage,
                    user=users["officer"],
                    reason="Synthetic demonstration review assignment",
                )
        CommunicationTemplate.objects.update_or_create(
            template_code="DEMO-SUMMARY",
            version_number=1,
            defaults={
                "category": "CASE_SUMMARY",
                "subject_template": "DEMONSTRATION — {case_number}",
                "body_template": "Synthetic demonstration case {case_number}. Institution: {institution_name}. Status: {status}.",
                "required_fields": ["case_number"],
                "policy_version": policy,
            },
        )
        record_audit_event(
            actor=users["admin"],
            actor_role="TECHNICAL_ADMIN",
            actor_scope={"demonstration": True},
            action="SYNTHETIC_DEMO_SEEDED",
            target_type="Environment",
            target_id="local-demo",
            reason="Explicitly authorised local synthetic data",
            inputs_snapshot={"at": timezone.now().isoformat()},
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Synthetic local demonstration ready. APH research configuration remains DRAFT. Accounts: "
                + ", ".join(u.username for u in users.values())
            )
        )
