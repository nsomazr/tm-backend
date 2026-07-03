from .models import User


def sync_user_staff_flags(user: User) -> None:
    """Keep Django admin flags aligned with Terra Meta platform roles."""
    if user.role == User.Role.SUPER_ADMIN:
        user.is_staff = True
        user.is_superuser = True
    elif user.role == User.Role.ADMIN:
        user.is_staff = True
        user.is_superuser = False
    elif not user.is_superuser:
        user.is_staff = False


def is_privileged_role(role: str) -> bool:
    return role in (User.Role.SUPER_ADMIN, User.Role.ADMIN)
