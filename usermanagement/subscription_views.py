from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from .models import SubscriptionPlan, Module, ModuleSubscription, SubscriptionCycle, ModuleUsageCycle
from .serializers import SubscriptionPlanSerializer, ModuleSubscriptionSerializer
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError


@api_view(['POST'])
@permission_classes([AllowAny])
def create_subscription_plan(request):
    """
    Create a new subscription plan for a module
    Required fields: module_id, name, plan_type, base_price
    Optional fields: description, usage_unit, free_tier_limit, price_per_unit, billing_cycle_days
    """
    try:
        # Validate module exists
        module_id = request.data.get('module_id')
        if not module_id:
            return Response({
                'success': False,
                'error': 'module_id is required'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            module = Module.objects.get(id=module_id)
        except Module.DoesNotExist:
            return Response({
                'success': False,
                'error': f'Module with id {module_id} does not exist'
            }, status=status.HTTP_404_NOT_FOUND)

        # Add module to request data
        data = request.data.copy()
        data['module'] = module_id

        serializer = SubscriptionPlanSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response({
                'success': True,
                'message': 'Subscription plan created successfully',
                'data': serializer.data
            }, status=status.HTTP_201_CREATED)
        return Response({
            'success': False,
            'error': 'Invalid data',
            'details': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

    except IntegrityError as e:
        return Response({
            'success': False,
            'error': 'A subscription plan with this name already exists for this module'
        }, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({
            'success': False,
            'error': 'An unexpected error occurred',
            'details': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

#
# @api_view(['GET'])
# @permission_classes([IsAuthenticated])
# def list_subscription_plans(request):
#     try:
#         module_id = request.query_params.get('module_id')
#         plan_type = request.query_params.get('plan_type')
#
#         query = {}
#         if module_id:
#             query['module_id'] = module_id
#         if plan_type:
#             query['plan_type'] = str(plan_type)  # fix: ensure it's not a tuple
#
#         plans = SubscriptionPlan.objects.filter(is_active=True)
#         serializer = SubscriptionPlanSerializer(plans, many=True)
#
#         return Response({
#             'success': True,
#             'data': serializer.data
#         }, status=status.HTTP_200_OK)
#
#     except Exception as e:
#         return Response({
#             'success': False,
#             'error': 'An unexpected error occurred',
#             'details': str(e)
#         }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def list_subscription_plans(request):
    """
    List all subscription plans.
    Optional filters: module_id, plan_type, is_active
    """
    module_id = request.query_params.get('module_id')
    plan_type = request.query_params.get('plan_type')
    is_active_param = request.query_params.get('is_active')

    filter_kwargs = {}

    if module_id:
        filter_kwargs['module_id'] = module_id
    if plan_type:
        filter_kwargs['plan_type'] = plan_type
    if is_active_param:
        is_active_param = is_active_param.lower()
        if is_active_param in ['yes', 'true', '1']:
            filter_kwargs['is_active'] = True
        elif is_active_param in ['no', 'false', '0']:
            filter_kwargs['is_active'] = False

    plans = SubscriptionPlan.objects.filter(**filter_kwargs)
    serializer = SubscriptionPlanSerializer(plans, many=True)

    return Response({
        'success': True,
        'data': serializer.data
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_subscription_plan(request, plan_id):
    """
    Get details of a specific subscription plan
    """
    try:
        plan = SubscriptionPlan.objects.get(id=plan_id)
        serializer = SubscriptionPlanSerializer(plan)
        return Response({
            'success': True,
            'data': serializer.data
        }, status=status.HTTP_200_OK)

    except SubscriptionPlan.DoesNotExist:
        return Response({
            'success': False,
            'error': f'Subscription plan with id {plan_id} does not exist'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'success': False,
            'error': 'An unexpected error occurred',
            'details': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_subscription_plan(request, plan_id):
    """
    Update a subscription plan
    """
    try:
        plan = SubscriptionPlan.objects.get(id=plan_id)
        serializer = SubscriptionPlanSerializer(plan, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()
            return Response({
                'success': True,
                'message': 'Subscription plan updated successfully',
                'data': serializer.data
            }, status=status.HTTP_200_OK)

        return Response({
            'success': False,
            'error': 'Invalid data',
            'details': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

    except SubscriptionPlan.DoesNotExist:
        return Response({
            'success': False,
            'error': f'Subscription plan with id {plan_id} does not exist'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'success': False,
            'error': 'An unexpected error occurred',
            'details': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_subscription_plan(request, plan_id):
    """
    Delete a subscription plan
    """
    try:
        plan = SubscriptionPlan.objects.get(id=plan_id)

        # Check if plan is being used by any active subscriptions
        if plan.module_subscriptions.filter(status__in=['trial', 'active', 'pending_renewal']).exists():
            return Response({
                'success': False,
                'error': 'Cannot delete plan with active subscriptions'
            }, status=status.HTTP_400_BAD_REQUEST)

        plan.delete()
        return Response({
            'success': True,
            'message': 'Subscription plan deleted successfully'
        }, status=status.HTTP_200_OK)

    except SubscriptionPlan.DoesNotExist:
        return Response({
            'success': False,
            'error': f'Subscription plan with id {plan_id} does not exist'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'success': False,
            'error': 'An unexpected error occurred',
            'details': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_active_module_subscriptions(request):
    """
    Get all subscriptions for a given context and module
    Required query params: context_id, module_id
    """
    context_id = request.query_params.get('context_id')
    module_id = request.query_params.get('module_id')

    if not context_id or not module_id:
        return Response({
            'success': False,
            'error': 'context_id and module_id are required query parameters'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Build filters for the original query
    subscription_filters = {
        "module_id": module_id,
        "context_id": context_id,
        "status__in": ["active", "trial"]
    }

    try:
        subscriptions = ModuleSubscription.objects.filter(**subscription_filters).distinct()

    except Exception as e:
        return Response({
            'success': False,
            'error': f'Error fetching subscriptions: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    serializer = ModuleSubscriptionSerializer(subscriptions, many=True)
    return Response({
        'success': True,
        'data': serializer.data
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_subscription_cycle(request):
    """
    Retrieve the most recent subscription cycle for a given subscription.

    This endpoint returns the latest subscription cycle based on start date
    for the specified subscription ID.

    Query Parameters:
        subscription (int): Required. The ID of the subscription to fetch cycles for.

    Returns:
        - 200 OK: Returns JSON with the cycle ID if found
          Example: {'id': 123}
        - 404 Not Found: Returns error if no subscription cycles exist
          Example: {'error': 'Data Not Found'}

    Example Request:
        GET subscription-cycle/?subscription=456

    Example Response (Success):
        HTTP 200 OK
        {'id': 789}

    Example Response (Failure):
        HTTP 404 Not Found
        {'error': 'Data Not Found'}

    Permissions:
        - User must be authenticated
    """
    subscription = request.query_params.get('subscription')
    cycle = SubscriptionCycle.objects.filter(subscription=subscription).order_by('-start_date').first()
    if cycle:
        return Response({'id': cycle.id})
    return Response({'error': 'Data Not Found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_module_usage_cycle(request):
    """
    Retrieve module usage cycle details for a specific cycle and feature.

    This endpoint fetches usage statistics for a particular feature within a
    subscription cycle, including actual usage count and allocated usage count.

    Query Parameters:
        cycle (int): Required. The ID of the subscription cycle to query.
        feature_key (str): Required. The key identifier of the feature to check usage for.

    Returns:
        - 200 OK: Returns usage cycle details if found
          Example: {
            'id': 45,
            'feature_key': 'storage_gb',
            'actual_count': 15,
            'usage_count': 20
          }
        - 404 Not Found: Returns error if no matching usage cycle entry exists
          Example: {'error': 'Module Usage Cycle Not Found'}

    Response Fields:
        id (int): The unique identifier of the usage cycle entry
        feature_key (str): The key identifying the feature being tracked
        actual_count (int): The current actual usage count for the feature
        usage_count (int): The allocated or maximum usage count for the feature

    Example Request:
        GET GET-module-usage-cycle/?cycle=123&feature_key=user_seats

    Example Response (Success):
        HTTP 200 OK
        {
            "id": 456,
            "feature_key": "user_seats",
            "actual_count": 25,
            "usage_count": 50
        }

    Example Response (Failure):
        HTTP 404 Not Found
        {"error": "Module Usage Cycle Not Found"}

    Permissions:
        - User must be authenticated to access this endpoint

    Use Case:
        This endpoint is typically used by frontend applications to display
        current usage statistics and progress bars for feature limits within
        a subscription cycle.
    """
    cycle_id = request.query_params.get('cycle')
    feature_key = request.query_params.get('feature_key')
    usage_entry = ModuleUsageCycle.objects.filter(cycle__id=cycle_id, feature_key=feature_key).first()
    if usage_entry:
        data = {
            'id': usage_entry.id,
            'feature_key': usage_entry.feature_key,
            'actual_count': usage_entry.actual_count,
            'usage_count': usage_entry.usage_count
        }
        return Response({'data': data}, status=status.HTTP_200_OK)
    return Response({'error': "Module Usage Cycle Not Found"}, status=status.HTTP_404_NOT_FOUND)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_module_usage_cycle(request):
    """
        Increment the usage counter for a limited feature in a module usage cycle.

        This endpoint increases the usage_count by 1 for the specified module usage cycle.
        The increment operation is only performed if the feature has limited usage
        (actual_count is not set to "unlimited").

        Request Body (JSON):
            {
                "id": <integer>  # Required: ID of the ModuleUsageCycle entry to update
            }

        Returns:
            - 200 OK: Success response when usage is incremented or already unlimited
              Example: {"message": "Data Updated Successfully"}
            - 404 Not Found: When the specified ModuleUsageCycle ID does not exist
              Example: {"success": false, "error": "Module Usage Cycle with id 123 does not exist"}
            - 500 Internal Server Error: For unexpected server errors

        Behavior:
            - If actual_count equals "unlimited": No operation performed, returns success
            - If actual_count is not "unlimited": Increments usage_count by 1
            - usage_count is treated as a string that can be converted to integer

        Example Usage:
            PUT module-usage-cycle/update
            Authorization: Bearer <token>
            Content-Type: application/json
            {"id": 45}

        Response Examples:
            Success (Limited feature):
                HTTP 200 OK
                {"message": "Data Updated Successfully"}

            Success (Unlimited feature - no change):
                HTTP 200 OK
                {"message": "Data Updated Successfully"}

            Error (Not found):
                HTTP 404 Not Found
                {"success": false, "error": "Module Usage Cycle with id 999 does not exist"}

        Permissions:
            - Requires authenticated user with valid JWT token
    """
    try:
        module_usage_cycle_id = request.data.get('id')
        try:
            usage = ModuleUsageCycle.objects.get(id=module_usage_cycle_id)
        except ModuleUsageCycle.DoesNotExist:
            return Response({
                'success': False,
                'error': f'Module Usage Cycle with id {module_usage_cycle_id} does not exist'
            }, status=status.HTTP_404_NOT_FOUND)
        if usage and usage.actual_count != "unlimited":
            usage.usage_count = str(int(usage.usage_count) + 1)
            usage.save(update_fields=['usage_count'])
        return Response({'message':'Data Updated Successfully'}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({
            'error': f'Error fetching subscriptions: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

