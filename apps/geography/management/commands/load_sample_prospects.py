from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Deprecated: demo prospect data is no longer seeded. Upload shapefiles via Admin → Layers."

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.WARNING(
                "Demo prospect loading is disabled. "
                "Use Admin → Layers to upload polygon, line, or point shapefiles."
            )
        )
