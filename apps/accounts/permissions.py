from rest_framework.permissions import BasePermission

from .models import User


class IsAdminUser(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role in (User.Role.SUPER_ADMIN, User.Role.ADMIN)
        )


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role == User.Role.SUPER_ADMIN
        )


class IsMineralManagerOrAdmin(BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in (
            User.Role.SUPER_ADMIN,
            User.Role.ADMIN,
            User.Role.MINERAL_MANAGER,
        )
