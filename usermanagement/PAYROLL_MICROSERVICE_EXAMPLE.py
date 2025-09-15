"""
PAYROLL MICROSERVICE EXAMPLE
============================

This shows how the payroll microservice would use JWT tokens
and make API calls to usermanagement for permissions and user data.
"""

import requests
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
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
        return {
            'valid': True,
            'payload': payload
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
        request.jwt_user = token_data['payload']
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


# =============================================================================
# USAGE: JWT + API CALLS APPROACH
# =============================================================================

@api_view(['GET'])
@jwt_required
def get_employees(request):
    """
    Get employees - uses JWT for basic info, API calls for permissions
    """
    try:
        # Extract basic info from JWT
        user_id = request.jwt_user['user_id']
        organization_id = request.jwt_user['organization_id']
        context_id = request.jwt_user['context_id']
        
        # Make API call to usermanagement to get permissions
        usermanagement_url = 'http://usermanagement.taarfirst.com'
        permissions_response = requests.get(
            f'{usermanagement_url}/api/user/{user_id}/permissions/',
            params={'context_id': context_id},
            headers={'Authorization': f'Bearer {request.META.get("HTTP_AUTHORIZATION").split(" ")[1]}'}
        )
        
        if permissions_response.status_code != 200:
            return Response({
                'error': 'Failed to get user permissions'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        permissions_data = permissions_response.json()
        permissions = permissions_data['permissions']
        
        # Check if user has permission to view employees
        if not permissions.get('payroll.view_employees', False):
            return Response({
                'error': 'Permission denied: payroll.view_employees required'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Get employees for this organization
        employees = [
            {
                'id': 1,
                'name': 'John Doe',
                'email': 'john@company.com',
                'department': 'Engineering',
                'organization_id': organization_id,
                'context_id': context_id
            },
            {
                'id': 2,
                'name': 'Jane Smith',
                'email': 'jane@company.com',
                'department': 'Marketing',
                'organization_id': organization_id,
                'context_id': context_id
            }
        ]
        
        return Response({
            'success': True,
            'employees': employees,
            'user_info': {
                'user_id': user_id,
                'organization_id': organization_id,
                'context_id': context_id,
                'permissions': permissions
            }
        })
        
    except Exception as e:
        return Response({
            'error': f'Failed to get employees: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@jwt_required
def add_employee(request):
    """
    Add employee - uses JWT + API calls for validation
    """
    try:
        # Extract basic info from JWT
        user_id = request.jwt_user['user_id']
        organization_id = request.jwt_user['organization_id']
        context_id = request.jwt_user['context_id']
        
        # Make API call to usermanagement to validate access
        usermanagement_url = 'http://usermanagement.taarfirst.com'
        access_response = requests.post(
            f'{usermanagement_url}/api/validate-access/',
            json={
                'service_name': 'payroll',
                'permission': 'payroll.add_employee',
                'context_id': context_id
            },
            headers={'Authorization': f'Bearer {request.META.get("HTTP_AUTHORIZATION").split(" ")[1]}'}
        )
        
        if access_response.status_code != 200:
            return Response({
                'error': 'Failed to validate access'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        access_data = access_response.json()
        
        if not access_data['has_access']:
            return Response({
                'error': 'Permission denied: payroll.add_employee required'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Extract employee data from request
        employee_data = request.data
        
        # Add employee with organization context
        new_employee = {
            'id': 3,
            'name': employee_data.get('name'),
            'email': employee_data.get('email'),
            'department': employee_data.get('department'),
            'created_by': user_id,
            'organization_id': organization_id,
            'context_id': context_id
        }
        
        return Response({
            'success': True,
            'message': 'Employee added successfully',
            'employee': new_employee
        })
        
    except Exception as e:
        return Response({
            'error': f'Failed to add employee: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@jwt_required
def get_user_info(request):
    """
    Get user info - uses JWT + API call for detailed info
    """
    try:
        # Extract basic info from JWT
        user_id = request.jwt_user['user_id']
        
        # Make API call to usermanagement for detailed user info
        usermanagement_url = 'http://usermanagement.taarfirst.com'
        user_response = requests.get(
            f'{usermanagement_url}/api/user/{user_id}/',
            headers={'Authorization': f'Bearer {request.META.get("HTTP_AUTHORIZATION").split(" ")[1]}'}
        )
        
        if user_response.status_code != 200:
            return Response({
                'error': 'Failed to get user info'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        user_data = user_response.json()
        
        return Response({
            'success': True,
            'user_info': user_data['user'],
            'jwt_info': {
                'user_id': request.jwt_user['user_id'],
                'email': request.jwt_user['email'],
                'organization_id': request.jwt_user['organization_id'],
                'context_id': request.jwt_user['context_id']
            }
        })
        
    except Exception as e:
        return Response({
            'error': f'Failed to get user info: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# =============================================================================
# COMPLETE FLOW EXAMPLE
# =============================================================================

def complete_flow_example():
    """
    Complete flow example: JWT + API calls
    """
    return {
        'step_1_login': {
            'description': 'User logs in to usermanagement',
            'endpoint': 'POST /usermanagement/auth/accounts-login/',
            'response': {
                'access_token': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...',
                'user': {
                    'id': 123,
                    'email': 'john@abc.com',
                    'organization_id': 456,
                    'context_id': 789,
                    'business_name': 'ABC Company'
                }
            }
        },
        'step_2_payroll_call': {
            'description': 'Frontend calls payroll with JWT',
            'endpoint': 'GET /payroll/api/employees/',
            'headers': {
                'Authorization': 'Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...'
            }
        },
        'step_3_payroll_validation': {
            'description': 'Payroll validates JWT and extracts basic info',
            'jwt_payload': {
                'user_id': 123,
                'email': 'john@abc.com',
                'organization_id': 456,
                'context_id': 789,
                'business_name': 'ABC Company'
            }
        },
        'step_4_permissions_api_call': {
            'description': 'Payroll calls usermanagement for permissions',
            'endpoint': 'GET /usermanagement/api/user/123/permissions/?context_id=789',
            'headers': {
                'Authorization': 'Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...'
            },
            'response': {
                'permissions': {
                    'payroll.view_employees': True,
                    'payroll.add_employee': True,
                    'payroll.edit_employee': False
                }
            }
        },
        'step_5_process_request': {
            'description': 'Payroll processes request using JWT + API data',
            'result': 'Returns employees for organization_id=456'
        }
    }


# =============================================================================
# BENEFITS OF THIS APPROACH
# =============================================================================

def benefits_explanation():
    """
    Benefits of JWT + API calls approach
    """
    return {
        'security': [
            'JWT tokens are small and contain minimal sensitive data',
            'Permissions can be updated without re-login',
            'Fine-grained access control via API calls'
        ],
        'performance': [
            'JWT validation is fast (no database lookup)',
            'API calls only when permissions needed',
            'Can cache permissions for better performance'
        ],
        'flexibility': [
            'Permissions can change dynamically',
            'Easy to add new permission types',
            'Microservices can have different permission models'
        ],
        'scalability': [
            'Each microservice validates JWT independently',
            'API calls can be cached or optimized',
            'Easy to add new microservices'
        ]
    }
