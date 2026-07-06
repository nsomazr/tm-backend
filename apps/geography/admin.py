from django.contrib import admin

from .models import AdminBoundary, Country, Region


class RegionInline(admin.TabularInline):
    model = Region
    extra = 0


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    inlines = [RegionInline]


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "is_active")
    list_filter = ("country",)


@admin.register(AdminBoundary)
class AdminBoundaryAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "level", "source", "updated_at")
    list_filter = ("country", "level", "source")
    search_fields = ("name", "code")
