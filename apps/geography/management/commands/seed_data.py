from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.compliance.models import TermsVersion
from apps.geography.models import Country, Region
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
            defaults={"name": "Tanzania", "name_sw": "Tanzania"},
        )

        for name in TANZANIA_REGIONS:
            Region.objects.get_or_create(country=country, name=name, defaults={"name_sw": name})

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

        layer_defs = [
            ("gold-priority-1", "Gold Priority 1", "Dhahabu - Kipaumbele - 1", gold, "polygon", "#E87722", True, 10),
            ("gold-priority-2", "Gold Priority 2", "Dhahabu - Kipaumbele - 2", gold, "polygon", "#C4A035", False, 20),
            ("gold-priority-3", "Gold Priority 3", "Dhahabu - Kipaumbele - 3", gold, "polygon", "#F5E6A3", False, 30),
            ("host-graphite-gold", "Host Rocks Graphite+Gold", "Miamba Mwenyeji kwa Grafiti + Dhahabu", graphite, "polygon", "#1B5E20", True, 45),
            ("host-graphite", "Host Rocks Graphite", "Miamba Mwenyeji kwa Grafiti", graphite, "polygon", "#81C784", False, 46),
            ("graphite-zones", "Graphite Zones", "Grafiti", graphite, "polygon", "#2D2D2D", True, 40),
            ("main-structures", "Main Linear Structures", "Miundo Mstari Mikuu", gold, "line", "#000000", True, 100),
            ("linear-structures", "Linear Structures", "Miundo Mstari", gold, "line", "#333333", True, 110),
            ("tanzanite-zones", "Tanzanite Zones", "Tanzanite", mineral_objs["tanzanite"], "polygon", "#7B2D8E", True, 50),
            ("copper-zones", "Copper Zones", "Shaba", mineral_objs["copper"], "polygon", "#B87333", True, 60),
            ("nickel-zones", "Nickel Zones", "Nikel", mineral_objs["nickel"], "polygon", "#708090", True, 70),
            ("iron-zones", "Iron Ore Zones", "Chuma", mineral_objs["iron-ore"], "polygon", "#4A3728", True, 80),
            ("lithium-zones", "Lithium Zones", "Lithiamu", mineral_objs["lithium"], "polygon", "#00CED1", True, 90),
        ]

        mwanza = Region.objects.filter(name="Mwanza").first()
        arusha = Region.objects.filter(name="Arusha").first()
        region_by_mineral = {
            gold: mwanza,
            graphite: mwanza,
            mineral_objs["tanzanite"]: arusha,
            mineral_objs["copper"]: mwanza,
            mineral_objs["nickel"]: Region.objects.filter(name="Morogoro").first() or mwanza,
            mineral_objs["iron-ore"]: Region.objects.filter(name="Lindi").first() or mwanza,
            mineral_objs["lithium"]: Region.objects.filter(name="Mbeya").first() or mwanza,
        }
        for slug, name, name_sw, mineral, ltype, color, is_preview, z_index in layer_defs:
            layer, created = MapLayer.objects.get_or_create(
                mineral=mineral,
                slug=slug,
                defaults={
                    "name": name,
                    "name_sw": name_sw,
                    "layer_type": ltype,
                    "region": region_by_mineral.get(mineral, mwanza),
                    "z_index": z_index,
                    "is_preview": is_preview,
                    "style": {
                        "fill": color,
                        "stroke": color if ltype == "polygon" else "#000000",
                        "strokeWidth": 2 if slug == "main-structures" else 1,
                        "fillOpacity": 0.55 if ltype == "polygon" else 1,
                    },
                },
            )
            if created:
                layer.z_index = z_index
                layer.save(update_fields=["z_index"])
            else:
                layer.name = name
                layer.name_sw = name_sw
                layer.layer_type = ltype
                layer.region = region_by_mineral.get(mineral, mwanza)
                layer.z_index = z_index
                layer.is_preview = is_preview
                layer.style = {
                    "fill": color,
                    "stroke": color if ltype == "polygon" else "#000000",
                    "strokeWidth": 2 if slug == "main-structures" else 1,
                    "fillOpacity": 0.55 if ltype == "polygon" else 1,
                }
                layer.save(
                    update_fields=[
                        "name",
                        "name_sw",
                        "layer_type",
                        "region",
                        "z_index",
                        "is_preview",
                        "style",
                    ]
                )

        from django.core.management import call_command
        call_command("load_sample_prospects")
        call_command("generate_sample_shapefiles")

        monthly, _ = SubscriptionPlan.objects.get_or_create(
            slug="monthly-standard",
            defaults={
                "name": "Monthly Standard",
                "description": "Full access to all mineral maps and analytics",
                "billing_cycle": "monthly",
                "price": 50000,
                "currency": "TZS",
            },
        )
        monthly.included_minerals.set(list(mineral_objs.values()))

        annual, _ = SubscriptionPlan.objects.get_or_create(
            slug="annual-standard",
            defaults={
                "name": "Annual Standard",
                "description": "Full year access with 20% savings",
                "billing_cycle": "annual",
                "price": 480000,
                "currency": "TZS",
            },
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

