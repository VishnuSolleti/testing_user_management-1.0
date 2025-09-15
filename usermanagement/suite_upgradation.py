from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from .models import SubscriptionPlan, Module
from .models import *
from .serializers import *
from .serializers import SubscriptionPlanSerializer
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upgrade_to_suite(request):
    """
    Upgrade from individual module subscriptions to a suite subscription
    with proration for existing subscriptions
    """
    context_id = request.data.get('context_id')
    suite_id = request.data.get('suite_id')
    subscription_type = request.data.get('subscription_type', 'monthly')  # monthly or yearly
    auto_renew = request.data.get('auto_renew', True)

    # Validate required fields
    if not all([context_id, suite_id]):
        return Response(
            {"error": "Missing required fields. Please provide context_id and suite_id."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # Get context
        context = Context.objects.get(id=context_id)

        # Check if user has access to this context
        if not UserContextRole.objects.filter(user=request.user, context=context, is_active=True).exists():
            return Response(
                {"error": "You don't have access to this context."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Get suite
        suite = Suite.objects.get(id=suite_id)

        # Get suite subscription plan
        suite_plan = SubscriptionPlan.objects.filter(
            module__isnull=True,  # Suite plans don't have a module
            plan_type=subscription_type,
            is_active=True
        ).first()

        if not suite_plan:
            return Response(
                {"error": f"No active {subscription_type} plan found for this suite."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Calculate suite price
        suite_price = suite_plan.base_price

        # Get existing module subscriptions
        existing_subscriptions = ModuleSubscription.objects.filter(
            context=context,
            status='active'
        ).select_related('module', 'plan')

        # Calculate proration credit
        total_credit = 0
        modules_to_cancel = []

        for sub in existing_subscriptions:
            # Check if this module is included in the suite
            if sub.module in suite.included_modules.all():
                # Calculate remaining days
                today = timezone.now().date()
                end_date = sub.end_date.date()

                if end_date > today:
                    remaining_days = (end_date - today).days
                    total_days = (sub.end_date - sub.start_date).days

                    # Calculate prorated credit
                    daily_rate = sub.plan.base_price / total_days
                    credit = daily_rate * remaining_days

                    total_credit += credit
                    modules_to_cancel.append(sub)

        # Apply credit to suite price
        final_suite_price = max(0, suite_price - total_credit)

        # Create suite subscription
        start_date = timezone.now()
        end_date = start_date + relativedelta(
            months=1) if subscription_type == 'monthly' else start_date + relativedelta(years=1)

        suite_subscription = ContextSuiteSubscription.objects.create(
            context=context,
            suite=suite,
            plan=suite_plan,
            status='active',
            start_date=start_date,
            end_date=end_date,
            auto_renew=auto_renew,
            original_price=suite_price,
            applied_credit=total_credit,
            final_price=final_suite_price
        )

        # Create module subscriptions for all modules in the suite
        module_subscriptions = []
        for module in suite.included_modules.all():
            # Check if we already have a subscription for this module
            existing_sub = next((s for s in existing_subscriptions if s.module_id == module.id), None)

            if existing_sub:
                # Update existing subscription
                existing_sub.status = 'cancelled'
                existing_sub.save()

            # Create new module subscription
            module_sub = ModuleSubscription.objects.create(
                context=context,
                module=module,
                plan=suite_plan,  # Use the suite plan
                status='active',
                start_date=start_date,
                end_date=end_date,
                auto_renew=auto_renew,
                via_suite=True,
                suite_subscription=suite_subscription
            )

            module_subscriptions.append(module_sub)

        # Create feature permissions for all modules in the suite
        user_context_role = UserContextRole.objects.get(user=request.user, context=context, is_active=True)

        for module in suite.included_modules.all():
            features = ModuleFeature.objects.filter(module=module, is_active=True)

            for feature in features:
                # Get or create permission
                permission, created = UserFeaturePermission.objects.get_or_create(
                    user_context_role=user_context_role,
                    feature=feature,
                    defaults={'actions': ['view']}  # Default to view permission
                )

                # If permission already exists, ensure it has at least view permission
                if not created and 'view' not in permission.actions:
                    permission.actions.append('view')
                    permission.save()

        # Return response
        return Response({
            "message": "Successfully upgraded to suite subscription.",
            "suite_subscription": {
                'id': suite_subscription.id,
                'suite_id': suite.id,
                'suite_name': suite.name,
                'plan_id': suite_plan.id,
                'plan_name': suite_plan.name,
                'status': suite_subscription.status,
                'start_date': suite_subscription.start_date,
                'end_date': suite_subscription.end_date,
                'auto_renew': suite_subscription.auto_renew,
                'original_price': suite_subscription.original_price,
                'applied_credit': suite_subscription.applied_credit,
                'final_price': suite_subscription.final_price
            },
            "module_subscriptions": [
                {
                    'id': sub.id,
                    'module_id': sub.module.id,
                    'module_name': sub.module.name,
                    'status': sub.status,
                    'start_date': sub.start_date,
                    'end_date': sub.end_date,
                    'auto_renew': sub.auto_renew,
                    'via_suite': sub.via_suite
                } for sub in module_subscriptions
            ]
        }, status=status.HTTP_200_OK)

    except Context.DoesNotExist:
        return Response(
            {"error": "Context not found."},
            status=status.HTTP_404_NOT_FOUND
        )
    except Suite.DoesNotExist:
        return Response(
            {"error": "Suite not found."},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {"error": f"Upgrade failed: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )