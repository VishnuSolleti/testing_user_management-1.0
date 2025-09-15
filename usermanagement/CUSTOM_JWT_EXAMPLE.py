"""
CUSTOM JWT PAYLOAD IMPLEMENTATION
=================================

This shows how to create custom JWT tokens with organization_id,
context_id, permissions, and other data for microservice architecture.
"""

import jwt
from datetime import datetime, timedelta
from django.conf import settings
from rest_framework_simplejwt.tokens import RefreshToken
from .models import Users, Context, UserContextRole, ModuleSubscription


# =============================================================================
# CUSTOM JWT TOKEN GENERATION
# =============================================================================

def create_custom_jwt_token(user, context=None, service_name=None):
    """
    Create custom JWT token with organization_id, context_id, permissions, etc.
    
    Args:
        user: User object
        context: Active context (business/personal)
        service_name: Service being accessed (payroll, accounting, etc.)
    
    Returns:
        dict: JWT token and payload data
    """
    
    # Get user's active context if not provided
    if not context:
        try:
            user_session = user.get_active_session()
            context = user_session.active_context
        except:
            context = None
    
    # Get user's permissions and role for the context
    permissions = {}
    role_data = {}
    organization_id = None
    context_id = None
    
    if context:
        context_id = context.id
        organization_id = context.business.id if context.business else None
        
        # Get user's role in this context
        try:
            user_context_role = UserContextRole.objects.get(
                user=user,
                context=context,
                status='active'
            )
            role_data = {
                'role_type': user_context_role.role.role_type,
                'context': context.context_type,
                'role_id': user_context_role.role.id
            }
            
            # Get user's permissions for this context
            permissions = get_user_permissions_for_context(user, context)
            
        except UserContextRole.DoesNotExist:
            role_data = {'role_type': 'guest', 'context': 'unknown'}
    
    # Create custom JWT payload
    payload = {
        # User information
        'user_id': user.id,
        'email': user.email,
        'is_active': user.is_active,
        
        # Organization and context information
        'organization_id': organization_id,
        'context_id': context_id,
        'context_type': context.context_type if context else None,
        'business_name': context.business.name if context and context.business else None,
        
        # Service information
        'service_name': service_name,
        'requested_service': service_name,
        
        # Permissions and role
        'permissions': permissions,
        'role': role_data,
        
        # JWT standard fields
        'exp': datetime.utcnow() + timedelta(hours=24),  # Expires in 24 hours
        'iat': datetime.utcnow(),  # Issued at
        'iss': 'usermanagement',  # Issuer
        'aud': 'microservices'  # Audience
    }
    
    # Generate JWT token
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')
    
    return {
        'token': token,
        'payload': payload,
        'expires_in': 24 * 60 * 60  # 24 hours in seconds
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
            permissions[f'{module.name.lower()}.view'] = True
            permissions[f'{module.name.lower()}.access'] = True
            
            # Add feature-level permissions
            for feature in module.features.all():
                feature_code = f'{module.name.lower()}.{feature.feature_code}'
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


# =============================================================================
# SIMPLE USE CASE EXAMPLE
# =============================================================================

def simple_use_case_example():
    """
    Simple use case: John from ABC Company accessing payroll
    """
    
    # Simulate user login
    user = Users.objects.get(email='john@abc.com')
    context = Context.objects.get(name='ABC Company Main')
    service_name = 'payroll'
    
    # Create custom JWT token
    jwt_data = create_custom_jwt_token(user, context, service_name)
    
    # JWT Payload will contain:
    payload_example = {
        'user_id': 123,
        'email': 'john@abc.com',
        'is_active': True,
        
        # Organization and context
        'organization_id': 456,  # ABC Company ID
        'context_id': 789,       # ABC Company Main context
        'context_type': 'business',
        'business_name': 'ABC Company',
        
        # Service
        'service_name': 'payroll',
        'requested_service': 'payroll',
        
        # Permissions
        'permissions': {
            'payroll.view': True,
            'payroll.add_employee': True,
            'payroll.edit_employee': True,
            'payroll.view_salary': True,
            'admin.manage_users': True
        },
        
        # Role
        'role': {
            'role_type': 'owner',
            'context': 'business',
            'role_id': 1
        },
        
        # JWT fields
        'exp': 1640995200,
        'iat': 1640908800,
        'iss': 'usermanagement',
        'aud': 'microservices'
    }
    
    return {
        'jwt_token': jwt_data['token'],
        'payload': payload_example,
        'usage': {
            'step_1': 'User logs in to usermanagement',
            'step_2': 'System creates JWT with organization_id, context_id, permissions',
            'step_3': 'Frontend sends JWT to payroll microservice',
            'step_4': 'Payroll extracts organization_id, permissions from JWT',
            'step_5': 'Payroll processes request using JWT data'
        }
    }


# =============================================================================
# PAYROLL MICROSERVICE USAGE
# =============================================================================

def payroll_microservice_usage():
    """
    How payroll microservice would use the JWT data
    """
    
    # Simulate JWT validation in payroll
    def validate_and_extract_jwt_data(token):
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            
            return {
                'user_id': payload['user_id'],
                'email': payload['email'],
                'organization_id': payload['organization_id'],  # ABC Company ID
                'context_id': payload['context_id'],           # ABC Company Main context
                'business_name': payload['business_name'],     # ABC Company
                'permissions': payload['permissions'],         # payroll permissions
                'role': payload['role']                        # owner role
            }
        except jwt.InvalidTokenError:
            return None
    
    # Example usage in payroll endpoints
    def get_employees_for_organization(jwt_data):
        organization_id = jwt_data['organization_id']  # 456
        business_name = jwt_data['business_name']      # ABC Company
        
        # Query employees for this organization
        employees = [
            {
                'id': 1,
                'name': 'John Doe',
                'email': 'john@abc.com',
                'organization_id': organization_id,
                'business_name': business_name
            },
            {
                'id': 2,
                'name': 'Jane Smith',
                'email': 'jane@abc.com',
                'organization_id': organization_id,
                'business_name': business_name
            }
        ]
        
        return employees
    
    return {
        'jwt_validation': validate_and_extract_jwt_data,
        'get_employees': get_employees_for_organization,
        'example_flow': {
            'step_1': 'Payroll receives JWT token',
            'step_2': 'Validates JWT and extracts organization_id=456',
            'step_3': 'Queries employees WHERE organization_id=456',
            'step_4': 'Returns employees for ABC Company only'
        }
    }


# =============================================================================
# INTEGRATION WITH EXISTING ACCOUNTS_AUTH.PY
# =============================================================================

def integrate_with_accounts_auth():
    """
    How to integrate this with existing accounts_auth.py
    """
    
    # In accounts_auth.py, replace the JWT generation:
    def accounts_login_with_custom_jwt(request):
        # ... existing authentication code ...
        
        # Instead of:
        # refresh = RefreshToken.for_user(user)
        # access_token = refresh.access_token
        
        # Use custom JWT:
        detected_service = detect_service_from_url(request)
        service_name = detected_service['service_key']
        
        jwt_data = create_custom_jwt_token(user, service_name=service_name)
        
        return Response({
            'success': True,
            'access_token': jwt_data['token'],
            'user': {
                'id': user.id,
                'email': user.email,
                'organization_id': jwt_data['payload']['organization_id'],
                'context_id': jwt_data['payload']['context_id'],
                'business_name': jwt_data['payload']['business_name']
            },
            'permissions': jwt_data['payload']['permissions'],
            'role': jwt_data['payload']['role'],
            'expires_in': jwt_data['expires_in']
        })
    
    return {
        'integration': 'Replace RefreshToken.for_user() with create_custom_jwt_token()',
        'benefits': [
            'Organization ID included in JWT',
            'Context ID included in JWT',
            'Permissions included in JWT',
            'Role information included in JWT',
            'No additional API calls needed'
        ]
    }
