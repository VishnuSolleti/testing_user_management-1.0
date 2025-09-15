from functools import wraps
from rest_framework.response import Response
from rest_framework import status
from datetime import date
from .models import SubscriptionCycle, ModuleUsageCycle, ModuleSubscription


def get_usage_entry(context_id, feature_key, module_id=None):
    try:
        # Build subscription query
        subscription_filters = {
            "context_id": context_id,
            "status__in": ["active", "trial"]
        }
        if module_id:
            subscription_filters["module_id"] = module_id

        # Get active or trial subscription
        subscription = ModuleSubscription.objects.filter(**subscription_filters).first()

        if not subscription:
            return None, Response(
                {"error": "No active or trial subscription found for this context/module."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get latest subscription cycle
        cycle = SubscriptionCycle.objects.filter(subscription=subscription).order_by('-start_date').first()
        if not cycle:
            return None, Response(
                {"error": "No active subscription cycle found."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Build usage entry query
        usage_filters = {
            "cycle": cycle,
            "feature_key": feature_key,
        }

        usage_entry = ModuleUsageCycle.objects.filter(**usage_filters).first()

        if not usage_entry:
            return None, Response(
                {"error": f"No usage data found for feature '{feature_key}'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check usage limit
        actual_limit = str(usage_entry.actual_count).strip().lower()
        if actual_limit != "unlimited":
            if int(usage_entry.usage_count) >= int(actual_limit):
                return None, Response(
                    {
                        "error": f"Usage limit reached for '{feature_key}'.",
                        "details": "Please upgrade your subscription or contact support."
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

        return usage_entry, None

    except Exception as e:
        return None, Response(
            {"error": "Failed to get usage entry", "details": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def increment_usage(usage):
    """
    This updates the usage count after the action is completed.
    """
    if usage and usage.actual_count != "unlimited":
        usage.usage_count = str(int(usage.usage_count) + 1)
        usage.save(update_fields=['usage_count'])

