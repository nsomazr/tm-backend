from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.reports.catalog_seed import seed_report_catalog
from apps.reports.models import Report


class Command(BaseCommand):
    help = "Seed or refresh the public report catalog with sample prospectivity reports"

    def handle(self, *args, **options):
        admin = User.objects.filter(email="admin@5ggeology.com").first()
        ensured = seed_report_catalog(created_by=admin)
        total = Report.objects.filter(is_active=True).count()
        self.stdout.write(
            self.style.SUCCESS(f"Catalog ready: {ensured} sample reports upserted ({total} active total)")
        )
