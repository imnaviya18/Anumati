"""URL routes for compliance and document validity."""
from django.urls import path
from apps.compliance.api.views import (
    DocumentValidityListView,
    RenewalActionView,
    ObligationListView,
    ObligationSubmitVerifyView,
)

urlpatterns = [
    path("validity/<uuid:validity_id>/<str:action_name>/", RenewalActionView.as_view()),
    path("obligations/", ObligationListView.as_view(), name="compliance-obligations-list"),
    path(
        "obligations/<uuid:obligation_id>/<str:action_name>/",
        ObligationSubmitVerifyView.as_view(),
        name="compliance-obligation-action",
    ),
    path("validity/", DocumentValidityListView.as_view(), name="compliance-validity-list"),
]
