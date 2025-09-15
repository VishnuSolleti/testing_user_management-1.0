# visa/permissions.py

from rest_framework.permissions import BasePermission
from functools import wraps
from rest_framework.response import Response
from rest_framework import status
from Tara.settings.default import *
import requests

class GroupPermission(BasePermission):
    """
    Custom permission to check if the user belongs to a group with a specific permission.
    """
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        # Get the single user group (assuming one group per user)
        try:
            user_group = UserAffiliatedRole.objects.get(user=request.user)
        except UserAffiliatedRole.DoesNotExist:
            return Response({"error": "User is not part of any group."}, status=status.HTTP_403_FORBIDDEN)

        permission_needed = getattr(view, 'permission_required', None)  # Get permission(s) required for the view

        if permission_needed:
            # If it's a list of permissions, check for each one
            if isinstance(permission_needed, list):
                for perm in permission_needed:
                    # Check if the user group has the required permission
                    if user_group.custom_permissions.filter(action_name=perm).exists():
                        return True
            else:
                # If it's a single permission, check if the user group has it
                if user_group.custom_permissions.filter(action_name=permission_needed).exists():
                    return True

        return False


def has_group_permission(*permissions_needed):
    """
    Decorator to check if the user belongs to a group with specific permissions.
    Supports multiple permissions.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return Response({"error": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

            # Check if the user belongs to any group (get one group per user)
            try:
                user_group = UserAffiliatedRole.objects.get(user=request.user)
            except UserAffiliatedRole.DoesNotExist:
                return Response({"error": "User is not part of any group."}, status=status.HTTP_403_FORBIDDEN)

            # Check if the group has the required permissions
            permissions_found = set()

            for permission_needed in permissions_needed:
                if user_group.custom_permissions.filter(action_name=permission_needed).exists():
                    permissions_found.add(permission_needed)

            # Check if all required permissions are found
            if set(permissions_needed) == permissions_found:
                return view_func(request, *args, **kwargs)

            return Response(
                {"error": "You do not have the necessary permissions to access this resource."},
                status=status.HTTP_403_FORBIDDEN
            )

        return _wrapped_view
    return decorator


def authenticate():
    url = "https://api.sandbox.co.in/authenticate"
    payload = {}
    headers = {
        'x-api-key': SANDBOX_API_KEY,
        'x-api-secret': SANDBOX_API_SECRET,
        'x-api-version': '3.4.0'
    }
    response = requests.request("POST", url, headers=headers, data=payload)
    return response.json()['access_token']


def verify_pan(pan, name_of_business, dob_or_incorp_date):
    """
    Sends a request to verify the PAN details using the sandbox API.

    Args:
        pan (str): PAN number to verify.
        name_of_business (str): Name as per PAN.
        dob_or_incorp_date (str): Date of birth or incorporation date.
        access_token (str): Authorization token.

    Returns:
        dict: API response data.

    Raises:
        ValueError: If the response contains errors or missing fields.
    """
    if not pan or not name_of_business or not dob_or_incorp_date:
        raise ValueError("All input parameters (PAN, name, DOB/incorp date) are required.")

        access_token = authenticate()

    url = "https://api.sandbox.co.in/kyc/pan/verify"

    payload = {
        "@entity": "in.co.sandbox.kyc.pan_verification.request",
        "pan": pan,
        "name_as_per_pan": name_of_business,
        "date_of_birth": dob_or_incorp_date,
        "consent": "Y",
        "reason": "For Onboarding"
    }

    headers = {
        "accept": "application/json",
        "authorization": access_token,
        "x-api-key": SANDBOX_API_KEY,
        "x-accept-cache": "true",
        "x-api-version": "1.0",
        "content-type": "application/json"
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response_data = response.json()
        pan_verification_data = response_data
        category = None
        if pan_verification_data['code'] == 200 and pan_verification_data['data']['status'] == 'VALID':
            category = pan_verification_data['data']['category'] \
                if pan_verification_data['data']['category'] == 'Individual' else None
        elif pan_verification_data['code'] == 200 and pan_verification_data['data']['status'] == 'NOT-VALID':

            raise ValueError("Invalid pan number")
        else:
            raise ValueError("Invalid response from PAN verification API.")

        if 'code' not in response_data or 'data' not in response_data:
            message = pan_verification_data['message'] if pan_verification_data['message'] else "Internal Server Error"
            raise ValueError(message)

        return category

    except requests.exceptions.RequestException as e:
        raise ValueError(f"Request error: {str(e)}")

