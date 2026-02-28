import logging
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Sum, Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, generics, filters
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny

from core.permissions import IsRider, IsDriver, IsAdmin, IsRiderOrAdmin
from .models import Ride, RideStatusLog, DriverLocation
from .serializers import (
    RideSerializer,
    RideRequestSerializer,
    RideCancelSerializer,
    RideAssignSerializer,
    RideStatusUpdateSerializer,
    RideAnalyticsSerializer,
)
from .map_utils import (
    get_route, autocomplete_address, reverse_geocode, find_nearby_drivers
)

import secrets

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
    
class UpdateDriverLocationView(APIView):
    """Driver sends location updates during ride"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request, ride_id):
        try:
            ride = Ride.objects.get(id=ride_id, driver=request.user)
        except Ride.DoesNotExist:
            return Response(
                {"success": False, "message": "Ride not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        latitude = request.data.get('latitude')
        longitude = request.data.get('longitude')
        
        if not latitude or not longitude:
            return Response(
                {"success": False, "message": "Location required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update ride location
        from django.utils import timezone
        ride.current_driver_lat = latitude
        ride.current_driver_lng = longitude
        ride.driver_location_updated_at = timezone.now()
        ride.save()
        
        # Also update driver's general location
        DriverLocation.objects.update_or_create(
            driver=request.user,
            defaults={
                'latitude': latitude,
                'longitude': longitude,
                'heading': request.data.get('heading'),
                'speed': request.data.get('speed'),
                'accuracy': request.data.get('accuracy'),
            }
        )
        
        return Response({"success": True})

class GetRouteView(APIView):
    """Get route between two points using FREE OSRM"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        origin_lat = request.data.get('origin_lat')
        origin_lng = request.data.get('origin_lng')
        dest_lat = request.data.get('dest_lat')
        dest_lng = request.data.get('dest_lng')
        
        if not all([origin_lat, origin_lng, dest_lat, dest_lng]):
            return Response(
                {"success": False, "message": "Origin and destination required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        route = get_route((origin_lat, origin_lng), (dest_lat, dest_lng))
        
        if not route:
            return Response(
                {"success": False, "message": "Could not find route"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        return Response({"success": True, "route": route})

class AddressAutocompleteView(APIView):
    """Address suggestions using FREE Photon service"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        input_text = request.data.get('input')
        
        if not input_text or len(input_text) < 3:
            return Response({
                "success": True,
                "suggestions": []
            })
        
        location = None
        if request.data.get('latitude') and request.data.get('longitude'):
            location = (request.data['latitude'], request.data['longitude'])
        
        suggestions = autocomplete_address(input_text, location)
        
        return Response({
            "success": True,
            "suggestions": suggestions
        })

class ReverseGeocodeView(APIView):
    """Convert coordinates to address using FREE Nominatim"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        latitude = request.data.get('latitude')
        longitude = request.data.get('longitude')
        
        if not latitude or not longitude:
            return Response(
                {"success": False, "message": "Coordinates required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        address = reverse_geocode(latitude, longitude)
        
        return Response({
            "success": True,
            "address": address,
            "latitude": latitude,
            "longitude": longitude,
        })

class NearbyDriversView(APIView):
    """Find available drivers near location"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        latitude = request.data.get('latitude')
        longitude = request.data.get('longitude')
        radius = request.data.get('radius_km', 5.0)
        
        if not latitude or not longitude:
            return Response(
                {"success": False, "message": "Location required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        drivers = find_nearby_drivers(latitude, longitude, radius)
        
        return Response({
            "success": True,
            "drivers": drivers,
            "count": len(drivers)
        })

class ShareTripView(APIView):
    """Generate shareable link for trip"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request, ride_id):
        try:
            ride = Ride.objects.get(id=ride_id, rider=request.user)
        except Ride.DoesNotExist:
            return Response(
                {"success": False, "message": "Ride not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if not ride.share_token:
            ride.share_token = secrets.token_urlsafe(16)
            ride.share_enabled = True
            ride.save()
        
        share_url = f"https://howfar.ng/shared-ride/{ride.share_token}"
        
        return Response({
            "success": True,
            "share_url": share_url,
            "share_token": ride.share_token
        })

class SharedRideView(APIView):
    """Public view of shared ride"""
    permission_classes = [AllowAny]
    
    def get(self, request, token):
        try:
            ride = Ride.objects.select_related('driver', 'rider').get(
                share_token=token,
                share_enabled=True
            )
        except Ride.DoesNotExist:
            return Response(
                {"success": False, "message": "Shared ride not found or expired"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        return Response({
            "success": True,
            "ride": {
                "id": str(ride.id),
                "status": ride.status,
                "rider_name": ride.rider.full_name,
                "driver_name": ride.driver.full_name if ride.driver else None,
                "pickup_address": ride.pickup_address,
                "dropoff_address": ride.dropoff_address,
                "current_driver_location": {
                    "latitude": ride.current_driver_lat,
                    "longitude": ride.current_driver_lng,
                } if ride.current_driver_lat else None,
                "route_geometry": ride.route_geometry,
                "estimated_arrival": ride.estimated_arrival_time,
                "created_at": ride.created_at,
            }
        })

class DriverLocationsView(APIView):
    """Get all active driver locations for fleet map (Admin only)"""
    permission_classes = [IsAuthenticated]  # Add IsAdminUser in production
    
    def get(self, request):
        locations = DriverLocation.objects.filter(
            driver__role='driver'
        ).select_related('driver')
        
        drivers_data = []
        for loc in locations:
            driver_data = {
                'driver_id': str(loc.driver.id),
                'driver_name': loc.driver.full_name,
                'latitude': loc.latitude,
                'longitude': loc.longitude,
                'heading': loc.heading,
                'speed': loc.speed,
                'is_active': loc.is_active,
            }
            
            # Check if driver has an active ride
            active_ride = Ride.objects.filter(
                driver=loc.driver,
                status__in=['accepted', 'started']
            ).select_related('rider').first()
            
            if active_ride:
                driver_data['current_ride'] = {
                    'id': str(active_ride.id),
                    'rider_name': active_ride.rider.full_name,
                    'pickup_address': active_ride.pickup_address,
                    'dropoff_address': active_ride.dropoff_address,
                    'status': active_ride.status,
                }
            
            drivers_data.append(driver_data)
        
        return Response({
            'success': True,
            'drivers': drivers_data,
            'count': len(drivers_data),
        })
