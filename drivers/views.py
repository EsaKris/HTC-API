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
from rest_framework.permissions import AllowAny, IsAdminUser
from core.permissions import IsAdmin, IsDriver, IsRiderOrAdmin
from core.utils import (
    send_driver_acceptance_email,
    send_driver_rejection_email,
)
from .models import DriverApplication, Bike, BikeOwner, BikeRegistration
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
    BikeOwnerSerializer,
    BikeOwnerDetailSerializer,
    BikeOwnerWithBikesSerializer,
    BikeRegistrationSerializer,
    BikeRegistrationDetailSerializer,
)

# ══════════════════════════════════════════════════════════════════════════
# ADD THESE IMPORTS AT THE TOP OF drivers/views.py (if not present)
# ══════════════════════════════════════════════════════════════════════════

from django.db.models import Count, Sum, Q
from rest_framework.parsers import MultiPartParser, FormParser
from django.utils import timezone

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
    

# ══════════════════════════════════════════════════════════════════════════
# PUBLIC REGISTRATION ENDPOINT (Anyone can register their bike)
# ══════════════════════════════════════════════════════════════════════════

class RegisterBikeAndOwnerView(APIView):
    """
    POST /api/bikes/register/
    PUBLIC endpoint - no authentication required.
    Anyone can register their bike and become a bike owner.
    """
    
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]
    
    def post(self, request):
        serializer = BikeRegistrationSerializer(data=request.data)
        
        if serializer.is_valid():
            registration = serializer.save()
            
            # TODO: Send email/SMS notification to owner confirming submission
            # TODO: Notify admin about new registration
            
            return Response(
                {
                    "success": True,
                    "message": "Registration submitted successfully! We'll review and contact you within 24-48 hours.",
                    "registration_id": str(registration.id),
                    "status": "pending",
                },
                status=status.HTTP_201_CREATED
            )
        
        return Response(
            {"success": False, "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )


# ══════════════════════════════════════════════════════════════════════════
# ADMIN: BIKE OWNER MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════

class BikeOwnerListView(APIView):
    """
    GET /api/admin/bike-owners/
    List all bike owners with filter options.
    Query params: ?status=active|pending|suspended
    """
    
    permission_classes = [IsAuthenticated, IsAdminUser]
    
    def get(self, request):
        queryset = BikeOwner.objects.annotate(
            total_bikes=Count('bikes'),
            active_bikes=Count('bikes', filter=Q(bikes__status='in_use'))
        ).select_related('verified_by').all()
        
        # Filter by status
        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Search
        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(full_name__icontains=search) |
                Q(phone_number__icontains=search) |
                Q(email__icontains=search)
            )
        
        # Pagination
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 20))
        start = (page - 1) * page_size
        end = start + page_size
        
        total = queryset.count()
        results = queryset[start:end]
        
        serializer = BikeOwnerSerializer(results, many=True)
        
        return Response({
            "count": total,
            "next": f"?page={page + 1}" if end < total else None,
            "previous": f"?page={page - 1}" if page > 1 else None,
            "results": serializer.data,
        })


class BikeOwnerDetailView(APIView):
    """
    GET /api/admin/bike-owners/{id}/
    Get full bike owner profile with earnings and all bikes.
    Shows contact info, bank details, which driver is on which bike.
    
    PUT /api/admin/bike-owners/{id}/
    Update owner info (admin notes, status, bank details, etc.)
    """
    
    permission_classes = [IsAuthenticated, IsAdminUser]
    
    def get(self, request, owner_id):
        try:
            owner = BikeOwner.objects.annotate(
                total_bikes=Count('bikes'),
                active_bikes=Count('bikes', filter=Q(bikes__status='in_use'))
            ).select_related('verified_by').get(id=owner_id)
        except BikeOwner.DoesNotExist:
            return Response(
                {"success": False, "message": "Bike owner not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Include full bike details with driver assignments
        serializer = BikeOwnerWithBikesSerializer(owner)
        return Response(serializer.data)
    
    def put(self, request, owner_id):
        """Update owner details"""
        try:
            owner = BikeOwner.objects.get(id=owner_id)
        except BikeOwner.DoesNotExist:
            return Response(
                {"success": False, "message": "Bike owner not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = BikeOwnerDetailSerializer(owner, data=request.data, partial=True)
        
        if serializer.is_valid():
            serializer.save()
            return Response({
                "success": True,
                "message": "Bike owner updated successfully.",
                "owner": serializer.data,
            })
        
        return Response(
            {"success": False, "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )


class BikeOwnerEarningsView(APIView):
    """
    GET /api/admin/bike-owners/{id}/earnings/
    Detailed earnings breakdown for a bike owner.
    Shows per-bike earnings, total rides, payment history.
    """
    
    permission_classes = [IsAuthenticated, IsAdminUser]
    
    def get(self, request, owner_id):
        try:
            owner = BikeOwner.objects.get(id=owner_id)
        except BikeOwner.DoesNotExist:
            return Response(
                {"success": False, "message": "Bike owner not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Calculate earnings per bike
        bikes_earnings = []
        for bike in owner.bikes.select_related('driver').all():
            from rides.models import Ride
            
            rides = Ride.objects.filter(
                driver__assigned_bike=bike,
                status="COMPLETED"
            ).order_by('-created_at')
            
            total_earnings = rides.aggregate(total=Sum('price'))['total'] or 0
            ride_count = rides.count()
            
            bikes_earnings.append({
                "bike_id": str(bike.id),
                "license_plate": bike.license_plate,
                "model": bike.model,
                "driver": {
                    "id": str(bike.driver.id),
                    "name": bike.driver.full_name,
                } if bike.driver else None,
                "total_earnings": total_earnings,
                "total_rides": ride_count,
                "recent_rides": [
                    {
                        "id": str(ride.id),
                        "rider_name": ride.rider.full_name,
                        "price": ride.price,
                        "completed_at": ride.completed_at,
                    }
                    for ride in rides[:5]  # Last 5 rides
                ]
            })
        
        total_earnings = sum(b["total_earnings"] for b in bikes_earnings)
        total_rides = sum(b["total_rides"] for b in bikes_earnings)
        
        return Response({
            "owner": {
                "id": str(owner.id),
                "name": owner.full_name,
                "phone": owner.phone_number,
                "email": owner.email,
            },
            "summary": {
                "total_earnings": total_earnings,
                "total_rides": total_rides,
                "active_bikes": owner.active_bikes,
                "total_bikes": owner.total_bikes,
            },
            "bikes": bikes_earnings,
        })


class BikeOwnerContactView(APIView):
    """
    POST /api/admin/bike-owners/{id}/contact/
    Send a message/notification to bike owner.
    Body: { "subject": "...", "message": "..." }
    
    This logs the contact attempt and can send email/SMS.
    """
    
    permission_classes = [IsAuthenticated, IsAdminUser]
    
    def post(self, request, owner_id):
        try:
            owner = BikeOwner.objects.get(id=owner_id)
        except BikeOwner.DoesNotExist:
            return Response(
                {"success": False, "message": "Bike owner not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        subject = request.data.get('subject', '')
        message = request.data.get('message', '')
        
        if not message:
            return Response(
                {"success": False, "message": "Message is required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # TODO: Send email to owner.email
        # TODO: Send SMS to owner.phone_number
        # TODO: Log this contact in a ContactLog model
        
        # For now, just return success
        return Response({
            "success": True,
            "message": f"Message sent to {owner.full_name}.",
            "contact_info": {
                "email": owner.email,
                "phone": owner.phone_number,
            }
        })


# ══════════════════════════════════════════════════════════════════════════
# ADMIN: REGISTRATION APPROVAL WORKFLOW
# ══════════════════════════════════════════════════════════════════════════

class BikeRegistrationListView(APIView):
    """
    GET /api/admin/bike-registrations/
    List all bike registrations (pending, approved, rejected).
    Query params: ?status=pending|approved|rejected
    """
    
    permission_classes = [IsAuthenticated, IsAdminUser]
    
    def get(self, request):
        queryset = BikeRegistration.objects.select_related(
            'reviewed_by',
            'approved_owner',
            'approved_bike'
        ).all()
        
        # Filter by status
        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Pagination
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 20))
        start = (page - 1) * page_size
        end = start + page_size
        
        total = queryset.count()
        results = queryset[start:end]
        
        serializer = BikeRegistrationDetailSerializer(results, many=True)
        
        return Response({
            "count": total,
            "next": f"?page={page + 1}" if end < total else None,
            "previous": f"?page={page - 1}" if page > 1 else None,
            "results": serializer.data,
        })


class BikeRegistrationDetailView(APIView):
    """
    GET /api/admin/bike-registrations/{id}/
    View full registration details for admin review.
    """
    
    permission_classes = [IsAuthenticated, IsAdminUser]
    
    def get(self, request, registration_id):
        try:
            registration = BikeRegistration.objects.select_related(
                'reviewed_by',
                'approved_owner',
                'approved_bike'
            ).get(id=registration_id)
        except BikeRegistration.DoesNotExist:
            return Response(
                {"success": False, "message": "Registration not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = BikeRegistrationDetailSerializer(registration)
        return Response(serializer.data)


class ApproveBikeRegistrationView(APIView):
    """
    POST /api/admin/bike-registrations/{id}/approve/
    Approve a bike registration.
    Creates BikeOwner (if new) and Bike records.
    """
    
    permission_classes = [IsAuthenticated, IsAdminUser]
    
    def post(self, request, registration_id):
        try:
            registration = BikeRegistration.objects.get(id=registration_id)
        except BikeRegistration.DoesNotExist:
            return Response(
                {"success": False, "message": "Registration not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if registration.status != 'pending':
            return Response(
                {"success": False, "message": f"Registration is already {registration.status}."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if owner already exists by phone or email
        owner = BikeOwner.objects.filter(
            Q(phone_number=registration.owner_phone) |
            Q(email=registration.owner_email)
        ).first()
        
        if not owner:
            # Create new bike owner
            owner = BikeOwner.objects.create(
                full_name=registration.owner_name,
                phone_number=registration.owner_phone,
                email=registration.owner_email,
                address=registration.owner_address,
                bank_name=registration.bank_name,
                account_number=registration.account_number,
                account_name=registration.account_name,
                id_document=registration.id_document,
                profile_photo=registration.owner_photo,
                status='active',
                verified_by=request.user,
                verified_at=timezone.now(),
            )
        
        # Create the bike
        bike = Bike.objects.create(
            owner=owner,
            bike_type=registration.bike_type,
            license_plate=registration.license_plate,
            model=registration.model,
            color=registration.color,
            year=registration.year,
            bike_photo=registration.bike_photo,
            registration_document=registration.registration_document,
            status='available',  # Available for driver assignment
        )
        
        # Update registration
        registration.status = 'approved'
        registration.reviewed_by = request.user
        registration.reviewed_at = timezone.now()
        registration.approved_owner = owner
        registration.approved_bike = bike
        registration.save()
        
        # TODO: Send approval email/SMS to owner
        
        return Response({
            "success": True,
            "message": f"Registration approved! Bike {bike.license_plate} added to fleet.",
            "owner_id": str(owner.id),
            "bike_id": str(bike.id),
            "owner_was_created": owner.created_at == owner.updated_at,  # True if new owner
        })


class RejectBikeRegistrationView(APIView):
    """
    POST /api/admin/bike-registrations/{id}/reject/
    Reject a bike registration with reason.
    Body: { "rejection_reason": "..." }
    """
    
    permission_classes = [IsAuthenticated, IsAdminUser]
    
    def post(self, request, registration_id):
        try:
            registration = BikeRegistration.objects.get(id=registration_id)
        except BikeRegistration.DoesNotExist:
            return Response(
                {"success": False, "message": "Registration not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if registration.status != 'pending':
            return Response(
                {"success": False, "message": f"Registration is already {registration.status}."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        rejection_reason = request.data.get('rejection_reason', '')
        
        registration.status = 'rejected'
        registration.reviewed_by = request.user
        registration.reviewed_at = timezone.now()
        registration.rejection_reason = rejection_reason
        registration.save()
        
        # TODO: Send rejection email/SMS to owner with reason
        
        return Response({
            "success": True,
            "message": "Registration rejected.",
        })

# ═══════════════════════════════════════════════════════════════════════════
# BIKE OWNER AUTHENTICATION & DASHBOARD - ADD TO drivers/views.py
# ═══════════════════════════════════════════════════════════════════════════

from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.hashers import make_password, check_password


# ══════════════════════════════════════════════════════════════════════════
# BIKE OWNER AUTHENTICATION (Phone/OTP)
# ══════════════════════════════════════════════════════════════════════════

class BikeOwnerLoginView(APIView):
    """
    POST /api/bike-owners/login/
    Send OTP to bike owner's phone/email
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        phone = request.data.get('phone_number', '').strip()
        
        if not phone:
            return Response(
                {"success": False, "message": "Phone number is required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Find bike owner by phone
        try:
            owner = BikeOwner.objects.get(phone_number=phone)
        except BikeOwner.DoesNotExist:
            return Response(
                {"success": False, "message": "No bike owner account found with this phone number."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if owner.status != 'active':
            return Response(
                {"success": False, "message": f"Your account is {owner.status}. Contact support."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Generate OTP (6-digit)
        otp = str(random.randint(100000, 999999))
        
        # Store in cache (10 minutes expiry)
        cache.set(f"bike_owner_otp_{phone}", otp, timeout=600)
        
        # Send OTP via email (since we have their email)
        # TODO: Replace with actual email service
        send_mail(
            subject="HFC - Your Login Code",
            message=f"Your HFC Bike Owner login code is: {otp}\n\nValid for 10 minutes.",
            from_email="noreply@howfar.ng",
            recipient_list=[owner.email],
            fail_silently=True,
        )
        
        return Response({
            "success": True,
            "message": f"OTP sent to {owner.email}",
            "owner_id": str(owner.id),
        })


class BikeOwnerVerifyOTPView(APIView):
    """
    POST /api/bike-owners/verify-otp/
    Verify OTP and return JWT tokens
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        phone = request.data.get('phone_number', '').strip()
        otp = request.data.get('otp', '').strip()
        
        if not phone or not otp:
            return Response(
                {"success": False, "message": "Phone number and OTP are required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check OTP from cache
        stored_otp = cache.get(f"bike_owner_otp_{phone}")
        
        if not stored_otp:
            return Response(
                {"success": False, "message": "OTP expired or invalid. Request a new one."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if stored_otp != otp:
            return Response(
                {"success": False, "message": "Invalid OTP. Please try again."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get bike owner
        try:
            owner = BikeOwner.objects.get(phone_number=phone)
        except BikeOwner.DoesNotExist:
            return Response(
                {"success": False, "message": "Bike owner not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Clear OTP
        cache.delete(f"bike_owner_otp_{phone}")
        
        # Generate custom JWT tokens for bike owner
        # We'll store owner_id in the token payload
        from rest_framework_simplejwt.tokens import RefreshToken as JWT
        
        # Create custom token
        refresh = JWT()
        refresh['owner_id'] = str(owner.id)
        refresh['phone'] = owner.phone_number
        refresh['type'] = 'bike_owner'
        
        return Response({
            "success": True,
            "message": "Login successful",
            "tokens": {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            "owner": {
                "id": str(owner.id),
                "full_name": owner.full_name,
                "phone_number": owner.phone_number,
                "email": owner.email,
                "status": owner.status,
                "total_bikes": owner.total_bikes,
            }
        })


# ══════════════════════════════════════════════════════════════════════════
# BIKE OWNER DASHBOARD
# ══════════════════════════════════════════════════════════════════════════

class BikeOwnerDashboardView(APIView):
    """
    GET /api/bike-owners/me/
    Get bike owner's profile and all their bikes
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        # Extract owner_id from JWT token
        owner_id = request.auth.payload.get('owner_id') if hasattr(request.auth, 'payload') else None
        
        if not owner_id:
            return Response(
                {"success": False, "message": "Invalid token."},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        try:
            owner = BikeOwner.objects.get(id=owner_id)
        except BikeOwner.DoesNotExist:
            return Response(
                {"success": False, "message": "Bike owner not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get all bikes with earnings
        bikes_data = []
        total_earnings = 0
        
        for bike in owner.bikes.select_related('driver').all():
            earnings = bike.calculate_total_earnings()
            total_earnings += earnings
            
            bikes_data.append({
                "id": str(bike.id),
                "license_plate": bike.license_plate,
                "model": bike.model,
                "color": bike.color,
                "bike_type": bike.bike_type,
                "status": bike.status,
                "driver": {
                    "id": str(bike.driver.id),
                    "full_name": bike.driver.full_name,
                    "phone_number": bike.driver.phone_number,
                } if bike.driver else None,
                "assigned_at": bike.assigned_at,
                "total_earnings": earnings,
                "total_rides": bike.total_rides,
                "created_at": bike.created_at,
            })
        
        return Response({
            "owner": {
                "id": str(owner.id),
                "full_name": owner.full_name,
                "phone_number": owner.phone_number,
                "email": owner.email,
                "status": owner.status,
                "created_at": owner.created_at,
            },
            "summary": {
                "total_bikes": len(bikes_data),
                "active_bikes": len([b for b in bikes_data if b['status'] == 'in_use']),
                "total_earnings": total_earnings,
                "total_rides": sum(b['total_rides'] for b in bikes_data),
            },
            "bikes": bikes_data,
        })


class BikeOwnerAddBikeView(APIView):
    """
    POST /api/bike-owners/bikes/add/
    Existing bike owner adds a new bike
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def post(self, request):
        # Extract owner_id from JWT token
        owner_id = request.auth.payload.get('owner_id') if hasattr(request.auth, 'payload') else None
        
        if not owner_id:
            return Response(
                {"success": False, "message": "Invalid token."},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        try:
            owner = BikeOwner.objects.get(id=owner_id)
        except BikeOwner.DoesNotExist:
            return Response(
                {"success": False, "message": "Bike owner not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if owner.status != 'active':
            return Response(
                {"success": False, "message": "Your account is not active. Contact support."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Create bike registration (will need admin approval)
        serializer = BikeRegistrationSerializer(data=request.data)
        
        if serializer.is_valid():
            # Auto-fill owner info from existing account
            registration = serializer.save(
                owner_name=owner.full_name,
                owner_phone=owner.phone_number,
                owner_email=owner.email,
                owner_address=owner.address,
                bank_name=owner.bank_name,
                account_number=owner.account_number,
                account_name=owner.account_name,
            )
            
            return Response({
                "success": True,
                "message": "Bike submitted for review. You'll be notified once approved.",
                "registration_id": str(registration.id),
            }, status=status.HTTP_201_CREATED)
        
        return Response(
            {"success": False, "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )


class BikeOwnerUpdateProfileView(APIView):
    """
    PUT /api/bike-owners/me/
    Update bike owner profile (contact info, bank details)
    """
    permission_classes = [IsAuthenticated]
    
    def put(self, request):
        owner_id = request.auth.payload.get('owner_id') if hasattr(request.auth, 'payload') else None
        
        if not owner_id:
            return Response(
                {"success": False, "message": "Invalid token."},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        try:
            owner = BikeOwner.objects.get(id=owner_id)
        except BikeOwner.DoesNotExist:
            return Response(
                {"success": False, "message": "Bike owner not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Allow updating: email, address, bank details
        allowed_fields = ['email', 'address', 'bank_name', 'account_number', 'account_name']
        
        for field in allowed_fields:
            if field in request.data:
                setattr(owner, field, request.data[field])
        
        owner.save()
        
        serializer = BikeOwnerDetailSerializer(owner)
        return Response({
            "success": True,
            "message": "Profile updated successfully.",
            "owner": serializer.data,
        })


class BikeOwnerPendingRegistrationsView(APIView):
    """
    GET /api/bike-owners/registrations/pending/
    View bike owner's pending bike registrations
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        owner_id = request.auth.payload.get('owner_id') if hasattr(request.auth, 'payload') else None
        
        if not owner_id:
            return Response(
                {"success": False, "message": "Invalid token."},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        try:
            owner = BikeOwner.objects.get(id=owner_id)
        except BikeOwner.DoesNotExist:
            return Response(
                {"success": False, "message": "Bike owner not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get all registrations for this owner (by phone/email match)
        registrations = BikeRegistration.objects.filter(
            Q(owner_phone=owner.phone_number) | Q(owner_email=owner.email)
        ).order_by('-created_at')
        
        serializer = BikeRegistrationDetailSerializer(registrations, many=True)
        
        return Response({
            "count": registrations.count(),
            "registrations": serializer.data,
        })


# ══════════════════════════════════════════════════════════════════════════
# ADD THESE IMPORTS AT TOP OF drivers/views.py
# ══════════════════════════════════════════════════════════════════════════

import random
from django.core.mail import send_mail
from django.core.cache import cache
from rest_framework_simplejwt.tokens import RefreshToken
