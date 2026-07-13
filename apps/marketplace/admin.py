from django.contrib import admin

from .models import ListingDocument, ListingInquiry, MarketplaceListing


class ListingDocumentInline(admin.TabularInline):
    model = ListingDocument
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(MarketplaceListing)
class MarketplaceListingAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "owner",
        "status",
        "show_on_map",
        "show_contact_public",
        "allow_inquiries",
        "updated_at",
    )
    list_filter = ("status", "show_on_map", "country")
    search_fields = ("title", "slug", "summary", "owner__username", "owner__email")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [ListingDocumentInline]
    readonly_fields = ("center_lat", "center_lng", "bounding_box", "created_at", "updated_at")


@admin.register(ListingDocument)
class ListingDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "listing", "is_public", "uploaded_by", "created_at")
    list_filter = ("is_public",)
    search_fields = ("title", "listing__title")


@admin.register(ListingInquiry)
class ListingInquiryAdmin(admin.ModelAdmin):
    list_display = ("listing", "from_user", "is_read", "created_at")
    list_filter = ("is_read",)
    search_fields = ("listing__title", "from_user__username", "message")
    readonly_fields = ("created_at",)
