"""URL routes for access and role assignments."""

from django.urls import path
from apps.access.api.views import (
    RoleAssignmentAdminView,
    CaseAssignmentView,
    AssignmentOptionsView,
    RevokeAssignmentView,
)

urlpatterns = [
    path("assignment-options/", AssignmentOptionsView.as_view()),
    path(
        "role-assignments/<uuid:assignment_id>/revoke/", RevokeAssignmentView.as_view()
    ),
    path("case-assignments/", CaseAssignmentView.as_view()),
    path(
        "role-assignments/",
        RoleAssignmentAdminView.as_view(),
        name="access-role-assignments",
    ),
]
