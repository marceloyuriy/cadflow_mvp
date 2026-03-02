from django.contrib import admin

from .models import (
    AuditEvent,
    BlockEvent,
    ManufacturingReview,
    Part,
    PartRevision,
    RevisionFile,
)


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    list_display = ("code", "description", "material", "quantity", "need_by", "created_at")
    search_fields = ("code", "description", "material")
    list_filter = ("material",)
    ordering = ("-created_at",)


class RevisionFileInline(admin.TabularInline):
    model = RevisionFile
    extra = 0
    readonly_fields = ("uid", "original_name", "sha256", "size_bytes", "uploaded_at", "uploaded_by")


@admin.register(PartRevision)
class PartRevisionAdmin(admin.ModelAdmin):
    list_display = ("part", "revision_no", "is_current", "status", "priority_rank", "created_by", "created_at")
    list_filter = ("status", "is_current")
    search_fields = ("part__code",)
    ordering = ("-created_at",)
    inlines = [RevisionFileInline]


@admin.register(RevisionFile)
class RevisionFileAdmin(admin.ModelAdmin):
    list_display = ("revision", "original_name", "sha256", "size_bytes", "uploaded_by", "uploaded_at")
    search_fields = ("revision__part__code", "original_name", "sha256")
    ordering = ("-uploaded_at",)


@admin.register(ManufacturingReview)
class ManufacturingReviewAdmin(admin.ModelAdmin):
    list_display = ("revision", "decision", "decided_by", "decided_at")
    list_filter = ("decision",)
    ordering = ("-decided_at",)


@admin.register(BlockEvent)
class BlockEventAdmin(admin.ModelAdmin):
    list_display = ("revision", "blocked_from_status", "blocked_by", "blocked_at", "unblocked_by", "unblocked_at")
    list_filter = ("blocked_from_status",)
    ordering = ("-blocked_at",)


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("entity_type", "entity_id", "action", "from_status", "to_status", "actor", "happened_at")
    list_filter = ("entity_type", "action", "from_status", "to_status")
    ordering = ("-happened_at",)
    search_fields = ("entity_type", "action")