"""URL routes for accounts and session auth."""
from django.urls import path
from apps.accounts.api.views import (
    CsrfTokenView,
    UserDirectoryView,
    CurrentActorMeView,
    SessionLoginView,
    SessionLogoutView,
)

urlpatterns = [
    path("users/", UserDirectoryView.as_view()),
    path("csrf/", CsrfTokenView.as_view(), name="auth-csrf"),
    path("login/", SessionLoginView.as_view(), name="auth-login"),
    path("logout/", SessionLogoutView.as_view(), name="auth-logout"),
    path("me/", CurrentActorMeView.as_view(), name="auth-me"),
]
