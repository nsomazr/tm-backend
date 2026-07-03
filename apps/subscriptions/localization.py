"""Bilingual copy for subscription plans (slug-keyed; DB values are fallback)."""

PLAN_LABELS: dict[str, dict[str, dict[str, str]]] = {
    "monthly-standard": {
        "sw": {
            "name": "Kiwango cha Kila Mwezi",
            "description": "Ufikiaji kamili wa ramani zote za madini na uchambuzi",
        },
    },
    "annual-standard": {
        "sw": {
            "name": "Kiwango cha Mwaka",
            "description": "Ufikiaji wa mwaka mzima na akiba ya asilimia 20",
        },
    },
}

BILLING_CYCLE_LABELS: dict[str, dict[str, str]] = {
    "monthly": {"en": "monthly", "sw": "kila mwezi"},
    "annual": {"en": "annual", "sw": "kwa mwaka"},
}


def localized_plan_text(plan, field: str, locale: str) -> str:
    if locale == "sw":
        alt = PLAN_LABELS.get(plan.slug, {}).get("sw", {}).get(field)
        if alt:
            return alt
    return (getattr(plan, field, None) or "").strip()


def billing_cycle_label(cycle: str, locale: str) -> str:
    labels = BILLING_CYCLE_LABELS.get(cycle, {})
    return labels.get("sw" if locale == "sw" else "en", cycle)
