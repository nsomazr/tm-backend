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
            "color_rgba",
            "icon",
            "description",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")


class SyncMineralManagerAssignmentsSerializer(serializers.Serializer):
    """Replace a manager's mineral assignments in one request."""

    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    minerals = serializers.ListField(child=serializers.IntegerField(), allow_empty=True)
    can_publish = serializers.BooleanField(default=False, required=False)

    def validate_minerals(self, value):
        ids = list(dict.fromkeys(value))
        found = set(Mineral.objects.filter(id__in=ids, is_active=True).values_list("id", flat=True))
        missing = sorted(set(ids) - found)
        if missing:
            raise serializers.ValidationError(f"Unknown mineral ids: {missing}")
        return ids

    def save(self):
        request = self.context.get("request")
        user = self.validated_data["user"]
        mineral_ids = self.validated_data["minerals"]
        can_publish = self.validated_data.get("can_publish", False)

        if user.role not in (User.Role.MINERAL_MANAGER, User.Role.ADMIN, User.Role.SUPER_ADMIN):
            user.role = User.Role.MINERAL_MANAGER
            user.save(update_fields=["role"])

        existing = {
            assignment.mineral_id: assignment
            for assignment in MineralManagerAssignment.objects.filter(user=user)
        }
        target_ids = set(mineral_ids)

        for mineral_id, assignment in list(existing.items()):
            if mineral_id not in target_ids:
                assignment.delete()

        assigned_by = request.user if request and request.user.is_authenticated else None
        for mineral_id in mineral_ids:
            assignment = existing.get(mineral_id)
            if assignment:
                if assignment.can_publish != can_publish:
                    assignment.can_publish = can_publish
                    assignment.save(update_fields=["can_publish"])
            else:
                MineralManagerAssignment.objects.create(
                    user=user,
                    mineral_id=mineral_id,
                    can_publish=can_publish,
                    assigned_by=assigned_by,
                )

        return MineralManagerAssignment.objects.filter(user=user).select_related(
            "user", "mineral", "assigned_by"
        )


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
