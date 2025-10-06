from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.utils import timezone
from dateutil.relativedelta import relativedelta
import logging
from .serializers import UserProfileSerializer

from .models import (
    Users, Context, Role, UserContextRole, Module,
    ModuleFeature, UserFeaturePermission, SubscriptionPlan, ModuleSubscription, Business, UserKYC, UserProfile
)


# Configure logging
logger = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([AllowAny])
def create_personal_context(request):
    """
    Create a new personal context with KYC information.

    Expected request data:
    {
        "user_id": 1,
        "first_name": "John",
        "last_name": "Doe",
        "name": "John Doe",
        "pan_number": "ABCDE1234F",
        "aadhaar_number": "123456789012",
        "date": "1990-01-01",
        "icai_number": "ICAI123456",
        "have_firm": true,
        "address": {
            "address_line1": "123 Main St",
            "address_line2": "Apt 4B",
            "state": "New York",
            "city": "New York City",
            "country": "USA",
            "pincode": "10001"
        }
    }
    """
    # Extract data from request
    user_id = request.data.get('user_id')
    first_name = request.data.get('first_name')
    last_name = request.data.get('last_name')

    # Extract KYC data
    name = request.data.get('name')
    pan_number = request.data.get('pan_number')
    aadhaar_number = request.data.get('aadhaar_number')
    date = request.data.get('date')
    icai_number = request.data.get('icai_number')
    have_firm = request.data.get('have_firm', False)
    address = request.data.get('address')

    # Validate required fields
    if not all([user_id, first_name, last_name, name, pan_number, aadhaar_number, date]):
        return Response(
                {"error": "Missing required fields. Please provide user_id, first_name, last_name, name, pan_number, aadhaar_number, and date."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Validate address if provided
    if address:
        required_address_fields = ['address_line1', 'state', 'city', 'country']
        missing_fields = [field for field in required_address_fields if not address.get(field)]
        if missing_fields:
            return Response(
                {"error": f"Missing required address fields: {', '.join(missing_fields)}"},
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

            # Check if user already has a KYC record
            try:
                existing_kyc = UserKYC.objects.get(user=user)
                return Response(
                    {"error": "User already has a KYC record."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            except UserKYC.DoesNotExist:
                pass

            # Update user profile details
            from .models import UserProfile
            user_profile, created = UserProfile.objects.get_or_create(
                user=user,
                defaults={
                    'first_name': first_name,
                    'last_name': last_name
                }
            )
            if not created:
                user_profile.first_name = first_name
                user_profile.last_name = last_name
                user_profile.save()

            # Create user KYC record first
            user_kyc = UserKYC.objects.create(
                user=user,
                name=name,
                pan_number=pan_number,
                aadhaar_number=aadhaar_number,
                date=date,
                icai_number=icai_number if have_firm else None,
                have_firm=have_firm,
                address=address
            )

            # Create personal context
            context = Context.objects.create(
                name=f"{first_name}'s Personal Context",
                context_type='personal',
                owner_user=user,
                status='active',
                profile_status='complete',
                metadata={
                    'kyc_id': user_kyc.id,
                    'kyc_completed': user_kyc.is_completed
                }
            )

            # Create owner role for the personal context
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

            return Response({
                "message": "Personal context created successfully",
                "context_id": context.id,
                "kyc_id": user_kyc.id,
                "kyc_completed": user_kyc.is_completed,
                "context_type": "personal"
            }, status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.error(f"Error creating personal context: {str(e)}")
        return Response(
            {"error": f"An error occurred while creating the personal context: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_user_by_email(request):
    """
    Search for a user by email and return their basic data.

    Query Parameters:
        email: The email address to search for

    Returns:
        Basic user data if found, error message if not found
    """
    email = request.query_params.get('email')

    if not email:
        return Response({
            'status': 'error',
            'message': 'Email parameter is required'
        }, status=400)

    try:
        # Search for the user by email
        user = Users.objects.filter(email=email).first()

        if not user:
            return Response({
                'status': 'error',
                'message': f'User with email {email} not found'
            }, status=404)

        # Prepare basic user data response
        user_data = {
            'user_id': user.id,
            'email': user.email,
            'mobile_number': user.mobile_number,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'status': user.status,
            'created_at': user.created_at,
            'is_active': user.is_active
        }

        return Response({
            'status': 'success',
            'data': user_data
        })

    except Exception as e:
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_context_subscriptions(request, context_id):
    """
    Get all recent subscriptions for a specific context with detailed information.

    Args:
        context_id (int): The ID of the context to get subscriptions for

    Returns:
        Response: List of subscriptions with their details including subscription plan, pricing, and usage information
    """
    try:
        # Get the context
        context = Context.objects.get(id=context_id)

        # Get all active subscriptions for this context
        subscriptions = ModuleSubscription.objects.filter(
            context=context,
            status__in=['active', 'trial']
        ).select_related(
            'module',
            'plan'
        ).order_by('-created_at')

        # Format the response
        subscription_data = []
        for subscription in subscriptions:
            # Get module features for this subscription
            module_features = ModuleFeature.objects.filter(
                module=subscription.module
            ).values('id', 'service', 'action', 'label')

            # Get subscription plan details if available
            plan_data = None
            if subscription.plan:
                plan = subscription.plan
                plan_data = {
                    'plan_id': plan.id,
                    'plan_name': plan.name,
                    'plan_type': plan.plan_type,
                    'description': plan.description,
                    'base_price': str(plan.base_price),  # Convert Decimal to string
                    'billing_cycle_days': plan.billing_cycle_days,
                    'features_enabled': plan.features_enabled,
                    'is_active': plan.is_active,
                    'created_at': plan.created_at,
                    'updated_at': plan.updated_at
                }

            subscription_data.append({
                'subscription_id': subscription.id,
                'module_id': subscription.module.id,
                'module_name': subscription.module.name,
                'module_description': subscription.module.description,
                'status': subscription.status,
                'start_date': subscription.start_date,
                'end_date': subscription.end_date,
                'created_at': subscription.created_at,
                'last_updated': subscription.updated_at,
                'auto_renew': subscription.auto_renew,
                'payment_status': subscription.payment_status if hasattr(subscription, 'payment_status') else None,
                'trial_period': subscription.status == 'trial',
                'trial_end_date': subscription.end_date if subscription.status == 'trial' else None,
                'subscription_plan': plan_data,
                'features': list(module_features),
                'subscription_history': [
                    {
                        'status': history.status,
                        'changed_at': history.changed_at,
                        'changed_by': history.changed_by.username if history.changed_by else None,
                        'reason': history.reason
                    }
                    for history in subscription.subscription_history.all()
                ] if hasattr(subscription, 'subscription_history') else []
            })

        return Response({
            'context_id': context.id,
            'context_name': context.name,
            'context_type': context.context_type,
            'total_active_subscriptions': len(subscription_data),
            'subscriptions': subscription_data
        }, status=status.HTTP_200_OK)

    except Context.DoesNotExist:
        return Response(
            {"error": f"Context with ID {context_id} does not exist."},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {"error": f"Failed to get subscriptions: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_profile_by_user(request, user_id):
    """
    Retrieve a user's profile.

    GET: Retrieve user profile details.

    Args:
        request
        user_id (int): The ID of the user to manage.
    """
    try:
        user = Users.objects.get(id=user_id)
    except Users.DoesNotExist:
        return Response(
            {"error": "User not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    if request.method == 'GET':
        # Retrieve user profile details
        user_profile = UserProfile.objects.get(user=user)
        serializer = UserProfileSerializer(user_profile)
        return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def user_profile_detail(request, profile_id):
    """
    Retrieve, update, or delete a user's profile.

    GET: Retrieve user profile details.
    PUT: Update user profile details.
    DELETE: Delete user profile.

    Args:
        request
        pk (int): The ID of the user to manage.
    """
    try:
        user_profile = UserProfile.objects.get(id=profile_id)
    except UserProfile.DoesNotExist:
        return Response(
            {"error": "User not found."},
            status=status.HTTP_404_NOT_FOUND
        )
    user = user_profile.user
    if request.method == 'GET':
        serializer = UserProfileSerializer(user_profile)
        return Response(serializer.data, status=status.HTTP_200_OK)
    elif request.method == 'PUT':
        # Update user profile details
        instance = UserProfileSerializer(user_profile, data=request.data, partial=True)
        if instance.is_valid():
            instance.save()
            return Response(instance.data, status=status.HTTP_200_OK)
        return Response(instance.errors, status=status.HTTP_400_BAD_REQUEST)
    elif request.method == 'DELETE':
        user_profile.delete()
        return Response(
            {"message": "User profile deleted successfully."},
            status=status.HTTP_200_OK
        )