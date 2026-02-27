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
    # Bike Owner Management
    BikeOwnerListView,
    BikeOwnerDetailView,
    BikeOwnerEarningsView,
    BikeOwnerContactView,

    # Bike Owner Auth & Dashboard
    BikeOwnerLoginView,
    BikeOwnerVerifyOTPView,
    BikeOwnerDashboardView,
    BikeOwnerAddBikeView,
    BikeOwnerUpdateProfileView,
    BikeOwnerPendingRegistrationsView,
    
    # Registration
    RegisterBikeAndOwnerView,
    BikeRegistrationListView,
    BikeRegistrationDetailView,
    ApproveBikeRegistrationView,
    RejectBikeRegistrationView,
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


        # ── Bike Owner Portal ────────────────────────────────────────────────
    path(
        "bike-owners/login/",
        BikeOwnerLoginView.as_view(),
        name="bike-owner-login"
    ),
    path(
        "bike-owners/verify-otp/",
        BikeOwnerVerifyOTPView.as_view(),
        name="bike-owner-verify-otp"
    ),
    path(
        "bike-owners/me/",
        BikeOwnerDashboardView.as_view(),
        name="bike-owner-dashboard"
    ),
    path(
        "bike-owners/bikes/add/",
        BikeOwnerAddBikeView.as_view(),
        name="bike-owner-add-bike"
    ),
    path(
        "bike-owners/registrations/pending/",
        BikeOwnerPendingRegistrationsView.as_view(),
        name="bike-owner-pending-registrations"
    ),

        # ── Admin: Bike Owner Management ─────────────────────────────────────
    
    path(
        "admin/bike-owners/",
        BikeOwnerListView.as_view(),
        name="bike-owners-list"
    ),
    path(
        "admin/bike-owners/<uuid:owner_id>/",
        BikeOwnerDetailView.as_view(),
        name="bike-owner-detail"
    ),
    path(
        "admin/bike-owners/<uuid:owner_id>/earnings/",
        BikeOwnerEarningsView.as_view(),
        name="bike-owner-earnings"
    ),
    path(
        "admin/bike-owners/<uuid:owner_id>/contact/",
        BikeOwnerContactView.as_view(),
        name="bike-owner-contact"
    ),
    
    # ── Admin: Bike Registrations ────────────────────────────────────────
    path(
        "admin/bike-registrations/",
        BikeRegistrationListView.as_view(),
        name="bike-registrations-list"
    ),
    path(
        "admin/bike-registrations/<uuid:registration_id>/",
        BikeRegistrationDetailView.as_view(),
        name="bike-registration-detail"
    ),
    path(
        "admin/bike-registrations/<uuid:registration_id>/approve/",
        ApproveBikeRegistrationView.as_view(),
        name="approve-bike-registration"
    ),
    path(
        "admin/bike-registrations/<uuid:registration_id>/reject/",
        RejectBikeRegistrationView.as_view(),
        name="reject-bike-registration"
    ),
]