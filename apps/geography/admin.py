from django.contrib import admin

from .models import Country, Region


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
