"""Bootstrap management command (DATA RULES: creates only roles/groups and one initial technical administrator from environment variables)."""
from __future__ import annotations

import os
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.access.models import RoleAssignment, RoleCode
from apps.audit.services import record_audit_event


class Command(BaseCommand):
    help = "Bootstrap canonical permission groups and one initial TECHNICAL_ADMIN from environment variables."

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        # 1. Ensure permission groups exist for all canonical roles (DATA RULES)
        for role_code, _label in RoleCode.choices:
            Group.objects.get_or_create(name=role_code)

        # 2. Create or fetch initial technical administrator from environment variables
        username = os.environ.get("BOOTSTRAP_ADMIN_USERNAME", "tech_admin").strip()
        email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "tech_admin@anumati.local").strip()
        password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "ChangeMe123!")

        User = get_user_model()
        admin_user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": email, "is_active": True, "is_staff": False, "is_superuser": False},
        )
        if created:
            admin_user.set_password(password)
            admin_user.save()

        ra, ra_created = RoleAssignment.objects.get_or_create(
            user=admin_user,
            role=RoleCode.TECHNICAL_ADMIN,
            defaults={
                "is_active": True,
                "assigned_reason": "Bootstrap initial technical administrator (No regulatory authority)",
            },
        )

        if created or ra_created:
            record_audit_event(
                actor=admin_user,
                actor_role=RoleCode.TECHNICAL_ADMIN,
                actor_scope={"roles": [RoleCode.TECHNICAL_ADMIN]},
                action="BOOTSTRAP_INITIAL_TECHNICAL_ADMIN",
                target_type="User",
                target_id=str(admin_user.pk),
                reason="System bootstrap command executed",
                inputs_snapshot={"username": username, "role": RoleCode.TECHNICAL_ADMIN},
            )
        self.stdout.write(self.style.SUCCESS(f"Bootstrapped roles and initial technical admin '{username}'."))
