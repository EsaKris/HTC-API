from django.urls import path
from .views import (
    ApplyToDriverView,
    AdminApplicationListView,
    AdminApplicationDetailView,
    ApproveApplicationView,
    RejectApplicationView,
    BikeListCreateView,
    AssignBikeView,
    UnassignBikeView,
    BikeStatusUpdateView,
    DriverProfileView,
    AdminDriverListView,
    DriverRideDetailView,
)

urlpatterns = [
    # ── Applicant ──────────────────────────────────────────────────────────
    # Submit application (POST) or check own status (GET)
    path("apply/", ApplyToDriverView.as_view(), name="driver-apply"),
    path("rides/<uuid:ride_id>/", DriverRideDetailView.as_view(), name="driver-ride-detail"),

    # Approved driver: own profile + bike
    path("me/", DriverProfileView.as_view(), name="driver-profile"),

    # ── Admin – Applications ───────────────────────────────────────────────
    # List all applications (filterable by status)
    path("applications/", AdminApplicationListView.as_view(), name="driver-applications-list"),

    # Single application detail
    path("applications/<uuid:pk>/", AdminApplicationDetailView.as_view(), name="driver-application-detail"),

    # Approve / Reject
    path("applications/<uuid:pk>/approve/", ApproveApplicationView.as_view(), name="driver-application-approve"),
    path("applications/<uuid:pk>/reject/", RejectApplicationView.as_view(), name="driver-application-reject"),

    # ── Admin – Drivers list ───────────────────────────────────────────────
    # List all approved drivers
    path("", AdminDriverListView.as_view(), name="driver-list"),

    # ── Admin – Bikes ──────────────────────────────────────────────────────
    # List all bikes / Add new bike to fleet
    path("bikes/", BikeListCreateView.as_view(), name="bike-list-create"),

    # Assign / Unassign bike
    path("bikes/<uuid:bike_id>/assign/", AssignBikeView.as_view(), name="bike-assign"),
    path("bikes/<uuid:bike_id>/unassign/", UnassignBikeView.as_view(), name="bike-unassign"),

    # Update bike status (available / maintenance / retired)
    path("bikes/<uuid:bike_id>/status/", BikeStatusUpdateView.as_view(), name="bike-status"),
]