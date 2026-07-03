from apps.geography.models import Region
from apps.minerals.models import Mineral

from .models import Report, ReportSummary

SAMPLE_REPORTS = [
    {
        "slug": "geita-gold-belt-prospectivity",
        "title": "Geita Gold Belt Prospectivity Assessment",
        "mineral_slug": "gold",
        "region_name": "Geita",
        "description": "Regional gold prospectivity synthesis across the Geita greenstone belt.",
        "price": 35000,
        "summary": (
            "This report integrates structural, geochemical, and historical production data across "
            "the Geita gold belt. High-priority corridors align with major shear zones and artisanal "
            "workings, with several under-explored gaps between known deposits."
        ),
        "key_findings": [
            "Three tier-1 corridors show consistent Au-in-soil anomalies above 50 ppb.",
            "Shear-parallel structures correlate with 78% of historical production.",
            "Under-explored gaps between Nyankanga and Geita Hill warrant follow-up drilling.",
        ],
    },
    {
        "slug": "lake-victoria-copper-arc",
        "title": "Lake Victoria Copper Arc Overview",
        "mineral_slug": "copper",
        "region_name": "Mwanza",
        "description": "Copper and associated base-metal targets along the Lake Victoria mobile belt.",
        "price": 40000,
        "summary": (
            "The Lake Victoria copper arc hosts VMS-style and shear-hosted copper-gold systems. "
            "This assessment ranks districts by geophysical response, host lithology, and access infrastructure."
        ),
        "key_findings": [
            "Five districts show coincident magnetic lows and Cu soil anomalies.",
            "BIF-hosted targets in eastern Mwanza remain sparsely drilled.",
            "Road access within 15 km improves viability for three priority blocks.",
        ],
    },
    {
        "slug": "southern-graphite-corridors",
        "title": "Southern Graphite Corridors Study",
        "mineral_slug": "graphite",
        "region_name": "Lindi",
        "description": "Graphite flake distribution and host-rock mapping in southern coastal belts.",
        "price": 30000,
        "summary": (
            "Southern Tanzania hosts multiple graphite-bearing metasedimentary packages with "
            "medium-to-coarse flake potential. This report maps corridor continuity and compares "
            "grade proxies from regional sampling campaigns."
        ),
        "key_findings": [
            "Two continuous corridors exceed 12 km strike length each.",
            "Host gneiss packages show favorable metamorphic grade for coarse flake.",
            "Port proximity gives southern blocks a logistics advantage over inland targets.",
        ],
    },
    {
        "slug": "mererani-tanzanite-zone",
        "title": "Mererani Tanzanite Zone Assessment",
        "mineral_slug": "tanzanite",
        "region_name": "Manyara",
        "description": "Gemstone prospectivity around the Mererani tanzanite mining district.",
        "price": 45000,
        "summary": (
            "The Mererani block is the world's sole commercial tanzanite source. This report "
            "evaluates structural controls, depth extensions, and adjacent under-licensed ground "
            "for blue zoisite potential."
        ),
        "key_findings": [
            "Primary control is NE-trending foliation parallel to known pay shoots.",
            "Depth modeling suggests viable extensions below 400 m in two blocks.",
            "Adjacent licenses with similar host chemistry remain under-sampled.",
        ],
    },
]


def seed_report_catalog(created_by=None) -> int:
    """Upsert demo catalog reports. Returns number of reports ensured active."""
    count = 0
    for spec in SAMPLE_REPORTS:
        mineral = Mineral.objects.filter(slug=spec["mineral_slug"]).first()
        if not mineral:
            continue

        region = Region.objects.filter(name=spec["region_name"]).first()
        report, _ = Report.objects.get_or_create(
            slug=spec["slug"],
            defaults={
                "title": spec["title"],
                "mineral": mineral,
                "region": region,
                "description": spec["description"],
                "price": spec["price"],
                "currency": "TZS",
                "is_active": True,
                "created_by": created_by,
            },
        )
        report.title = spec["title"]
        report.mineral = mineral
        report.region = region
        report.description = spec["description"]
        report.price = spec["price"]
        report.is_active = True
        report.save()

        ReportSummary.objects.update_or_create(
            report=report,
            defaults={
                "summary": spec["summary"],
                "key_findings": spec["key_findings"],
                "model_used": "seed",
            },
        )
        count += 1

    return count
