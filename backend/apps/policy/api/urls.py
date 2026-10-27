"""URL routes for policy governance."""
from django.urls import path
from apps.policy.api.views import PolicyActionView, PolicyListDraftView, PolicyMigrateCasesView

from apps.policy.api.sync_views import SyncExceptionsView, SyncExceptionActionView

urlpatterns = [
    path("sync-exceptions/", SyncExceptionsView.as_view()),
    path("sync-exceptions/<uuid:exception_id>/resolve/", SyncExceptionActionView.as_view()),
    path("", PolicyListDraftView.as_view(), name="policy-list-draft"),
    path("migrate/", PolicyMigrateCasesView.as_view(), name="policy-migrate"),
    path("<uuid:policy_id>/<str:action_name>/", PolicyActionView.as_view(), name="policy-action"),
]
