from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db import transaction
from .models import ModuleFeature, UserFeaturePermission
from .models import *
from .serializers import ModuleFeatureSerializer, UserFeaturePermissionSerializer, RoleSerializer


# ModuleFeature Views
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_module_features(request):
    """List all module features"""
    # Get user's active context from UserSession
    try:
        user_session = request.user.get_active_session()
        active_context = user_session.active_context if user_session else None
        print(f"Active context: {active_context}")
    except:
        print("No active context found")
    
    features = ModuleFeature.objects.all()
    serializer = ModuleFeatureSerializer(features, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_module_features_by_module(request, module_id):
    """List all module features for a specific module"""
    features = ModuleFeature.objects.filter(module_id=module_id)
    serializer = ModuleFeatureSerializer(features, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_module_feature(request):
    """Create a new module feature"""
    serializer = ModuleFeatureSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def manage_module_feature(request, pk):
    """Get, update or delete a module feature"""
    feature = get_object_or_404(ModuleFeature, pk=pk)

    if request.method == 'GET':
        serializer = ModuleFeatureSerializer(feature)
        return Response(serializer.data)

    elif request.method == 'PUT':
        serializer = ModuleFeatureSerializer(feature, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        feature.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_create_module_features(request):
    """Bulk create module features"""
    serializer = ModuleFeatureSerializer(data=request.data, many=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# UserFeaturePermission Views
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_user_feature_permissions(request):
    """List all user feature permissions"""
    permissions = UserFeaturePermission.objects.all()
    serializer = UserFeaturePermissionSerializer(permissions, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_user_feature_permission(request):
    """Create a new user feature permission"""
    serializer = UserFeaturePermissionSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_create_user_feature_permissions(request):
    """Bulk create user feature permissions"""
    serializer = UserFeaturePermissionSerializer(data=request.data, many=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def bulk_update_user_context_role_permissions(request, user_context_role_id):
    """
    Bulk update permissions for a user context role across multiple modules.

    Expected payload:
    [
        {
            "module": 1,
            "actions": [
                "EmployeeManagement.create",
                "EmployeeManagement.read",
                ...
            ]
        },
        {
            "module": 2,
            "actions": [
                "Invoice.create",
                "Invoice.read",
                ...
            ]
        }
    ]
    """
    try:
        # Verify the user_context_role exists
        user_context_role = get_object_or_404(UserContextRole, pk=user_context_role_id)

        if not request.data:
            return Response(
                {"error": "Request body is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Convert single object to list if needed
        permissions_data = request.data if isinstance(request.data, list) else [request.data]

        with transaction.atomic():
            results = []
            for permission_data in permissions_data:
                module_id = permission_data.get('module')
                actions = permission_data.get('actions', [])

                if not module_id:
                    return Response(
                        {"error": "Module id is required to update permissions"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Get or create the permission
                permission, created = UserFeaturePermission.objects.get_or_create(
                    user_context_role=user_context_role,
                    module_id=module_id,
                    defaults={'actions': actions}
                )

                if not created:
                    permission.actions = actions
                    permission.save()

                serializer = UserFeaturePermissionSerializer(permission)
                results.append(serializer.data)

            return Response(results)

    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def manage_user_feature_permission(request, pk):
    """Get, update or delete a user feature permission"""
    permission = get_object_or_404(UserFeaturePermission, pk=pk)

    if request.method == 'GET':
        serializer = UserFeaturePermissionSerializer(permission)
        return Response(serializer.data)

    elif request.method == 'PUT':
        serializer = UserFeaturePermissionSerializer(permission, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        permission.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_feature_permissions_by_role(request, user_context_role_id):
    """Get all feature permissions for a specific user context role"""
    role = get_object_or_404(UserContextRole, pk=user_context_role_id)
    permissions = UserFeaturePermission.objects.filter(user_context_role=role)
    serializer = UserFeaturePermissionSerializer(permissions, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_feature_permissions_by_module(request, module_id):
    """Get all feature permissions for a specific module"""
    module = get_object_or_404(Module, pk=module_id)
    permissions = UserFeaturePermission.objects.filter(module=module)
    serializer = UserFeaturePermissionSerializer(permissions, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_context_module_features(request):
    """Get all feature permissions for a specific user context and module"""
    user_context_id = request.query_params.get('user_context_role_id')
    module_id = request.query_params.get('module_id')

    if not user_context_id or not module_id:
        return Response(
            {"error": "Both user_context_id and module_id are required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    permissions = UserFeaturePermission.objects.filter(
        user_context_role__id=user_context_id,
        module_id=module_id
    )
    serializer = UserFeaturePermissionSerializer(permissions, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_feature_permissions_by_feature(request, feature_code):
    """Get all feature permissions for a specific feature code"""
    permissions = UserFeaturePermission.objects.filter(feature_code=feature_code)
    serializer = UserFeaturePermissionSerializer(permissions, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_context_module_features(request, context_id):
    """
    Get all module features for a given context.

    Args:
        context_id: ID of the context to get features for

    Returns:
        List of modules with their features
    """
    try:
        # Verify context exists and user has access
        context = Context.objects.get(id=context_id)

        # Get all active module subscriptions for this context
        subscribed_modules = ModuleSubscription.objects.filter(
            context=context,
            status__in=['active', 'trial']
        ).select_related('module')

        result = []
        for subscription in subscribed_modules:
            module = subscription.module
            # Get all features for this module
            features = ModuleFeature.objects.filter(module=module).values(
                'service',
                'action',
                'label'
            )

            module_data = {
                'module_id': module.id,
                'module_name': module.name,
                'module_description': module.description,
                'subscription_status': subscription.status,
                'features': list(features)
            }
            result.append(module_data)

        return Response({
            'status': 'success',
            'data': result
        })

    except Context.DoesNotExist:
        return Response({
            'status': 'error',
            'message': 'Context not found'
        }, status=404)
    except Exception as e:
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_role_for_employee(request):
    data = request.data
    print(data)
    role = RoleSerializer(data=data)
    if role.is_valid():
        role.save()
        return Response({
            'status': 'success',
            'data': role.data
        }, status=status.HTTP_201_CREATED)
    return Response({'error': role.errors})


