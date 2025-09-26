from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from .models import *


# Utility function to create tokens
def get_tokens_for_user(user, business_id=None):
    refresh = RefreshToken.for_user(user)
    if business_id:
        refresh['org_id'] = business_id
    return {
        'access': str(refresh.access_token),
        'refresh': str(refresh)
    }


# Reusable response builder
def generate_user_profile_response(user):
    context = user.active_context

    user_context_role = UserContextRole.objects.filter(
        user=user,
        context=context,
        status='active'
    ).select_related('role').first()

    # permissions = UserFeaturePermission.objects.filter(
    #     user_context_role=user_context_role,
    #     is_active='yes'
    # )
    #
    # permission_data = [{
    #     "id": p.id,
    #     "module_id": p.module.id,
    #     "module_name": p.module.name,
    #     "actions": p.actions
    # } for p in permissions]

    module_subs = ModuleSubscription.objects.filter(context=context)

    module_data = [{
        "id": m.id,
        "module_id": m.module.id,
        "module_name": m.module.name,
        "plan_id": m.plan.id,
        "plan_name": m.plan.name,
        "status": m.status,
        "start_date": m.start_date,
        "end_date": m.end_date,
        "auto_renew": m.auto_renew
    } for m in module_subs]

    all_contexts = []
    user_context_roles = UserContextRole.objects.filter(
        user=user,
        status='active'
    ).select_related('context', 'role')

    for ucr in user_context_roles:
        ucr_context = ucr.context
        context_info = {
            "id": ucr_context.id,
            "name": ucr_context.name,
            "context_type": ucr_context.context_type,
            "status": ucr_context.status,
            "profile_status": ucr_context.profile_status,
            "created_at": ucr_context.created_at,
            "is_active": ucr_context.id == user.active_context.id if user.active_context else False,
            "business_id": ucr_context.business_id,
            "legal_name": ucr_context.business.legal_name if ucr_context.business and ucr_context.business.legal_name else None,
            "role": {
                "id": ucr.role.id,
                "name": ucr.role.name,
                "role_type": ucr.role.role_type,
                "description": ucr.role.description
            }
        }
        all_contexts.append(context_info)

    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "mobile_number": user.mobile_number,
            "status": user.status,
            "registration_flow": user.registration_flow,
            "initial_selection": user.initial_selection,
            "registration_completed": user.registration_completed,
            "created_at": user.created_at,
            "last_login": user.last_login,
        },
        "active_context": {
            "id": context.id,
            "name": context.name,
            "context_type": context.context_type,
            "status": context.status,
            "profile_status": context.profile_status,
            "created_at": context.created_at,
            "business_id": context.business_id,
            "legal_name": context.business.legal_name if context.business and context.business.legal_name else None,
        },
        "all_contexts": all_contexts,
        "user_role": {
            "id": user_context_role.role.id,
            "name": user_context_role.role.name,
            "role_type": user_context_role.role.role_type,
            "description": user_context_role.role.description
        },
        "module_subscriptions": module_data,
        "user_context_role": user_context_role.id

    }


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def switch_user_context(request):
    """
    Switch user's active context and return updated tokens + user state.
    Request: {
        "context_id": 2,
        "user_id": 123  # Optional: If not provided, the authenticated user will be used
    }
    """
    context_id = request.data.get("context_id")
    user_id = request.data.get("user_id")

    if not context_id:
        return Response({"error": "context_id is required."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        # Determine which user to use
        if user_id:
            # Check if the authenticated user has permission to switch context for another user

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
            user = request.user

        # Check context exists
        context = Context.objects.get(id=context_id)

        # Check if user has access to this context FIRST
        ucr = UserContextRole.objects.get(user=user, context=context, status="active")

        # Only create/update UserSession AFTER confirming user has access
        from .models import UserSession
        try:
            # Get existing active session
            user_session = UserSession.objects.get(user=user, is_active=True)
            # Update the active context
            user_session.active_context = context
            user_session.session_data = {
                **user_session.session_data,
                'switched_to_context': context.id,
                'switched_at': timezone.now().isoformat()
            }
            user_session.save()
        except UserSession.DoesNotExist:
            # Create new session if none exists
            user_session = UserSession.objects.create(
                user=user,
                active_context=context,
                is_active=True,
                default_session=False,  # Don't make it default automatically
                session_data={'switched_to_context': context.id, 'switched_at': timezone.now().isoformat()}
            )
        
        # Set this session as the default session
        user.set_default_session(user_session)

        # # Generate new token
        print(context.context_type)
        if context.context_type == 'personal':
            tokens = get_tokens_for_user(user)
        else:
            tokens = get_tokens_for_user(user, context.business.id)

        # Generate login-like response
        profile_data = generate_user_profile_response(user)
        profile_data["message"] = "Context switched successfully"
        profile_data["user_session_id"] = user_session.id
        profile_data["active_context_id"] = user_session.active_context.id
        profile_data["access_token"] = tokens["access"]
        profile_data["refresh_token"] = tokens["refresh"]

        return Response(profile_data, status=status.HTTP_200_OK)

    except Context.DoesNotExist:
        return Response({"error": "Context not found."}, status=status.HTTP_404_NOT_FOUND)

    except UserContextRole.DoesNotExist:
        return Response({"error": "You do not have access to this context."}, status=status.HTTP_403_FORBIDDEN)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
