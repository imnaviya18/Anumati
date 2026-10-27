"""Celery application and Beat schedule configuration (Sheet 01 Block 08, Sheet 05)."""
from __future__ import annotations

import os
from typing import Any, Callable

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

try:
    from celery import Celery  # type: ignore[import-untyped]
except ImportError:  # Fallback shim when running Django outside the Celery container

    class Celery:  # type: ignore[no-redef]
        def __init__(self, main: str) -> None:
            self.main = main
            self.conf: dict[str, Any] = {}

        def config_from_object(self, obj: str, namespace: str = "") -> None:
            pass

        def autodiscover_tasks(self) -> None:
            pass

        def task(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
            def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
                func.delay = lambda *a, **kw: func(*a, **kw)  # type: ignore[attr-defined]
                func.apply_async = lambda args=None, kwargs=None, **_opts: func(  # type: ignore[attr-defined]
                    *(args or ()), **(kwargs or {})
                )
                return func

            if len(args) == 1 and callable(args[0]):
                return decorator(args[0])
            return decorator


app = Celery("anumati")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
