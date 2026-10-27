"""URL routes for electronic case summaries and standardised communications."""
from django.urls import path
from apps.communications.api.views import ElectronicCaseSummaryView, IssueCommunicationView

urlpatterns = [
    path("cases/<uuid:case_id>/summary/", ElectronicCaseSummaryView.as_view(), name="comm-case-summary"),
    path("cases/<uuid:case_id>/issue/", IssueCommunicationView.as_view(), name="comm-issue"),
]
