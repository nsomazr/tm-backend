from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.compliance.models import TermsVersion
from apps.geography.models import Country, Region
from apps.geography.region_geo import region_bounds
from apps.geography.country_geo import preset_for_code
from apps.geography.world_countries import WORLD_COUNTRIES
from apps.minerals.models import Mineral, MineralCategory, MineralManagerAssignment
from apps.maps.models import MapLayer
from apps.subscriptions.models import SubscriptionPlan, UserSubscription


TANZANIA_REGIONS = [
    "Arusha", "Dar es Salaam", "Dodoma", "Geita", "Iringa", "Kagera",
    "Katavi", "Kigoma", "Kilimanjaro", "Lindi", "Manyara", "Mara",
    "Mbeya", "Morogoro", "Mtwara", "Mwanza", "Njombe", "Pwani",
    "Rukwa", "Ruvuma", "Shinyanga", "Simiyu", "Singida", "Songwe",
    "Tabora", "Tanga", "Zanzibar",
]

TANZANIA_BOUNDS = {
    "type": "Polygon",
    "coordinates": [[
        [29.3, -12.0], [40.5, -12.0], [40.5, -0.9], [29.3, -0.9], [29.3, -12.0]
    ]],
}


class Command(BaseCommand):
    help = "Seed Terra Meta with Tanzania data, minerals, layers, and admin user"

    def handle(self, *args, **options):
        country, _ = Country.objects.get_or_create(
            code="TZ",
            defaults={
                "name": "Tanzania",
                "name_sw": "Tanzania",
                **preset_for_code("TZ"),
            },
        )
        tz_preset = preset_for_code("TZ")
        country.center_lat = tz_preset["center_lat"]
        country.center_lng = tz_preset["center_lng"]
        country.default_zoom = tz_preset["default_zoom"]
        country.bounds = tz_preset["bounds"]
        country.boundary = tz_preset["boundary"]
        country.save(
            update_fields=[
                "center_lat",
                "center_lng",
                "default_zoom",
                "bounds",
                "boundary",
            ]
        )

        for extra_code in ("KE", "UG"):
            preset = preset_for_code(extra_code)
            if not preset:
                continue
            extra, created = Country.objects.get_or_create(
                code=extra_code,
                defaults={
                    "name": "Kenya" if extra_code == "KE" else "Uganda",
                    "name_sw": "Kenya" if extra_code == "KE" else "Uganda",
                    "center_lat": preset["center_lat"],
                    "center_lng": preset["center_lng"],
                    "default_zoom": preset["default_zoom"],
                    "bounds": preset["bounds"],
                    "boundary": preset["boundary"],
                    "is_active": True,
                },
            )
            if not created and not extra.bounds:
                extra.center_lat = preset["center_lat"]
                extra.center_lng = preset["center_lng"]
                extra.default_zoom = preset["default_zoom"]
                extra.bounds = preset["bounds"]
                extra.boundary = preset["boundary"]
                extra.save(
                    update_fields=[
                        "center_lat",
                        "center_lng",
                        "default_zoom",
                        "bounds",
                        "boundary",
                    ]
                )

        for code, name in WORLD_COUNTRIES:
            preset = preset_for_code(code)
            defaults = {
                "name": name,
                "name_sw": name,
                "is_active": True,
            }
            if preset:
                defaults.update(
                    {
                        "center_lat": preset["center_lat"],
                        "center_lng": preset["center_lng"],
                        "default_zoom": preset["default_zoom"],
                        "bounds": preset["bounds"],
                        "boundary": preset["boundary"],
                    }
                )
            Country.objects.get_or_create(code=code, defaults=defaults)

        for name in TANZANIA_REGIONS:
            bounds = region_bounds(name)
            region, created = Region.objects.get_or_create(
                country=country,
                name=name,
                defaults={"name_sw": name, "bounds": bounds},
            )
            if not created and not region.bounds:
                region.bounds = bounds
                region.save(update_fields=["bounds"])

        categories = [
            ("Gold Priority 1", "Dhahabu - Kipaumbele -1", "gold-priority-1", "#E87722", 1),
            ("Gold Priority 2", "Dhahabu - Kipaumbele -2", "gold-priority-2", "#C4A035", 2),
            ("Gold Priority 3", "Dhahabu - Kipaumbele -3", "gold-priority-3", "#F5E6A3", 3),
            ("Graphite", "Grafiti", "graphite", "#2D2D2D", 4),
            ("Host Rocks Graphite+Gold", "Miamba Mwenyeji kwa Grafiti + Dhahabu", "host-graphite-gold", "#1B5E20", 5),
            ("Host Rocks Graphite", "Miamba Mwenyeji kwa Grafiti", "host-graphite", "#81C784", 6),
        ]
        cat_objs = {}
        for name, name_sw, slug, color, priority in categories:
            cat, _ = MineralCategory.objects.get_or_create(
                slug=slug,
                defaults={"name": name, "name_sw": name_sw, "color": color, "priority": priority},
            )
            cat_objs[slug] = cat

        gold, _ = Mineral.objects.get_or_create(
            slug="gold",
            defaults={
                "name": "Gold",
                "name_sw": "Dhahabu",
                "category": cat_objs["gold-priority-1"],
                "country": country,
                "color": "#E87722",
                "description": "Gold prospectivity zones across Tanzania",
            },
        )
        graphite, _ = Mineral.objects.get_or_create(
            slug="graphite",
            defaults={
                "name": "Graphite",
                "name_sw": "Grafiti",
                "category": cat_objs["graphite"],
                "country": country,
                "color": "#2D2D2D",
                "description": "Graphite deposits and host rock zones",
            },
        )

        extra_minerals = [
            ("tanzanite", "Tanzanite", "Tanzanite", "graphite", "#7B2D8E", "Unique gemstone found only in northern Tanzania"),
            ("copper", "Copper", "Shaba", "gold-priority-2", "#B87333", "Copper prospectivity in Lake Zone and central belts"),
            ("nickel", "Nickel", "Nikel", "gold-priority-2", "#708090", "Nickel laterite and sulphide targets"),
            ("iron-ore", "Iron Ore", "Chuma", "host-graphite", "#4A3728", "Iron ore bands and magnetite zones"),
            ("lithium", "Lithium", "Lithiamu", "gold-priority-1", "#00CED1", "Lithium pegmatite and brine prospects"),
        ]
        mineral_objs = {"gold": gold, "graphite": graphite}
        for slug, name, name_sw, cat_slug, color, desc in extra_minerals:
            obj, _ = Mineral.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "name_sw": name_sw,
                    "category": cat_objs[cat_slug],
                    "country": country,
                    "color": color,
                    "description": desc,
                },
            )
            mineral_objs[slug] = obj

        from apps.maps.models import MapFeature, MapLayer

        demo_layer_types = (MapLayer.LayerType.POLYGON, MapLayer.LayerType.LINE)
        layer_ids_with_features = set(
            MapFeature.objects.filter(is_active=True).values_list("layer_id", flat=True)
        )
        stale_layers = MapLayer.objects.filter(
            layer_type__in=demo_layer_types, is_active=False
        ).exclude(id__in=layer_ids_with_features)
        cleared_layers = stale_layers.count()
        if cleared_layers:
            stale_layers.delete()
            self.stdout.write(
                self.style.WARNING(
                    f"Removed {cleared_layers} inactive empty map layer(s). "
                    "Upload shapefiles via Admin → Layers."
                )
            )

        monthly, _ = SubscriptionPlan.objects.get_or_create(
            slug="monthly-standard",
            defaults={
                "name": "Monthly Standard",
                "description": "Terra insights, show-on-map, full AI, analytics, and 3 PDF downloads per month",
                "billing_cycle": "monthly",
                "price": 50000,
                "currency": "TZS",
                "included_report_downloads": 3,
            },
        )
        monthly.included_report_downloads = 3
        monthly.included_assistant_credits = 3000
        monthly.includes_chat_history = True
        monthly.description = (
            "Terra insights, show-on-map, full AI, analytics, and 3 PDF downloads per month"
        )
        monthly.save(
            update_fields=[
                "description",
                "included_report_downloads",
                "included_assistant_credits",
                "includes_chat_history",
            ]
        )
        monthly.included_minerals.set(list(mineral_objs.values()))

        annual, _ = SubscriptionPlan.objects.get_or_create(
            slug="annual-standard",
            defaults={
                "name": "Annual Standard",
                "description": "Full year: Terra insights, show-on-map, full AI, analytics, and 10 PDF downloads",
                "billing_cycle": "annual",
                "price": 480000,
                "currency": "TZS",
                "included_report_downloads": 10,
            },
        )
        annual.included_report_downloads = 10
        annual.included_assistant_credits = 5000
        annual.includes_chat_history = True
        annual.description = (
            "Full year: Terra insights, show-on-map, full AI, analytics, and 10 PDF downloads"
        )
        annual.save(
            update_fields=[
                "description",
                "included_report_downloads",
                "included_assistant_credits",
                "includes_chat_history",
            ]
        )
        annual.included_minerals.set(list(mineral_objs.values()))

        TermsVersion.objects.get_or_create(
            version="1.0",
            defaults={
                "title": "Terra Meta Terms of Service",
                "content": "By using Terra Meta you agree to comply with Tanzanian mining regulations and data licensing terms.",
                "is_active": True,
            },
        )

        admin_user, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@5ggeology.com",
                "role": User.Role.SUPER_ADMIN,
                "is_staff": True,
                "is_superuser": True,
                "profile_complete": True,
            },
        )
        admin_user.email = "admin@5ggeology.com"
        admin_user.profile_complete = True
        if created:
            admin_user.set_password("admin123")
            admin_user.save()
            self.stdout.write(
                self.style.SUCCESS("Created admin: admin@5ggeology.com / admin123")
            )
        else:
            if admin_user.role not in (User.Role.SUPER_ADMIN, User.Role.ADMIN):
                admin_user.role = User.Role.SUPER_ADMIN
                admin_user.is_staff = True
                admin_user.is_superuser = True
            admin_user.set_password("admin123")
            admin_user.save()
            self.stdout.write(
                self.style.SUCCESS("Admin ready: admin@5ggeology.com / admin123")
            )

        from apps.reports.catalog_seed import seed_report_catalog

        seed_report_catalog(created_by=admin_user)
        self.stdout.write(self.style.SUCCESS("Report catalog seeded"))

        demo_password = "test123"
        today = timezone.now().date()

        def ensure_demo_user(username, email, role):
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={"email": email, "role": role, "profile_complete": True},
            )
            user.email = email
            user.role = role
            user.profile_complete = True
            user.is_staff = role in (User.Role.SUPER_ADMIN, User.Role.ADMIN)
            user.is_superuser = role == User.Role.SUPER_ADMIN
            user.set_password(demo_password)
            user.save()
            return user

        free_user = ensure_demo_user("testfree", "testfree@5ggeology.com", User.Role.FREE)

        paid_user = ensure_demo_user("testpaid", "testpaid@5ggeology.com", User.Role.SUBSCRIBER)
        paid_sub, _ = UserSubscription.objects.get_or_create(
            user=paid_user,
            defaults={"plan": monthly},
        )
        paid_sub.plan = monthly
        paid_sub.status = UserSubscription.Status.ACTIVE
        paid_sub.start_date = today
        paid_sub.end_date = today + timedelta(days=365)
        paid_sub.auto_renew = True
        paid_sub.save()

        from apps.payments.models import PaymentOrder

        PaymentOrder.objects.get_or_create(
            user=paid_user,
            subscription=paid_sub,
            defaults={
                "order_type": PaymentOrder.OrderType.SUBSCRIPTION,
                "amount": monthly.price,
                "currency": monthly.currency,
                "status": PaymentOrder.Status.COMPLETED,
                "payment_provider": "simulated",
            },
        )

        manager_user = ensure_demo_user(
            "testmanager",
            "testmanager@5ggeology.com",
            User.Role.MINERAL_MANAGER,
        )
        MineralManagerAssignment.objects.get_or_create(
            user=manager_user,
            mineral=gold,
            defaults={"can_publish": True, "assigned_by": admin_user},
        )

        self.stdout.write(self.style.SUCCESS("Demo accounts (sign in with email + password):"))
        self.stdout.write(f"  Free:     {free_user.email} / {demo_password}")
        self.stdout.write(f"  Paid:     {paid_user.email} / {demo_password}")
        self.stdout.write(f"  Manager:  {manager_user.email} / {demo_password}")

        self.stdout.write(self.style.SUCCESS("Seed data loaded successfully."))

