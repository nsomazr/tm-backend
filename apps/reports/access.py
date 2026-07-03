"""Report catalog access: preview vs full exploration."""

from apps.accounts.models import User


def user_has_report_detail_access(user, report=None) -> bool:
    if not user.is_authenticated:
        return False
    if user.has_paid_access or user.is_admin_user:
        return True
    if user.role == User.Role.MINERAL_MANAGER:
        return True
    if report is not None:
        return report.purchases.filter(user=user).exists()
    return False
