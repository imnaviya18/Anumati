"""URL routes for organisation administration."""

from django.urls import path
from apps.organisation.api.views import (
    OrganisationSummaryAdminView,
    CommitteeMembershipView,
)

urlpatterns = [
    path("committee-members/", CommitteeMembershipView.as_view()),
    path("", OrganisationSummaryAdminView.as_view(), name="organisation-admin"),
]
