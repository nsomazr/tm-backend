from rest_framework import serializers

from .models import Country, Region


class CountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Country
        fields = ("id", "code", "name", "name_sw", "is_active")


class RegionSerializer(serializers.ModelSerializer):
    country_name = serializers.CharField(source="country.name", read_only=True)

    class Meta:
        model = Region
        fields = ("id", "country", "country_name", "name", "name_sw", "bounds", "is_active")
