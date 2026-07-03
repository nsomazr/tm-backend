from django.contrib import admin

from .models import LayerUpload, LayerVersion, MapFeature, MapLayer


class MapFeatureInline(admin.TabularInline):
    model = MapFeature
    extra = 0


@admin.register(MapLayer)
class MapLayerAdmin(admin.ModelAdmin):
    list_display = ("name", "layer_type", "mineral", "z_index", "is_preview", "is_active")
    list_filter = ("layer_type", "is_preview", "is_active", "mineral")
    inlines = [MapFeatureInline]


@admin.register(MapFeature)
class MapFeatureAdmin(admin.ModelAdmin):
    list_display = ("id", "layer", "label", "latitude", "longitude", "is_active")
    list_filter = ("layer",)


@admin.register(LayerVersion)
class LayerVersionAdmin(admin.ModelAdmin):
    list_display = ("layer", "version_number", "feature_count", "created_at")


@admin.register(LayerUpload)
class LayerUploadAdmin(admin.ModelAdmin):
    list_display = ("layer", "file_type", "status", "created_at")
    list_filter = ("status",)
