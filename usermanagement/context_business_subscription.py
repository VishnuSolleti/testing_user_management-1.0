from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.utils import timezone
from dateutil.relativedelta import relativedelta
import logging

from .models import (
    Users, Context, Role, UserContextRole, Module,
    ModuleFeature, UserFeaturePermission, SubscriptionPlan, ModuleSubscription, Business
)

# Configure logging
logger = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_business_context(request):
    """
    Create a new business context without a subscription plan.

    Expected request data:
    {
        "user_id": 1,
        "business_name": "My Business",
        "registration_number": "REG123",
        "entity_type": "privateLimitedCompany",
        "head_office": {
            "address": "123 Main St",
            "city": "New York",
            "state": "NY",
            "country": "USA",
            "pincode": "10001"
        },
        "pan": "ABCDE1234F",
        "business_nature": "Technology",
        "legal_name": "MyTrade",
        "mobile_number": "+1234567890",
        "email": "business@example.com",
        "dob_or_incorp_date": "2020-01-01"
    }
    """
    # Extract data from request
    user_id = request.data.get('user_id')
    business_name = request.data.get('business_name')

    # Extract additional business data
    registration_number = request.data.get('registration_number')
    entity_type = request.data.get('entity_type')
    head_office = request.data.get('head_office')
    pan = request.data.get('pan')
    business_nature = request.data.get('business_nature')
    legal_name = request.data.get('legal_name')
    mobile_number = request.data.get('mobile_number')
    email = request.data.get('email')
    dob_or_incorp_date = request.data.get('dob_or_incorp_date')

    # Validate required fields
    if not all([user_id, business_name]):
        return Response(
            {"error": "Missing required fields. Please provide user_id and business_name."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        with transaction.atomic():
            # Get user
            try:
                user = Users.objects.get(id=user_id)
            except Users.DoesNotExist:
                return Response(
                    {"error": "User not found."},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Check if user is active
            if not user.is_active:
                return Response(
                    {"error": "User account is not active. Please activate your account first."},
                    status=status.HTTP_403_FORBIDDEN
                )
            try:
                # Create business context
                context = Context.objects.create(
                    name=business_name,
                    context_type='business',
                    owner_user=user,
                    status='active',
                    profile_status='complete',
                    metadata={
                        'registration_number': registration_number,
                        'entity_type': entity_type,
                        'head_office': head_office,
                        'pan': pan,
                        'business_nature': business_nature,
                        'legal_name': legal_name,
                        'mobile_number': mobile_number,
                        'email': email,
                        'dob_or_incorp_date': dob_or_incorp_date
                    }
                )

                # Create owner role for the business
                owner_role = Role.objects.get(
                    context=context,
                    role_type='owner'
                )

                # Assign user to context with owner role
                user_context_role = UserContextRole.objects.create(
                    user=user,
                    context=context,
                    role=owner_role,
                    status='active',
                    added_by=user
                )

                # Create UserSession for the new business context
                from .models import UserSession
                user_session = UserSession.objects.create(
                    user=user,
                    active_context=context,
                    is_active=True,
                    default_session=True,  # Set as default since it's their first business context
                    session_data={'context_type': 'business', 'created_by': 'create_business_context'}
                )

                # Get the business created by the signal
                business = context.business

                # Update business with additional data
                if business:
                    business.registrationNumber = registration_number
                    business.entityType = entity_type
                    business.headOffice = head_office
                    business.pan = pan
                    business.business_nature = business_nature
                    business.legal_name = legal_name
                    business.mobile_number = mobile_number
                    business.email = email
                    business.dob_or_incorp_date = dob_or_incorp_date
                    business.save()

                return Response({
                    "message": "Business context created successfully",
                    "context_id": context.id,
                    "business_id": business.id if business else None,
                    "business_name": business_name,
                    "user_session_id": user_session.id,
                    "active_context_id": user_session.active_context.id
                }, status=status.HTTP_201_CREATED)
            except Exception as e:
                logger.error(f"Error creating business context: {str(e)}")
                return Response(
                    {"error": f"An error occurred while creating the business context: {str(e)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

    except Exception as e:
        logger.error(f"Error creating business context: {str(e)}")
        return Response(
            {"error": f"An error occurred while creating the business context: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([AllowAny])
def add_subscription_to_business(request):
    """
        Add a subscription plan to an existing business context.
        Expected request data:
        {
            "context_id": 1,
            "module_id": 1,
            "subscription_plan_id": 1,
            "added_by": 1  # User ID of the person adding the subscription
        }
    """
    context_id = request.data.get('context_id')
    module_id = request.data.get('module_id')
    subscription_plan_id = request.data.get('subscription_plan_id')
    added_by_id = request.data.get('added_by')

    if not all([context_id, module_id, subscription_plan_id, added_by_id]):
        return Response(
            {
                "error": "Missing required fields. Please provide context_id, "
                         "module_id, subscription_plan_id, and added_by."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        with transaction.atomic():
            # Fetch all required instances
            context = Context.objects.get(id=context_id, context_type='business')
            module = Module.objects.get(id=module_id)
            subscription_plan = SubscriptionPlan.objects.get(id=subscription_plan_id)
            added_by = Users.objects.get(id=added_by_id)

            now = timezone.now()
            billing_duration = relativedelta(days=subscription_plan.billing_cycle_days)
            new_end_date = now + billing_duration

            # Block re-use of trial plan
            if subscription_plan.plan_type == 'trial':
                trial_exists = ModuleSubscription.objects.filter(
                    context=context,
                    module=module,
                    plan__plan_type='trial',
                ).exists()

                if trial_exists:
                    return Response(
                        {"error": "Trial plan has already been used for this context and module. Please choose a paid plan."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            # Check if subscription exists and is active
            try:
                module_subscription = ModuleSubscription.objects.get(
                    context=context,
                    module=module,
                    status='active'
                )

                if subscription_plan.plan_type == 'trial':
                    return Response(
                        {
                            "error": "Trial plan can only be used once and cannot update an existing active subscription."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                if module_subscription.end_date > now:
                    module_subscription.end_date = new_end_date
                else:
                    module_subscription.start_date = now
                    module_subscription.end_date = new_end_date

                module_subscription.plan = subscription_plan
                module_subscription.added_by = added_by
                module_subscription.save()

            except ModuleSubscription.DoesNotExist:
                # Create new subscription
                module_subscription = ModuleSubscription.objects.create(
                    context=context,
                    module=module,
                    plan=subscription_plan,
                    status='active',
                    start_date=now,
                    end_date=new_end_date,
                    auto_renew=False,
                    added_by=added_by
                )

            # Set up permissions
            module_features = ModuleFeature.objects.filter(module=module)
            user_context_roles = UserContextRole.objects.filter(context=context)

            actions = list({
                f"{feature.service}.{feature.action}"
                for feature in module_features
            })

            for ucr in user_context_roles:
                ufp, created = UserFeaturePermission.objects.get_or_create(
                    user_context_role=ucr,
                    module=module,
                    defaults={
                        'actions': actions,
                        'is_active': True,
                        'created_by': added_by
                    }
                )
                if not created:
                    ufp.actions = actions
                    ufp.is_active = True
                    ufp.save()

            return Response({
                "message": "Subscription added or updated successfully",
                "module_subscription_id": module_subscription.id,
                "start_date": module_subscription.start_date,
                "end_date": module_subscription.end_date,
                "added_by": {
                    "id": added_by.id,
                    "email": added_by.email,
                    "first_name": added_by.first_name,
                    "last_name": added_by.last_name
                }
            }, status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.error(f"Error adding subscription to business: {str(e)}")
        return Response(
            {"error": f"An error occurred while adding the subscription: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_module_subscriptions(request,pk):
    """
    Retrieve module subscription details for a specific context.
    
    Query parameters:
    - context_id: ID of the context to get subscriptions for
    """

    
    try:
        # Verify context exists
        try:
            context = Context.objects.get(pk=pk)
        except Context.DoesNotExist:
            return Response(
                {"error": "Context not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get all module subscriptions for the context
        subscriptions = ModuleSubscription.objects.filter(context=pk)
        
        # Format the response data
        subscription_data = []
        for subscription in subscriptions:
            # Get module features if needed
            price = subscription.plan.base_price
            if hasattr(price, 'to_decimal'):  # Check if it's a Decimal128 object
                price = float(price.to_decimal())
            else:
                # Try to convert to float if it's not Decimal128 but still needs conversion
                try:
                    price = float(price)
                except (TypeError, ValueError):
                    price = str(price)  # Fallback to string if conversion fails


            subscription_data.append({
                "id": subscription.id,
                "module": {
                    "id": subscription.module.id,
                    "name": subscription.module.name,
                    "description": subscription.module.description
                },
                "plan": {
                    "id": subscription.plan.id,
                    "name": subscription.plan.name,
                    "description": subscription.plan.description,
                    "plan_type": subscription.plan.plan_type,
                    "price": price,
                    "billing_cycle_days": subscription.plan.billing_cycle_days
                },
                "status": subscription.status,
                "start_date": subscription.start_date,
                "end_date": subscription.end_date,
                "auto_renew": subscription.auto_renew,
            })
        
        return Response(
            {"subscriptions": subscription_data},
            status=status.HTTP_200_OK
        )
        
    except Exception as e:
        logger.error(f"Error retrieving module subscriptions: {str(e)}")
        return Response(
            {"error": f"An error occurred while retrieving module subscriptions: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


