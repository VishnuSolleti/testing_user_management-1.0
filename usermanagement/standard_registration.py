from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
import uuid
import json
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from .models import (
    Context, Role, UserContextRole, Module,
    ModuleFeature, UserFeaturePermission
)
from django.db import IntegrityError
from .models import *
import boto3
from botocore.exceptions import ClientError
from .rate_limit_decorator import rate_limit
import logging
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import *
from .get_login_data import get_login_response


User = get_user_model()
# Configure logging
logger = logging.getLogger(__name__)


# @api_view(['POST'])
# @permission_classes([AllowAny])
# def initial_registration(request):
#     """
#     Initial registration API that creates a user with email and password,
#     and sends an activation email.
#
#     Expected request data:
#     {
#         "email": "user@example.com",
#         "password": "securepassword"
#     }
#     """
#     # Extract data from request
#     email = request.data.get('email')
#     submitted_otp = request.data.get('otp')
#     password = request.data.get('password')
#
#     # Validate required fields
#     if not all([email, password, submitted_otp]):
#         return Response(
#             {"error": "Missing required fields. Please provide email, otp and password."},
#             status=status.HTTP_400_BAD_REQUEST
#         )
#     try:
#         otp_obj = PendingUserOTP.objects.get(email=email)
#     except PendingUserOTP.DoesNotExist:
#         return Response({'error': 'OTP not requested for this email'}, status=status.HTTP_400_BAD_REQUEST)
#
#     if otp_obj.is_expired():
#         return Response({'error': 'OTP expired'}, status=status.HTTP_400_BAD_REQUEST)
#
#     if otp_obj.otp_code != submitted_otp:
#         return Response({'error': 'Invalid OTP'}, status=status.HTTP_400_BAD_REQUEST)
#
#     try:
#         # Check if user already exists
#         if User.objects.filter(email=email).exists():
#             return Response(
#                 {"error": "A user with this email already exists."},
#                 status=status.HTTP_400_BAD_REQUEST
#             )
#
#         # Create user
#         user = User.objects.create(
#             email=email,
#             status='invited',
#             registration_flow='standard',
#             registration_completed='no',
#             is_active='no',
#             is_super_admin=False,
#         )
#         user.set_password(password)
#         user.save()
#
#         # Generate activation token
#         # 12. Send activation email - This is a required step
#         token = default_token_generator.make_token(user)
#         uid = urlsafe_base64_encode(str(user.pk).encode())
#         activation_link = f"{FRONTEND_URL}activation?uid={uid}&token={token}"
#
#         # Initialize SES client
#         ses_client = boto3.client(
#             'ses',
#             region_name=AWS_REGION,
#             aws_access_key_id=AWS_ACCESS_KEY_ID,
#             aws_secret_access_key=AWS_SECRET_ACCESS_KEY
#         )
#
#         subject = "Activate your account"
#         body_html = f"""
#                                         <html>
#                                         <body>
#                                             <h1>Activate Your Account</h1>
#                                             <p>Click the link below to activate your account:</p>
#                                             <a href="{activation_link}">Activate Account</a>
#                                         </body>
#                                         </html>
#                                         """
#
#         try:
#             # Send the email
#             response = ses_client.send_email(
#                 Source=EMAIL_HOST_USER,
#                 Destination={'ToAddresses': [email]},
#                 Message={
#                     'Subject': {'Data': subject},
#                     'Body': {
#                         'Html': {'Data': body_html},
#                         'Text': {'Data': f"Activate your account using the link: {activation_link}"}
#                     },
#                 }
#             )
#             logger.info(f"Activation email sent to: {email}")
#
#             # Return success response
#             return Response({
#                 "message": "Registration successful. Please check your email to activate your account.",
#                 "user_id": user.id,
#                 "email": user.email
#             }, status=status.HTTP_201_CREATED)
#         except ClientError as e:
#             # Log the error but don't fail the registration
#             logger.error(f"Failed to send email via SES: {e.response['Error']['Message']}")
#
#             # Return success response but note the email failure
#             return Response(
#                 {
#                     "message": "User registration successful, but failed to send activation email. "
#                                "Please contact support.",
#                     "user_id": user.id,
#                     "activation_link": activation_link,  # Include the activation link in the response
#                     "registration_flow": user.registration_flow
#                 },
#                 status=status.HTTP_201_CREATED)
#     except Exception as e:
#         return Response(
#             {"error": f"Registration failed: {str(e)}"},
#             status=status.HTTP_500_INTERNAL_SERVER_ERROR
#         )


@api_view(['POST'])
@permission_classes([AllowAny])
@rate_limit(key='ip', rate='3/h', message='Too many registration attempts. Try again in 1 hour.')
def initial_registration(request):
    """
    Final step of registration that creates a user after OTP verification.

    Expected request data:
    {
        "email": "user@example.com",
        "otp": "123456",
        "password": "securepassword"
    }
    """
    email = request.data.get('email')
    submitted_otp = request.data.get('otp')
    password = request.data.get('password')

    if not all([email, password, submitted_otp]):
        return Response(
            {"error": "Missing required fields. Please provide email, otp and password."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        otp_obj = PendingUserOTP.objects.get(email=email)
    except PendingUserOTP.DoesNotExist:
        return Response({'error': 'OTP not requested for this email'}, status=status.HTTP_400_BAD_REQUEST)

    if otp_obj.is_expired():
        return Response({'error': 'OTP expired'}, status=status.HTTP_400_BAD_REQUEST)

    if otp_obj.otp_code != submitted_otp:
        return Response({'error': 'Invalid OTP'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(email=email).exists():
        return Response(
            {"error": "A user with this email already exists."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        user = User.objects.create(
            email=email,
            status='active',
            is_active=True,  # Now activate the user directly
            is_super_admin=False,
        )
        user.set_password(password)
        user.save()

        # Update UserRegistration (created by signal)
        from .models import UserRegistration
        try:
            user_registration = user.userregistration
            user_registration.registration_flow = 'standard'
            user_registration.registration_completed = False
            user_registration.registration_status = 'incomplete'
            user_registration.steps_completed = ['user_created']
            user_registration.save()
        except:
            pass

        # OTP is now used; delete it
        otp_obj.delete()
        login_response_data = get_login_response(user)

        response = Response(login_response_data, status=status.HTTP_201_CREATED)
        # Cookie settings for cross-subdomain support
        cookie_domain = '.tarafirst.com'  # Works across all subdomains
        cookie_secure = False  # Allow HTTP for testing

        # Debug: Log what domain we're setting
        print(f"DEBUG: Setting cookies with domain={cookie_domain}, secure={cookie_secure}")
        print(f"DEBUG: Request host={request.get_host()}")

        # Set environment-aware cookies
        response.set_cookie(
            'access_token',
            str(login_response_data.get('access_token')),
            domain=cookie_domain,  # localhost for testing
            secure=cookie_secure,  # False for HTTP
            httponly=True,  # No JS access (XSS protection)
            samesite='Lax',  # Lax for local testing (works with same domain)
            max_age=43200  # 12 hours
        )

        response.set_cookie(
            'refresh_token',
            login_response_data.get('refresh_token'),
            domain=cookie_domain,  # localhost for testing
            secure=cookie_secure,  # False for HTTP
            httponly=True,  # No JS access (XSS protection)
            samesite='Lax',  # Lax for local testing
            max_age=86400  # 24 hours
        )

        # Set user context cookie for frontend state management
        response.set_cookie(
            'user_context',
            str(context_id) if context_id else '',
            domain=cookie_domain,
            secure=cookie_secure,
            httponly=False,  # Allow JS access for context switching
            samesite='Lax',  # Lax for local testing
            max_age=86400
        )

        # Set active service cookie for service detection
        response.set_cookie(
            'active_service',
            detected_service.get('service_key', ''),
            domain=cookie_domain,
            secure=cookie_secure,
            httponly=False,  # Allow JS access for service routing
            samesite='Lax',  # Lax for local testing
            max_age=86400
        )

        # Set organization cookie for multi-tenant support
        response.set_cookie(
            'organization_id',
            str(organization_id) if organization_id else '',
            domain=cookie_domain,
            secure=cookie_secure,
            httponly=False,  # Allow JS access for organization context
            samesite='Lax',  # Lax for local testing
            max_age=86400
        )

    except Exception as e:
        logger.error(f"Error during registration: {str(e)}")
        return Response(
            {"error": f"Registration failed: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def select_context(request):
    user_id = request.data.get('user_id')
    context_type = request.data.get('context_type')
    user_kyc_data = request.data.get('user_kyc', {})
    business_data = request.data.get('business_details', {})

    if not user_id or context_type not in ['personal', 'business']:
        return Response(
            {"error": "Missing required fields. Provide user_id and valid context_type."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        user = User.objects.get(id=user_id)
        if not user.is_active:
            return Response({"error": "User is not active."}, status=status.HTTP_403_FORBIDDEN)

        if context_type == 'personal':
            # Ensure only one personal context per user
            if hasattr(user, 'userkyc'):
                return Response({"error": "Personal context already exists for this user."}, status=status.HTTP_400_BAD_REQUEST)

            name = user_kyc_data.get('name')
            if not name:
                return Response({"error": "Missing name in user_kyc data."}, status=status.HTTP_400_BAD_REQUEST)

            # Validate UserKYC data
            kyc_serializer = UsersKYCSerializer(data=user_kyc_data, context={'request': request, 'user': user})
            kyc_serializer.is_valid(raise_exception=True)

            # Create Context
            context = Context.objects.create(
                name=name,
                context_type='personal',
                owner_user=user,
                metadata={}
            )

            # Save UserKYC with associated user
            kyc_serializer.save(user=user)

        else:
            business_name = business_data.get('nameOfBusiness')
            if not business_name:
                return Response({"error": "Missing nameOfBusiness in business_details."}, status=status.HTTP_400_BAD_REQUEST)

            # Validate Business Data
            business_data_with_client = {**business_data, 'client': user.id}
            business_serializer = BusinessSerializer(data=business_data_with_client)
            business_serializer.is_valid(raise_exception=True)

            # Create Context
            context = Context.objects.create(
                name=business_name,
                context_type='business',
                owner_user=user,
                metadata={}
            )

            # Business should be auto-created via signal
            business = getattr(context, 'business', None)
            if not business:
                return Response({"error": "Business creation via signal failed."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # Update business with validated data
            business_serializer = BusinessSerializer(business, data=business_data, partial=True)
            business_serializer.is_valid(raise_exception=True)
            business_serializer.save()

        # Assign role and make this the active context
        role = Role.objects.get(name='Owner', context=context)
        UserContextRole.objects.create(user=user, context=context, role=role, status='active', added_by=user)
        
        # Create UserSession for the new context
        from .models import UserSession
        user_session = UserSession.objects.create(
            user=user,
            active_context=context,
            is_active=True,
            default_session=True,  # Set as default since it's their first context selection
            session_data={'context_type': context_type, 'created_by': 'select_context'}
        )

        return Response({
            "message": f"{context_type.capitalize()} context created successfully.",
            "user_id": user.id,
            "context_id": context.id,
            "context_type": context.context_type,
            "context_name": context.name,
            "user_session_id": user_session.id,
            "active_context_id": user_session.active_context.id
        }, status=status.HTTP_201_CREATED)

    except User.DoesNotExist:
        return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
    except ValidationError as e:
        return Response({"error": e.message_dict if hasattr(e, 'message_dict') else str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({"error": f"Context selection failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([AllowAny])
def subscribe_business_suite(request):
    """
    Subscribe a business context to a suite and set up module-wise feature permissions.

    Expected request data:
    {
        "user_id": 1,
        "context_id": 1,
        "suite_id": 1,
        "subscription_type": "monthly" or "yearly",
        "auto_renew": true or false
    }
    """
    # Extract data from request
    user_id = request.data.get('user_id')
    context_id = request.data.get('context_id')
    suite_id = request.data.get('suite_id')
    subscription_type = request.data.get('subscription_type', 'monthly')
    auto_renew = request.data.get('auto_renew', False)

    # Validate required fields
    if not all([user_id, context_id, suite_id]):
        return Response(
            {"error": "Missing required fields. Please provide user_id, context_id, and suite_id."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Validate subscription type
    if subscription_type not in ['monthly', 'yearly']:
        return Response(
            {"error": "Invalid subscription type. Must be 'monthly' or 'yearly'."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # Get user
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {"error": "User not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Get context
        try:
            context = Context.objects.get(id=context_id)
        except Context.DoesNotExist:
            return Response(
                {"error": "Context not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Check if context belongs to user
        if context.created_by != user:
            return Response(
                {"error": "Context does not belong to the user."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Check if context is business type
        if context.context_type != 'business':
            return Response(
                {"error": "Only business contexts can subscribe to suites."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get suite
        try:
            suite = Suite.objects.get(id=suite_id)
        except Suite.DoesNotExist:
            return Response(
                {"error": "Suite not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Get subscription plan based on subscription type
        try:
            subscription_plan = SubscriptionPlan.objects.get(
                suite=suite,
                billing_cycle=subscription_type
            )
        except SubscriptionPlan.DoesNotExist:
            return Response(
                {"error": f"No {subscription_type} subscription plan found for this suite."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Get user context role
        try:
            user_context_role = UserContextRole.objects.get(
                user=user,
                context=context,
                status='active'
            )
        except UserContextRole.DoesNotExist:
            return Response(
                {"error": "User context role not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        context_suite = ContextSuiteSubscription.objects.create(
            context=context,
            plan=subscription_plan,
            status='active',
            start_date=timezone.now(),
            end_date=timezone.now() + timezone.timedelta(days=30 if subscription_type == 'monthly' else 365),
            auto_renew=auto_renew
        )

        # Create module subscriptions for each module in the suite
        module_subscriptions = []
        for module in suite.modules.all():
            # Create module subscription
            module_subscription = ModuleSubscription.objects.create(
                context=context,
                module=module,
                plan=subscription_plan,
                status='active',
                start_date=timezone.now(),
                end_date=timezone.now() + timezone.timedelta(days=30 if subscription_type == 'monthly' else 365),
                auto_renew=auto_renew,
                via_suite=True,
                suite_subscription=context_suite
            )
            module_subscriptions.append(module_subscription)

            # Get all features for this module
            module_features = ModuleFeature.objects.filter(module=module)

            all_actions = []
            for feature in module_features:
                action = f"{feature.service}.{feature.action}"
                if action not in all_actions:
                    all_actions.append(action)

            # Create a single user feature permission with all actions
            UserFeaturePermission.objects.create(
                user_context_role=user_context_role,
                module=module,
                actions=all_actions,  # All service.action combinations
                is_active=True,
                created_by=user  # Set the created_by field to the user being registered
            )

        # Return success response
        return Response({
            "message": "Business suite subscription created successfully.",
            "user_id": user.id,
            "context_id": context.id,
            "suite_id": suite.id,
            "subscription_type": subscription_type,
            "auto_renew": auto_renew,
            "start_date": context_suite.start_date,
            "end_date": context_suite.end_date,
            "module_subscriptions": [
                {
                    "module_id": sub.module.id,
                    "module_name": sub.module.name,
                    "status": sub.status,
                    "start_date": sub.start_date,
                    "end_date": sub.end_date
                } for sub in module_subscriptions
            ]
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response(
            {"error": f"Business suite subscription failed: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def subscribe_to_module(request):
    """
    Subscribe a context to a specific module with a selected plan and assign feature permissions.

    Expected request:
    {
        "user_id": 1,
        "context_id": 1,
        "module_id": 1,
        "subscription_plan_id": 5,
        "user_context_role_id": 3
    }
    """
    user_id = request.data.get('user_id')
    context_id = request.data.get('context_id')
    module_id = request.data.get('module_id')
    subscription_plan_id = request.data.get('subscription_plan_id')
    user_context_role_id = request.data.get('user_context_role_id')

    # Validate input
    if not all([user_id, context_id, module_id, subscription_plan_id, user_context_role_id]):
        return Response(
            {"error": "Missing required fields."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        user = User.objects.get(id=user_id)
        context = Context.objects.get(id=context_id)
        module = Module.objects.get(id=module_id)
        plan = SubscriptionPlan.objects.get(id=subscription_plan_id)
        user_context_role = UserContextRole.objects.get(id=user_context_role_id)

        # Validate context match
        if user_context_role.context.id != context.id:
            return Response(
                {"error": "User context role does not match the provided context."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create subscription
        end_date = timezone.now() + relativedelta(days=plan.billing_cycle_days)

        module_subscription = ModuleSubscription.objects.create(
            context=context,
            module=module,
            plan=plan,
            status='active' if plan.plan_type != 'trial' else 'trial',
            start_date=timezone.now(),
            end_date=end_date,
            auto_renew='yes' if plan.plan_type != 'trial' else 'no'
        )

        # Create user feature permissions
        module_features = ModuleFeature.objects.filter(module=module)

        all_actions = []
        for feature in module_features:
            action = f"{feature.service}.{feature.action}"
            if action not in all_actions:
                all_actions.append(action)

        UserFeaturePermission.objects.create(
            user_context_role=user_context_role,
            module=module,
            actions=all_actions,
            is_active=True,
            created_by=user
        )

        return Response({
            "message": "Module subscription created successfully.",
            "module_id": module.id,
            "module_name": module.name,
            "subscription_status": module_subscription.status,
            "start_date": module_subscription.start_date,
            "end_date": module_subscription.end_date,
            "plan": plan.name
        }, status=status.HTTP_201_CREATED)

    except (User.DoesNotExist, Context.DoesNotExist, Module.DoesNotExist,
            SubscriptionPlan.DoesNotExist, UserContextRole.DoesNotExist) as e:
        return Response(
            {"error": f"{e.__class__.__name__.replace('DoesNotExist', '')} not found."},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {"error": f"Module subscription failed: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def token_refresh(request):
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


#dharma
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def user_registration_create_for_employee(request):
    """
    API endpoint to create a user registration entry for an employee.
    """
    data = request.data
    authenticated_user = request.user

    with transaction.atomic():
        try:
            user = User.objects.create_user(
                email=data.get('email'),
                is_active=True,
                status='active',
                is_super_admin=False,
                password=data.get('password'),
                created_by=authenticated_user
            )
            print(user)
        except IntegrityError:
            return Response({"error": "User with this email already exists."}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": f"Failed to create user: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response({
        "success": True,
        "message": "User created successfully",
        "user_id": user.id
    }, status=status.HTTP_201_CREATED)

