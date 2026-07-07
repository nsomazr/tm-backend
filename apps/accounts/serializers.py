from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.analytics.credits import get_assistant_credit_quota
from apps.analytics.mineral_exploration import get_mineral_exploration_quota

from .models import User
from .staff_sync import is_privileged_role, sync_user_staff_flags


class UserSerializer(serializers.ModelSerializer):
    has_paid_access = serializers.BooleanField(read_only=True)
    can_save_explorations = serializers.BooleanField(read_only=True)
    assistant_credits = serializers.SerializerMethodField()
    mineral_exploration = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "phone",
            "organization",
            "profile_complete",
            "has_paid_access",
            "can_save_explorations",
            "assistant_credits",
            "mineral_exploration",
            "created_at",
        )
        read_only_fields = ("id", "role", "created_at")

    def get_assistant_credits(self, obj):
        request = self.context.get("request")
        if not request:
            return None
        return get_assistant_credit_quota(request, obj)

    def get_mineral_exploration(self, obj):
        request = self.context.get("request")
        if not request:
            return None
        return get_mineral_exploration_quota(request, obj)


class ProfileCompleteSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "username", "phone", "organization")

    def validate_username(self, value):
        value = value.strip()
        user = self.instance
        if User.objects.filter(username=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def update(self, instance, validated_data):
        user = super().update(instance, validated_data)
        user.profile_complete = True
        user.save(update_fields=["profile_complete"])
        return user


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = (
            "username",
            "email",
            "password",
            "password_confirm",
            "first_name",
            "last_name",
            "phone",
            "organization",
        )

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        return attrs

    def create(self, validated_data):
        validated_data.pop("password_confirm")
        password = validated_data.pop("password")
        user = User(**validated_data, role=User.Role.FREE, profile_complete=True)
        user.set_password(password)
        user.save()
        return user


class EmailOnlySerializer(serializers.Serializer):
    email = serializers.EmailField()


class SendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=20)
    purpose = serializers.ChoiceField(choices=["register", "login"])

    def validate(self, attrs):
        from .phone_utils import normalize_tz_phone

        email = (attrs.get("email") or "").strip().lower()
        phone_raw = (attrs.get("phone") or "").strip()
        purpose = attrs["purpose"]

        if email and phone_raw:
            raise serializers.ValidationError("Provide either email or phone, not both.")
        if not email and not phone_raw:
            raise serializers.ValidationError("Email or phone number is required.")

        if phone_raw:
            phone = normalize_tz_phone(phone_raw)
            if not phone:
                raise serializers.ValidationError(
                    {"phone": "Enter a valid Tanzania mobile number (e.g. 07XXXXXXXX)."}
                )
            exists = User.objects.filter(phone__in=[phone, f"0{phone[3:]}"]).exists()
            if purpose == "register" and exists:
                raise serializers.ValidationError(
                    {"phone": "An account with this phone number already exists. Sign in instead."}
                )
            if purpose == "login" and not exists:
                raise serializers.ValidationError(
                    {"phone": "No account found for this phone number. Create an account first."}
                )
            attrs["channel"] = "sms"
            attrs["phone"] = phone
            attrs.pop("email", None)
            return attrs

        exists = User.objects.filter(email__iexact=email).exists()
        if purpose == "register" and exists:
            raise serializers.ValidationError(
                {"email": "An account with this email already exists. Sign in instead."}
            )
        if purpose == "login" and not exists:
            raise serializers.ValidationError(
                {"email": "No account found for this email. Create an account first."}
            )
        attrs["channel"] = "email"
        attrs["email"] = email
        return attrs


class VerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=20)
    code = serializers.CharField(min_length=6, max_length=6)
    purpose = serializers.ChoiceField(choices=["register", "login"])

    def validate(self, attrs):
        from .phone_utils import normalize_tz_phone

        email = (attrs.get("email") or "").strip().lower()
        phone_raw = (attrs.get("phone") or "").strip()
        if email and phone_raw:
            raise serializers.ValidationError("Provide either email or phone, not both.")
        if not email and not phone_raw:
            raise serializers.ValidationError("Email or phone number is required.")

        if phone_raw:
            phone = normalize_tz_phone(phone_raw)
            if not phone:
                raise serializers.ValidationError(
                    {"phone": "Enter a valid Tanzania mobile number (e.g. 07XXXXXXXX)."}
                )
            attrs["channel"] = "sms"
            attrs["phone"] = phone
        else:
            attrs["channel"] = "email"
            attrs["email"] = email
        attrs["code"] = attrs["code"].strip()
        return attrs


class PasswordSignupSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(min_length=8, write_only=True)

    def validate_email(self, value):
        return value.strip().lower()


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Accept username or email in the username field."""

    def validate(self, attrs):
        identifier = attrs.get(self.username_field, "").strip()
        if "@" in identifier:
            user = User.objects.filter(email__iexact=identifier).first()
        else:
            user = User.objects.filter(username__iexact=identifier).first()
        if user:
            attrs[self.username_field] = user.username
        return super().validate(attrs)


class AdminUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "phone",
            "organization",
            "profile_complete",
            "is_active",
            "created_at",
        )
        read_only_fields = ("id", "created_at")

    def validate_is_active(self, value):
        request = self.context.get("request")
        actor = getattr(request, "user", None)
        if (
            self.instance
            and is_privileged_role(self.instance.role)
            and actor
            and actor.is_authenticated
            and actor.role != User.Role.SUPER_ADMIN
            and value is False
        ):
            raise serializers.ValidationError("Only super admins can deactivate admin accounts.")
        return value

    def validate_role(self, value):
        request = self.context.get("request")
        actor = getattr(request, "user", None)
        if not actor or not actor.is_authenticated:
            return value

        if self.instance and self.instance.pk == actor.pk and value != actor.role:
            raise serializers.ValidationError("You cannot change your own role.")

        if actor.role != User.Role.SUPER_ADMIN:
            if value in (User.Role.SUPER_ADMIN, User.Role.ADMIN):
                raise serializers.ValidationError("Only super admins can assign admin roles.")
            if self.instance and is_privileged_role(self.instance.role):
                raise serializers.ValidationError("Only super admins can modify admin accounts.")
        return value

    def update(self, instance, validated_data):
        user = super().update(instance, validated_data)
        if "role" in validated_data:
            sync_user_staff_flags(user)
            user.save(update_fields=["is_staff", "is_superuser"])
        return user


class AdminUserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = (
            "email",
            "password",
            "first_name",
            "last_name",
            "role",
            "phone",
        )

    def validate_email(self, value):
        email = value.strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return email

    def validate_role(self, value):
        if value not in (User.Role.ADMIN, User.Role.SUPER_ADMIN):
            raise serializers.ValidationError("Only admin or super_admin roles can be created here.")
        request = self.context.get("request")
        actor = getattr(request, "user", None)
        if actor and actor.role != User.Role.SUPER_ADMIN:
            raise serializers.ValidationError("Only super admins can create admin accounts.")
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        email = validated_data["email"]
        username_base = email.split("@")[0].replace(".", "_")[:30] or "admin"
        username = username_base
        suffix = 1
        while User.objects.filter(username=username).exists():
            username = f"{username_base}{suffix}"[:30]
            suffix += 1

        user = User(
            username=username,
            email=email,
            profile_complete=True,
            **validated_data,
        )
        user.set_password(password)
        sync_user_staff_flags(user)
        user.save()
        return user
