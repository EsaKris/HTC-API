import logging
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, generics, filters
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, JSONParser

from core.permissions import IsAdmin, IsDriver, IsRiderOrAdmin
from core.utils import (
    send_driver_acceptance_email,
    send_driver_rejection_email,
)
from .models import DriverApplication, Bike
from rides.models import Ride
from rides.serializers import RideSerializer

from .serializers import (
    DriverApplicationCreateSerializer,
    DriverApplicationListSerializer,
    DriverApplicationDetailSerializer,
    ApproveApplicationSerializer,
    RejectApplicationSerializer,
    BikeSerializer,
    BikeCreateSerializer,
    AssignBikeSerializer,
    DriverProfileSerializer,
)

logger = logging.getLogger(__name__)
User = get_user_model()


# ---------------------------------------------------------------------------
# Driver: Submit Application
# ---------------------------------------------------------------------------

class ApplyToDriverView(APIView):
    """
    POST /api/drivers/apply/
    Any authenticated user (rider) can submit a driver application.
    Automatically flips their role to pending_driver.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, JSONParser]

    def post(self, request):
        # Reject if already pending or approved
        if request.user.role == User.Role.DRIVER:
            return Response(
                {"detail": "You are already an approved driver."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if request.user.role == User.Role.PENDING_DRIVER:
            return Response(
                {"detail": "Your application is already under review."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if request.user.role == User.Role.ADMIN:
            return Response(
                {"detail": "Admin accounts cannot apply as drivers."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = DriverApplicationCreateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        application = serializer.save()

        return Response(
            {
                "message": "Application submitted successfully. You will be notified via email.",
                "application": DriverApplicationDetailSerializer(application).data,
            },
            status=status.HTTP_201_CREATED,
        )

    def get(self, request):
        """Let applicants check their own application status."""
        try:
            application = DriverApplication.objects.get(applicant=request.user)
        except DriverApplication.DoesNotExist:
            return Response(
                {"detail": "No driver application found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(DriverApplicationDetailSerializer(application).data)


# ---------------------------------------------------------------------------
# Admin: List All Applications
# ---------------------------------------------------------------------------

class AdminApplicationListView(generics.ListAPIView):
    """
    GET /api/drivers/applications/
    Admin-only. Supports filtering by status and searching by name/email.
    """

    permission_classes = [IsAdmin]
    serializer_class = DriverApplicationListSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status"]
    search_fields = [
        "applicant__full_name",
        "applicant__email",
        "applicant__phone_number",
    ]
    ordering_fields = ["created_at", "updated_at", "status"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return DriverApplication.objects.select_related(
            "applicant", "reviewed_by"
        ).all()


# ---------------------------------------------------------------------------
# Admin: Approve Application
# ---------------------------------------------------------------------------

class ApproveApplicationView(APIView):
    """
    POST /api/drivers/applications/<id>/approve/
    Admin approves a pending driver application.
    - Sets application status to accepted
    - Upgrades user role to driver
    - Sends acceptance + employment letter email
    """

    permission_classes = [IsAdmin]

    @transaction.atomic
    def post(self, request, pk):
        try:
            application = DriverApplication.objects.select_related("applicant").get(pk=pk)
        except DriverApplication.DoesNotExist:
            return Response(
                {"detail": "Application not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if application.status == DriverApplication.Status.ACCEPTED:
            return Response(
                {"detail": "Application has already been approved."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if application.status == DriverApplication.Status.REJECTED:
            return Response(
                {"detail": "Cannot approve a previously rejected application. "
                           "Ask the applicant to re-apply."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Update application
        application.status = DriverApplication.Status.ACCEPTED
        application.reviewed_by = request.user
        application.reviewed_at = timezone.now()
        application.save(
            update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"]
        )

        # Upgrade user role
        applicant = application.applicant
        applicant.role = User.Role.DRIVER
        applicant.save(update_fields=["role"])

        # Fire acceptance email (non-blocking — log failure, don't raise)
        email_sent = send_driver_acceptance_email(applicant)
        if not email_sent:
            logger.warning(
                f"Acceptance email failed for driver {applicant.id} ({applicant.email})"
            )

        return Response(
            {
                "message": f"Driver '{applicant.full_name}' has been approved. "
                           f"Acceptance email {'sent' if email_sent else 'could not be sent'}.",
                "application": DriverApplicationDetailSerializer(application).data,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Admin: Reject Application
# ---------------------------------------------------------------------------

class RejectApplicationView(APIView):
    """
    POST /api/drivers/applications/<id>/reject/
    Admin rejects a driver application with an optional reason.
    - Sets application status to rejected
    - Reverts user role to user (rider)
    - Sends rejection notification email
    """

    permission_classes = [IsAdmin]

    @transaction.atomic
    def post(self, request, pk):
        try:
            application = DriverApplication.objects.select_related("applicant").get(pk=pk)
        except DriverApplication.DoesNotExist:
            return Response(
                {"detail": "Application not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if application.status == DriverApplication.Status.REJECTED:
            return Response(
                {"detail": "Application has already been rejected."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = RejectApplicationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        application.status = DriverApplication.Status.REJECTED
        application.reviewed_by = request.user
        application.reviewed_at = timezone.now()
        application.rejection_reason = serializer.validated_data.get("rejection_reason", "")
        application.save(
            update_fields=[
                "status", "reviewed_by", "reviewed_at",
                "rejection_reason", "updated_at",
            ]
        )

        # Revert role back to rider
        applicant = application.applicant
        applicant.role = User.Role.USER
        applicant.save(update_fields=["role"])

        # Fire rejection email
        email_sent = send_driver_rejection_email(applicant)
        if not email_sent:
            logger.warning(
                f"Rejection email failed for applicant {applicant.id} ({applicant.email})"
            )

        return Response(
            {
                "message": f"Application for '{applicant.full_name}' has been rejected. "
                           f"Notification email {'sent' if email_sent else 'could not be sent'}.",
                "application": DriverApplicationDetailSerializer(application).data,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Admin: Application Detail
# ---------------------------------------------------------------------------

class AdminApplicationDetailView(APIView):
    """
    GET /api/drivers/applications/<id>/
    Admin views full details of a single application.
    """

    permission_classes = [IsAdmin]

    def get(self, request, pk):
        try:
            application = DriverApplication.objects.select_related(
                "applicant", "reviewed_by"
            ).get(pk=pk)
        except DriverApplication.DoesNotExist:
            return Response(
                {"detail": "Application not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(DriverApplicationDetailSerializer(application).data)


# ---------------------------------------------------------------------------
# Admin: Bikes — List + Create
# ---------------------------------------------------------------------------

class BikeListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/drivers/bikes/   → Admin lists all bikes
    POST /api/drivers/bikes/   → Admin adds a new bike to the fleet
    """

    permission_classes = [IsAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status", "bike_type"]
    search_fields = ["license_plate", "model", "driver__full_name"]
    ordering_fields = ["created_at", "status"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return Bike.objects.select_related("driver", "assigned_by").all()

    def get_serializer_class(self):
        if self.request.method == "POST":
            return BikeCreateSerializer
        return BikeSerializer

    def create(self, request, *args, **kwargs):
        serializer = BikeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bike = serializer.save()
        return Response(
            {
                "message": "Bike added to fleet successfully.",
                "bike": BikeSerializer(bike).data,
            },
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Admin: Assign / Unassign Bike to Driver
# ---------------------------------------------------------------------------

class AssignBikeView(APIView):
    """
    POST /api/drivers/bikes/<bike_id>/assign/
    Admin assigns a bike to an approved driver.
    Body: { "driver_id": "<uuid>" }
    """

    permission_classes = [IsAdmin]

    @transaction.atomic
    def post(self, request, bike_id):
        try:
            bike = Bike.objects.select_related("driver").get(pk=bike_id)
        except Bike.DoesNotExist:
            return Response(
                {"detail": "Bike not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if bike.driver is not None:
            return Response(
                {
                    "detail": (
                        f"Bike '{bike.license_plate}' is already assigned to "
                        f"'{bike.driver.full_name}'. Unassign it first."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = AssignBikeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        driver_id = serializer.validated_data["driver_id"]
        driver = User.objects.get(id=driver_id)

        bike.driver = driver
        bike.assigned_by = request.user
        bike.assigned_at = timezone.now()
        bike.status = Bike.BikeStatus.AVAILABLE
        bike.save(update_fields=["driver", "assigned_by", "assigned_at", "status", "updated_at"])

        return Response(
            {
                "message": f"Bike '{bike.license_plate}' assigned to '{driver.full_name}'.",
                "bike": BikeSerializer(bike).data,
            },
            status=status.HTTP_200_OK,
        )


class UnassignBikeView(APIView):
    """
    POST /api/drivers/bikes/<bike_id>/unassign/
    Admin removes a bike from a driver (e.g. for maintenance or reassignment).
    """

    permission_classes = [IsAdmin]

    @transaction.atomic
    def post(self, request, bike_id):
        try:
            bike = Bike.objects.select_related("driver").get(pk=bike_id)
        except Bike.DoesNotExist:
            return Response(
                {"detail": "Bike not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if bike.driver is None:
            return Response(
                {"detail": "Bike is not currently assigned to any driver."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        prev_driver = bike.driver.full_name
        bike.driver = None
        bike.assigned_by = None
        bike.assigned_at = None
        bike.save(update_fields=["driver", "assigned_by", "assigned_at", "updated_at"])

        return Response(
            {
                "message": f"Bike '{bike.license_plate}' unassigned from '{prev_driver}'.",
                "bike": BikeSerializer(bike).data,
            },
            status=status.HTTP_200_OK,
        )

class DriverRideDetailView(APIView):
    permission_classes = [IsDriver]

    def get(self, request, ride_id):
        ride = Ride.objects.get(pk=ride_id, driver=request.user)
        return Response(RideSerializer(ride).data)



# ---------------------------------------------------------------------------
# Admin: Update Bike Status
# ---------------------------------------------------------------------------

class BikeStatusUpdateView(APIView):
    """
    PATCH /api/drivers/bikes/<bike_id>/status/
    Admin updates the operational status of a bike.
    Body: { "status": "maintenance" }
    """

    permission_classes = [IsAdmin]

    def patch(self, request, bike_id):
        try:
            bike = Bike.objects.get(pk=bike_id)
        except Bike.DoesNotExist:
            return Response({"detail": "Bike not found."}, status=status.HTTP_404_NOT_FOUND)

        new_status = request.data.get("status")
        valid_statuses = [s.value for s in Bike.BikeStatus]
        if new_status not in valid_statuses:
            return Response(
                {"detail": f"Invalid status. Choices: {valid_statuses}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        bike.status = new_status
        bike.save(update_fields=["status", "updated_at"])
        return Response(
            {
                "message": f"Bike status updated to '{new_status}'.",
                "bike": BikeSerializer(bike).data,
            }
        )


# ---------------------------------------------------------------------------
# Driver: Own Profile
# ---------------------------------------------------------------------------

class DriverProfileView(APIView):
    """
    GET /api/drivers/me/
    Approved driver views their own profile including assigned bike.
    """

    permission_classes = [IsDriver]

    def get(self, request):
        serializer = DriverProfileSerializer(request.user)
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# Admin: List All Drivers
# ---------------------------------------------------------------------------

class AdminDriverListView(generics.ListAPIView):
    """
    GET /api/drivers/
    Admin lists all approved drivers with their assigned bikes.
    """

    permission_classes = [IsAdmin]
    serializer_class = DriverProfileSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["full_name", "email", "phone_number"]
    ordering_fields = ["full_name", "created_at"]
    ordering = ["full_name"]

    def get_queryset(self):
        return User.objects.filter(
            role=User.Role.DRIVER, is_active=True
        ).select_related("assigned_bike").all()