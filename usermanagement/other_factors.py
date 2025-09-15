from django.shortcuts import render
from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import api_view
from .serializers import (UsersKYCSerializer, UserActivationSerializer,
                          FirmKYCSerializer)
from django.db.models import Count
from .serializers import *
from password_generator import PasswordGenerator
from rest_framework.views import APIView
import traceback
from django.db import DatabaseError, IntegrityError
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.core.mail import send_mail
from django.contrib.auth import get_user_model
from django.conf import settings
from .models import *
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.tokens import RefreshToken
import logging
import random
import requests
import json
from Tara.settings.default import *
import boto3
from botocore.exceptions import ClientError, BotoCoreError
from .rate_limit_decorator import rate_limit
from datetime import datetime, timezone
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotFound
from django.contrib.auth.password_validation import validate_password
from django.http import Http404
from .permissions import GroupPermission, has_group_permission
from django.contrib.auth.decorators import permission_required
from django.db.models.functions import Coalesce
from django.db.models import Count, F, Value
from collections import defaultdict
from django.core.exceptions import ObjectDoesNotExist
from django.http import JsonResponse
from urllib.parse import urlparse, unquote
from django.db.models.functions import TruncDate
from .usage_limits import *
# Create loggers for general and error logs
logger = logging.getLogger(__name__)



class Constants:
    SMS_API_POST_URL = 'https://www.fast2sms.com/dev/bulkV2'


def auto_generate_password():
    pwo = PasswordGenerator()
    return pwo.shuffle_password('abcdefghijklmnopqrstuvwxyz', 8)  # Generates an 8-character password


def generate_otp():
    return random.randint(100000, 999999)


def send_otp_helper(phone_number, otp):
    try:
        payload = f"variables_values={otp}&route=otp&numbers={phone_number}"
        headers = {
            'authorization': "8Vt5jZpbP2KwMDOLlIeSGN9g7qn6kBi4FHuy1dvhoYEaARJQfsHlpLvoyPKxfN2jIbSkrXG3CdhRVQ1E",
            'Content-Type': "application/x-www-form-urlencoded",
            'Cache-Control': "no-cache",
        }
        response = requests.request("POST", Constants.SMS_API_POST_URL, data=payload, headers=headers)
        returned_msg = json.loads(response.text)
        return returned_msg
    except Exception as e:
        logger.error(e, exc_info=1)
        raise ValueError(f'Request failed: {str(e)}')



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


@permission_classes([IsAuthenticated])
@api_view(['POST'])
def visa_users_creation(request):
    """
    Handles the creation of a visa user by ServiceProvider_Admin.
    Creates a user first and associates visa application details with them.
    """
    if request.method != 'POST':
        return Response({"error": "Invalid HTTP method."}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    service_provider_admin_roles = [
        'ServiceProvider_Owner', 'ServiceProvider_Admin',
        'Tara_SuperAdmin', 'Tara_Admin'
    ]

    if request.user_role.role_type not in service_provider_admin_roles:
        return Response(
            {'error_message': 'Unauthorized Access. Only ServiceProviderAdmin can create visa users.', 'status_cd': 1},
            status=status.HTTP_401_UNAUTHORIZED
        )

    try:
        # Step 1: Create the user
        email = request.data.get('email', '').lower()
        mobile_number = request.data.get('mobile_number', '')
        if not email and not mobile_number:
            return Response(
                {"error": "Either email or mobile number must be provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_data = {
            'email': email,
            'password': auto_generate_password(),
            'created_by': request.user.id,
            'status': 'active',
            'is_active': True,
            'is_super_admin': False
        }

        with transaction.atomic():
            # Validate and save user
            user_serializer = UserSerializer(data=user_data)
            if user_serializer.is_valid():
                user_instance = user_serializer.save()
                
                # Create UserProfile for personal information
                from .models import UserProfile
                UserProfile.objects.create(
                    user=user_instance,
                    first_name=request.data.get('first_name'),
                    last_name=request.data.get('last_name'),
                    mobile_number=mobile_number
                )
            else:
                return Response(user_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # Step 2: Create visa application details
            visa_applications_data = {
                'passport_number': request.data.get('passport_number', ''),
                'purpose': request.data.get('purpose'),
                'visa_type': request.data.get('visa_type'),
                'destination_country': request.data.get('destination_country'),
                'user': user_instance.id,
            }

            visa_serializer = VisaApplicationsSerializer(data=visa_applications_data)
            if visa_serializer.is_valid():
                visa_serializer.save()
            else:
                return Response(visa_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # Send email or OTP for the created user
            if email:
                send_user_email(email, user_data['password'])
            elif mobile_number:
                if not send_user_otp(mobile_number):
                    raise Exception("Failed to send OTP to mobile number.")

        return Response(
            {"message": "Visa user registered successfully."},
            status=status.HTTP_201_CREATED,
        )
    except IntegrityError as e:
        logger.error(f"Integrity error: {str(e)}")
        return Response(
            {"error": "User with this email or mobile already exists."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return Response(
            {"error": "An unexpected error occurred.", "details": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@permission_classes([IsAuthenticated])
@api_view(['POST'])
def serviceproviders_user_creation(request):
    """
    Handles the creation of a visa user by ServiceProvider_Admin.
    Creates a user first and associates visa application details with them.
    """
    if request.method != 'POST':
        return Response({"error": "Invalid HTTP method."}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    service_provider_admin_roles = [
        'ServiceProvider_Owner', 'ServiceProvider_Admin',
        'Tara_SuperAdmin', 'Tara_Admin'
    ]

    if request.user_role.role_type not in service_provider_admin_roles:
        return Response(
            {'error_message': 'Unauthorized Access. Only ServiceProviderAdmin can create visa users.', 'status_cd': 1},
            status=status.HTTP_401_UNAUTHORIZED
        )

    try:
        # Step 1: Create the user
        email = request.data.get('email', '').lower()
        mobile_number = request.data.get('mobile_number', '')
        user_name = request.data.get('user_name')
        group = request.data.pop('group', None)
        custom_permissions = request.data.pop('custom_permissions', [])
        if not email and not mobile_number:
            return Response(
                {"error": "Either email or mobile number must be provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_data = {
            'email': email,
            'password': auto_generate_password(),
            'created_by': request.data.get('created_by'),
            'status': 'active',
            'is_active': True,
            'is_super_admin': False
        }

        with transaction.atomic():
            # Validate and save user
            user_serializer = UserSerializer(data=user_data)
            if user_serializer.is_valid():
                user_instance = user_serializer.save()
                
                # Create UserProfile for personal information
                from .models import UserProfile
                UserProfile.objects.create(
                    user=user_instance,
                    first_name=request.data.get('first_name'),
                    last_name=request.data.get('last_name'),
                    mobile_number=mobile_number
                )
                
                user_data = user_serializer.data
                user_data['group'] = group
                user_data['custom_permissions'] = custom_permissions
            else:
                return Response(user_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # Step 2: Create visa application details
            visa_applications_data = {
                'passport_number': request.data.get('passport_number', ''),
                'purpose': request.data.get('purpose'),
                'visa_type': request.data.get('visa_type'),
                'destination_country': request.data.get('destination_country'),
                'user': user_instance.id,
            }

            visa_serializer = VisaApplicationsSerializer(data=visa_applications_data)
            if visa_serializer.is_valid():
                visa_serializer.save()
            else:
                return Response(visa_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # Send email or OTP for the created user
            if email:
                send_user_email(email, user_data['password'])
            elif mobile_number:
                if not send_user_otp(mobile_number):
                    raise Exception("Failed to send OTP to mobile number.")

        return Response(
            {"message": "Visa user registered successfully."},
            status=status.HTTP_201_CREATED,
        )
    except IntegrityError as e:
        logger.error(f"Integrity error: {str(e)}")
        return Response(
            {"error": "User with this email or mobile already exists."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return Response(
            {"error": "An unexpected error occurred.", "details": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

class DynamicUserStatsAPIView(APIView):
    """
    API View to fetch dynamic user statistics grouped by user_type.
    Ignores users with user_type='SuperAdmin'.
    """
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        # Exclude 'SuperAdmin'
        users = Users.objects.exclude(user_type="SuperAdmin")

        # Get the stats for user types, including those with None values
        user_stats = users.values("user_type").annotate(count=Count("id"))

        # Initialize stats dictionary with "Individual" for None user_type
        stats = {"Individual": 0}

        # Loop through each user type count and add to stats
        for stat in user_stats:
            user_type = stat["user_type"]
            if user_type is None:
                stats["Individual"] += stat["count"]
            else:
                stats[user_type] = stat["count"]

        return Response(stats, status=status.HTTP_200_OK)


class UsersByDynamicTypeAPIView(APIView):
    """
    API View to retrieve users based on user_type dynamically.
    Ignores users with user_type='SuperAdmin'.
    """
    permission_classes = [AllowAny]  # Adjust permissions as needed

    def get(self, request, *args, **kwargs):
        # Get user_type from query parameters
        user_type = request.query_params.get("user_type")

        if not user_type:
            return Response({"error": "user_type parameter is required."}, status=400)

        # Filter users dynamically based on user_type
        if user_type == "Individual":
            users = Users.objects.filter(user_type__isnull=True)
        else:
            users = Users.objects.filter(user_type=user_type)

        # Exclude 'SuperAdmin' in all cases
        users = users.exclude(user_type="SuperAdmin")

        # Serialize and return data
        user_data = UserSerializer(users, many=True).data

        return Response({
            "users": user_data
        },  status=status.HTTP_200_OK)

class UserListByTypeAPIView(APIView):
    """
    API View to list all users grouped by user_type.
    Users with user_type = None are categorized under 'Individual'.
    """
    permission_classes = [AllowAny]  # Adjust permissions as needed

    def get(self, request, *args, **kwargs):
        user_groups = {
            "CA": [],
            "Business": [],
            "ServiceProvider": [],
            "Individual": []
        }

        # Fetch all users
        users = Users.objects.exclude(user_type="SuperAdmin")

        # Serialize users and group them by user_type
        for user in users:
            user_type = user.user_type or "Individual"
            user_groups[user_type].append(UserSerializer(user).data)

        return Response(user_groups)


def send_user_email(email, password):
    """Sends autogenerated credentials to user's email."""
    ses_client = boto3.client(
        'ses',
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )
    subject = "Welcome to TaraFirst! Your Account Has Been Created"
    body_html = f"""
        <html>
        <body>
            <h1>Welcome to TaraFirst!</h1>
            <p>Your account has been created.</p>
            <p><strong>Username:</strong> {email}</p>
            <p><strong>Password:</strong> {password}</p>
            <footer style="margin-top: 30px;">TaraFirst Team</footer>
        </body>
        </html>
    """
    ses_client.send_email(
        Source=EMAIL_HOST_USER,
        Destination={'ToAddresses': [email]},
        Message={
            'Subject': {'Data': subject},
            'Body': {'Html': {'Data': body_html}},
        },
    )


def send_user_otp(mobile_number):
    """Generates and sends OTP to user's mobile number."""
    otp = generate_otp()
    response = send_otp_helper(mobile_number, otp)
    if response['return']:
        query = Users.objects.filter(mobile_number=mobile_number)
        if query.exists():
            user = query.first()
            user.otp = otp
            user.save()
        return True
    return False


# Activate User

class ActivateUserView(APIView):
    """
    View for activating user accounts using UID and token.
    """
    permission_classes = [AllowAny]


    def post(self, request, *args, **kwargs):
        """
        Handle user account activation using query parameters (uid and token).
        """
        logger.info("Starting user account activation process.")

        # Get 'uid' and 'token' from query parameters
        uid = request.data.get('uid')
        token = request.data.get('token')

        if not uid or not token:
            raise Http404("UID or token is missing from the request.")

        try:
            uid = urlsafe_base64_decode(uid).decode()
            user = Users.objects.get(pk=uid)
            logger.info(f"User with UID {uid} found.")
        except (ValueError, TypeError, Users.DoesNotExist) as e:
            logger.error(f"Error during activation process: {e}")
            return Response({"message": "Invalid activation link"}, status=status.HTTP_400_BAD_REQUEST)

        if default_token_generator.check_token(user, token):
            user.is_active = True
            user.save()
            logger.info(f"User account with UID {uid} successfully activated.")
            return Response({"message": "Account activated successfully"}, status=status.HTTP_200_OK)

        logger.warning(f"Activation token for user with UID {uid} is invalid or expired.")
        return Response({"message": "Invalid or expired token"}, status=status.HTTP_400_BAD_REQUEST)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, *args, **kwargs):
        """
        Allow the authenticated user to change their password.
        """
        user = request.user
        old_password = request.data.get("old_password")
        new_password = request.data.get("new_password")

        if not old_password or not new_password:
            raise ValidationError({"error": "Both 'old_password' and 'new_password' are required."})

        # Check if the old password is correct
        if not user.check_password(old_password):
            raise ValidationError({"error": "Old password is incorrect."})

        # Validate the new password
        try:
            validate_password(new_password, user=user)
        except ValidationError as e:
            # Catch the ValidationError and return a 400 Bad Request with the error message
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Set the new password
        user.set_password(new_password)
        user.save()

        return Response({"message": "Password changed successfully."}, status=status.HTTP_200_OK)


# Test Protected API

class TestProtectedAPIView(APIView):

    def get(self, request):
        """
        Protected endpoint for authenticated users.
        """
        return Response({
            'message': 'You have access to this protected view!',
            'user_id': request.user.id,
            'email': request.user.email
        })


# Forgot Password
class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        """
        Handle forgot password functionality with Amazon SES.
        """
        email = request.data.get("email")
        if not email:
            logger.warning("Email not provided in the request.")
            print("**********************")
            raise ValidationError("Email is required.")

        try:
            user = Users.objects.get(email=email.lower())
            logger.info(f"User found for email: {email}")
        except Users.DoesNotExist:
            logger.info(f"Attempt to reset password for non-existent email: {email}")
            # Send a generic response even if the email does not exist
            return Response(
                {"error": "No account exists with this email address."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Generate reset token and link
        token = default_token_generator.make_token(user)
        uid = urlsafe_base64_encode(str(user.pk).encode())
        reset_link = f"{Reference_link}reset-password?uid={uid}&token={token}"

        # Send the email via Amazon SES
        try:
            ses_client = boto3.client(
                'ses',
                region_name=settings.AWS_REGION,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
            )

            subject = "Reset Your Password"
            body = f"""
            Hello Sir/Madam,

            You requested to reset your password. Click the link below to reset it:
            {reset_link}

            If you did not request this, please ignore this email.

            Thanks,
            TaraFirst
            """

            response = ses_client.send_email(
                Source=settings.EMAIL_HOST_USER,
                Destination={'ToAddresses': [email]},
                Message={
                    'Subject': {'Data': subject},
                    'Body': {'Text': {'Data': body}}
                }
            )
            logger.info(f"Password reset email sent to {email} successfully.")
            return Response({"message": "If an account exists with this email, you will receive a reset link."},
                            status=status.HTTP_200_OK)

        except (BotoCoreError, ClientError) as e:
            # Log SES-related errors
            logger.error(f"SES Error: {str(e)}")
            return Response({"message": "Unable to send reset email. Please try again later."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Reset Password
class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        """
        Reset user password via query parameters (?uid=...&token=...)
        """
        password = request.data.get("password")
        if not password:
            logger.warning("Password not provided in the request.")
            raise ValidationError("Password is required.")

        uid_b64 = request.query_params.get("uid")
        token = request.query_params.get("token")

        if not uid_b64 or not token:
            return Response({"message": "Missing UID or token in query parameters."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            uid = urlsafe_base64_decode(uid_b64).decode()
            user = Users.objects.get(pk=uid)
            logger.info(f"User found for UID: {uid}")
        except (Users.DoesNotExist, ValueError, TypeError) as e:
            logger.error(f"Error decoding UID or finding user: {str(e)}")
            return Response({"message": "Invalid reset link"}, status=status.HTTP_400_BAD_REQUEST)

        if default_token_generator.check_token(user, token):
            user.set_password(password)
            user.save()
            logger.info(f"Password successfully reset for user: {user.email}")
            return Response({"message": "Password has been successfully reset."}, status=status.HTTP_200_OK)

        logger.warning(f"Invalid or expired token for user: {user.email}")
        return Response({"message": "Invalid or expired token"}, status=status.HTTP_400_BAD_REQUEST)



# Refresh Token
class RefreshTokenView(APIView):
    permission_classes = [IsAuthenticated]


    def post(self, request, *args, **kwargs):
        """
        Refresh the access token using the provided refresh token.
        """
        refresh_token = request.data.get("refresh")

        # Ensure the refresh token is provided
        if not refresh_token:
            logger.warning("Refresh token is missing from the request.")
            return Response(
                {"detail": "Refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Validate and create a new access token
            token = RefreshToken(refresh_token)
            new_access_token = str(token.access_token)
            logger.info(f"New access token generated for refresh token: {refresh_token}")
            return Response(
                {"access": new_access_token},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            # Handle invalid or expired refresh tokens
            logger.error(f"Error generating new access token: {str(e)}. Refresh token: {refresh_token}")
            return Response(
                {"detail": "Invalid refresh token.", "error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class UsersKYCListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_details = UserKYC.objects.all()
        serializer = UsersKYCSerializer(user_details, many=True)
        return Response(serializer.data)

    def post(self, request):
        try:
            # Prevent duplicate KYC entry
            if hasattr(request.user, 'userkyc'):
                return Response({"detail": "User KYC already exists."}, status=status.HTTP_400_BAD_REQUEST)

            serializer = UsersKYCSerializer(data=request.data, context={'request': request})
            if serializer.is_valid():
                serializer.save(user=request.user)
                return Response(
                    {
                        "data": serializer.data,
                        "detail": "User KYC saved successfully."
                    },
                    status=status.HTTP_201_CREATED
                )

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(e, exc_info=True)
            return Response(
                {"error_message": str(e), "status_cd": 1},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class UsersKYCDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk=None):
        """
        Retrieve user details by ID.
        """
        try:
            user_details = UserKYC.objects.get(user=pk)
            serializer = UsersKYCSerializer(user_details)
            return Response(serializer.data)
        except UserKYC.DoesNotExist:
            raise NotFound("User details not found.")

    def put(self, request, pk=None):
        """
        Update user details by ID.
        """
        try:
            user_details = UserKYC.objects.get(pk=pk, user=request.user)
            serializer = UsersKYCSerializer(user_details, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response({"detail": "User details updated successfully."}, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except UserKYC.DoesNotExist:
            raise NotFound("User details not found.")

    def delete(self, request, pk=None):
        """
        Delete user details by ID.
        """
        try:
            user_details = UserKYC.objects.get(pk=pk, user=request.user)
            user_details.delete()
            return Response({"detail": "User details deleted successfully."}, status=status.HTTP_204_NO_CONTENT)
        except UserKYC.DoesNotExist:
            raise NotFound("User details not found.")


class FirmKYCView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Retrieve FirmKYC details for the authenticated user.
        """
        try:
            firm_kyc = request.user.firmkyc
            serializer = FirmKYCSerializer(firm_kyc)
            return Response({"data": serializer.data, "detail": "FIRM KYC saved successfully."},
                            status=status.HTTP_200_OK)
        except FirmKYC.DoesNotExist:
            return Response({"detail": "FirmKYC details not found."}, status=status.HTTP_404_NOT_FOUND)

    def post(self, request):
        """
        Create FirmKYC details for the authenticated user.
        """
        serializer = FirmKYCSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request):
        """
        Update FirmKYC details for the authenticated user.
        """
        try:
            firm_kyc = request.user.firmkyc
            serializer = FirmKYCSerializer(firm_kyc, data=request.data)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except FirmKYC.DoesNotExist:
            return Response({"detail": "FirmKYC details not found."}, status=status.HTTP_404_NOT_FOUND)

    def delete(self, request):
        """
        Delete FirmKYC details for the authenticated user.
        """
        try:
            firm_kyc = request.user.firmkyc
            firm_kyc.delete()
            return Response({"detail": "FirmKYC details deleted successfully."}, status=status.HTTP_204_NO_CONTENT)
        except FirmKYC.DoesNotExist:
            return Response({"detail": "FirmKYC details not found."}, status=status.HTTP_404_NOT_FOUND)


@permission_classes([IsAuthenticated])  # Ensure only authenticated users can access this endpoint
@api_view(['PATCH'])
def partial_update_user(request):
    """
    Handle partial update of user profile. If `id` is passed, update that user;
    otherwise, update the currently authenticated user.
    """
    try:
        user_id = request.data.get('id', None)  # Get the 'id' from request data

        if user_id:
            # If `id` is passed, fetch the user with the provided `id`
            try:
                user = Users.objects.get(id=user_id)
            except Users.DoesNotExist:
                return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        else:
            # If no `id` is passed, update the currently authenticated user
            user = request.user  # Get the currently authenticated user

        # Create a serializer instance with partial update flag
        serializer = UserUpdateSerializer(user, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()  # Save the updated user data
            return Response({
                "message": "User updated successfully.",
                "data": serializer.data  # Include the updated user data in the response
            }, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error updating user info: {str(e)}")
        return Response({"error": "An unexpected error occurred while updating user info."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def corporate_details(request):
    """
    API to retrieve business users created by the authenticated user.
    Ignores users with user_type='SuperAdmin'.
    """
    try:
        user_id = request.query_params.get('user_id')

        if not user_id:
            return Response({"error": "User ID is required."}, status=status.HTTP_400_BAD_REQUEST)

        # Log the user_id to debug
        print(f"Received user_id: {user_id}")

        try:
            # Check if the user exists
            created_by_user = Users.objects.get(id=user_id)
        except Users.DoesNotExist:
            return Response({"error": f"User with ID {user_id} not found."}, status=status.HTTP_404_NOT_FOUND)

        # Fetch business users created by the user
        users = Users.objects.filter(created_by=user_id, user_type="Business")

        if not users.exists():
            return Response({"message": "No business users found."}, status=status.HTTP_404_NOT_FOUND)

        return Response({"users": UserSerializer(users, many=True).data}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": f"An unexpected error occurred: {str(e)}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)



@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_search(request):
    """
    API to search for users by email.
    Returns a single object if only one user is found, otherwise returns a list.
    """
    try:
        email = request.query_params.get('email')

        if not email:
            return Response({"error": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        users = Users.objects.filter(email=email)

        if not users.exists():
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response(UserSerializer(users, many=True).data, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": f"An unexpected error occurred: {str(e)}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def business_list_by_client(request):
    """
    API to retrieve a business by client ID.
    """
    try:
        client_id = request.query_params.get('user_id')

        if not client_id:
            return Response({'error': 'User ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            business = Business.objects.get(client=client_id)  # Using get() instead of filter()
        except Business.DoesNotExist:
            return Response({'error': 'No business found for this client.'}, status=status.HTTP_404_NOT_FOUND)

        # Serialize and return the business data
        serializer = BusinessUserSerializer(business)
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({'error': f'An unexpected error occurred: {str(e)}'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def manage_corporate_entity(request):
    """
    API to retrieve business users created by the authenticated user.
    Ignores users with user_type='SuperAdmin'.
    """
    try:
        user_id = request.query_params.get('user_id')

        if not user_id:
            return Response({"error": "User ID is required."}, status=status.HTTP_400_BAD_REQUEST)

        # Log the user_id to debug
        print(f"Received user_id: {user_id}")

        try:
            # Check if the user exists
            created_by_user = Users.objects.get(id=user_id)
        except Users.DoesNotExist:
            return Response({"error": f"User with ID {user_id} not found."}, status=status.HTTP_404_NOT_FOUND)

        # Fetch business users created by the user
        users = Users.objects.filter(created_by=user_id, user_type="Business")

        if not users.exists():
            return Response({"message": "No business users found."}, status=status.HTTP_404_NOT_FOUND)

        return Response({"users": UserSerializer(users, many=True).data}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": f"An unexpected error occurred: {str(e)}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def validate_user(user_id):
    try:
        return Users.objects.get(id=user_id)
    except ObjectDoesNotExist:
        raise ValueError(f"User with ID {user_id} not found.")

def check_business_existence(business_data):
    """
    Check if the business or PAN already exists in the database.
    """
    if business_data.get('entityType') != 'individual':
        if Business.objects.filter(nameOfBusiness__iexact=business_data['nameOfBusiness']).exists():
            return "Business already exists"
        if Business.objects.filter(pan=business_data['pan']).exists():
            return "Business with PAN already exists"
    return None


def send_account_email(user, email, password):
    """
    Send account details to the user's email.
    """
    subject = "Your Account Details"
    body_html = f"""
        <html>
        <body>
            <h1>Welcome to Our Platform</h1>
            <p>Your account has been created by the superadmin.</p>
            <p><strong>Username:</strong> {user.user_name}</p>
            <p><strong>Password:</strong> {password}</p>
        </body>
        </html>
    """

    # ses_client = boto3.client(
    #     'ses',
    #     region_name=AWS_REGION,
    #     aws_access_key_id=AWS_ACCESS_KEY_ID,
    #     aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    # )
    ses_client = boto3.client(
        'ses',
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )

    try:
        # ses_client.send_email(
        #     Source=EMAIL_HOST_USER,
        #     Destination={'ToAddresses': [email]},
        #     Message={
        #         'Subject': {'Data': subject},
        #         'Body': {
        #             'Html': {'Data': body_html},
        #             'Text': {'Data': f"Your username is: {user.user_name}\nYour password is: {password}"}
        #         },
        #     }
        # )
        response = ses_client.send_email(
            Source="admin@tarafirst.com",
            Destination={'ToAddresses': [email]},
            Message={
                'Subject': {'Data': subject},
                'Body': {
                    'Html': {'Data': body_html},
                    'Text': {'Data': f"Your username is: {user.email}\nYour password is: {password}"}
                },
            }
        )
        logger.info(f"Account details email sent to: {email}")
        return Response(
            {"message": "User created successfully. Check your email for the username and password."},
            status=status.HTTP_201_CREATED,
        )


    except ClientError as e:
        logger.error(f"Failed to send email via SES: {e.response['Error']['Message']}")
        return Response(
            {"error": "Failed to send account details email. Please try again later."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def business_set_up(business_data):
    """
    Handle business registration.
    Returns the instance and serialized data.
    """
    serializer = BusinessSerializer(data=business_data)
    if serializer.is_valid():
        business_instance = serializer.save()
        return business_instance, serializer.data  # Returning both
    raise ValueError(f"Invalid business data provided: {serializer.errors}")



def object_remove(created_objects):
    # Reverse the list to delete the last created object first
    for obj in reversed(created_objects):
        try:
            obj.delete()
            logger.info(f"Successfully deleted: {obj}")
        except Exception as e:
            logger.error(f"Failed to delete {obj}: {str(e)}")
    return


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def business_list(request):
    if request.method == 'GET':
        businesses = Business.objects.all()
        serializer = BusinessSerializer(businesses, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':

        request_data = request.data.copy()  # Create a mutable copy of request data

        request_data['nameOfBusiness'] = request_data.get('nameOfBusiness', '').strip().title()

        entity_type = request_data.get('entityType', '').strip().lower()

        business_name = request_data.get('nameOfBusiness')

        pan = request_data.get('pan', '').strip()

        # Check if a non-individual business with the same name exists

        if entity_type and entity_type != 'individual':

            if Business.objects.filter(nameOfBusiness__iexact=business_name).exists():
                return Response({'error_message': 'Business already exists'}, status=status.HTTP_400_BAD_REQUEST)

        # Check if a business with the same PAN exists

        if pan and Business.objects.filter(pan=pan).exists():
            return Response({'error_message': 'Business with PAN already exists'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = BusinessSerializer(data=request_data)

        if serializer.is_valid():
            serializer.save()

            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def business_detail(request, pk):
    business = get_object_or_404(Business, pk=pk)

    if request.method == 'GET':
        serializer = BusinessUserSerializer(business)
        return Response(serializer.data)

    elif request.method == 'PUT':
        serializer = BusinessSerializer(business, data=request.data, partial=True)
        if serializer.is_valid():
            try:
                serializer.save()
                return Response(serializer.data)
            except Exception as e:
                logger.error(f"Error saving business data: {str(e)}")
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        business.delete()
        return Response({'message': 'Business deleted successfully'}, status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def gst_details_list_create(request):
    """
    Create a new GST detail and update usage count for GSTIN.
    Context is extracted from business_id or falls back to user's active context.
    """
    data = request.data.copy()

    # Remove gst_document if not provided
    if 'gst_document' not in request.FILES:
        data.pop('gst_document', None)

    # Step 1: Get context from business or fallback to user's active_context
    context = None
    business_id = data.get('business')

    if business_id:
        try:
            business = Business.objects.get(id=business_id)
            context = business.context
        except Business.DoesNotExist:
            return Response({"error": "Invalid business ID."}, status=status.HTTP_400_BAD_REQUEST)
        except AttributeError:
            pass

    if not context:
        # Get user's active context from UserSession
        try:
            user_session = request.user.get_active_session()
            context = user_session.active_context if user_session else None
        except:
            context = None

    if not context:
        return Response({"error": "No context found from business or user."}, status=status.HTTP_400_BAD_REQUEST)

    # Step 2: Check usage entry for 'gstin'
    usage_entry, error_response = get_usage_entry(context.id, 'gstin', 2)
    if error_response:
        return error_response

    # Step 3: Enforce usage limits
    if usage_entry.actual_count != 'unlimited':
        if int(usage_entry.usage_count) >= int(usage_entry.actual_count):
            return Response({"error": "GSTIN usage limit reached."}, status=status.HTTP_403_FORBIDDEN)

    # Step 4: Create GST detail
    serializer = GSTDetailsSerializer(data=data)
    if serializer.is_valid():
        serializer.save()

        # Step 5: Increment usage
        increment_usage(usage_entry)

        return Response(serializer.data, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'DELETE'])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def gst_details_detail(request, pk):
    """
    Retrieve, update or delete a GST detail by ID.
    """
    if request.method == 'GET':
        try:
            gst_detail = GSTDetails.objects.filter(business_id=pk)
            serializer = GSTDetailsSerializer(gst_detail, many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    elif request.method in ['PUT']:
        gst_detail = GSTDetails.objects.get(pk=pk)
        data = request.data.copy()
        # Remove gst_document from data if it's not provided
        if 'gst_document' not in request.FILES:
            data.pop('gst_document', None)
            
        serializer = GSTDetailsSerializer(gst_detail, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        gst_detail = GSTDetails.objects.get(pk=pk)
        gst_detail.delete()
        return Response({"message": "GST Detail deleted successfully"}, status=status.HTTP_204_NO_CONTENT)

@api_view(['POST'])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def tds_details_list_create(request):
    """
    List all TDS details or create a new TDS detail.
    """
    if request.method == 'POST':
        serializer = TDSDetailsSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PUT', 'DELETE'])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def tds_details_detail(request, pk):
    """
    Retrieve, update or delete a TDS detail by ID.
    """
    if request.method == 'GET':
        try:
            tds_detail = TDSDetails.objects.filter(business_id=pk)
            serializer = TDSDetailsSerializer(tds_detail,many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    elif request.method in ['PUT', 'PATCH']:
        tds_detail = TDSDetails.objects.get(pk=pk)
        serializer = TDSDetailsSerializer(tds_detail, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        tds_detail = TDSDetails.objects.get(pk=pk)
        tds_detail.delete()
        return Response({"message": "TDS Detail deleted successfully"}, status=status.HTTP_204_NO_CONTENT)

@api_view(['POST'])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def license_details_list_create(request):
    """
    List all license details or create a new license detail.
    """
    if request.method == 'POST':
        serializer = LicenseDetailsSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PUT', 'DELETE'])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def license_details_detail(request, pk):
    """
    Retrieve, update or delete a license detail by ID.
    """
    if request.method == 'GET':
        try:
            license_detail = LicenseDetails.objects.filter(business_id=pk)
            serializer = LicenseDetailsSerializer(license_detail,many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    elif request.method in ['PUT']:
        license_detail = LicenseDetails.objects.get(pk=pk)
        serializer = LicenseDetailsSerializer(license_detail, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        license_detail = LicenseDetails.objects.get(pk=pk)
        license_detail.delete()
        return Response({"message": "License Detail deleted successfully"}, status=status.HTTP_204_NO_CONTENT)

@api_view(['POST'])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def dsc_details_list_create(request):
    """
    List all DSC details or create a new DSC detail.
    """
    if request.method == 'POST':
        serializer = DSCDetailsSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def dsc_details_detail(request, pk):
    """
    Retrieve, update or delete a DSC detail by ID.
    """
    if request.method == 'GET':
        try:
            dsc_detail = DSCDetails.objects.filter(business_id=pk)
            serializer = DSCDetailsSerializer(dsc_detail,many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    elif request.method in ['PUT']:
        dsc_detail = DSCDetails.objects.get(pk=pk)
        serializer = DSCDetailsSerializer(dsc_detail, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        dsc_detail = DSCDetails.objects.get(pk=pk)
        dsc_detail.delete()
        return Response({"message": "DSC Detail deleted successfully"}, status=status.HTTP_204_NO_CONTENT)

@api_view(['POST'])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def bank_details_list_create(request):
    """
    List all bank details or create a new bank detail.
    """
    if request.method == 'POST':
        serializer = BankDetailsSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'DELETE'])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def bank_details_detail(request, pk):
    """
    Retrieve, update or delete a bank detail.
    """
    if request.method == 'GET':
        try:
            bank_detail = BankDetails.objects.filter(business_id=pk)
            serializer = BankDetailsSerializer(bank_detail,many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'PUT':
        bank_detail = BankDetails.objects.get(pk=pk)
        serializer = BankDetailsSerializer(bank_detail, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        bank_detail = BankDetails.objects.get(pk=pk)
        bank_detail.delete()
        return Response({"message": "Bank Detail deleted successfully"}, status=status.HTTP_204_NO_CONTENT)

@api_view(['POST'])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def kmp_list_create(request):
    """
    List all KMP details or create a new KMP detail.
    """
    if request.method == 'POST':
        serializer = KeyManagerialPersonnelSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'DELETE'])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def kmp_detail(request, pk):
    """
    Retrieve, update or delete a KMP detail.
    """
    if request.method == 'GET':
        try:
            try:
                kmp = KeyManagerialPersonnel.objects.filter(business_id=pk)
            except KeyManagerialPersonnel.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)
            serializer = KeyManagerialPersonnelSerializer(kmp, many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    elif request.method == 'PUT':
        try:
            try:
                kmp = KeyManagerialPersonnel.objects.get(pk=pk)
            except KeyManagerialPersonnel.DoesNotExist:
                return Response({"error": "Key Managerial Personnel not found"}, status=status.HTTP_404_NOT_FOUND)

            serializer = KeyManagerialPersonnelSerializer(kmp, data=request.data)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    elif request.method == 'DELETE':
        try:
            try:
                kmp = KeyManagerialPersonnel.objects.get(pk=pk)
            except KeyManagerialPersonnel.DoesNotExist:
                return Response({"error": "Key Managerial Personnel not found"}, status=status.HTTP_404_NOT_FOUND)

            kmp.delete()
            return Response({"message": "Key Managerial Personnel Detail deleted successfully"},
                            status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'POST'])
def branch_list_create(request):
    if request.method == 'GET':
        branches = Branch.objects.all()
        serializer = BranchSerializer(branches, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        serializer = BranchSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'DELETE'])
def branch_detail(request, pk):

    if request.method == 'GET':
        branch = Branch.objects.filter(business_id=pk)
        serializer = BranchSerializer(branch, many=True)
        return Response(serializer.data)

    elif request.method == 'PUT':
        branch = Branch.objects.get(pk=pk)
        serializer = BranchSerializer(branch, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        branch = Branch.objects.get(pk=pk)
        branch.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def documents_view(request):
    # Get the URL from the query parameters
    document_url = request.GET.get('url', None)

    if not document_url:
        return JsonResponse({'error': 'URL parameter is required'}, status=400)

    try:
        # Parse the URL to extract the file name (Key)
        parsed_url = urlparse(document_url)
        file_key = unquote(parsed_url.path.lstrip('/'))  # Remove leading '/' and decode URL

        # Initialize S3 client
        s3_client = boto3.client(
            's3',
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY
        )

        # Generate a pre-signed URL
        file_url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': S3_BUCKET_NAME,
                'Key': file_key
            },
            ExpiresIn=3600  # URL expires in 1 hour
        )

        # Return the pre-signed URL
        return JsonResponse({'url': file_url}, status=200)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@api_view(['GET'])
def business_with_gst_details(request, business_id):
    """
    Retrieve a Business along with all its associated GST details using serializers.
    """
    try:
        business = Business.objects.prefetch_related('gst_details').get(id=business_id)
    except Business.DoesNotExist:
        return Response({"error": "Business not found"}, status=status.HTTP_404_NOT_FOUND)

    serializer = BusinessWithGSTSerializer(business)
    return Response(serializer.data, status=status.HTTP_200_OK)


class ServicesMasterDataListAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        services = ServicesMasterData.objects.all()
        if not services.exists():
            return Response({"error": "No services found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = ServicesMasterDataSerializer(services, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        services = request.data.get("services", [])
        if not services or not isinstance(services, list):
            return Response({"error": "Please provide a list of service names."}, status=status.HTTP_400_BAD_REQUEST)

        created_services = []
        for service_name in services:
            service, created = ServicesMasterData.objects.get_or_create(service_name=service_name)
            if created:
                created_services.append(service_name)

        return Response(
            {
                "message": "Services created successfully.",
                "created_services": created_services
            },
            status=status.HTTP_201_CREATED
        )


class ServicesMasterDataDetailAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, pk):
        try:
            service = ServicesMasterData.objects.get(pk=pk)
            serializer = ServicesMasterDataSerializer(service)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except ServicesMasterData.DoesNotExist:
            return Response({"error": "Service not found"}, status=status.HTTP_404_NOT_FOUND)

    def put(self, request, pk):
        try:
            service = ServicesMasterData.objects.get(pk=pk)
        except ServicesMasterData.DoesNotExist:
            return Response({"error": "Service not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = ServicesMasterDataSerializer(service, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        try:
            service = ServicesMasterData.objects.get(pk=pk)
            service.delete()
            return Response({"message": "Service deleted successfully"}, status=status.HTTP_204_NO_CONTENT)
        except ServicesMasterData.DoesNotExist:
            return Response({"error": "Service not found"}, status=status.HTTP_404_NOT_FOUND)



class VisaApplicationDetailAPIView(APIView):
    permission_classes = [GroupPermission]
    permission_required = "VS_Task_View"

    def get(self, request, pk):
        try:
            # visa_application = VisaApplications.objects.get(user_id=pk)
            # serializer = VisaApplicationsGetSerializer(visa_application)
            visa_applications = VisaApplications.objects.filter(user_id=pk)
            serializer = VisaClientUserListSerializer(visa_applications, many=True)
            response_data = []
            user_data_map = {}

            for visa_app in serializer.data:  # Use serializer.data to get the serialized data
                user = visa_app['email']

                if user not in user_data_map:
                    # Add user data to the map if not already added
                    user_data_map[user] = {
                        "email": visa_app['email'],
                        "mobile_number": visa_app['mobile_number'],
                        "first_name": visa_app['first_name'],
                        "last_name": visa_app['last_name'],
                        "services": [],
                        "user": visa_app['user'],
                    }

                # Check if services list is empty
                services = visa_app['services']
                if len(services) > 0:
                    for service in services:
                        user_data_map[user]["services"].append({
                            "id": service['id'],
                            "service_type": service['service_type'],
                            "service_name": service['service_name'],
                            "date": service['date'],
                            "status": service['status'],
                            "comments": service['comments'],
                            "quantity": service['quantity'],
                            "visa_application": visa_app['id'],
                            "last_updated_date": service['last_updated_date'],
                            "passport_number": visa_app['passport_number'],
                            "purpose": visa_app['purpose'],
                            "visa_type": visa_app['visa_type'],
                            "destination_country": visa_app['destination_country'],
                            'user_id': visa_app['user']
                        })
                else:
                    # If no services, add specific fields directly to user data
                    user_data_map[user].update({
                        "passport_number": visa_app['passport_number'],
                        "purpose": visa_app['purpose'],
                        "visa_type": visa_app['visa_type'],
                        "destination_country": visa_app['destination_country'],
                        'user_id': visa_app['user']
                    })

            # Convert the user data map to a list
            response_data = user_data_map[user]

            return Response(response_data, status=status.HTTP_200_OK)

        except Users.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except VisaApplications.DoesNotExist:
            return Response({"error": "Visa application not found"}, status=status.HTTP_404_NOT_FOUND)

    permission_required = "VS_Task_Edit"

    def put(self, request, pk):
        try:
            visa_application = VisaApplications.objects.get(pk=pk)
        except VisaApplications.DoesNotExist:
            return Response({"error": "Visa application not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = VisaApplicationsSerializer(visa_application, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # For DELETE
    permission_required = "VS_Task_Delete"  # Define the required permission for DELETE method


    def delete(self, request, pk):
        try:
            visa_application = VisaApplications.objects.get(pk=pk)
            visa_application.delete()
            return Response({"message": "Visa application deleted successfully"}, status=status.HTTP_204_NO_CONTENT)
        except VisaApplications.DoesNotExist:
            return Response({"error": "Visa application not found"}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([AllowAny])  # Add 'GroupPermission' if necessary for handling role-based permission
@has_group_permission('VS_Task_Create')
def manage_visa_applications(request):
    try:
        # Authorization check
        if request.user.user_role not in ["ServiceProvider_Admin", "Individual_User"] or request.user.user_type != "ServiceProvider":
            return Response(
                {
                    'error_message': 'Unauthorized Access. Only Service Providers with roles '
                                     '(ServiceProvider_Admin, Individual_User) can add visa users.',
                    'status_cd': 1
                },
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Extract required fields from request data
        user_id = request.data.get('user_id')
        passport_number = request.data.get('passport_number', '')
        purpose = request.data.get('purpose')
        visa_type = request.data.get('visa_type')
        destination_country = request.data.get('destination_country')


        # Validate required fields
        if not all([user_id, purpose, visa_type, destination_country]):
            return Response(
                {"error": "Missing required fields. Provide 'user_id', "
                          "'purpose', 'visa_type', and 'destination_country'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check if the visa application already exists
        visa_applications = VisaApplications.objects.filter(
            visa_type=visa_type, user_id=user_id, purpose=purpose, destination_country=destination_country
        )
        if visa_applications.exists():
            visa_application = visa_applications.first()
        else:
            # Create a new visa application
            visa_data = {
                'user': user_id,
                'passport_number': passport_number,
                'purpose': purpose,
                'visa_type': visa_type,
                'destination_country': destination_country
            }
            visa_serializer = VisaApplicationsSerializer(data=visa_data)
            if visa_serializer.is_valid():
                visa_serializer.save()
                visa_application = VisaApplications.objects.get(id=visa_serializer.data['id'])
            else:
                return Response(visa_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Process services data
        services_data = request.data.get('services', [])
        if services_data:
            for service in services_data:
                service['visa_application'] = visa_application.id
                service_serializer = ServiceDetailsSerializer(data=service)
                if service_serializer.is_valid():
                    service_serializer.save()
                else:
                    return Response(service_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            return Response({"message": "Visa application and services added successfully."},
                            status=status.HTTP_201_CREATED)

        return Response(
            {"error": "No services provided. Provide 'services' data to add to the visa application."},
            status=status.HTTP_400_BAD_REQUEST
        )

    except Exception as e:
        logger.error(f"Error managing visa applications: {str(e)}", exc_info=True)
        return Response({"error": "An internal error occurred. Please try again later."},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@has_group_permission('VS_Task_View')
def get_visa_clients_users_list(request):
    try:
        # Check if the user is a ServiceProvider_Admin with the correct type
        print("****************")
        if request.user.user_role == "ServiceProvider_Admin" and request.user.user_type == "ServiceProvider":
            # Get all users created by the current ServiceProviderAdmin
            created_by_id = request.user.id
            users = Users.objects.filter(created_by=created_by_id)

            # Retrieve VisaApplications for these users
            visa_applications = VisaApplications.objects.filter(user__in=users)
            serializer = VisaClientUserListSerializer(visa_applications, many=True)

        elif request.user.user_role == "Individual_User" and request.user.user_type == "ServiceProvider":
            visa_applications = VisaApplications.objects.filter(user=request.user)
            serializer = VisaClientUserListSerializer(visa_applications, many=True)

        else:
            return Response({"error": "Unauthorized access."}, status=status.HTTP_403_FORBIDDEN)

        # Grouping visa applications and services by user
        response_data = []
        user_data_map = {}

        for visa_app in serializer.data:  # Use serializer.data to get the serialized data
            user = visa_app['email']

            if user not in user_data_map:
                # Add user data to the map if not already added
                user_data_map[user] = {
                    "email": visa_app['email'],
                    "mobile_number": visa_app['mobile_number'],
                    "first_name": visa_app['first_name'],
                    "last_name": visa_app['last_name'],
                    "services": [],
                    "user": visa_app['user'],
                }

            # Check if services list is empty
            services = visa_app['services']
            if len(services) > 0:
                for service in services:
                    user_data_map[user]["services"].append({
                        "id": service['id'],
                        "service_type": service['service_type'],
                        "service_name": service['service_name'],
                        "date": service['date'],
                        "status": service['status'],
                        "comments": service['comments'],
                        "quantity": service['quantity'],
                        "visa_application": visa_app['id'],
                        "last_updated_date": service['last_updated_date'],
                        "passport_number": visa_app['passport_number'],
                        "purpose": visa_app['purpose'],
                        "visa_type": visa_app['visa_type'],
                        "destination_country": visa_app['destination_country'],
                        'user_id': visa_app['user']
                    })
            else:
                # If no services, add specific fields directly to user data
                user_data_map[user].update({
                    "passport_number": visa_app['passport_number'],
                    "purpose": visa_app['purpose'],
                    "visa_type": visa_app['visa_type'],
                    "destination_country": visa_app['destination_country'],
                    'user_id': visa_app['user']
                })

        # Convert the user data map to a list
        response_data = list(user_data_map.values())

        return Response(response_data, status=status.HTTP_200_OK)

    except Users.DoesNotExist:
        return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

    except VisaApplications.DoesNotExist:
        return Response({"error": "No visa applications found."}, status=status.HTTP_404_NOT_FOUND)

    except Exception as e:
        return Response({"error": f"An unexpected error occurred: {str(e)}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@has_group_permission('VS_Task_View')
def service_status(request):
    try:
        # Check if the user has the appropriate role and type
        if (request.user.user_role in ["ServiceProvider_Admin", "Individual_User"] and
                request.user.user_type == "ServiceProvider"):
            # Determine the users and VisaApplications based on the role
            if request.user.user_role == "ServiceProvider_Admin":
                created_by_id = request.user.id
                users = Users.objects.filter(created_by=created_by_id)
                visa_applications = VisaApplications.objects.filter(user__in=users)
            elif request.user.user_role == "Individual_User":
                visa_applications = VisaApplications.objects.filter(user=request.user)

            # Serialize the VisaApplications data
            serializer = VisaClientUserListSerializer(visa_applications, many=True)

            # Initialize counters and data containers
            counts = {
                'pending': 0,
                'pending_data': [],
                'in_progress': 0,
                'in_progress_data': [],
                'completed': 0,
                'completed_data': []
            }

            # Process each serialized item
            for item in serializer.data:
                for service in item['services']:
                    service_data = {
                        'service_id': service['id'],
                        'visa_applicant_name': item['first_name'] + ' ' + item['last_name'],
                        'service_type': service['service_type'],
                        'service_name': service['service_name'],
                        'comments': service.get('comments', ''),
                        'quantity': service.get('quantity', 0),
                        'date': service.get('date', ''),
                        'status': service['status'],
                        'passport_number': item.get('passport_number'),
                        'visa_type': item.get('visa_type'),
                        'destination_country': item.get('destination_country'),
                        'purpose': item.get('purpose'),
                        'user': item.get('user')
                    }

                    # Categorize based on the service status
                    if service['status'] == 'pending':
                        counts['pending'] += 1
                        counts['pending_data'].append(service_data)
                    elif service['status'] == 'in progress':
                        counts['in_progress'] += 1
                        counts['in_progress_data'].append(service_data)
                    elif service['status'] == 'completed':
                        counts['completed'] += 1
                        counts['completed_data'].append(service_data)

            return Response(counts, status=status.HTTP_200_OK)

        # If user is unauthorized
        return Response({"error": "Unauthorized access."}, status=status.HTTP_403_FORBIDDEN)

    except Users.DoesNotExist:
        # Handle the case where the user is not found
        return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

    except VisaApplications.DoesNotExist:
        # Handle the case where visa applications are not found
        return Response({"error": "No visa applications found."}, status=status.HTTP_404_NOT_FOUND)

    except Exception as e:
        # Handle other unexpected errors
        return Response({"error": f"An unexpected error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def parse_last_updated_date(last_updated):
    """
    Helper function to parse the last_updated field.
    """
    try:
        # Parse the string to a datetime object using strptime
        return datetime.strptime(last_updated, '%Y-%m-%dT%H:%M:%S.%fZ').date()
    except (ValueError, TypeError) as e:
        logger.error(f"Error parsing last_updated: {e}")
        # Return an empty string if the date parsing fails
        return ''


def collect_service_data(serializer_data, user_role):
    """
    Helper function to collect and format service data.
    """
    all_services = []
    for item in serializer_data:
        if user_role == 'Individual_User':
            if not item['services']:
                service_data = {
                    'email': item.get('email'),
                    'mobile_number': item.get('mobile_number'),
                    'passport_number': item.get('passport_number'),
                    'visa_type': item.get('visa_type'),
                    'destination_country': item.get('destination_country'),
                    'purpose': item.get('purpose'),
                    'first_name': item['first_name'],
                    'last_name': item['last_name'],
                    'user': item.get('user')
                }
                all_services = service_data

        for service in item['services']:
            try:
                last_updated_date = parse_last_updated_date(service.get('last_updated'))
                service_data = {
                    'email': item.get('email'),
                    'mobile_number': item.get('mobile_number'),
                    'passport_number': item.get('passport_number'),
                    'visa_type': item.get('visa_type'),
                    'destination_country': item.get('destination_country'),
                    'purpose': item.get('purpose'),
                    'id': service['id'],
                    'service_type': service['service_type'],
                    'service_name': service['service_name'],
                    'first_name': item['first_name'],
                    'last_name': item['last_name'],
                    'comments': service.get('comments', ''),
                    'quantity': service.get('quantity', 0),
                    'date': service.get('date', ''),
                    'last_updated': last_updated_date,
                    'status': service['status'],
                    'passport': item.get('passport_number'),
                    'user': item.get('user')
                }
                all_services.append(service_data)
            except KeyError as e:
                logger.error(f"Missing key in service data: {e}")
                return {"error": f"Missing key in service data: {e}"}, False
            except Exception as e:
                logger.error(f"Unexpected error while processing service data: {e}")
                return {"error": f"Unexpected error: {e}"}, False
    return all_services, True


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@has_group_permission('VS_Task_View')
def all_service_data(request):
    user_role = request.user.user_role

    try:
        if user_role == "ServiceProvider_Admin":
            # Get all VisaApplications for the current ServiceProviderAdmin
            created_by_id = request.user.id
            users = Users.objects.filter(created_by=created_by_id)
            visa_applications = VisaApplications.objects.filter(user__in=users)

        elif user_role == "Individual_User":
            # Get all VisaApplications for the current Individual User
            user_id = request.user.id
            visa_applications = VisaApplications.objects.filter(user=user_id)

        else:
            return Response(
                {"error": "Unauthorized access."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Serialize the data
        serializer = VisaClientUserListSerializer(visa_applications, many=True)

        # Collect and format all services data
        all_services, success = collect_service_data(serializer.data, user_role)
        if not success:
            return Response(all_services, status=status.HTTP_400_BAD_REQUEST)

        return Response(all_services, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Unexpected error in all_service_data: {e}")
        return Response(
            {"error": f"An unexpected error occurred: {e}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class ServiceDetailsAPIView(APIView):
    permission_classes = [IsAuthenticated]
    permission_required = "VS_Task_View"

    def has_permission(self, user):
        """
        Check if the user has the required role and type.
        """
        return (
                user.user_role in ['ServiceProvider_Admin', 'Individual_User'] and
                user.user_type == 'ServiceProvider'
        )

    def get(self, request, pk):
        """Retrieve a specific ServiceDetails instance by ID."""
        print("****")
        if not self.has_permission(request.user):
            return Response(
                {"error": "You do not have permission to perform this action."},
                status=status.HTTP_403_FORBIDDEN,
            )
        service = get_object_or_404(ServiceDetails, pk=pk)
        serializer = ServiceDetailsSerializer(service)
        return Response(serializer.data, status=status.HTTP_200_OK)


    permission_required = "VS_Task_Edit"

    def put(self, request, pk):
        """Partially update a specific ServiceDetails instance (partial=True)."""
        if not self.has_permission(request.user):
            return Response(
                {"error": "You do not have permission to perform this action."},
                status=status.HTTP_403_FORBIDDEN,
            )
        # service = get_object_or_404(ServiceDetails, pk=pk)
        service = ServiceDetails.objects.get(id=pk)

        visa_data = request.data.get('visa_application', {})
        # Check if the VisaApplication exists
        user_id = visa_data.get('user')
        passport_number= visa_data.get('passport_number', '')
        purpose= visa_data.get('purpose')
        visa_type = visa_data.get('visa_type')
        destination_country = visa_data.get('destination_country')
        visa_application = VisaApplications.objects.filter(
            user_id=visa_data.get('user'),
            purpose=visa_data.get('purpose'),
            visa_type=visa_data.get('visa_type'),
            destination_country=visa_data.get('destination_country')
        ).first()
        if visa_application:
            # Update existing VisaApplication with provided data
            service_data = request.data.get('service', {})
            service_data['visa_application'] = visa_application.id  # Set the existing visa application ID
        else:
            visa_data['passport_number'] = passport_number
            visa_application_serializer = VisaApplicationsSerializer(data=visa_data)
            if visa_application_serializer.is_valid():
                visa_application_ = visa_application_serializer.save()
                service_data = request.data.get('service', {})
                service_data['visa_application'] = visa_application_.id
            else:
                return Response(visa_application_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
                # Update the ServiceDetails instance
        service = get_object_or_404(ServiceDetails, id=request.data.get('service').get('id'))
        serializer = ServiceDetailsSerializer(service, data=service_data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    permission_required = "VS_Task_Delete"

    def delete(self, request, pk):
        """Delete a specific ServiceDetails instance."""
        if not self.has_permission(request.user):
            return Response(
                {"error": "You do not have permission to perform this action."},
                status=status.HTTP_403_FORBIDDEN,
            )
        service = get_object_or_404(ServiceDetails, pk=pk)
        service.delete()
        return Response({"message": "Service deleted successfully."}, status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
@permission_classes([AllowAny])
def create_contact(request):
    """ API to handle contact form submissions """
    serializer = ContactSerializer(data=request.data)

    if serializer.is_valid():
        serializer.save()
        return Response(
            {
                "message": "Request submitted successfully! One of our executives will get in touch with you."
            },
            status=status.HTTP_201_CREATED
        )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@permission_classes([AllowAny])
def list_contacts(request):
    try:
        contacts = Contact.objects.all().order_by('-created_date')
        serializer = ContactSerializer(contacts, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        return Response(
            {"error": f"An error occurred while retrieving contacts: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(["PUT", "DELETE"])
@permission_classes([AllowAny])
def contact_detail(request, pk):
    try:
        contact = Contact.objects.get(pk=pk)
    except Contact.DoesNotExist:
        return Response({"error": "Contact not found"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'PUT':
        try:
            serializer = ContactSerializer(contact, data=request.data, partial=True)
            if serializer.is_valid():
                try:
                    serializer.save()
                    return Response(serializer.data)
                except Exception as e:
                    return Response({"error": f"Failed to update contact: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": f"Failed to update contact: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        try:
            contact.delete()
            return Response({"message": "Contact deleted successfully"}, status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            return Response({"error": f"Failed to delete contact: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
def list_contacts_by_date(request):
    """API to list contacts for a specific date"""
    date_str = request.GET.get("date")  # Get date from query parameters (YYYY-MM-DD)

    if not date_str:
        return Response({"error": "Date parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        contacts = Contact.objects.filter(created_date=date_str)  # Filter by created_date
        serializer = ContactSerializer(contacts, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


def generate_teams_meeting(start_datetime, end_datetime, subject="Consultation Meeting"):
    object_id =None
    tenant_id =None
    client_id = None
    client_secret = None
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    token_data = {
        "grant_type": "client_credentials",
        "client_id": {client_id},
        "client_secret": {client_secret},
        "scope": "https://graph.microsoft.com/.default",
    }

    token_resp = requests.post(token_url, data=token_data)
    access_token = token_resp.json().get("access_token")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    body = {
        "startDateTime": start_datetime.isoformat(),
        "endDateTime": end_datetime.isoformat(),
        "subject": subject
    }

    meeting_resp = requests.post(
        f"https://graph.microsoft.com/v1.0/users/{object_id}/onlineMeetings",
        headers=headers,
        json=body
    )

    return meeting_resp.json().get("joinUrl")


def send_customer_notification(consultation, join_url):
    # Initialize S3 client
    ses_client = boto3.client(
        'ses',
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )

    """ Sends an email notification using AWS SES """
    subject = "Consultation Booking Confirmation"
    body = f"""
    Hello {consultation.name},

    Your consultation has been successfully booked.

    📅 Date: {consultation.date}
    ⏰ Time: {consultation.time}
    📞 Mobile: {consultation.mobile_number}

    Our team will contact you soon.

    Best Regards,
    TaraFirst
    """

    response = ses_client.send_email(
        Source="admin@tarafirst.com",  # Must be verified in AWS SES
        Destination={"ToAddresses": [consultation.email]},
        Message={
            "Subject": {"Data": subject},
            "Body": {"Text": {"Data": body}},
        },
    )
    return response


#     🔗 Microsoft Teams Meeting Link:
# {join_url}

def send_admin_notification(consultation, join_url):
    # Initialize SES client
    ses_client = boto3.client(
        'ses',
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )

    """ Sends an email notification to the admin when a consultation is booked """
    subject = "New Consultation Booking Notification"
    body = f"""
    📢 New Consultation Booking Alert!

    A new consultation has been scheduled:

    🧑 Name: {consultation.name}
    📧 Email: {consultation.email}
    📞 Mobile: {consultation.mobile_number}
    📅 Date: {consultation.date}
    ⏰ Time: {consultation.time}


    Please follow up with the customer as required.

    Best Regards,
    TaraFirst Admin
    """

    response = ses_client.send_email(
        Source="admin@tarafirst.com",  # Must be verified in AWS SES
        Destination={"ToAddresses": ["admin@tarafirst.com"]},  # Replace with actual admin email
        Message={
            "Subject": {"Data": subject},
            "Body": {"Text": {"Data": body}},
        },
    )
    return response


@api_view(["POST"])
@permission_classes([AllowAny])
@rate_limit(key='ip', rate='5/h', message='Too many consultation bookings. Try again in 1 hour.')
def create_consultation(request):
    """ API to create a new consultation with 30-minute slot validation """
    serializer = ConsultationSerializer(data=request.data)

    if serializer.is_valid():
        consultation = serializer.save()
        start_time = datetime.combine(consultation.date, consultation.time).replace(tzinfo=timezone.utc)
        end_time = start_time + timedelta(minutes=30)
        # join_url = generate_teams_meeting(start_time, end_time)
        # Send email notification
        join_url = None
        send_customer_notification(consultation, join_url)
        send_admin_notification(consultation, join_url)

        return Response({"message": "Consultation booked successfully! Email sent."},
                        status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(["GET"])
@permission_classes([AllowAny])
def list_consultation(request):
    try:
        consultations = Consultation.objects.all().order_by('-created_date')
        serializer = ConsultationSerializer(consultations, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        return Response(
            {"error": f"An error occurred while retrieving contacts: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(["GET"])
@permission_classes([AllowAny])
def booked_time_slots(request):
    date_param = request.query_params.get('date', None)

    if not date_param:
        return Response(
            {"error": "Date parameter (YYYY-MM-DD) is required."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # Filter by date and get only time slots
        booked_slots = Consultation.objects.filter(
            date=date_param,
            status__in=['pending', 'reviewed', 'resolved']  # Only count active bookings
        ).values_list('time', flat=True)  # Get only time values

        # Format times as strings (e.g., "14:30")
        booked_times = [slot.strftime("%H:%M") for slot in booked_slots]

        return Response({
            "date": date_param,
            "booked_times": booked_times,
            "count": len(booked_times)
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response(
            {"error": "Invalid date or server error", "details": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(["GET"])
def list_consultations(request):
    """ API to list all consultations or filter by date """
    date = request.GET.get("date")  # User passes date as a query param (YYYY-MM-DD)

    if date:
        consultations = Consultation.objects.filter(date=date)
    else:
        consultations = Consultation.objects.all()

    serializer = ConsultationSerializer(consultations, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['PUT', 'DELETE'])
@permission_classes([AllowAny])
def consultation_detail(request, pk):
    try:
        consultation = Consultation.objects.get(pk=pk)
    except Consultation.DoesNotExist:
        return Response({"error": "Consultation not found"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'PUT':
        try:
            serializer = ConsultationSerializer(consultation, data=request.data, partial=True)
            if serializer.is_valid():
                try:
                    serializer.save()
                    return Response(serializer.data)
                except Exception as e:
                    return Response({"error": f"Failed to update consultation: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": f"Failed to update consultation: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        try:
            consultation.delete()
            return Response({"message": "Consultation deleted successfully"}, status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            return Response({"error": f"Failed to delete consultation: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)


# Add these functions at the end of the file
@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def user_detail(request, pk):
    """
    Get, update or delete a user by ID.
    """
    try:
        user = Users.objects.get(pk=pk)
    except Users.DoesNotExist:
        return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = UserSerializer(user)
        return Response(serializer.data)

    elif request.method == 'PUT':
        serializer = UserSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "message": "User updated successfully",
                "data": serializer.data
            })
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        user.delete()
        return Response({"message": "User deleted successfully"}, status=status.HTTP_204_NO_CONTENT)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def upload_business_logo(request):
    """
    Upload a logo for the user.
    """
    if request.method == 'POST':
        serializer = LogoSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'GET':
        logos = BusinessLogo.objects.all()
        serializer = LogoSerializer(logos, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def business_logo_detail(request, pk):
    """
    Get, update or delete a logo by ID.
    """
    if request.method == 'GET':
        try:
            logo = BusinessLogo.objects.get(business_id=pk)
        except BusinessLogo.DoesNotExist:
            return Response({"error": "Logo not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = LogoSerializer(logo)
        return Response(serializer.data)

    elif request.method == 'PUT':
        try:
            logo = BusinessLogo.objects.get(pk=pk)
        except BusinessLogo.DoesNotExist:
            return Response({"error": "Logo not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = LogoSerializer(logo, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        try:
            logo = BusinessLogo.objects.get(pk=pk)
        except BusinessLogo.DoesNotExist:
            return Response({"error": "Logo not found"}, status=status.HTTP_404_NOT_FOUND)
        logo.delete()
        return Response({"message": "Logo deleted successfully"}, status=status.HTTP_204_NO_CONTENT)
