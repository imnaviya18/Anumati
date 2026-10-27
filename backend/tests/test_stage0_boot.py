"""Stage 0 boot and structure verification tests (Sheet 01, Sheet 05, Sheet 07 Q5)."""
from pathlib import Path
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

EXPECTED_DOMAIN_APPS = [
    "apps.common",
    "apps.accounts",
    "apps.access",
    "apps.organisation",
    "apps.cases",
    "apps.routing",
    "apps.evc",
    "apps.decisions",
    "apps.compliance",
    "apps.documents",
    "apps.policy",
    "apps.deadlines",
    "apps.escalation",
    "apps.notifications",
    "apps.communications",
    "apps.outbox",
    "apps.audit",
    "apps.reporting",
    "apps.adapters",
]


class Stage0BootTests(TestCase):
    def test_all_domain_apps_registered_and_layered(self) -> None:
        """Verify every required domain app is installed and has models, services, selectors, api, tests, migrations."""
        installed_names = {app_config.name for app_config in apps.get_app_configs()}
        base_dir: Path = settings.BASE_DIR
        for app_path in EXPECTED_DOMAIN_APPS:
            self.assertIn(app_path, installed_names, f"{app_path} is not registered in INSTALLED_APPS")
            rel_dir = base_dir / app_path.replace(".", "/")
            self.assertTrue((rel_dir / "models.py").is_file())
            self.assertTrue((rel_dir / "services.py").is_file())
            self.assertTrue((rel_dir / "selectors.py").is_file())
            self.assertTrue((rel_dir / "api").is_dir())
            self.assertTrue((rel_dir / "tests").is_dir())
            self.assertTrue((rel_dir / "migrations").is_dir())

    def test_database_migrations_clean_boot(self) -> None:
        """Verify migrations apply cleanly and database queries execute."""
        User = get_user_model()
        self.assertEqual(User.objects.count(), 0)
