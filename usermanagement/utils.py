from django.db.models import Q
from rest_framework.response import Response
from rest_framework import status
from .models import (
    UserContextRole, ModuleSubscription, UserFeaturePermission,
    Module, ModuleFeature
)
import logging
import json

logger = logging.getLogger(__name__)


def validate_user_permissions(user_context_role_id, module_id, required_actions=None):
    """
    Validate user permissions and subscription status.

    Args:
        user_context_role_id (int): ID of the user's context role
        module_id (int): ID of the module to check permissions for
        required_actions (list): List of required actions to check. If None, only checks subscription.

    Returns:
        tuple: (is_valid, response)
            - is_valid (bool): True if all validations pass
            - response (Response): Response object with error details if validation fails, None if valid
    """
    try:
        # 1. Check if user context role exists
        try:
            user_context_role = UserContextRole.objects.get(
                id=user_context_role_id,
                status='active'
            )
        except UserContextRole.DoesNotExist:
            return False, Response(
                {"error": "Invalid or inactive user context role"},
                status=status.HTTP_403_FORBIDDEN
            )

        # 2. Check if module exists
        try:
            module = Module.objects.get(id=module_id)
        except Module.DoesNotExist:
            return False, Response(
                {"error": "Invalid module"},
                status=status.HTTP_404_NOT_FOUND
            )

        # 3. Check subscription status
        subscription = ModuleSubscription.objects.filter(
            context=user_context_role.context,
            module=module,
            status='active'
        ).first()

        if not subscription:
            return False, Response(
                {"error": "No active subscription found for this module"},
                status=status.HTTP_403_FORBIDDEN
            )

        # If no specific actions required, just checking subscription is enough
        if not required_actions:
            return True, None

        # 4. Check user permissions for required actions
        try:
            permission = UserFeaturePermission.objects.get(
                user_context_role=user_context_role,
                module=module,
                is_active=True
            )
        except UserFeaturePermission.DoesNotExist:
            return False, Response(
                {"error": "No permissions found for this module"},
                status=status.HTTP_403_FORBIDDEN
            )

        # 5. Validate required actions against user's permissions
        user_actions = permission.actions
        if isinstance(user_actions, str):
            user_actions = json.loads(user_actions)

        missing_actions = [action for action in required_actions if action not in user_actions]
        if missing_actions:
            return False, Response(
                {
                    "error": "Insufficient permissions",
                    "missing_actions": missing_actions
                },
                status=status.HTTP_403_FORBIDDEN
            )

        # 6. Check module feature usage limits
        module_features = ModuleFeature.objects.filter(
            module=module,
            action__in=required_actions
        )

        for feature in module_features:
            if feature.usage_limit:
                # Here you would implement the logic to check usage against the limit
                # This could involve querying a usage tracking table
                # For now, we'll just check if the feature exists and has a limit
                pass

        return True, None

    except Exception as e:
        logger.error(f"Error validating user permissions: {str(e)}")
        return False, Response(
            {"error": "An error occurred while validating permissions"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )