"""
JWT UTILITIES FOR MICROSERVICE ARCHITECTURE
==========================================

Custom JWT token generation with organization_id, context_id, permissions, etc.
"""

import jwt
from datetime import datetime, timedelta
from django.conf import settings
from .models import Users, Context, UserContextRole, ModuleSubscription


def create_jwt_tokens(user, context=None, service_name=None):
    """
    Create JWT access token and refresh token (like real companies)
    Permissions and detailed data fetched via API calls when needed
    
    Args:
        user: User object
        context: Active context (business/personal)
        service_name: Service being accessed (payroll, accounting, etc.)
    
    Returns:
        dict: Access token, refresh token, and payload data
    """
    
    # Get user's active context if not provided
    if not context:
        try:
            user_session = user.get_active_session()
            context = user_session.active_context
        except:
            context = None
    
    # Basic organization and context info
    organization_id = None
    context_id = None
    business_name = None
    
    if context:
        context_id = context.id
        if context.business:
            organization_id = context.business.id
            business_name = context.business.name
    
    # Create access token payload (short-lived)
    access_payload = {
        # Basic user information
        'user_id': user.id,
        'email': user.email,
        'is_active': user.is_active,
        
        # Basic organization info
        'organization_id': organization_id,
        'context_id': context_id,
        'business_name': business_name,
        
        # Service info
        'service_name': service_name,
        
        # JWT standard fields
        'exp': datetime.utcnow() + timedelta(hours=1),  # Expires in 1 hour
        'iat': datetime.utcnow(),  # Issued at
        'iss': 'usermanagement',  # Issuer
        'aud': 'microservices',  # Audience
        'token_type': 'access'
    }
    
    # Create refresh token payload (long-lived)
    refresh_payload = {
        'user_id': user.id,
        'email': user.email,
        'exp': datetime.utcnow() + timedelta(days=30),  # Expires in 30 days
        'iat': datetime.utcnow(),
        'iss': 'usermanagement',
        'aud': 'microservices',
        'token_type': 'refresh'
    }
    
    # Generate tokens
    access_token = jwt.encode(access_payload, settings.SECRET_KEY, algorithm='HS256')
    refresh_token = jwt.encode(refresh_payload, settings.SECRET_KEY, algorithm='HS256')
    
    return {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'access_payload': access_payload,
        'refresh_payload': refresh_payload,
        'expires_in': 3600,  # 1 hour in seconds
        'refresh_expires_in': 30 * 24 * 60 * 60  # 30 days in seconds
    }


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


def validate_jwt_token(token):
    """
    Validate JWT token and return payload
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
        return {
            'valid': True,
            'payload': payload
        }
    except jwt.ExpiredSignatureError:
        return {'valid': False, 'error': 'Token expired'}
    except jwt.InvalidTokenError:
        return {'valid': False, 'error': 'Invalid token'}


def refresh_access_token(refresh_token):
    """
    Refresh access token using refresh token
    """
    try:
        # Validate refresh token
        token_data = validate_jwt_token(refresh_token)
        
        if not token_data['valid']:
            return {'success': False, 'error': token_data['error']}
        
        payload = token_data['payload']
        
        # Check if it's a refresh token
        if payload.get('token_type') != 'refresh':
            return {'success': False, 'error': 'Invalid token type'}
        
        # Get user
        user = User.objects.get(id=payload['user_id'])
        
        if not user.is_active:
            return {'success': False, 'error': 'User account is deactivated'}
        
        # Create new access token
        new_access_payload = {
            'user_id': user.id,
            'email': user.email,
            'is_active': user.is_active,
            'organization_id': payload.get('organization_id'),
            'context_id': payload.get('context_id'),
            'business_name': payload.get('business_name'),
            'service_name': payload.get('service_name'),
            'exp': datetime.utcnow() + timedelta(hours=1),
            'iat': datetime.utcnow(),
            'iss': 'usermanagement',
            'aud': 'microservices',
            'token_type': 'access'
        }
        
        new_access_token = jwt.encode(new_access_payload, settings.SECRET_KEY, algorithm='HS256')
        
        return {
            'success': True,
            'access_token': new_access_token,
            'expires_in': 3600
        }
        
    except User.DoesNotExist:
        return {'success': False, 'error': 'User not found'}
    except Exception as e:
        return {'success': False, 'error': f'Token refresh failed: {str(e)}'}
