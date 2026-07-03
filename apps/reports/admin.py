from django.contrib import admin

from .models import Report, ReportSummary


class ReportSummaryInline(admin.StackedInline):
    model = ReportSummary
    extra = 0


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("title", "mineral", "region", "price", "is_active")
    list_filter = ("mineral", "is_active")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [ReportSummaryInline]
