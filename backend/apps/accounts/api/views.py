"""API views for session authentication, CSRF, and actor scope introspection (Sheet 01 Block 01, Sheet 06 K1-K2)."""

from __future__ import annotations

from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import PermissionDenied
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.throttling import AnonRateThrottle
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.services import resolve_actor_scope


class CsrfTokenView(APIView):
    """Return a CSRF token cookie and value for browser session clients."""

    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        return Response({"csrfToken": get_token(request)})


class LoginThrottle(AnonRateThrottle):
    rate = "10/min"


@method_decorator(csrf_protect, name="dispatch")
class SessionLoginView(APIView):
    """Authenticate user credentials and establish a server-side session."""

    permission_classes = [AllowAny]

    throttle_classes = [LoginThrottle]

    def post(self, request: Request) -> Response:
        username = str(request.data.get("username", "")).strip()
        password = str(request.data.get("password", ""))
        user = authenticate(request, username=username, password=password)
        if user is None or not user.is_active:
            return Response(
                {"detail": "Invalid credentials or inactive account."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        login(request, user)
        try:
            scope = resolve_actor_scope(user).to_audit_dict()
        except PermissionDenied:
            scope = {"roles": []}
        return Response(
            {
                "id": user.pk,
                "username": user.username,
                "email": user.email,
                "scope": scope,
            }
        )


class SessionLogoutView(APIView):
    """Terminate the current authenticated session."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        logout(request)
        return Response({"status": "logged_out"})


class CurrentActorMeView(APIView):
    """Return the authenticated actor's profile and active resolved scope."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            scope = resolve_actor_scope(request.user).to_audit_dict()
        except PermissionDenied:
            scope = {"roles": []}
        return Response(
            {
                "id": request.user.pk,
                "username": request.user.username,
                "email": request.user.email,
                "scope": scope,
            }
        )


class UserDirectoryView(APIView):
    """Audited local account provisioning restricted to technical administrators."""

    permission_classes = [IsAuthenticated]

    def _scope(self, request):
        from apps.access.models import RoleCode

        scope = resolve_actor_scope(request.user)
        if RoleCode.TECHNICAL_ADMIN not in scope.roles:
            raise PermissionDenied("User administration requires TECHNICAL_ADMIN.")
        return scope

    def get(self, request):
        from django.contrib.auth import get_user_model

        self._scope(request)
        return Response(
            list(
                get_user_model()
                .objects.order_by("username")
                .values("id", "username", "email", "is_active")[:200]
            )
        )

    def post(self, request):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError
        from django.db import transaction
        from apps.audit.services import record_audit_event

        scope = self._scope(request)
        username = str(request.data.get("username", "")).strip()
        password = str(request.data.get("password", ""))
        if not username:
            raise ValidationError("Username is required.")
        user = get_user_model()(
            username=username, email=str(request.data.get("email", "")).strip()
        )
        validate_password(password, user)
        user.full_clean(exclude=["password"])
        with transaction.atomic():
            user.set_password(password)
            user.save()
            record_audit_event(
                actor=request.user,
                actor_role="TECHNICAL_ADMIN",
                actor_scope=scope.to_audit_dict(),
                action="USER_CREATED",
                target_type="User",
                target_id=str(user.id),
                reason="Provision local account",
                inputs_snapshot={"username": username},
            )
        return Response({"id": user.id, "username": user.username}, status=201)
