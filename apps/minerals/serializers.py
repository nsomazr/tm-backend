from rest_framework import serializers

from apps.accounts.models import User
from apps.accounts.serializers import UserSerializer
from apps.maps.localization import get_request_locale, localized_name

from .models import Mineral, MineralCategory, MineralManagerAssignment


class MineralCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = MineralCategory
        fields = ("id", "name", "name_sw", "slug", "color", "description", "priority")


class MineralSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    country_code = serializers.CharField(source="country.code", read_only=True)

    class Meta:
        model = Mineral
        fields = (
            "id",
            "name",
            "name_sw",
            "slug",
            "category",
            "category_name",
            "country",
            "country_code",
            "color",
            "icon",
            "description",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")


class MineralManagerAssignmentSerializer(serializers.ModelSerializer):
    user_detail = UserSerializer(source="user", read_only=True)
    mineral_name = serializers.SerializerMethodField()

    class Meta:
        model = MineralManagerAssignment
        fields = (
            "id",
            "user",
            "user_detail",
            "mineral",
            "mineral_name",
            "can_publish",
            "assigned_by",
            "assigned_at",
        )
        read_only_fields = ("assigned_by", "assigned_at")

    def get_mineral_name(self, obj):
        locale = get_request_locale(self.context.get("request"))
        return localized_name(obj.mineral, locale)

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            validated_data["assigned_by"] = request.user
        user = validated_data["user"]
        if user.role not in (User.Role.MINERAL_MANAGER, User.Role.ADMIN, User.Role.SUPER_ADMIN):
            user.role = User.Role.MINERAL_MANAGER
            user.save(update_fields=["role"])
        return super().create(validated_data)
