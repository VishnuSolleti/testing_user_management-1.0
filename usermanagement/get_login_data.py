# utils/auth.py
from rest_framework_simplejwt.tokens import RefreshToken
from django.utils import timezone
from rest_framework import status
from .models import UserContextRole, ModuleSubscription, ServiceRequest, UserFeaturePermission


def get_login_response(user):

    refresh = RefreshToken.for_user(user)
    access_token = str(refresh.access_token)
    refresh_token = str(refresh)

    active_context = None
    context_data = None
    user_role = None
    role_data = None
    module_subscriptions = []
    all_contexts = []
    active_user_context_role = None
    user_context_role_id = None
    service_requests = []

    user_context_roles = UserContextRole.objects.filter(
        user=user,
        status='active'
    ).select_related('context', 'role')

    for ucr in user_context_roles:
        context = ucr.context
        context_info = {
            "id": context.id,
            "name": context.name,
            "context_type": context.context_type,
            "status": context.status,
            "profile_status": context.profile_status,
            "created_at": context.created_at,
            "is_active": context.id == user.active_context.id if user.active_context else False,
            "business_id": context.business_id,
            "is_platform_context": context.is_platform_context,
            "role": {
                "id": ucr.role.id,
                "name": ucr.role.name,
                "role_type": ucr.role.role_type,
                "description": ucr.role.description
            }
        }
        all_contexts.append(context_info)

    if user.active_context:
        active_context = user.active_context
        context_data = {
            "id": active_context.id,
            "name": active_context.name,
            "context_type": active_context.context_type,
            "status": active_context.status,
            "profile_status": active_context.profile_status,
            "created_at": active_context.created_at,
            "business_id": active_context.business_id,
            "is_platform_context": active_context.is_platform_context,
        }

        try:
            user_context_role = UserContextRole.objects.get(
                user=user,
                context=active_context,
                status='active'
            )
            active_user_context_role = user_context_role
            user_context_role_id = user_context_role.id
            user_role = user_context_role.role
            role_data = {
                "id": user_role.id,
                "name": user_role.name,
                "role_type": user_role.role_type,
                "description": user_role.description
            }

            _ = UserFeaturePermission.objects.filter(
                user_context_role=user_context_role,
                is_active=True
            )

        except UserContextRole.DoesNotExist:
            pass

        subscriptions = ModuleSubscription.objects.filter(
            context=active_context,
            status__in=['active', 'trial']
        )

        for subscription in subscriptions:
            module_subscriptions.append({
                "id": subscription.id,
                "module_id": subscription.module.id,
                "module_name": subscription.module.name,
                "plan_id": subscription.plan.id,
                "plan_name": subscription.plan.name,
                "status": subscription.status,
                "start_date": subscription.start_date,
                "end_date": subscription.end_date,
                "auto_renew": subscription.auto_renew
            })

        if active_context.owner_user_id == user.id:
            requests = ServiceRequest.objects.filter(context=active_context)
            for req in requests:
                service_requests.append({
                    "id": req.id,
                    "service_id": req.service.id,
                    "service_name": req.service.name,
                    "plan_id": req.plan.id if req.plan else None,
                    "plan_name": req.plan.name if req.plan else None,
                    "status": req.status,
                    "payment_order_id": req.payment_order_id,
                    "created_at": req.created_at,
                    "updated_at": req.updated_at
                })

    user_data = {
        "id": user.id,
        "email": user.email,
        "mobile_number": user.mobile_number,
        "status": user.status,
        "registration_flow": user.registration_flow,
        "initial_selection": user.initial_selection,
        "registration_completed": user.registration_completed,
        "created_at": user.created_at,
        "last_login": user.last_login,
        "user_context_role": user_context_role_id,
        "is_super_admin": user.is_super_admin,
    }

    if active_user_context_role:
        refresh['user_context_role'] = active_user_context_role.id
        access_token = str(refresh.access_token)
        refresh_token = str(refresh)

    return {
        "message": "Registration successful",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": user_data,
        "active_context": context_data,
        "all_contexts": all_contexts,
        "user_role": role_data,
        "module_subscriptions": module_subscriptions,
        "service_requests": service_requests,
        "user_context_role": user_context_role_id
    }
