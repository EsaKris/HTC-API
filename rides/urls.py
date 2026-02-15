from django.urls import path
from .views import (
    RideRequestView,
    RiderRideHistoryView,
    RiderRideDetailView,
    RideCancelView,
    RideAssignDriverView,
    RideStatusUpdateView,
    DriverRideListView,
    DriverActiveRideView,
    AdminRideListView,
    AdminRideDetailView,
    AdminAnalyticsView,
)

urlpatterns = [
    # ── Rider ──────────────────────────────────────────────────────────────
    # Request a new ride
    path("request/", RideRequestView.as_view(), name="ride-request"),

    # Full ride history (filterable by status)
    path("history/", RiderRideHistoryView.as_view(), name="ride-history"),

    # View a single ride
    path("<uuid:ride_id>/", RiderRideDetailView.as_view(), name="ride-detail"),

    # Cancel a ride (REQUESTED only)
    path("<uuid:ride_id>/cancel/", RideCancelView.as_view(), name="ride-cancel"),

    # ── Driver ─────────────────────────────────────────────────────────────
    # All rides assigned to the authenticated driver
    path("driver/", DriverRideListView.as_view(), name="driver-rides"),

    # Driver's current active ride
    path("driver/active/", DriverActiveRideView.as_view(), name="driver-active-ride"),

    # Advance ride status: ASSIGNED → IN_PROGRESS → COMPLETED
    path("<uuid:ride_id>/status/", RideStatusUpdateView.as_view(), name="ride-status-update"),

    # ── Admin ──────────────────────────────────────────────────────────────
    # List all rides (filterable, searchable)
    path("", AdminRideListView.as_view(), name="admin-ride-list"),

    # Admin full ride detail with audit log
    path("<uuid:ride_id>/admin/", AdminRideDetailView.as_view(), name="admin-ride-detail"),

    # Assign a driver to a REQUESTED ride
    path("<uuid:ride_id>/assign/", RideAssignDriverView.as_view(), name="ride-assign"),

    # Analytics / dashboard stats
    path("analytics/", AdminAnalyticsView.as_view(), name="ride-analytics"),
]