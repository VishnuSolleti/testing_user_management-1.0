from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from django.contrib.auth.tokens import default_token_generator, PasswordResetTokenGenerator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
import boto3
from botocore.exceptions import ClientError
import logging
from Tara.settings.default import *
from django.utils.http import urlsafe_base64_decode
from .models import (
    Users, Context, Role, UserContextRole, Module,
    ModuleFeature, UserFeaturePermission, SubscriptionPlan, ModuleSubscription, ModuleUsageCycle
)
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from .usage_limits import get_usage_entry, increment_usage

# Configure logging
logger = logging.getLogger(__name__)


class InvitationTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, user, timestamp):
        """
        Generate a hash value that doesn't depend on user's password or last login.
        Only depends on user ID and timestamp.
        """
        return f"{user.pk}{timestamp}"


invitation_token_generator = InvitationTokenGenerator()


def get_default_permissions_by_role(role_type, module_features):
    """
    Get default permissions based on role type and available module features.

    Args:
        role_type (str): The type of role (owner, admin, manager, employee)
        module_features (list): List of available module features

    Returns:
        dict: Dictionary with module_id as key and list of service actions as value
    """
    default_permissions = {}

    # Group features by module
    module_features_map = {}
    for feature in module_features:
        module_id = feature['module']
        if module_id not in module_features_map:
            module_features_map[module_id] = []
        module_features_map[module_id].append(feature)

    # Define permission sets based on role type
    if role_type in ['owner', 'admin']:
        # Full access - all actions
        for module_id, features in module_features_map.items():
            service_actions = []
            for feature in features:
                service_actions.append(f"{feature['service']}.{feature['action']}")
            default_permissions[module_id] = service_actions

    elif role_type == 'manager':
        # Manager access - create, read, update, approve (no delete)
        for module_id, features in module_features_map.items():
            service_actions = []
            for feature in features:
                if feature['action'] != 'delete':
                    service_actions.append(f"{feature['service']}.{feature['action']}")
            default_permissions[module_id] = service_actions

    else:  # employee
        # Employee access - create, read, update (no delete or approve)
        for module_id, features in module_features_map.items():
            service_actions = []
            for feature in features:
                if feature['action'] not in ['delete', 'approve']:
                    service_actions.append(f"{feature['service']}.{feature['action']}")
            default_permissions[module_id] = service_actions

    return default_permissions


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_team_member_to_business(request):
    """
    Add a team member to a business context with a specific role and permissions.
    If permissions are not provided, default permissions will be set based on the role type.
    """
    # Extract data from request
    context_id = request.data.get('context_id')
    email = request.data.get('email')
    first_name = request.data.get('first_name')
    last_name = request.data.get('last_name')
    mobile_number = request.data.get('mobile_number')
    role_id = request.data.get('role_id')
    permissions = request.data.get('permissions', [])
    authenticated_user = request.user

    # Validate required fields
    if not all([context_id, email,role_id]):
        return Response(
            {
                "error": "Missing required fields. Please provide context_id, email, role_id."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # Get the context first to check subscriptions
        context = Context.objects.get(id=context_id)

        # Check if the context is a business context
        if context.context_type != 'business':
            return Response(
                {"error": "Team members can only be added to business contexts."},
                status=status.HTTP_400_BAD_REQUEST
            )
            # ✅ Validate usage entry AFTER getting the context
        if not context.is_platform_context:
            # Get usage entry
            usage_entry, error_response = get_usage_entry(context_id, "users_count")
            if error_response:
                return error_response

            # Count pending invites
            pending_invites = UserContextRole.objects.filter(
                context_id=context_id,
                status='pending'
            ).count()

            remaining_slots = int(usage_entry.actual_count) - int(usage_entry.usage_count) - pending_invites
            if remaining_slots <= 0:
                return Response(
                    {"error": "User limit reached or pending invitations already occupy available slots."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Get all active subscriptions for this context
        active_subscriptions = ModuleSubscription.objects.filter(
            context=context,
            status__in=['active', 'trial']
        ).values_list('module_id', flat=True)

        # if not active_subscriptions:
        #     return Response(
        #         {"error": "This context has no active module subscriptions."},
        #         status=status.HTTP_400_BAD_REQUEST
        #     )

        # Get the role
        if role_id:
            try:
                role = Role.objects.get(id=role_id, context=context)
            except Role.DoesNotExist:
                return Response(
                    {"error": f"Role with ID {role_id} does not exist in this context."},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            # Get the default employee role
            role = Role.objects.get(
                context=context,
                role_type='employee',
                is_default_role=True
            )

        # If no permissions provided, get default permissions based on role type
        if not permissions:
            # Get all module features for subscribed modules
            module_features = ModuleFeature.objects.filter(
                module_id__in=active_subscriptions
            ).values('id', 'module', 'service', 'action', 'label')

            # Convert to list for easier processing
            module_features_list = list(module_features)

            # Get default permissions based on role type
            permissions = [
                {
                    "module_id": module_id,
                    "service_actions": service_actions
                }
                for module_id, service_actions in get_default_permissions_by_role(
                    role.role_type,
                    module_features_list
                ).items()
            ]

        # Validate permission format and module existence
        for permission_data in permissions:
            module_id = permission_data.get('module_id')
            service_actions = permission_data.get('service_actions', [])

            if not module_id or not service_actions:
                return Response(
                    {"error": "Invalid permission format. Each permission must include module_id and service_actions."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check if module exists
            try:
                module = Module.objects.get(id=module_id)
            except Module.DoesNotExist:
                return Response(
                    {"error": f"Module with ID {module_id} does not exist."},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Check if context is subscribed to this module
            if module_id not in active_subscriptions:
                return Response(
                    {
                        "error": f"Context is not subscribed to module {module.name}. Please subscribe to the module first."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Use transaction to ensure all operations succeed or fail together
        with transaction.atomic():
            # 1. Check if user already exists
            try:
                user = Users.objects.get(email=email)
                # If user exists, check if they already have a role in this context
                existing_role = UserContextRole.objects.filter(
                    user=user,
                    context=context,
                    status='active'
                ).first()

                if existing_role:
                    return Response(
                        {"error": f"User with email {email} already has an active role in this context."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Check if there's a pending invitation
                pending_role = UserContextRole.objects.filter(
                    user=user,
                    context=context,
                    status='pending'
                ).first()

                if pending_role:
                    return Response(
                        {"error": f"User with email {email} already has a pending invitation to this context."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                is_new_user = False
            except Users.DoesNotExist:
                # Create new user if they don't exist
                if not all([first_name, last_name, mobile_number]):
                    return Response(
                        {"error": "New user must provide first_name, last_name, and mobile_number."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                # Create user with only authentication fields
                user = Users.objects.create(
                    email=email,
                    status='invited',
                    is_active=False,
                    created_by=authenticated_user,
                    is_super_admin=False
                )
                is_new_user = True
                
                # Create UserProfile for personal information
                from .models import UserProfile
                UserProfile.objects.create(
                    user=user,
                    first_name=first_name,
                    last_name=last_name,
                    mobile_number=mobile_number
                )
                
                # Create UserRegistration for new invited user
                from .models import UserRegistration
                UserRegistration.objects.create(
                    user=user,
                    registration_flow='standard',
                    initial_selection='team_invitation',
                    registration_completed=False,
                    registration_status='invited',
                    steps_completed=['user_created', 'invited_to_team']
                )
                
                # Create UserSession for invited user (they'll be activated when they accept)
                from .models import UserSession
                UserSession.objects.create(
                    user=user,
                    active_context=context,  # Set the context they're invited to
                    is_active=False,  # Not active until they accept invitation
                    default_session=True,  # Set as default since it's their first session
                    session_data={'invitation_status': 'pending', 'invited_to_context': context.id}
                )

            # 2. Create user context role with pending status
            user_context_role = UserContextRole.objects.create(
                user=user,
                context=context,
                role=role,
                status='pending',  # Set to pending until the user accepts
                added_by=authenticated_user
            )
            # 3. Set up feature permissions
            for permission_data in permissions:
                module_id = permission_data.get('module_id')
                service_actions = permission_data.get('service_actions', [])
                module = Module.objects.get(id=module_id)

                UserFeaturePermission.objects.create(
                    user_context_role=user_context_role,
                    module=module,
                    actions=service_actions,
                    is_active=True,
                    created_by=authenticated_user
                )

            # 4. Send invitation email
            try:
                # Generate invitation token
                token = invitation_token_generator.make_token(user)
                uid = urlsafe_base64_encode(str(user.pk).encode())
                invitation_link = f"{FRONTEND_URL}accept-invitation?uid={uid}&token={token}"

                # Initialize SES client
                ses_client = boto3.client(
                    'ses',
                    region_name=AWS_REGION,
                    aws_access_key_id=AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
                )

                # Prepare email content
                business_name = context.name
                # Get owner name from UserProfile
                try:
                    owner_profile = authenticated_user.userprofile
                    owner_name = f"{owner_profile.first_name} {owner_profile.last_name}"
                except:
                    owner_name = authenticated_user.email
                role_name = role.name

                subject = f"Invitation to join {business_name}"

                if is_new_user:
                    # Generate temporary password for new user
                    temp_password = Users.objects.make_random_password()
                    user.set_password(temp_password)
                    user.save()

                    body_html = f"""
                    <html>
                    <body>
                        <h1>Join {business_name}</h1>
                        <p>Hello {first_name},</p>
                        <p>{owner_name} has invited you to join {business_name} as a {role_name}.</p>
                        <p>Your temporary login credentials are:</p>
                        <p>Email: {email}</p>
                        <p>Password: {temp_password}</p>
                        <p>Please click the link below to accept the invitation:</p>
                        <a href="{invitation_link}">Accept Invitation</a>
                        <p>After accepting, please change your password for security.</p>
                        <p>If you did not expect this invitation, please ignore this email.</p>
                        <p>Best regards,<br>The {business_name} Team</p>
                    </body>
                    </html>
                    """

                    text_content = f'''
                        Hello {first_name},

                        {owner_name} has invited you to join {business_name} as a {role_name}.

                        Your temporary login credentials are:
                        Email: {email}
                        Password: {temp_password}

                        Please click the following link to accept the invitation:
                        {invitation_link}

                        After accepting, please change your password for security.

                        If you did not expect this invitation, please ignore this email.

                        Best regards,
                        The {business_name} Team
                    '''
                else:
                    # Get user's name from UserProfile
                    try:
                        user_profile = user.userprofile
                        user_name = user_profile.first_name
                    except:
                        user_name = user.email
                    
                    body_html = f"""
                    <html>
                    <body>
                        <h1>Join {business_name}</h1>
                        <p>Hello {user_name},</p>
                        <p>{owner_name} has invited you to join {business_name} as a {role_name}.</p>
                        <p>Please click the link below to accept the invitation:</p>
                        <a href="{invitation_link}">Accept Invitation</a>
                        <p>You can use your existing account credentials to access the platform.</p>
                        <p>If you did not expect this invitation, please ignore this email.</p>
                        <p>Best regards,<br>The {business_name} Team</p>
                    </body>
                    </html>
                    """

                    text_content = f'''
                        Hello {user_name},

                        {owner_name} has invited you to join {business_name} as a {role_name}.

                        Please click the following link to accept the invitation:
                        {invitation_link}

                        You can use your existing account credentials to access the platform.

                        If you did not expect this invitation, please ignore this email.

                        Best regards,
                        The {business_name} Team
                    '''

                # Send the email using SES
                response = ses_client.send_email(
                    Source=EMAIL_HOST_USER,
                    Destination={'ToAddresses': [email]},
                    Message={
                        'Subject': {'Data': subject},
                        'Body': {
                            'Html': {'Data': body_html},
                            'Text': {'Data': text_content}
                        },
                    }
                )
                logger.info(f"Invitation email sent to: {email}")

            except Exception as e:
                # Log the error but don't fail the request
                logger.error(f"Failed to send invitation email: {str(e)}")

            # Return success response
            return Response(
                {
                    "message": "Team member invitation sent successfully.",
                    "user_id": user.id,
                    "email": user.email,
                    "context_id": context.id,
                    "role_id": role.id,
                    "role_name": role.name,
                    "user_context_role_id": user_context_role.id,
                    "status": "pending",
                    "is_new_user": is_new_user,
                    "permissions": permissions  # Include the permissions in response
                },
                status=status.HTTP_201_CREATED
            )

    except Context.DoesNotExist:
        return Response(
            {"error": f"Context with ID {context_id} does not exist."},
            status=status.HTTP_404_NOT_FOUND
        )
    except Role.DoesNotExist:
        return Response(
            {"error": "Default employee role not found in this context."},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {"error": f"Failed to add team member: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([AllowAny])
def accept_team_invitation(request):
    uid = request.data.get('uid')
    token = request.data.get('token')

    if not all([uid, token]):
        return Response({"error": "Missing required fields"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user_id = urlsafe_base64_decode(uid).decode()
    except Exception:
        return Response({"error": "Invalid user ID format"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = Users.objects.get(pk=user_id)
        if not invitation_token_generator.check_token(user, token):
            return Response({"error": "Invalid or expired invitation link"}, status=status.HTTP_400_BAD_REQUEST)
    except Users.DoesNotExist:
        return Response({"error": "Invalid user ID"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user_context_role = UserContextRole.objects.select_related('context').get(
            user=user,
            status='pending'
        )
        context = user_context_role.context

        with transaction.atomic():
            # Get usage cycle and lock it
            if not context.is_platform_context:
                usage_entry = ModuleUsageCycle.objects.select_for_update().filter(
                    cycle__subscription__context=context,
                    feature_key='users_count'
                ).order_by('-id').first()

                if usage_entry:
                    if usage_entry.actual_count != "unlimited":
                        actual = int(usage_entry.actual_count or 0)
                        usage = int(usage_entry.usage_count or 0)

                        if usage >= actual:
                            return Response(
                                {"error": "User limit reached. Cannot accept invitation."},
                                status=status.HTTP_400_BAD_REQUEST
                            )

                        # Increment usage count
                        usage_entry.usage_count = str(usage + 1)
                        usage_entry.save()

            # Activate user context role
            user_context_role.status = 'active'
            user_context_role.save()

            if user.status in ['pending', 'invited']:
                user.status = 'active'
                user.is_active = True
                user.save()
                
                # Update UserRegistration
                try:
                    user_registration = user.userregistration
                    user_registration.registration_completed = True
                    user_registration.registration_status = 'completed'
                    user_registration.save()
                except:
                    pass
                
                # Update or create UserSession
                from .models import UserSession
                user_session, created = UserSession.objects.get_or_create(
                    user=user,
                    active_context=context,
                    defaults={
                        'is_active': True,
                        'default_session': True,  # Set as default since they're accepting invitation
                        'session_data': {'invitation_accepted': True, 'accepted_at': timezone.now().isoformat()}
                    }
                )
                if not created:
                    user_session.is_active = True
                    user_session.default_session = True  # Set as default
                    user_session.session_data = {'invitation_accepted': True, 'accepted_at': timezone.now().isoformat()}
                    user_session.save()

        return Response(
            {
                "message": "You have successfully joined the organization.",
                "user_id": user.id,
                "email": user.email,
                "context_id": context.id,
                "role_id": user_context_role.role.id,
                "role_name": user_context_role.role.name,
                "is_new_user": user.status == 'invited'
            },
            status=status.HTTP_200_OK
        )

    except UserContextRole.DoesNotExist:
        return Response({"error": "No pending invitation found"}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Failed to accept invitation: {str(e)}")
        return Response({"error": f"Failed to accept invitation: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_contexts(request):
    """
    Get all contexts and their roles for a user.
    If user_id is provided, get contexts for that user (requires admin/staff permissions).
    If no user_id is provided, get contexts for the authenticated user.

    Query Parameters:
    - user_id (optional): ID of the user to get contexts for

    Expected response:
    {
        "contexts": [
            {
                "context_id": 1,
                "context_name": "Business Name",
                "context_type": "business",
                "status": "active",
                "role": {
                    "role_id": 1,
                    "role_name": "Admin",
                    "role_type": "admin"
                },
                "permissions": [
                    {
                        "module_id": 1,
                        "module_name": "Payroll",
                        "service_actions": [
                            "EmployeeManagement.create",
                            "EmployeeManagement.read",
                            "EmployeeManagement.update",
                            "EmployeeManagement.delete"
                        ]
                    }
                ],
                "subscribed_modules": [
                    {
                        "module_id": 1,
                        "module_name": "Payroll",
                        "subscription_status": "active",
                        "plan_name": "Basic Plan",
                        "start_date": "2024-01-01T00:00:00Z",
                        "end_date": "2024-12-31T23:59:59Z",
                        "auto_renew": "yes",
                        "via_suite": "no"
                    }
                ]
            }
        ]
    }
    """
    try:
        # Get user_id from query parameters
        user_id = request.query_params.get('user_id')
        authenticated_user = request.user

        # If user_id is provided, check permissions and get that user
        if user_id:
            try:
                target_user = Users.objects.get(id=user_id)
            except Users.DoesNotExist:
                return Response(
                    {"error": f"User with ID {user_id} does not exist."},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            target_user = authenticated_user

        # Get all active user context roles for the target user
        user_context_roles = UserContextRole.objects.filter(
            user=target_user,
            status='active'
        ).select_related(
            'context',
            'role'
        )

        contexts_data = []
        for ucr in user_context_roles:
            context = ucr.context
            role = ucr.role

            # Get all permissions for this context role
            permissions = []
            feature_permissions = UserFeaturePermission.objects.filter(
                user_context_role=ucr,
                is_active=True
            ).select_related('module')

            for permission in feature_permissions:
                permissions.append({
                    "module_id": permission.module.id,
                    "module_name": permission.module.name,
                    "service_actions": permission.actions
                })

            # Get all module subscriptions for this context
            subscriptions = ModuleSubscription.objects.filter(
                context=context,
                status__in=['active', 'trial']
            ).select_related('module', 'plan')

            subscribed_modules = [
                {
                    "module_id": sub.module.id,
                    "module_name": sub.module.name,
                    "subscription_status": sub.status,
                    "plan_name": sub.plan.name,
                    "start_date": sub.start_date,
                    "end_date": sub.end_date,
                    "auto_renew": sub.auto_renew,
                    "via_suite": sub.via_suite
                }
                for sub in subscriptions
            ]

            context_data = {
                "id": context.id,
                "name": context.name,
                "context_type": context.context_type,
                "status": context.status,
                "role": {
                    "role_id": role.id,
                    "role_name": role.name,
                    "role_type": role.role_type
                },
                "permissions": permissions,
                "subscribed_modules": subscribed_modules
            }
            contexts_data.append(context_data)

        return Response(
            {
                "user_id": target_user.id,
                "user_email": target_user.email,
                "user_name": f"{target_user.userprofile.first_name} {target_user.userprofile.last_name}" if hasattr(target_user, 'userprofile') else target_user.email,
                "contexts": contexts_data
            },
            status=status.HTTP_200_OK
        )

    except Exception as e:
        logger.error(f"Failed to get user contexts: {str(e)}")
        return Response(
            {"error": f"Failed to get user contexts: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_context_users(request):
    """
    List all users for a specific context, including their role and permissions.
    Each user can have only one role in a context.

    Query Parameters:
    - context_id: ID of the context to list users for

    Expected response:
    {
        "users": [
            {
                "user_id": 1,
                "email": "user@example.com",
                "first_name": "John",
                "last_name": "Doe",
                "mobile_number": "1234567890",
                "status": "active",
                "role": {
                    "user_context_role_id": 1,
                    "role_id": 1,
                    "role_name": "Admin",
                    "role_type": "admin",
                    "added_at": "2024-04-22T10:00:00Z",
                    "added_by": {
                        "user_id": 2,
                        "email": "admin@example.com",
                        "name": "Admin User"
                    }
                },
                "permissions": [
                    {
                        "module_id": 1,
                        "module_name": "Payroll",
                        "service_actions": [
                            "EmployeeManagement.create",
                            "EmployeeManagement.read",
                            "EmployeeManagement.update",
                            "EmployeeManagement.delete"
                        ]
                    }
                ]
            }
        ]
    }
    """
    try:
        context_id = request.query_params.get('context_id')
        if not context_id:
            return Response(
                {"error": "context_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get the context
        try:
            context = Context.objects.get(id=context_id)
        except Context.DoesNotExist:
            return Response(
                {"error": f"Context with ID {context_id} does not exist"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Get all active user context roles for this context
        user_context_roles = UserContextRole.objects.filter(
            context=context
        )

        # Group by user
        users_dict = {}
        for ucr in user_context_roles:
            user = ucr.user
            role = ucr.role

            # Get all permissions for this user context role
            permissions = []
            feature_permissions = UserFeaturePermission.objects.filter(
                user_context_role=ucr,
                is_active=True
            ).select_related('module')

            for permission in feature_permissions:
                permissions.append({
                    "module_id": permission.module.id,
                    "module_name": permission.module.name,
                    "service_actions": permission.actions
                })

            # Get added by user info
            added_by = None
            if ucr.added_by:
                added_by = {
                    "user_id": ucr.added_by.id,
                    "email": ucr.added_by.email,
                    "name": f"{ucr.added_by.userprofile.first_name or ''} {ucr.added_by.userprofile.last_name or ''}".strip() if hasattr(ucr.added_by, 'userprofile') else "Unknown"
                }

            # Create or update user entry
            if user.id not in users_dict:
                # Get user profile information
                try:
                    user_profile = user.userprofile
                    first_name = user_profile.first_name
                    last_name = user_profile.last_name
                    mobile_number = user_profile.mobile_number
                except:
                    first_name = ""
                    last_name = ""
                    mobile_number = ""
                
                users_dict[user.id] = {
                    "user_id": user.id,
                    "email": user.email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "mobile_number": mobile_number,
                    "status": user.status,
                    "role": {
                        "user_context_role_id": ucr.id,  # Added user_context_role_id
                        "role_id": role.id,
                        "role_name": role.name,
                        "role_type": role.role_type,
                        "added_at": ucr.created_at,
                        "added_by": added_by
                    },
                    "permissions": permissions
                }
            else:
                # If user already exists, merge permissions
                for permission in permissions:
                    # Check if module already exists in permissions
                    module_exists = False
                    for existing_permission in users_dict[user.id]["permissions"]:
                        if existing_permission["module_id"] == permission["module_id"]:
                            # Merge service actions
                            existing_actions = set(existing_permission["service_actions"])
                            new_actions = set(permission["service_actions"])
                            existing_permission["service_actions"] = list(existing_actions.union(new_actions))
                            module_exists = True
                            break

                    if not module_exists:
                        users_dict[user.id]["permissions"].append(permission)

        # Convert dictionary to list and sort by email
        users_data = list(users_dict.values())
        users_data.sort(key=lambda x: x["email"])

        return Response(
            {
                "context_id": context.id,
                "context_name": context.name,
                "context_type": context.context_type,
                "total_users": len(users_data),
                "users": users_data
            },
            status=status.HTTP_200_OK
        )

    except Exception as e:
        logger.error(f"Failed to list context users: {str(e)}")
        return Response(
            {"error": f"Failed to list context users: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_business_context_data(request):
    """
    Get comprehensive business data for a specific context ID.

    Query Parameters:
    - context_id: ID of the business context

    Expected response:
    {
        "business": {
            "id": 1,
            "nameOfBusiness": "Business Name",
            "registrationNumber": "REG123456",
            "entityType": "privateLimitedCompany",
            "headOffice": {
                "address": "Business Address",
                "city": "City",
                "state": "State",
                "country": "Country",
                "postal_code": "123456"
            },
            "pan": "ABCDE1234F",
            "business_nature": "Technology",
            "legal_name": "legal Name",
            "mobile_number": "1234567890",
            "email": "business@example.com",
            "dob_or_incorp_date": "2020-01-01",
            "client": {
                "user_id": 1,
                "email": "owner@example.com",
                "name": "Owner Name",
                "mobile_number": "1234567890"
            }
        },
        "context": {
            "id": 1,
            "name": "Business Name",
            "context_type": "business",
            "status": "active",
            "created_at": "2024-04-22T10:00:00Z"
        }
    }
    """
    try:
        context_id = request.query_params.get('context_id')
        if not context_id:
            return Response(
                {"error": "context_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get the context with related data
        try:
            context = Context.objects.select_related(
                'owner_user',
                'business'
            ).get(id=context_id)
        except Context.DoesNotExist:
            return Response(
                {"error": f"Context with ID {context_id} does not exist"},
                status=status.HTTP_404_NOT_FOUND
            )

        if not context.business:
            return Response(
                {"error": "No business information found for this context"},
                status=status.HTTP_404_NOT_FOUND
            )

        business = context.business

        # Prepare response data
        response_data = {
            "business": {
                "id": business.id,
                "nameOfBusiness": business.nameOfBusiness,
                "registrationNumber": business.registrationNumber,
                "entityType": business.entityType,
                "headOffice": business.headOffice or {},
                "pan": business.pan,
                "business_nature": business.business_nature,
                "legal_name": business.legal_name,
                "mobile_number": business.mobile_number,
                "email": business.email,
                "dob_or_incorp_date": business.dob_or_incorp_date,
                "client": {
                    "user_id": business.client.id,
                    "email": business.client.email,
                    "name": f"{business.client.userprofile.first_name or ''} {business.client.userprofile.last_name or ''}".strip() if hasattr(business.client, 'userprofile') else "Unknown",
                    "mobile_number": business.client.userprofile.mobile_number if hasattr(business.client, 'userprofile') else ""
                }
            },
            "context": {
                "id": context.id,
                "name": context.name,
                "context_type": context.context_type,
                "status": context.status,
                "created_at": context.created_at
            }
        }

        return Response(response_data, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Failed to get business context data: {str(e)}")
        return Response(
            {"error": f"Failed to get business context data: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )