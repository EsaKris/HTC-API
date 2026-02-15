import logging
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Sum, Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, generics, filters
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from core.permissions import IsRider, IsDriver, IsAdmin, IsRiderOrAdmin
from .models import Ride, RideStatusLog
from .serializers import (
    RideSerializer,
    RideRequestSerializer,
    RideCancelSerializer,
    RideAssignSerializer,
    RideStatusUpdateSerializer,
    RideAnalyticsSerializer,
)

logger = logging.getLogger(__name__)
User = get_user_model()


def _log_status_change(ride, from_status, to_status, changed_by, note=""):
    """Record a status transition in the audit log."""
    RideStatusLog.objects.create(
        ride=ride,
        from_status=from_status,
        to_status=to_status,
        changed_by=changed_by,
        note=note,
    )


# ---------------------------------------------------------------------------
# Rider: Request a Ride
# ---------------------------------------------------------------------------

class RideRequestView(APIView):
    """
    POST /api/rides/request/
    Authenticated rider requests a new trip. Price locked to ₦500.
    """

    permission_classes = [IsRider]

    @transaction.atomic
    def post(self, request):
        serializer = RideRequestSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        ride = serializer.save()

        _log_status_change(
            ride=ride,
            from_status="",
            to_status=Ride.Status.REQUESTED,
            changed_by=request.user,
            note="Ride requested by rider.",
        )

        return Response(
            {
                "message": "Ride requested successfully. A driver will be assigned shortly.",
                "ride": RideSerializer(ride).data,
            },
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Rider: Ride History
# ---------------------------------------------------------------------------

class RiderRideHistoryView(generics.ListAPIView):
    """
    GET /api/rides/history/
    Authenticated rider's full ride history, newest first.
    Supports ?status=COMPLETED filtering.
    """

    permission_classes = [IsRider]
    serializer_class = RideSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["status"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return (
            Ride.objects.filter(rider=self.request.user)
            .select_related("rider", "driver", "driver__assigned_bike")
            .prefetch_related("status_logs", "status_logs__changed_by")
        )


# ---------------------------------------------------------------------------
# Rider: Cancel a Ride
# ---------------------------------------------------------------------------

class RideCancelView(APIView):
    """
    POST /api/rides/<id>/cancel/
    Rider can cancel only rides in REQUESTED status (before a driver is assigned).
    """

    permission_classes = [IsRider]

    @transaction.atomic
    def post(self, request, ride_id):
        try:
            ride = Ride.objects.get(pk=ride_id, rider=request.user)
        except Ride.DoesNotExist:
            return Response(
                {"detail": "Ride not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if ride.status != Ride.Status.REQUESTED:
            return Response(
                {
                    "detail": (
                        f"Cannot cancel a ride that is '{ride.status}'. "
                        "Cancellation is only allowed before a driver is assigned."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = RideCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        prev_status = ride.status
        ride.status = Ride.Status.CANCELLED
        ride.cancelled_by = request.user
        ride.cancelled_at = timezone.now()
        ride.cancellation_reason = serializer.validated_data.get("cancellation_reason", "")
        ride.save(
            update_fields=[
                "status", "cancelled_by", "cancelled_at",
                "cancellation_reason", "updated_at",
            ]
        )

        _log_status_change(
            ride=ride,
            from_status=prev_status,
            to_status=Ride.Status.CANCELLED,
            changed_by=request.user,
            note=f"Cancelled by rider. Reason: {ride.cancellation_reason or 'Not provided'}",
        )

        return Response(
            {
                "message": "Ride cancelled successfully.",
                "ride": RideSerializer(ride).data,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Rider: View Single Ride
# ---------------------------------------------------------------------------

class RiderRideDetailView(APIView):
    """
    GET /api/rides/<id>/
    Rider views details and live status of one of their rides.
    """

    permission_classes = [IsRider]

    def get(self, request, ride_id):
        try:
            ride = (
                Ride.objects.select_related("rider", "driver", "driver__assigned_bike")
                .prefetch_related("status_logs", "status_logs__changed_by")
                .get(pk=ride_id, rider=request.user)
            )
        except Ride.DoesNotExist:
            return Response({"detail": "Ride not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response(RideSerializer(ride).data)


# ---------------------------------------------------------------------------
# Admin: Assign Driver to Ride
# ---------------------------------------------------------------------------

class RideAssignDriverView(APIView):
    """
    PATCH /api/rides/<id>/assign/
    Admin assigns an available driver to a REQUESTED ride.
    Body: { "driver_id": "<uuid>" }
    """

    permission_classes = [IsAdmin]

    @transaction.atomic
    def patch(self, request, ride_id):
        try:
            ride = Ride.objects.select_related("rider", "driver").get(pk=ride_id)
        except Ride.DoesNotExist:
            return Response({"detail": "Ride not found."}, status=status.HTTP_404_NOT_FOUND)

        if ride.status != Ride.Status.REQUESTED:
            return Response(
                {"detail": f"Only REQUESTED rides can be assigned. Current status: '{ride.status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = RideAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        driver_id = serializer.validated_data["driver_id"]
        driver = User.objects.select_related("assigned_bike").get(id=driver_id)

        prev_status = ride.status
        ride.driver = driver
        ride.status = Ride.Status.ASSIGNED
        ride.assigned_by = request.user
        ride.assigned_at = timezone.now()
        ride.save(
            update_fields=["driver", "status", "assigned_by", "assigned_at", "updated_at"]
        )

        _log_status_change(
            ride=ride,
            from_status=prev_status,
            to_status=Ride.Status.ASSIGNED,
            changed_by=request.user,
            note=f"Driver '{driver.full_name}' assigned by admin '{request.user.full_name}'.",
        )

        return Response(
            {
                "message": f"Driver '{driver.full_name}' assigned to ride successfully.",
                "ride": RideSerializer(ride).data,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Driver: Update Ride Status
# ---------------------------------------------------------------------------

class RideStatusUpdateView(APIView):
    """
    PATCH /api/rides/<id>/status/
    Driver advances the ride status:
      ASSIGNED → IN_PROGRESS  (driver has picked up rider)
      IN_PROGRESS → COMPLETED (trip finished)
    """

    permission_classes = [IsDriver]

    @transaction.atomic
    def patch(self, request, ride_id):
        try:
            ride = Ride.objects.select_related("rider", "driver").get(
                pk=ride_id, driver=request.user
            )
        except Ride.DoesNotExist:
            return Response(
                {"detail": "Ride not found or not assigned to you."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = RideStatusUpdateSerializer(
            data=request.data, context={"ride": ride}
        )
        serializer.is_valid(raise_exception=True)

        new_status = serializer.validated_data["status"]
        prev_status = ride.status

        ride.status = new_status
        update_fields = ["status", "updated_at"]

        if new_status == Ride.Status.IN_PROGRESS:
            ride.started_at = timezone.now()
            update_fields.append("started_at")
            note = f"Ride started by driver '{request.user.full_name}'."
        else:  # COMPLETED
            ride.completed_at = timezone.now()
            update_fields.append("completed_at")
            note = f"Ride completed by driver '{request.user.full_name}'."

        ride.save(update_fields=update_fields)

        _log_status_change(
            ride=ride,
            from_status=prev_status,
            to_status=new_status,
            changed_by=request.user,
            note=note,
        )

        return Response(
            {
                "message": f"Ride status updated to '{new_status}'.",
                "ride": RideSerializer(ride).data,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Driver: View Assigned Rides
# ---------------------------------------------------------------------------

class DriverRideListView(generics.ListAPIView):
    """
    GET /api/rides/driver/
    Driver sees all rides assigned to them.
    Supports ?status=ASSIGNED filtering.
    """

    permission_classes = [IsDriver]
    serializer_class = RideSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["status"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return (
            Ride.objects.filter(driver=self.request.user)
            .select_related("rider", "driver", "driver__assigned_bike")
            .prefetch_related("status_logs")
        )


# ---------------------------------------------------------------------------
# Driver: Active Ride
# ---------------------------------------------------------------------------

class DriverActiveRideView(APIView):
    """
    GET /api/rides/driver/active/
    Returns the driver's currently active ride (ASSIGNED or IN_PROGRESS), if any.
    """

    permission_classes = [IsDriver]

    def get(self, request):
        ride = (
            Ride.objects.filter(
                driver=request.user,
                status__in=[Ride.Status.ASSIGNED, Ride.Status.IN_PROGRESS],
            )
            .select_related("rider", "driver", "driver__assigned_bike")
            .prefetch_related("status_logs")
            .first()
        )
        if not ride:
            return Response(
                {"detail": "No active ride at the moment."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(RideSerializer(ride).data)


# ---------------------------------------------------------------------------
# Admin: All Rides List
# ---------------------------------------------------------------------------

class AdminRideListView(generics.ListAPIView):
    """
    GET /api/rides/
    Admin sees all rides with filtering, search, and ordering.
    Supports: ?status=REQUESTED, ?search=rider_name, ?ordering=-created_at
    """

    permission_classes = [IsAdmin]
    serializer_class = RideSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status"]
    search_fields = [
        "rider__full_name",
        "rider__phone_number",
        "driver__full_name",
        "pickup_address",
        "dropoff_address",
    ]
    ordering_fields = ["created_at", "status", "price"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return (
            Ride.objects.select_related(
                "rider", "driver", "driver__assigned_bike", "assigned_by"
            )
            .prefetch_related("status_logs", "status_logs__changed_by")
            .all()
        )


# ---------------------------------------------------------------------------
# Admin: Single Ride Detail
# ---------------------------------------------------------------------------

class AdminRideDetailView(APIView):
    """
    GET /api/rides/<id>/admin/
    Admin views full ride details including full audit log.
    """

    permission_classes = [IsAdmin]

    def get(self, request, ride_id):
        try:
            ride = (
                Ride.objects.select_related(
                    "rider", "driver", "driver__assigned_bike",
                    "assigned_by", "cancelled_by",
                )
                .prefetch_related("status_logs", "status_logs__changed_by")
                .get(pk=ride_id)
            )
        except Ride.DoesNotExist:
            return Response({"detail": "Ride not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response(RideSerializer(ride).data)


# ---------------------------------------------------------------------------
# Admin: Analytics Dashboard
# ---------------------------------------------------------------------------

class AdminAnalyticsView(APIView):
    """
    GET /api/rides/analytics/
    Returns aggregate platform statistics for admin dashboard.
    """

    permission_classes = [IsAdmin]

    def get(self, request):
        ride_stats = Ride.objects.aggregate(
            total_rides=Count("id"),
            total_completed=Count("id", filter=Q(status=Ride.Status.COMPLETED)),
            total_cancelled=Count("id", filter=Q(status=Ride.Status.CANCELLED)),
            total_in_progress=Count("id", filter=Q(status=Ride.Status.IN_PROGRESS)),
            total_requested=Count("id", filter=Q(status=Ride.Status.REQUESTED)),
            total_assigned=Count("id", filter=Q(status=Ride.Status.ASSIGNED)),
            total_earnings=Sum("price", filter=Q(status=Ride.Status.COMPLETED)),
        )

        ride_stats["total_earnings"] = ride_stats["total_earnings"] or 0
        ride_stats["total_drivers"] = User.objects.filter(role=User.Role.DRIVER, is_active=True).count()
        ride_stats["total_riders"] = User.objects.filter(role=User.Role.USER, is_active=True).count()
        ride_stats["pending_applications"] = (
            User.objects.filter(role=User.Role.PENDING_DRIVER).count()
        )

        return Response(
            {
                "summary": {
                    "total_rides": ride_stats["total_rides"],
                    "completed": ride_stats["total_completed"],
                    "cancelled": ride_stats["total_cancelled"],
                    "in_progress": ride_stats["total_in_progress"],
                    "requested": ride_stats["total_requested"],
                    "assigned": ride_stats["total_assigned"],
                    "total_earnings": f"₦{ride_stats['total_earnings']:,}",
                    "total_drivers": ride_stats["total_drivers"],
                    "total_riders": ride_stats["total_riders"],
                    "pending_driver_applications": ride_stats["pending_applications"],
                }
            }
        )