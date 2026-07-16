from rest_framework.permissions import BasePermission

from .models import User


class IsAdminUser(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return user.is_authenticated and bool(getattr(user, "is_admin_user", False))


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
        if getattr(request.user, "is_admin_user", False):
            return True
        return request.user.role == User.Role.MINERAL_MANAGER

