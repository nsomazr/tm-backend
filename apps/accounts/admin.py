from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "role", "is_active", "created_at")
    list_filter = ("role", "is_active", "is_staff")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Terra Meta", {"fields": ("role", "phone", "organization")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Terra Meta", {"fields": ("role", "phone", "organization")}),
    )
