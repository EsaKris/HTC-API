from rest_framework.permissions import BasePermission


class IsRider(BasePermission):
    """Allow access only to authenticated users with role='user'."""

    message = "Access restricted to riders only."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == "user"
        )


class IsDriver(BasePermission):
    """Allow access only to authenticated approved drivers."""

    message = "Access restricted to verified drivers only."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == "driver"
        )


class IsAdmin(BasePermission):
    """Allow access only to authenticated admins."""

    message = "Access restricted to admins only."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == "admin"
        )


class IsRiderOrAdmin(BasePermission):
    """Allow access to riders or admins."""

    message = "Access restricted to riders or admins."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role in ("user", "admin")
        )


class IsDriverOrAdmin(BasePermission):
    """Allow access to drivers or admins."""

    message = "Access restricted to drivers or admins."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role in ("driver", "admin")
        )