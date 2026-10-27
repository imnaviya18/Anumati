"""URL routes for cases API."""
from django.urls import path
from apps.cases.api.views import (
    CaseDetailView,
    CaseLifecycleView,
    CaseListIntakeView,
    CaseRouteResolveView,
    CaseStageTransitionView,
    DeficiencyResponseView,
)

urlpatterns = [
    path("<uuid:case_id>/lifecycle/<str:action>/", CaseLifecycleView.as_view()),
    path("", CaseListIntakeView.as_view(), name="cases-list-intake"),
    path("<uuid:case_id>/", CaseDetailView.as_view(), name="cases-detail"),
    path("<uuid:case_id>/resolve-route/", CaseRouteResolveView.as_view(), name="cases-resolve-route"),
    path(
        "<uuid:case_id>/stages/<uuid:stage_instance_id>/transition/",
        CaseStageTransitionView.as_view(),
        name="cases-stage-transition",
    ),
    path(
        "<uuid:case_id>/deficiencies/<uuid:deficiency_cycle_id>/respond/",
        DeficiencyResponseView.as_view(),
        name="cases-deficiency-respond",
    ),
]
