"""
MICROSERVICE API ENDPOINTS
==========================

API endpoints for other microservices to call usermanagement
for user data, permissions, and validation.
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import get_user_model
from .models import Users, Context, UserContextRole, ModuleSubscription
import jwt
from django.conf import settings
from functools import wraps

User = get_user_model()


# =============================================================================
# JWT VALIDATION DECORATOR FOR INTERNAL API CALLS
# =============================================================================

def validate_internal_jwt(view_func):
    """
    Decorator to validate JWT tokens for internal microservice API calls
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Get token from Authorization header
        auth_header = request.META.get('HTTP_AUTHORIZATION')
        
        if not auth_header or not auth_header.startswith('Bearer '):
            return Response({
                'error': 'Authentication required'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        # Extract and validate token
        token = auth_header.split(' ')[1]
        
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            request.jwt_user = payload
        except jwt.ExpiredSignatureError:
            return Response({
                'error': 'Token expired'
            }, status=status.HTTP_401_UNAUTHORIZED)
        except jwt.InvalidTokenError:
            return Response({
                'error': 'Invalid token'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


# =============================================================================
# MICROSERVICE API ENDPOINTS
# =============================================================================

@api_view(['GET'])
@validate_internal_jwt
def get_user_info(request, user_id):
    """
    Get user information by user_id
    Called by other microservices to get user details
    """
    try:
        # Verify the JWT user matches the requested user_id
        jwt_user_id = request.jwt_user['user_id']
        if jwt_user_id != user_id:
            return Response({
                'error': 'Access denied'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Get user from database
        user = User.objects.get(id=user_id)
        
        # Get user's active context
        try:
            user_session = user.get_active_session()
            context = user_session.active_context
        except:
            context = None
        
        # Build user info response
        user_info = {
            'id': user.id,
            'email': user.email,
            'is_active': user.is_active,
            'created_at': user.created_at,
            'last_login': user.last_login,
        }
        
        # Add context info if available
        if context:
            user_info.update({
                'context_id': context.id,
                'context_type': context.context_type,
                'organization_id': context.business.id if context.business else None,
                'business_name': context.business.name if context.business else None,
            })
        
        return Response({
            'success': True,
            'user': user_info
        })
        
    except User.DoesNotExist:
        return Response({
            'error': 'User not found'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'error': f'Failed to get user info: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@validate_internal_jwt
def get_user_permissions(request, user_id):
    """
    Get user permissions for a specific context
    Called by other microservices to check user permissions
    """
    try:
        # Verify the JWT user matches the requested user_id
        jwt_user_id = request.jwt_user['user_id']
        if jwt_user_id != user_id:
            return Response({
                'error': 'Access denied'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Get user from database
        user = User.objects.get(id=user_id)
        
        # Get context_id from query parameters or JWT
        context_id = request.GET.get('context_id') or request.jwt_user.get('context_id')
        
        if not context_id:
            return Response({
                'error': 'context_id is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get context
        try:
            context = Context.objects.get(id=context_id)
        except Context.DoesNotExist:
            return Response({
                'error': 'Context not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Get user's role in this context
        try:
            user_context_role = UserContextRole.objects.get(
                user=user,
                context=context,
                status='active'
            )
            role = user_context_role.role
        except UserContextRole.DoesNotExist:
            return Response({
                'error': 'User has no role in this context'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Get user's permissions
        permissions = get_user_permissions_for_context(user, context)
        
        return Response({
            'success': True,
            'user_id': user_id,
            'context_id': context_id,
            'role': {
                'role_type': role.role_type,
                'context': context.context_type,
                'role_id': role.id
            },
            'permissions': permissions
        })
        
    except User.DoesNotExist:
        return Response({
            'error': 'User not found'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'error': f'Failed to get user permissions: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@validate_internal_jwt
def get_user_contexts(request, user_id):
    """
    Get all contexts (organizations) for a user
    Called by other microservices to get user's available contexts
    """
    try:
        # Verify the JWT user matches the requested user_id
        jwt_user_id = request.jwt_user['user_id']
        if jwt_user_id != user_id:
            return Response({
                'error': 'Access denied'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Get user from database
        user = User.objects.get(id=user_id)
        
        # Get user's contexts
        user_context_roles = UserContextRole.objects.filter(
            user=user,
            status='active'
        ).select_related('context', 'context__business', 'role')
        
        contexts = []
        for ucr in user_context_roles:
            context = ucr.context
            contexts.append({
                'context_id': context.id,
                'context_type': context.context_type,
                'context_name': context.name,
                'organization_id': context.business.id if context.business else None,
                'business_name': context.business.name if context.business else None,
                'role': {
                    'role_type': ucr.role.role_type,
                    'role_id': ucr.role.id
                }
            })
        
        return Response({
            'success': True,
            'user_id': user_id,
            'contexts': contexts
        })
        
    except User.DoesNotExist:
        return Response({
            'error': 'User not found'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'error': f'Failed to get user contexts: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@validate_internal_jwt
def validate_user_access(request):
    """
    Validate if user has access to a specific service/feature
    Called by other microservices to check access
    """
    try:
        user_id = request.jwt_user['user_id']
        service_name = request.data.get('service_name')
        permission = request.data.get('permission')
        context_id = request.data.get('context_id')
        
        if not all([service_name, permission]):
            return Response({
                'error': 'service_name and permission are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get user from database
        user = User.objects.get(id=user_id)
        
        # Get context
        if context_id:
            try:
                context = Context.objects.get(id=context_id)
            except Context.DoesNotExist:
                return Response({
                    'error': 'Context not found'
                }, status=status.HTTP_404_NOT_FOUND)
        else:
            # Use context from JWT
            context_id = request.jwt_user.get('context_id')
            if not context_id:
                return Response({
                    'error': 'context_id is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            try:
                context = Context.objects.get(id=context_id)
            except Context.DoesNotExist:
                return Response({
                    'error': 'Context not found'
                }, status=status.HTTP_404_NOT_FOUND)
        
        # Check user's permissions
        permissions = get_user_permissions_for_context(user, context)
        has_permission = permissions.get(permission, False)
        
        return Response({
            'success': True,
            'user_id': user_id,
            'context_id': context.id,
            'service_name': service_name,
            'permission': permission,
            'has_access': has_permission,
            'permissions': permissions
        })
        
    except User.DoesNotExist:
        return Response({
            'error': 'User not found'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'error': f'Failed to validate user access: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# =============================================================================
# HELPER FUNCTION
# =============================================================================

def get_user_permissions_for_context(user, context):
    """
    Get user's permissions for a specific context
    """
    permissions = {}
    
    try:
        # Get user's role in this context
        user_context_role = UserContextRole.objects.get(
            user=user,
            context=context,
            status='active'
        )
        
        # Get module subscriptions for this context
        module_subscriptions = ModuleSubscription.objects.filter(
            context=context,
            status='active'
        )
        
        # Build permissions based on modules and features
        for subscription in module_subscriptions:
            module = subscription.plan.module
            
            # Add module-level permissions
            module_name = module.name.lower().replace(' ', '_')
            permissions[f'{module_name}.view'] = True
            permissions[f'{module_name}.access'] = True
            
            # Add feature-level permissions
            for feature in module.features.all():
                feature_code = f'{module_name}.{feature.feature_code}'
                permissions[feature_code] = True
        
        # Add role-based permissions
        role = user_context_role.role
        if role.role_type == 'owner':
            permissions['admin.all'] = True
            permissions['admin.manage_users'] = True
        elif role.role_type == 'admin':
            permissions['admin.manage_content'] = True
        elif role.role_type == 'user':
            permissions['user.basic'] = True
            
    except UserContextRole.DoesNotExist:
        # Default permissions for users without context role
        permissions = {
            'user.basic': True,
            'user.view_profile': True
        }
    
    return permissions
