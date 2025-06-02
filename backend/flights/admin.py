from django.contrib import admin

from .models import EnrichmentTask, Flight, PriceQuoteCache


@admin.register(Flight)
class FlightAdmin(admin.ModelAdmin):
    list_display = (
        "flight_id",
        "origin",
        "destination",
        "travel_class",
        "retail_price",
        "currency",
        "enriched",
    )
    list_filter = ("enriched", "travel_class", "price_provider")
    search_fields = ("flight_id", "origin", "destination")


@admin.register(EnrichmentTask)
class EnrichmentTaskAdmin(admin.ModelAdmin):
    list_display = ("task_id", "flight", "status", "attempts", "created_at", "completed_at")
    list_filter = ("status",)
    search_fields = ("task_id", "flight__flight_id")
    # Without this the changelist issues one query per row for the flight.
    list_select_related = ("flight",)


@admin.register(PriceQuoteCache)
class PriceQuoteCacheAdmin(admin.ModelAdmin):
    list_display = (
        "origin",
        "destination",
        "cabin",
        "amount",
        "currency",
        "provider",
        "fetched_at",
    )
    list_filter = ("provider", "cabin")
