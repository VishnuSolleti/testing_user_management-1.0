"""
PAYROLL MICROSERVICE JWT VALIDATION EXAMPLE
==========================================

This shows how the payroll microservice would validate JWT tokens
from the usermanagement microservice.
"""

import jwt
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from functools import wraps


# =============================================================================
# JWT VALIDATION FOR PAYROLL MICROSERVICE
# =============================================================================

def validate_jwt_token(token):
    """
    Validate JWT token from usermanagement microservice
    """
    try:
        # Decode JWT using shared secret key
        payload = jwt.decode(
            token, 
            settings.SECRET_KEY,  # SAME SECRET KEY as usermanagement
            algorithms=['HS256']
        )
        
        return {
            'valid': True,
            'user_id': payload['user_id'],
            'email': payload['email'],
            'organization_id': payload['organization_id'],
            'context_id': payload['context_id'],
            'service_name': payload['service_name'],
            'permissions': payload['permissions'],
            'role': payload['role']
        }
        
    except jwt.ExpiredSignatureError:
        return {'valid': False, 'error': 'Token expired'}
    except jwt.InvalidTokenError:
        return {'valid': False, 'error': 'Invalid token'}


def jwt_required(view_func):
    """
    Decorator to require valid JWT token
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Get token from Authorization header
        auth_header = request.META.get('HTTP_AUTHORIZATION')
        
        if not auth_header or not auth_header.startswith('Bearer '):
            return Response({
                'error': 'Authentication required'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        # Extract token
        token = auth_header.split(' ')[1]
        
        # Validate token
        token_data = validate_jwt_token(token)
        
        if not token_data['valid']:
            return Response({
                'error': f'Authentication failed: {token_data["error"]}'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        # Add user info to request
        request.jwt_user = token_data
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


def require_permission(permission):
    """
    Decorator to require specific permission
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Check if user has permission
            if not request.jwt_user['permissions'].get(permission, False):
                return Response({
                    'error': f'Permission required: {permission}'
                }, status=status.HTTP_403_FORBIDDEN)
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


# =============================================================================
# PAYROLL MICROSERVICE ENDPOINTS
# =============================================================================

@api_view(['GET'])
@jwt_required
@require_permission('payroll.view_employees')
def get_employees(request):
    """
    Get employees - requires payroll.view_employees permission
    """
    user_id = request.jwt_user['user_id']
    organization_id = request.jwt_user['organization_id']
    context_id = request.jwt_user['context_id']
    
    # Use user info from JWT to fetch employees
    employees = [
        {
            'id': 1,
            'name': 'John Doe',
            'email': 'john@company.com',
            'department': 'Engineering',
            'user_id': user_id,
            'organization_id': organization_id
        }
    ]
    
    return Response({
        'employees': employees,
        'user_info': {
            'user_id': user_id,
            'organization_id': organization_id,
            'context_id': context_id
        }
    })


@api_view(['POST'])
@jwt_required
@require_permission('payroll.add_employee')
def add_employee(request):
    """
    Add employee - requires payroll.add_employee permission
    """
    user_id = request.jwt_user['user_id']
    organization_id = request.jwt_user['organization_id']
    
    # Extract employee data from request
    employee_data = request.data
    
    # Add employee with user context
    new_employee = {
        'id': 2,
        'name': employee_data.get('name'),
        'email': employee_data.get('email'),
        'department': employee_data.get('department'),
        'created_by': user_id,
        'organization_id': organization_id
    }
    
    return Response({
        'message': 'Employee added successfully',
        'employee': new_employee
    })


@api_view(['GET'])
@jwt_required
def get_user_info(request):
    """
    Get user info from JWT token
    """
    return Response({
        'user_info': request.jwt_user
    })


# =============================================================================
# FRONTEND INTEGRATION EXAMPLE
# =============================================================================

def frontend_integration_example():
    """
    How frontend would use JWT with payroll microservice
    """
    return {
        'login_flow': {
            'step_1': 'User logs in to usermanagement',
            'step_2': 'Frontend receives JWT token',
            'step_3': 'Frontend stores JWT in localStorage',
            'step_4': 'Frontend makes API calls to payroll with JWT',
            'step_5': 'Payroll validates JWT and processes request'
        },
        'api_calls': {
            'get_employees': {
                'url': 'http://payroll.taarfirst.com/api/employees/',
                'headers': {
                    'Authorization': 'Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...',
                    'Content-Type': 'application/json'
                }
            },
            'add_employee': {
                'url': 'http://payroll.taarfirst.com/api/employees/',
                'method': 'POST',
                'headers': {
                    'Authorization': 'Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...',
                    'Content-Type': 'application/json'
                },
                'body': {
                    'name': 'Jane Doe',
                    'email': 'jane@company.com',
                    'department': 'Marketing'
                }
            }
        }
    }


# =============================================================================
# SHARED SECRET KEY CONFIGURATION
# =============================================================================

def shared_secret_setup():
    """
    How to set up shared secret key across microservices
    """
    return {
        'usermanagement_settings': {
            'SECRET_KEY': 'your-shared-secret-key-here',
            'JWT_ALGORITHM': 'HS256'
        },
        'payroll_settings': {
            'SECRET_KEY': 'your-shared-secret-key-here',  # SAME KEY
            'JWT_ALGORITHM': 'HS256'
        },
        'environment_variables': {
            'SHARED_JWT_SECRET': 'your-shared-secret-key-here'
        }
    }
