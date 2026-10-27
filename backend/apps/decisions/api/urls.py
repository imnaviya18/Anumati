"""URL routes for guarded decision commands."""
from django.urls import path
from apps.decisions.api.views import GuardedDecisionCommandView

urlpatterns = [
    path("cases/<uuid:case_id>/decide/", GuardedDecisionCommandView.as_view(), name="decisions-command"),
]
