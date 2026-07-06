from django.contrib import admin

from .models import Report, ReportChatThread, ReportDocumentChunk, ReportSummary, UserExplorationReport


class ReportSummaryInline(admin.StackedInline):
    model = ReportSummary
    extra = 0


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("title", "mineral", "region", "access_type", "report_format", "price", "is_active")
    list_filter = ("access_type", "report_format", "source_type", "mineral", "is_active")
    prepopulated_fields = {"slug": ("title",)}
    filter_horizontal = ("allowed_plans", "layers", "boundaries")
    inlines = [ReportSummaryInline]


@admin.register(ReportDocumentChunk)
class ReportDocumentChunkAdmin(admin.ModelAdmin):
    list_display = ("report", "page_number", "chunk_index", "token_count")
    list_filter = ("report",)


@admin.register(ReportChatThread)
class ReportChatThreadAdmin(admin.ModelAdmin):
    list_display = ("report", "user", "updated_at")


@admin.register(UserExplorationReport)
class UserExplorationReportAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "status", "updated_at")
    list_filter = ("status",)
