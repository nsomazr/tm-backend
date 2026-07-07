"""Print why ad campaigns are or are not served publicly."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.ads.models import Ad, AdAudience, AdPlacement
from apps.ads.services import ads_for_placement


class Command(BaseCommand):
    help = "Diagnose ad campaigns and simulate public serve responses."

    def add_arguments(self, parser):
        parser.add_argument(
            "--placement",
            default="about_banner",
            help="Placement to simulate (default: about_banner)",
        )
        parser.add_argument("--country", default="TZ", help="Country code (default: TZ)")

    def handle(self, *args, **options):
        placement = options["placement"]
        country = options["country"]
        now = timezone.now()

        total = Ad.objects.count()
        self.stdout.write(f"Total campaigns in database: {total}")
        if total == 0:
            self.stdout.write(
                self.style.WARNING(
                    "No campaigns found. Create one in Admin → Ads → Campaigns on production."
                )
            )
            return

        self.stdout.write(f"\nCampaign details (now={now.isoformat()}):\n")
        for ad in Ad.objects.order_by("-priority", "-created_at"):
            reasons = []
            if not ad.is_active:
                reasons.append("inactive")
            if ad.is_hidden:
                reasons.append("hidden")
            if ad.starts_at and ad.starts_at > now:
                reasons.append(f"scheduled (starts {ad.starts_at})")
            if ad.ends_at and ad.ends_at < now:
                reasons.append(f"expired (ended {ad.ends_at})")
            if not (ad.placements or []):
                reasons.append("no placements selected")

            status = "LIVE" if ad.is_live(now=now) else "NOT LIVE"
            style = self.style.SUCCESS if status == "LIVE" else self.style.WARNING
            self.stdout.write(style(f"  [{ad.id}] {ad.title} — {status}"))
            self.stdout.write(f"      company={ad.company_name!r} audience={ad.audience}")
            self.stdout.write(f"      placements={ad.placements!r} countries={ad.country_codes!r}")
            if reasons:
                self.stdout.write(f"      blockers: {', '.join(reasons)}")

        served = ads_for_placement(placement, user=None, country_code=country)
        self.stdout.write(f"\nSimulated public serve: placement={placement!r} country={country!r}")
        if served:
            self.stdout.write(self.style.SUCCESS(f"  → {len(served)} campaign(s) would render"))
            for ad in served:
                self.stdout.write(f"     - [{ad.id}] {ad.title}")
                if ad.image:
                    image_path = ad.image.path
                    exists = "found" if __import__("os").path.isfile(image_path) else "MISSING on disk"
                    self.stdout.write(f"       image: {ad.image.name} ({exists})")
        else:
            self.stdout.write(self.style.ERROR("  → [] (nothing would render)"))
            self.stdout.write(
                "\nChecklist for public visitors:\n"
                "  • is_active=True, is_hidden=False\n"
                "  • audience is 'all' or 'free' (not 'subscriber' only)\n"
                f"  • placements includes '{placement}' (or map_sidebar for map_overlay)\n"
                "  • country_codes empty OR includes TZ\n"
                "  • starts_at / ends_at not blocking today\n"
            )

        self.stdout.write(f"\nValid placements: {', '.join(AdPlacement.values)}")
        self.stdout.write(f"Valid audiences: {', '.join(AdAudience.values)}")
