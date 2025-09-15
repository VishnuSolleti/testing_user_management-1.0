from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from decimal import Decimal
from .models import (
    ModuleSubscription,
    Context,
    Module,
    SubscriptionPlan,
    ModuleAddOn,
    SubscriptionCycle,
    ModuleUsageCycle
)
from decimal import Decimal, InvalidOperation


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upgrade_module_subscription(request):
    """
    Upgrade a module subscription to a new plan.

    This API handles the upgrade of a module subscription by:
    1. Updating the main ModuleSubscription record with the new plan
    2. Creating a new SubscriptionCycle for the new billing period
    3. Initializing ModuleUsageCycle records for the new cycle
    4. Handling any add-ons if specified

    Required fields:
    - subscription_id: ID of the existing subscription
    - new_plan_id: ID of the new plan to upgrade to

    Optional fields:
    - auto_renew: String (default: 'no') - Whether to auto-renew the subscription ('yes' or 'no')
    - add_ons: List of add-ons to include with the upgrade
        [
            {
                "type": "extra_user",
                "quantity": 5,
                "price_per_unit": "10.00",
                "billing_cycle": "monthly"
            }
        ]

    Returns:
    - Success: Updated subscription details with new cycle and usage tracking
    - Error: Error message with appropriate status code
    """
    try:
        # Validate required fields
        subscription_id = request.data.get('subscription_id')
        new_plan_id = request.data.get('new_plan_id')

        if not subscription_id or not new_plan_id:
            return Response(
                {"error": "subscription_id and new_plan_id are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get optional fields
        auto_renew = request.data.get('auto_renew', False)
        add_ons = request.data.get('add_ons', [])

        # Get existing subscription with related data
        try:
            subscription = ModuleSubscription.objects.select_related(
                'context', 'module', 'plan'
            ).get(id=subscription_id)
        except ModuleSubscription.DoesNotExist:
            return Response(
                {"error": "Subscription not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Get new plan
        try:
            new_plan = SubscriptionPlan.objects.get(id=new_plan_id)
        except SubscriptionPlan.DoesNotExist:
            return Response(
                {"error": "New plan not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        with transaction.atomic():
            # End current cycle if it exists
            try:
                # Get current active cycle using the reverse relationship
                current_cycle = SubscriptionCycle.objects.filter(
                    subscription=subscription,
                    is_paid=True,
                    end_date__gt=timezone.now()
                ).first()

                if current_cycle:
                    # Update the end_date directly using update() method
                    SubscriptionCycle.objects.filter(id=current_cycle.id).update(
                        end_date=timezone.now()
                    )
            except Exception as e:
                # If there's an error with the current cycle, log it but continue
                print(f"Error handling current cycle: {str(e)}")

            # Calculate new end date based on billing cycle
            new_end_date = timezone.now() + relativedelta(days=new_plan.billing_cycle_days)

            # Create new subscription cycle with proper decimal handling
            try:
                # Convert base_price to Decimal, handling None and invalid values
                if new_plan.base_price is None:
                    base_price = Decimal('0.00')
                else:
                    try:
                        base_price = Decimal(str(new_plan.base_price))
                    except (InvalidOperation, TypeError, ValueError):
                        base_price = Decimal('0.00')
            except Exception:
                base_price = Decimal('0.00')

            # Create new cycle with the converted decimal value
            new_cycle = SubscriptionCycle.objects.create(
                subscription=subscription,
                start_date=timezone.now(),
                end_date=new_end_date,
                amount=base_price,
                is_paid=False,
                feature_usage={}
            )

            # Initialize usage cycles for the new plan's features
            if new_plan.features_enabled:
                for feature_key, config in new_plan.features_enabled.items():
                    if isinstance(config, dict) and (config.get("limit") is not None or config.get("track") is True):
                        ModuleUsageCycle.objects.create(
                            cycle=new_cycle,
                            feature_key=feature_key,
                            usage_count=0
                        )

            # Update main subscription record
            subscription.plan = new_plan
            subscription.auto_renew = auto_renew
            subscription.start_date = timezone.now()
            subscription.end_date = new_end_date
            subscription.status = 'active'
            subscription.save()

            # Create add-ons if specified with proper decimal handling
            for add_on in add_ons:
                try:
                    price_str = str(add_on.get('price_per_unit', '0.00'))
                    price_per_unit = Decimal(price_str) if price_str else Decimal('0.00')
                except (InvalidOperation, TypeError, ValueError):
                    price_per_unit = Decimal('0.00')

                ModuleAddOn.objects.create(
                    subscription=subscription,
                    type=add_on['type'],
                    quantity=add_on['quantity'],
                    price_per_unit=price_per_unit,
                    billing_cycle=add_on['billing_cycle']
                )

            # Get updated subscription details
            subscription.refresh_from_db()

            # Get current cycle details
            current_cycle = subscription.cycles.filter(
                is_paid=True,
                end_date__gt=timezone.now()
            ).first()

            # Get usage details for current cycle
            usage_details = {}
            if current_cycle:
                for usage in current_cycle.usages.all():
                    usage_details[usage.feature_key] = usage.usage_count

            # Get add-ons
            add_ons_data = []
            for add_on in subscription.moduleaddon_set.all():
                add_ons_data.append({
                    'type': add_on.type,
                    'quantity': add_on.quantity,
                    'price_per_unit': str(add_on.price_per_unit),
                    'billing_cycle': add_on.billing_cycle
                })

            # Format response
            response_data = {
                "subscription_id": subscription.id,
                "module_id": subscription.module.id,
                "module_name": subscription.module.name,
                "old_plan": {
                    "plan_id": subscription.plan.id,
                    "plan_name": subscription.plan.name,
                    "plan_type": subscription.plan.plan_type,
                    "base_price": str(subscription.plan.base_price or '0.00')
                },
                "new_plan": {
                    "plan_id": new_plan.id,
                    "plan_name": new_plan.name,
                    "plan_type": new_plan.plan_type,
                    "base_price": str(new_plan.base_price or '0.00')
                },
                "status": subscription.status,
                "start_date": subscription.start_date,
                "end_date": subscription.end_date,
                "auto_renew": subscription.auto_renew,
                "current_cycle": {
                    "start_date": current_cycle.start_date if current_cycle else None,
                    "end_date": current_cycle.end_date if current_cycle else None,
                    "amount": str(current_cycle.amount) if current_cycle else None,
                    "is_paid": current_cycle.is_paid if current_cycle else None,
                    "usage_details": usage_details
                } if current_cycle else None,
                "add_ons": add_ons_data,
                "message": "Subscription upgraded successfully"
            }

            return Response(response_data, status=status.HTTP_200_OK)

    except Exception as e:
        return Response(
            {"error": f"Failed to upgrade subscription: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )