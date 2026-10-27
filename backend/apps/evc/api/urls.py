from django.urls import path
from apps.evc.api.views import EvcView

urlpatterns = [
    path("", EvcView.as_view()),
    path("<uuid:coordination_id>/<str:action>/", EvcView.as_view()),
]
