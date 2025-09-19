from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
import logging

from .models import (
    Users, UserSession, Context, UserContextRole, Role, 
    Module, ModuleFeature, UserFeaturePermission, ModuleSubscription
)

# Configure logging
logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_current_user_session(request):
    """
    Get the current user's active session and context information.
    
    Returns:
        Current session details including context, business info, and session data
    """
    try:
        user = request.user
        
        # Get the default session (most reliable)
        default_session = user.get_default_session()
        
        if not default_session:
            return Response({
                'error': 'No active session found for user'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Get context information
        context = default_session.active_context
        print(context)
        context_data = None
        business = context.business.id

        
        if context:
            context_data = {
                'context_id': context.id,
                'context_name': context.name,
                'context_type': context.context_type,
                'status': context.status,
                'profile_status': context.profile_status,
                'metadata': context.metadata,
                'created_at': context.created_at,
                'updated_at': context.updated_at
            }
        
        # Get user's role in this context
        role_info = None
        if context:
            try:
                user_role = UserContextRole.objects.get(
                    user=user,
                    context=context,
                    status='active'
                )
                role_info = {
                    'role_id': user_role.role.id,
                    'role_type': user_role.role.role_type,
                    'role_name': user_role.role.name,
                    'permissions': list(user_role.feature_permissions.all().values_list('actions', flat=True))
                }
            except UserContextRole.DoesNotExist:
                role_info = None
        
        return Response({
            'session_id': default_session.id,
            'is_active': default_session.is_active,
            'default_session': default_session.default_session,
            'session_data': default_session.session_data,
            'context': context_data,
            'role': role_info,
            'business':business,
            'created_at': default_session.created_at,
            'updated_at': default_session.updated_at
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error getting current user session: {str(e)}")
        return Response({
            'error': f'An error occurred while getting user session: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_user_contexts(request):
    """
    List all contexts that the user has access to.
    
    Returns:
        List of all contexts with their details and user's role in each
    """
    try:
        user = request.user
        
        # Get all contexts where user has active roles
        user_contexts = UserContextRole.objects.filter(
            user=user,
            status='active'
        ).select_related('context', 'role')
        
        contexts_data = []
        
        for user_context in user_contexts:
            context = user_context.context
            role = user_context.role
            
            # Get module subscriptions for this context
            subscriptions = ModuleSubscription.objects.filter(
                context=context,
                status__in=['active', 'trial']
            ).select_related('module', 'plan')
            
            subscription_data = []
            for sub in subscriptions:
                subscription_data.append({
                    'subscription_id': sub.id,
                    'module_id': sub.module.id,
                    'module_name': sub.module.name,
                    'module_description': sub.module.description,
                    'status': sub.status,
                    'start_date': sub.start_date,
                    'end_date': sub.end_date,
                    'auto_renew': sub.auto_renew,
                    'plan_name': sub.plan.name if sub.plan else None,
                    'plan_type': sub.plan.plan_type if sub.plan else None
                })
            
            # Check if this is the default session
            is_default_session = False
            try:
                default_session = user.get_default_session()
                if default_session and default_session.active_context == context:
                    is_default_session = True
            except:
                pass
            
            context_info = {
                'context_id': context.id,
                'context_name': context.name,
                'context_type': context.context_type,
                'status': context.status,
                'profile_status': context.profile_status,
                'metadata': context.metadata,
                'is_default_session': is_default_session,
                'user_role': {
                    'role_id': role.id,
                    'role_type': role.role_type,
                    'role_name': role.name,
                    'permissions': list(
                                UserFeaturePermission.objects.filter(user_context_role__role=role)
                                .values_list('actions', flat=True)
                            )
                },
                'module_subscriptions': subscription_data,
                'created_at': context.created_at,
                'updated_at': context.updated_at
            }
            
            contexts_data.append(context_info)
        
        return Response({
            'total_contexts': len(contexts_data),
            'contexts': contexts_data
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error listing user contexts: {str(e)}")
        return Response({
            'error': f'An error occurred while listing user contexts: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_module_permissions(request, module_id):
    """
    Get all permissions available for a specific module.
    
    Parameters:
        module_id: ID of the module to get permissions for
    
    Returns:
        Module details and all available permissions
    """
    try:
        user = request.user
        
        # Get the module
        module = get_object_or_404(Module, id=module_id)
        
        # Get all features for this module
        features = ModuleFeature.objects.filter(module=module).select_related('feature')
        
        features_data = []
        for feature in features:
            feature_info = {
                'feature_id': feature.feature.id,
                'feature_name': feature.feature.name,
                'feature_description': feature.feature.description,
                'feature_type': feature.feature.feature_type,
                'is_active': feature.is_active,
                'permissions': list(feature.feature.permissions.all().values_list('name', flat=True))
            }
            features_data.append(feature_info)
        
        # Get all unique permissions across all features
        all_permissions = set()
        for feature in features:
            all_permissions.update(feature.feature.permissions.all().values_list('name', flat=True))
        
        return Response({
            'module_id': module.id,
            'module_name': module.name,
            'module_description': module.description,
            'module_type': module.module_type,
            'is_active': module.is_active,
            'total_features': len(features_data),
            'features': features_data,
            'all_permissions': list(all_permissions),
            'total_permissions': len(all_permissions)
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error getting module permissions: {str(e)}")
        return Response({
            'error': f'An error occurred while getting module permissions: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def check_module_access(request, module_id):
    """
    Check if the user has access to a specific module in their current context.

    Parameters:
        module_id: ID of the module to check access for

    Returns:
        Access status and details about the user's access to the module
    """
    try:
        user = request.user

        # Get the module
        module = get_object_or_404(Module, id=module_id)

        # Get user's current default session
        default_session = user.get_default_session()

        if not default_session or not default_session.active_context:
            return Response({
                'has_access': False,
                'reason': 'No active context found',
                'module_id': module_id,
                'module_name': module.name
            }, status=status.HTTP_200_OK)

        context = default_session.active_context

        # Check if user has an active role in this context (handle multiple roles)
        user_role = None
        ucr_qs = UserContextRole.objects.select_related('role').filter(
            user=user,
            context=context,
            status='active'
        )
        if ucr_qs.exists():
            priority = {'owner': 0, 'admin': 1, 'manager': 2, 'employee': 3, 'custom': 4}
            picked_rank = 999
            for u in ucr_qs:
                rtype = (u.role.role_type or 'custom').lower()
                rank = priority.get(rtype, 9)
                if rank < picked_rank:
                    user_role = u
                    picked_rank = rank

        if not user_role:
            return Response({
                'has_access': False,
                'reason': 'No active role in current context',
                'module_id': module_id,
                'module_name': module.name,
                'context_id': context.id,
                'context_name': context.name
            }, status=status.HTTP_200_OK)

        # Check if there's an active subscription for this module in this context
        try:
            subscription = ModuleSubscription.objects.get(
                context=context,
                module=module,
                status__in=['active', 'trial']
            )

            # Check if subscription is still valid
            from django.utils import timezone
            now = timezone.now()

            if subscription.end_date and subscription.end_date < now:
                return Response({
                    'has_access': False,
                    'reason': 'Subscription expired',
                    'module_id': module_id,
                    'module_name': module.name,
                    'context_id': context.id,
                    'context_name': context.name,
                    'subscription_status': subscription.status,
                    'subscription_end_date': subscription.end_date
                }, status=status.HTTP_200_OK)

            # User has access
            return Response({
                'has_access': True,
                'reason': 'Active subscription found',
                'module_id': module_id,
                'module_name': module.name,
                'context_id': context.id,
                'context_name': context.name,
                'subscription_id': subscription.id,
                'subscription_status': subscription.status,
                'subscription_start_date': subscription.start_date,
                'subscription_end_date': subscription.end_date,
                'auto_renew': subscription.auto_renew,
                'user_role': {
                    'role_id': user_role.role.id,
                    'role_type': user_role.role.role_type,
                    'role_name': user_role.role.name
                }
            }, status=status.HTTP_200_OK)

        except ModuleSubscription.DoesNotExist:
            return Response({
                'has_access': False,
                'reason': 'No active subscription for this module',
                'module_id': module_id,
                'module_name': module.name,
                'context_id': context.id,
                'context_name': context.name,
                'user_role': {
                    'role_id': user_role.role.id,
                    'role_type': user_role.role.role_type,
                    'role_name': user_role.role.name
                }
            }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error checking module access: {str(e)}")
        return Response({
            'error': f'An error occurred while checking module access: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_permissions_summary(request):
    """
    Get a comprehensive summary of user's permissions across all contexts and modules.
    
    Returns:
        Complete summary of user's access, roles, and permissions
    """
    try:
        user = request.user
        
        # Get current session
        default_session = user.get_default_session()
        current_context = default_session.active_context if default_session else None
        
        # Get all user contexts with roles
        user_contexts = UserContextRole.objects.filter(
            user=user,
            status='active'
        ).select_related('context', 'role')
        
        # Get all module subscriptions
        all_subscriptions = ModuleSubscription.objects.filter(
            context__in=[uc.context for uc in user_contexts],
            status__in=['active', 'trial']
        ).select_related('module', 'context', 'plan')
        
        # Organize data by context
        contexts_summary = []
        for user_context in user_contexts:
            context = user_context.context
            role = user_context.role
            
            # Get subscriptions for this context
            context_subscriptions = [sub for sub in all_subscriptions if sub.context == context]
            
            # Get all permissions for this role
            role_permissions = list(role.permissions.all().values_list('name', flat=True))
            
            context_info = {
                'context_id': context.id,
                'context_name': context.name,
                'context_type': context.context_type,
                'is_current_context': context == current_context,
                'user_role': {
                    'role_id': role.id,
                    'role_type': role.role_type,
                    'role_name': role.name,
                    'permissions': role_permissions
                },
                'module_subscriptions': [
                    {
                        'subscription_id': sub.id,
                        'module_id': sub.module.id,
                        'module_name': sub.module.name,
                        'status': sub.status,
                        'start_date': sub.start_date,
                        'end_date': sub.end_date,
                        'auto_renew': sub.auto_renew
                    }
                    for sub in context_subscriptions
                ],
                'total_modules': len(context_subscriptions)
            }
            
            contexts_summary.append(context_info)
        
        # Calculate totals
        total_contexts = len(contexts_summary)
        total_modules = sum(len(ctx['module_subscriptions']) for ctx in contexts_summary)
        all_permissions = set()
        for ctx in contexts_summary:
            all_permissions.update(ctx['user_role']['permissions'])
        
        return Response({
            'user_id': user.id,
            'user_email': user.email,
            'current_context': {
                'context_id': current_context.id if current_context else None,
                'context_name': current_context.name if current_context else None,
                'context_type': current_context.context_type if current_context else None
            } if current_context else None,
            'summary': {
                'total_contexts': total_contexts,
                'total_modules': total_modules,
                'total_permissions': len(all_permissions),
                'all_permissions': list(all_permissions)
            },
            'contexts': contexts_summary
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error getting user permissions summary: {str(e)}")
        return Response({
            'error': f'An error occurred while getting user permissions summary: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_user_context_role(request):
    """
    Create a new user context role with specific feature permissions.

    Expected JSON payload:
    {
        "user_id": int,
        "context_id": int,
        "role_id": int,
        "feature_permissions": [int, int, ...]
    }
    Returns:
        Details of the created user context role
    """
    try:
        data = request.data
        user_id = data.get('user_id')
        context_id = data.get('context_id')
        role_id = data.get('role_id')

        # Validate required fields
        if not all([user_id, context_id, role_id]):
            return Response({
                'error': 'user_id, context_id, and role_id are required fields'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Fetch related objects
        user = get_object_or_404(Users, id=user_id)
        context = get_object_or_404(Context, id=context_id)
        role = get_object_or_404(Role, id=role_id)

        # Create UserContextRole
        user_context_role = UserContextRole.objects.create(
            user=user,
            context=context,
            role=role,
            status='active',
            added_by=request.user
        )

        return Response({
            'message': 'User context role created successfully',
            'user_context_role': {
                'id': user_context_role.id,
                'user_id': user_context_role.user.id,
                'context_id': user_context_role.context.id,
                'role_id': user_context_role.role.id,
                'status': user_context_role.status,
            }
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.error(f"Error creating user context role: {str(e)}")
        return Response({
            'error': f'An error occurred while creating user context role: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_context_role(request):
    """
        Get details of a specific user context role using User_id, context_id.
        Expected query parameters:
            user_id: int
            context_id: int
            role_id: int
        Returns:
            Details of the user context role if found
            {
                'id': int,
                'user_id': int,
                'context_id': int,
                'role_id': int,
                'status': str,
                'feature_permissions': [int, int, ...],
                'created_at': datetime,
                'updated_at': datetime
            }
    """
    try:
        user_id = request.query_params.get('user_id')
        context_id = request.query_params.get('context_id')
        role_id = request.query_params.get('role_id')

        if not all([user_id, context_id]):
            return Response({
                'error': 'user_id and context_id are required query parameters'
            }, status=status.HTTP_400_BAD_REQUEST)

        user_context_role = UserContextRole.objects.filter(
            user__id=user_id,
            context__id=context_id,
            role__id=role_id,
            status='active'
        ).first()

        if not user_context_role:
            return Response({
                'error': 'User context role not found'
            }, status=status.HTTP_404_NOT_FOUND)

        return Response({
            'user_context_role': {
                'id': user_context_role.id,
                'user_id': user_context_role.user.id,
                'context_id': user_context_role.context.id,
                'role_id': user_context_role.role.id,
                'status': user_context_role.status,
                'feature_permissions': list(user_context_role.feature_permissions.all().values_list('id', flat=True)),
                'created_at': user_context_role.created_at,
                'updated_at': user_context_role.updated_at
            }
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error getting user context role: {str(e)}")
        return Response({
            'error': f'An error occurred while getting user context role: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

