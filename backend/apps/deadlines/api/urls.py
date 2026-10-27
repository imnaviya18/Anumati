from django.urls import path
from .views import DeadlineOperationsView

urlpatterns = [
    path("", DeadlineOperationsView.as_view()),
    path("<uuid:record_id>/<str:action>/", DeadlineOperationsView.as_view()),
]
