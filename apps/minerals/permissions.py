from apps.accounts.models import User


def get_managed_mineral_ids(user):
    if not user.is_authenticated:
        return []
    if user.role in (User.Role.SUPER_ADMIN, User.Role.ADMIN):
        return None
    if user.role == User.Role.MINERAL_MANAGER:
        return list(
            user.mineral_assignments.values_list("mineral_id", flat=True)
        )
    return []


def user_can_manage_mineral(user, mineral_id):
    if not user.is_authenticated:
        return False
    if user.role in (User.Role.SUPER_ADMIN, User.Role.ADMIN):
        return True
    if user.role == User.Role.MINERAL_MANAGER:
        return user.mineral_assignments.filter(mineral_id=mineral_id).exists()
    return False
