from apps.geography.models import Country
from apps.minerals.models import Mineral

GENERAL_MINERAL_SLUG = "general"


def get_or_create_general_mineral() -> Mineral:
    country = Country.objects.filter(code="TZ").first()
    mineral, _ = Mineral.objects.get_or_create(
        slug=GENERAL_MINERAL_SLUG,
        defaults={
            "name": "General",
            "name_sw": "Jumla",
            "country": country,
            "color": "#64748B",
            "description": "Default grouping for map layers",
        },
    )
    if country and mineral.country_id != country.id:
        mineral.country = country
        mineral.save(update_fields=["country"])
    return mineral
