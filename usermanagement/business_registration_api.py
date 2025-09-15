from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes
import boto3
from botocore.exceptions import ClientError
import logging
from Tara.settings.default import *
import json
from .get_login_data import get_login_response

from .models import (
    Users, Context, Role, UserContextRole, Module,
    ModuleFeature, UserFeaturePermission, SubscriptionPlan, ModuleSubscription, PendingUserOTP
)
from .rate_limit_decorator import rate_limit
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

# Configure logging
logger = logging.getLogger(__name__)


@extend_schema(
    operation_id='register_business',
    summary='Register Business with Module Subscription',
    description='Register a new business with user account and module subscription. Automatically creates PayrollOrg if Payroll module is selected.',
    tags=['Business Registration'],
    request={
        'application/json': {
            'type': 'object',
            'properties': {
                'email': {'type': 'string', 'format': 'email', 'description': 'Business owner email'},
                'password': {'type': 'string', 'description': 'User password'},
                'first_name': {'type': 'string', 'description': 'First name'},
                'last_name': {'type': 'string', 'description': 'Last name'},
                'mobile_number': {'type': 'string', 'description': 'Mobile number'},
                'nameOfBusiness': {'type': 'string', 'description': 'Business name'},
                'otp': {'type': 'string', 'description': 'OTP for verification'},
                'selected_modules': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'List of selected modules (e.g., ["payroll"])'
                },
                'head_office': {
                    'type': 'object',
                    'properties': {
                        'address_line1': {'type': 'string'},
                        'address_line2': {'type': 'string'},
                        'state': {'type': 'string'},
                        'city': {'type': 'string'},
                        'pincode': {'type': 'string'}
                    }
                }
            },
            'required': ['email', 'password', 'first_name', 'last_name', 'mobile_number', 'nameOfBusiness', 'otp', 'selected_modules']
        }
    },
    responses={
        201: {
            'description': 'Business registered successfully',
            'content': {
                'application/json': {
                    'example': {
                        'user_id': 123,
                        'context_id': 456,
                        'business_id': 789,
                        'access_token': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...',
                        'refresh_token': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...',
                        'payroll_org_created': True,
                        'message': 'Business registered successfully'
                    }
                }
            }
        },
        400: {
            'description': 'Bad request - validation error',
            'content': {
                'application/json': {
                    'example': {
                        'error': 'Invalid OTP or missing required fields'
                    }
                }
            }
        },
        429: {
            'description': 'Too many requests',
            'content': {
                'application/json': {
                    'example': {
                        'error': 'Too many business registration attempts. Try again in 1 hour.'
                    }
                }
            }
        }
    },
    examples=[
        OpenApiExample(
            'Business Registration Example',
            summary='Example for business registration with Payroll module',
            description='Example payload for registering a business with Payroll module',
            value={
                'email': 'owner@business.com',
                'password': 'SecurePassword123!',
                'first_name': 'John',
                'last_name': 'Doe',
                'mobile_number': '+1234567890',
                'nameOfBusiness': 'My Business',
                'otp': '123456',
                'selected_modules': ['payroll'],
                'head_office': {
                    'address_line1': '123 Main St',
                    'address_line2': 'Suite 100',
                    'state': 'California',
                    'city': 'San Francisco',
                    'pincode': '94105'
                }
            }
        )
    ]
)
@api_view(['POST'])
@permission_classes([AllowAny])
@rate_limit(key='ip', rate='3/h', message='Too many business registration attempts. Try again in 1 hour.')
def register_business(request):
    """
    Register a new business user with a module subscription and full feature permissions.

    Expected request data:
    {
        "email": "user@example.com",
        "password": "securepassword",
        "business_name": "My Business",
        "module_id": 1
    }
    """
    # Extract data from request
    email = request.data.get('email')
    password = request.data.get('password')
    business_name = request.data.get('business_name')
    module_id = request.data.get('module_id')
    submitted_otp = request.data.get('otp')

    # Validate required fields
    if not all([email, password, business_name, module_id, submitted_otp]):
        return Response(
            {"error": "Missing required fields. Please provide email, password, business_name, otp and module_id."},
            status=status.HTTP_400_BAD_REQUEST
        )
    # Check OTP
    try:
        otp_obj = PendingUserOTP.objects.get(email=email)
    except PendingUserOTP.DoesNotExist:
        return Response({'error': 'OTP not requested for this email'}, status=400)

    if otp_obj.is_expired():
        return Response({'error': 'OTP expired'}, status=400)

    if otp_obj.otp_code != submitted_otp:
        return Response({'error': 'Invalid OTP'}, status=400)

    # Validate user does not already exist
    if Users.objects.filter(email=email).exists():
        return Response({"error": "User already exists with this email."}, status=400)

    # Validate module
    try:
        module = Module.objects.get(id=module_id)
    except Module.DoesNotExist:
        return Response({"error": f"Module with ID {module_id} does not exist."}, status=404)

    # # Validate business does not exist
    # if Context.objects.filter(name__iexact=business_name).exists():
    #     return Response({"error": "Business with this name already exists."}, status=400)

    # Validate trial plan exists
    trial_plan = SubscriptionPlan.objects.filter(module=module, plan_type='trial', is_active=True).first()
    if not trial_plan:
        return Response({"error": "No active trial plan found for the selected module."}, status=400)

    # Validate module features
    module_features = ModuleFeature.objects.filter(module=module)
    if not module_features.exists():
        return Response({"error": "No features found for the selected module."}, status=400)

    try:
        # Use transaction to ensure all operations succeed or fail together
        with transaction.atomic():
            # 1. Create user
            user = Users.objects.create_user(
                email=email,
                password=password,
                status='active',
                registration_flow='module',  # Set registration flow to 'module'
                registration_completed=False,
                is_active=True,
                is_super_admin=False  # Set is_active to 'yes'
            )

            # 2. Create business context
            context = Context.objects.create(
                name=business_name,
                context_type='business',
                owner_user=user,
                status='active',
                profile_status='complete',
                metadata={}
            )

            # 3. Set active_context_id for the user
            user.active_context = context
            user.save()

            # 4. Get the module
            module = Module.objects.get(id=module_id)

            # 5. Set initial_selection to the module name
            user.initial_selection = module.name
            user.save()

            # 6. Get or create owner role for this context
            owner_role = Role.objects.get(
                context=context,
                role_type='owner'
            )

            # 7. Create user context role (owner)
            user_context_role = UserContextRole.objects.create(
                user=user,
                context=context,
                role=owner_role,
                status='active',
                added_by=user  # Self-registered
            )

            # 8. Get or create a trial subscription plan for this module
            trial_plan, created = SubscriptionPlan.objects.get_or_create(
                module=module,
                plan_type="trial",
                is_active=True

            )

            # 9. Create module subscription (trial)
            end_date = timezone.now() + relativedelta(days=30)
            module_subscription = ModuleSubscription.objects.create(
                context=context,
                module=module,
                plan=trial_plan,
                status='trial',
                start_date=timezone.now(),
                end_date=end_date,
                auto_renew=False,  # Don't auto-renew trial
                added_by=user  # Set the added_by field to the user being registered
            )

            # 10. Get all features for this module
            module_features = ModuleFeature.objects.filter(module=module)

            # 11. Create a single user feature permission with all actions
            # Collect all unique service.action combinations
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
            
            # 12. If Payroll module, create PayrollOrg
            payroll_org_response = None
            if module.name.lower() == 'payroll':
                try:
                    from .payroll_integration import handle_payroll_module_registration
                    payroll_org_response = handle_payroll_module_registration(
                        context, user, request.data
                    )
                except Exception as e:
                    # Log error but don't fail the entire registration
                    logger.error(f"Failed to create PayrollOrg during registration: {str(e)}")
                    # Continue with registration even if PayrollOrg creation fails
            
            # Delete used OTP
            otp_obj.delete()

            login_response_data = get_login_response(user)
            
            # Add PayrollOrg creation response to login data if available
            if payroll_org_response:
                login_response_data['payroll_org_creation'] = payroll_org_response

            return Response(login_response_data, status=status.HTTP_201_CREATED)

            # # 12. Send activation email - This is a required step
            # token = default_token_generator.make_token(user)
            # uid = urlsafe_base64_encode(str(user.pk).encode())
            # activation_link = f"{FRONTEND_URL}activation?uid={uid}&token={token}"
            #
            # # Initialize SES client
            # ses_client = boto3.client(
            #     'ses',
            #     region_name=AWS_REGION,
            #     aws_access_key_id=AWS_ACCESS_KEY_ID,
            #     aws_secret_access_key=AWS_SECRET_ACCESS_KEY
            # )
            #
            # subject = "Activate your account"
            # body_html = f"""
            #                     <html>
            #                     <body>
            #                         <h1>Activate Your Account</h1>
            #                         <p>Click the link below to activate your account:</p>
            #                         <a href="{activation_link}">Activate Account</a>
            #                     </body>
            #                     </html>
            #                     """
            #
            # try:
            #     # Send the email
            #     response = ses_client.send_email(
            #         Source=EMAIL_HOST_USER,
            #         Destination={'ToAddresses': [email]},
            #         Message={
            #             'Subject': {'Data': subject},
            #             'Body': {
            #                 'Html': {'Data': body_html},
            #                 'Text': {'Data': f"Activate your account using the link: {activation_link}"}
            #             },
            #         }
            #     )
            #     logger.info(f"Activation email sent to: {email}")
            #
            #     # Return success response with activation information
            #     return Response(
            #         {
            #             "message": "Business registration successful. Check your email for activation link.",
            #             "user_id": user.id,
            #             "context_id": context.id,
            #             "module_subscription_id": module_subscription.id,
            #             "trial_end_date": end_date,
            #             "active_context_id": user.active_context.id,
            #             "initial_selection": user.initial_selection,
            #             "registration_flow": user.registration_flow
            #         },
            #         status=status.HTTP_201_CREATED
            #     )
            # except ClientError as e:
            #     # Log the error but don't fail the registration
            #     logger.error(f"Failed to send email via SES: {e.response['Error']['Message']}")
            #
            #     # Return success response but note the email failure
            #     return Response(
            #         {
            #             "message": "Business registration successful, but failed to send activation email. "
            #                        "Please contact support.",
            #             "user_id": user.id,
            #             "context_id": context.id,
            #             "module_subscription_id": module_subscription.id,
            #             "trial_end_date": end_date,
            #             "activation_link": activation_link,  # Include the activation link in the response
            #             "active_context_id": user.active_context.id,
            #             "initial_selection": user.initial_selection,
            #             "registration_flow": user.registration_flow
            #         },
            #         status=status.HTTP_201_CREATED
            #     )

    except Module.DoesNotExist:
        return Response(
            {"error": f"Module with ID {module_id} does not exist."},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {"error": f"Registration failed: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_another_context(request):
    """
    Add another context to an existing user. The user will be the owner of the new context.

    Expected request data:
    {
        "business_name": "My New Business",
        "module_id": 1,
        "subscription_plan_id": 123,  # Optional: If not provided, a free trial will be created
        "user_id": 456  # Optional: If not provided, the authenticated user will be used
    }
    """
    # Extract data from request
    business_name = request.data.get('business_name')
    module_id = request.data.get('module_id')
    subscription_plan_id = request.data.get('subscription_plan_id')
    user_id = request.data.get('user_id')
    authenticated_user = request.user  # Get the authenticated user

    # Validate required fields
    if not all([business_name, module_id]):
        return Response(
            {"error": "Missing required fields. Please provide business_name and module_id."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # Determine which user to use
        if user_id:
            # Check if the authenticated user has permission to add context for another user
            # This is a simple check - you might want to implement more sophisticated permission logic
            # if not authenticated_user.is_staff and not authenticated_user.is_superuser:
            #     return Response(
            #         {"error": "You don't have permission to add a context for another user."},
            #         status=status.HTTP_403_FORBIDDEN
            #     )

            # Get the specified user
            try:
                user = Users.objects.get(id=user_id)
            except Users.DoesNotExist:
                return Response(
                    {"error": f"User with ID {user_id} does not exist."},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            # Use the authenticated user
            user = authenticated_user

        # Use transaction to ensure all operations succeed or fail together
        with transaction.atomic():
            # 1. Create business context
            context = Context.objects.create(
                name=business_name,
                context_type='business',
                owner_user=user,
                status='active',
                profile_status='complete',
                metadata={}
            )

            # 2. Create UserSession for the new context
            from .models import UserSession
            user_session = UserSession.objects.create(
                user=user,
                active_context=context,
                is_active=True,
                default_session=False,  # Don't make it default since user might have other contexts
                session_data={'context_type': 'business', 'added_by': 'add_another_context'}
            )

            # 3. Get or create owner role for this context
            owner_role = Role.objects.get(
                context=context,
                role_type='owner'
            )

            # 4. Create user context role (owner)
            user_context_role = UserContextRole.objects.create(
                user=user,
                context=context,
                role=owner_role,
                status='active',
                added_by=authenticated_user  # The user who is performing the action
            )

            # 5. Get the module
            module = Module.objects.get(id=module_id)

            # 6. Determine which subscription plan to use
            if subscription_plan_id:
                # User provided a subscription plan ID
                try:
                    subscription_plan = SubscriptionPlan.objects.get(id=subscription_plan_id)
                    subscription_type = 'paid'
                    auto_renew = request.data.get('auto_renew', False)
                except SubscriptionPlan.DoesNotExist:
                    return Response(
                        {"error": f"Subscription plan with ID {subscription_plan_id} does not exist."},
                        status=status.HTTP_404_NOT_FOUND
                    )
            else:
                # No subscription plan provided, create a trial
                subscription_plan, created = SubscriptionPlan.objects.get_or_create(
                    module=module,
                    plan_type="trial",
                    is_active=True
                )
                subscription_type = 'trial'
                auto_renew = False

            # 7. Create module subscription
            if subscription_type == 'trial':
                end_date = timezone.now() + relativedelta(days=30)
                subscription_status = 'trial'
            else:
                # For paid subscriptions, use the plan's billing cycle
                end_date = timezone.now() + relativedelta(days=subscription_plan.billing_cycle_days)
                subscription_status = 'active'

            module_subscription = ModuleSubscription.objects.create(
                context=context,
                module=module,
                plan=subscription_plan,
                status=subscription_status,
                start_date=timezone.now(),
                end_date=end_date,
                auto_renew=auto_renew,
                added_by=authenticated_user  # The user who is performing the action
            )

            # 8. Get all features for this module
            module_features = ModuleFeature.objects.filter(module=module)

            # 9. Create a single user feature permission with all actions
            # Collect all unique service.action combinations
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
                created_by=authenticated_user  # The user who is performing the action
            )

            # Return success response
            return Response(
                {
                    "message": f"New business context added successfully with {subscription_type} subscription.",
                    "user_id": user.id,
                    "context_id": context.id,
                    "module_subscription_id": module_subscription.id,
                    "subscription_type": subscription_type,
                    "subscription_plan_id": subscription_plan.id,
                    "subscription_plan_name": subscription_plan.name,
                    "end_date": end_date,
                    "auto_renew": auto_renew,
                    "active_context_id": user_session.active_context.id if user_session else None
                },
                status=status.HTTP_201_CREATED
            )

    except Module.DoesNotExist:
        return Response(
            {"error": f"Module with ID {module_id} does not exist."},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {"error": f"Failed to add new context: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_permissions(request):
    """
    Retrieve permissions for a user based on user context role and module_id.

    Expected query parameters:
    - user_context_role_id: ID of the user context role
    - module_id: ID of the module

    Returns:
    {
        "user_context_role_id": 9,
        "module_id": 1,
        "actions": ["EmployeeManagement.create", "EmployeeManagement.read", ...],
        "is_active": "yes",
        "created_at": "2025-04-21T07:13:39.524Z",
        "updated_at": "2025-04-21T07:13:39.524Z"
    }
    """
    # Extract query parameters
    user_context_role_id = request.query_params.get('user_context_role_id')
    module_id = request.query_params.get('module_id')

    # Validate required parameters
    if not all([user_context_role_id, module_id]):
        return Response(
            {"error": "Missing required parameters. Please provide user_context_role_id and module_id."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # Get user context role
        try:
            user_context_role = UserContextRole.objects.get(id=user_context_role_id)
        except UserContextRole.DoesNotExist:
            return Response(
                {"error": "User context role not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Get module
        try:
            module = Module.objects.get(id=module_id)
        except Module.DoesNotExist:
            return Response(
                {"error": "Module not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Get user feature permission
        try:
            permission = UserFeaturePermission.objects.get(
                user_context_role=user_context_role,
                module=module,
                is_active=True
            )

            # Parse actions from JSON string if needed
            actions = permission.actions
            if isinstance(actions, str):
                try:
                    actions = json.loads(actions)
                except json.JSONDecodeError:
                    actions = [actions]

            # Format response
            response_data = {
                "user_context_role_id": user_context_role_id,
                "module_id": module_id,
                "actions": actions,
                "is_active": permission.is_active,
                "created_at": permission.created_at.isoformat() if permission.created_at else None,
                "updated_at": permission.updated_at.isoformat() if permission.updated_at else None
            }

            return Response(response_data, status=status.HTTP_200_OK)

        except UserFeaturePermission.DoesNotExist:
            # If no permission exists, return empty actions list
            return Response({
                "user_context_role_id": user_context_role_id,
                "module_id": module_id,
                "actions": [],
                "is_active": False,
                "created_at": None,
                "updated_at": None
            }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error retrieving user permissions: {str(e)}")
        return Response(
            {"error": f"An error occurred while retrieving user permissions: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_context_details_using_business(request):
    """
    Retrieve context details using business id.

    Expected query parameters:
    - business_id: id of the business

    Returns:
    {
        "context_id": 1,
        "business_id": 1,
        "owner_user_id": 123,
        "status": "active",
        "profile_status": "complete",
        "created_at": "2025-04-21T07:13:39.524Z",
        "updated_at": "2025-04-21T07:13:39.524Z"
    }
    """
    # Extract query parameter
    business_id = request.query_params.get('business_id')

    # Validate required parameter
    if not business_id:
        return Response(
            {"error": "Missing required parameter. Please provide business id."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # Get context by business name (case-insensitive)
        try:
            context = Context.objects.get(business__id=business_id)
        except Context.DoesNotExist:
            return Response(
                {"error": f"Context with business id '{business_id}' not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Format response
        response_data = {
            "context_id": context.id,
            "business_name": context.business.nameOfBusiness,
            "owner_user_id": context.owner_user.id if context.owner_user else None,
            "status": context.status,
            "profile_status": context.profile_status,
            "created_at": context.created_at.isoformat() if context.created_at else None,
            "updated_at": context.updated_at.isoformat() if context.updated_at else None
        }

        return Response(response_data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error retrieving context details: {str(e)}")
        return Response(
            {"error": f"An error occurred while retrieving context details: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )