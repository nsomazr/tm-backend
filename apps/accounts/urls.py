from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    CompleteProfileView,
    LoginView,
    MeView,
    PasswordSignupView,
    RegisterView,
    SendOTPView,
    VerifyOTPView,
)
from .notification_views import (
    NotificationListView,
    NotificationMarkAllReadView,
    NotificationMarkReadView,
    NotificationUnreadCountView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("signup/password/", PasswordSignupView.as_view(), name="signup-password"),
    path("otp/send/", SendOTPView.as_view(), name="otp-send"),
    path("otp/verify/", VerifyOTPView.as_view(), name="otp-verify"),
    path("login/", LoginView.as_view(), name="login"),
    path("refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("me/", MeView.as_view(), name="me"),
    path("complete-profile/", CompleteProfileView.as_view(), name="complete-profile"),
    path("notifications/", NotificationListView.as_view(), name="notifications"),
    path("notifications/unread-count/", NotificationUnreadCountView.as_view(), name="notifications-unread-count"),
    path("notifications/read-all/", NotificationMarkAllReadView.as_view(), name="notifications-read-all"),
    path("notifications/<int:pk>/read/", NotificationMarkReadView.as_view(), name="notification-read"),
]
