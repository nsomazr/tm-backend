from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .beem_sms import BeemSmsError
from .models import EmailOTP, User
from .otp_service import (
    get_or_create_password_user,
    send_email_otp,
    send_phone_otp,
    verify_email_otp,
    verify_phone_otp,
    OTP_SMS_TTL_MINUTES,
    OTP_TTL_MINUTES,
)
from .permissions import IsAdminUser, IsSuperAdmin
from .throttling import AuthAnonThrottle, OTPSendThrottle, OTPVerifyThrottle
from .serializers import (
    AdminUserCreateSerializer,
    AdminUserSerializer,
    EmailTokenObtainPairSerializer,
    PasswordSignupSerializer,
    ProfileCompleteSerializer,
    RegisterSerializer,
    SendOTPSerializer,
    UserSerializer,
    VerifyOTPSerializer,
)


def _tokens_for_user(user: User) -> dict:
    refresh = RefreshToken.for_user(user)
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "user": UserSerializer(user).data,
    }


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    throttle_classes = [AuthAnonThrottle]


class LoginView(TokenObtainPairView):
    permission_classes = [AllowAny]
    serializer_class = EmailTokenObtainPairSerializer
    throttle_classes = [AuthAnonThrottle]

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            identifier = request.data.get("username", "")
            user = None
            if "@" in identifier:
                user = User.objects.filter(email__iexact=identifier.strip()).first()
            else:
                user = User.objects.filter(username__iexact=identifier.strip()).first()
            if user:
                response.data["user"] = UserSerializer(user).data
        return response


class SendOTPView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [OTPSendThrottle, AnonRateThrottle]

    def post(self, request):
        serializer = SendOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        purpose = data["purpose"]
        channel = data["channel"]
        try:
            if channel == "sms":
                send_phone_otp(data["phone"], purpose)
            else:
                send_email_otp(data["email"], purpose)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        except BeemSmsError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception:
            detail = (
                "Could not send verification SMS. Please try again later."
                if channel == "sms"
                else "Could not send verification email. Please try password sign-up or try again later."
            )
            return Response({"detail": detail}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        ttl_minutes = OTP_SMS_TTL_MINUTES if channel == "sms" else OTP_TTL_MINUTES
        payload = {
            "detail": "Verification code sent.",
            "channel": channel,
            "expires_in": ttl_minutes * 60,
        }
        if channel == "sms":
            payload["phone"] = data["phone"]
        else:
            payload["email"] = data["email"]
        return Response(payload)


class VerifyOTPView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [OTPVerifyThrottle, AnonRateThrottle]

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        code = data["code"]
        purpose = data["purpose"]
        otp_purpose = (
            EmailOTP.Purpose.REGISTER if purpose == "register" else EmailOTP.Purpose.LOGIN
        )
        try:
            if data["channel"] == "sms":
                user, _created = verify_phone_otp(data["phone"], code, otp_purpose)
            else:
                user, _created = verify_email_otp(data["email"], code, otp_purpose)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_tokens_for_user(user))


class PasswordSignupView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthAnonThrottle]

    def post(self, request):
        serializer = PasswordSignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        password = serializer.validated_data["password"]
        try:
            user, _created = get_or_create_password_user(email, password)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_tokens_for_user(user), status=status.HTTP_201_CREATED)


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


class CompleteProfileView(generics.UpdateAPIView):
    serializer_class = ProfileCompleteSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


class AdminUserListView(generics.ListCreateAPIView):
    queryset = User.objects.all().order_by("-created_at")
    permission_classes = [IsAdminUser]
    filterset_fields = ["role", "is_active"]
    search_fields = ["username", "email", "first_name", "last_name"]

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsSuperAdmin()]
        return [IsAdminUser()]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return AdminUserCreateSerializer
        return AdminUserSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context


class AdminUserDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = User.objects.all()
    serializer_class = AdminUserSerializer
    permission_classes = [IsAdminUser]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.pk == request.user.pk:
            return Response(
                {"detail": "You cannot delete your own account."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if (
            request.user.role != User.Role.SUPER_ADMIN
            and instance.role in (User.Role.SUPER_ADMIN, User.Role.ADMIN)
        ):
            return Response(
                {"detail": "Only super admins can delete admin accounts."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)
