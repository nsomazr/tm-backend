from django.contrib import admin

from .models import Mineral, MineralCategory, MineralManagerAssignment


@admin.register(MineralCategory)
class MineralCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "color", "priority")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Mineral)
class MineralAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "category", "country", "is_active")
    list_filter = ("country", "category", "is_active")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(MineralManagerAssignment)
class MineralManagerAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "mineral", "can_publish", "assigned_at")
    list_filter = ("can_publish",)
