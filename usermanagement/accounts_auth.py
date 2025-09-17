"""
ACCOUNTS AUTHENTICATION SYSTEM
==============================

This implements a unified authentication system like Zoho:
1. Single login endpoint for all services
2. URL-based service detection
3. Smart routing after login
4. Service selection page for users

Usage:
- User goes to /payroll/login → Redirects to central login
- User logs in → Redirects back to /payroll/dashboard
- User goes to /login → Shows service selection page
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from django.shortcuts import redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
import re
from urllib.parse import urlparse, parse_qs
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes
from .models import Users, Context, ModuleSubscription
from .rate_limit_decorator import rate_limit
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
import requests
import logging

User = get_user_model()
logger = logging.getLogger(__name__)


# =============================================================================
# ACCOUNTS SERVICE DETECTION
# =============================================================================

def detect_service_from_url(request):
    """
    Detect which service the user wants to access (Accounts-style)
    Returns the service key and redirect URL
    """
    url_path = request.path.lower().strip()
    referer = request.META.get('HTTP_REFERER', '')
    
    # Accounts-style service mappings
    service_mappings = {
        'payroll': {
            'patterns': [r'^/payroll', r'^/payroll/'],
            'redirect_url': '/payroll/dashboard',
            'service_name': 'Payroll Management'
        },
        'invoicing': {
            'patterns': [r'^/invoicing', r'^/invoice', r'^/billing'],
            'redirect_url': '/invoicing/dashboard', 
            'service_name': 'Invoice Management'
        },
        'accounting': {
            'patterns': [r'^/accounting', r'^/books', r'^/finance'],
            'redirect_url': '/accounting/dashboard',
            'service_name': 'Accounting & Books'
        },
        'gst': {
            'patterns': [r'^/gst', r'^/tax', r'^/compliance'],
            'redirect_url': '/gst/dashboard',
            'service_name': 'GST Management'
        },
        'hr': {
            'patterns': [r'^/hr', r'^/human', r'^/employee'],
            'redirect_url': '/hr/dashboard',
            'service_name': 'Human Resources'
        },
        'inventory': {
            'patterns': [r'^/inventory', r'^/stock', r'^/warehouse'],
            'redirect_url': '/inventory/dashboard',
            'service_name': 'Inventory Management'
        }
    }
    
    # Check URL path first
    for service_key, config in service_mappings.items():
        for pattern in config['patterns']:
            if re.search(pattern, url_path):
                return {
                    'service_key': service_key,
                    'redirect_url': config['redirect_url'],
                    'service_name': config['service_name'],
                    'detected_from': 'url_path'
                }
    
    # Check referer if no URL match
    if referer:
        parsed_referer = urlparse(referer)
        referer_path = parsed_referer.path.lower()
        
        for service_key, config in service_mappings.items():
            for pattern in config['patterns']:
                if re.search(pattern, referer_path):
                    return {
                        'service_key': service_key,
                        'redirect_url': config['redirect_url'],
                        'service_name': config['service_name'],
                        'detected_from': 'referer'
                    }
    
    # Check request parameters
    service_param = request.data.get('service') or request.data.get('module')
    if service_param:
        service_param = service_param.lower()
        for service_key, config in service_mappings.items():
            if service_key in service_param or service_param in service_key:
                return {
                    'service_key': service_key,
                    'redirect_url': config['redirect_url'],
                    'service_name': config['service_name'],
                    'detected_from': 'request_param'
                }
    
    # Default to dashboard
    return {
        'service_key': 'dashboard',
        'redirect_url': '/dashboard',
        'service_name': 'Main Dashboard',
        'detected_from': 'default'
    }


def get_user_available_services(user):
    """
    Get list of services available to the user (Zoho-style)
    """
    available_services = []
    
    # Get user's active contexts
    user_contexts = Context.objects.filter(
        user_roles__user=user,
        user_roles__status='active'
    ).distinct()
    
    # Service mapping
    service_mapping = {
        'payroll': {
            'name': 'Payroll Management',
            'url': '/payroll/dashboard',
            'icon': 'payroll-icon',
            'keywords': ['payroll', 'salary', 'attendance', 'employee']
        },
        'invoicing': {
            'name': 'Invoice Management',
            'url': '/invoicing/dashboard',
            'icon': 'invoice-icon',
            'keywords': ['invoice', 'billing', 'payment', 'client']
        },
        'accounting': {
            'name': 'Accounting & Books',
            'url': '/accounting/dashboard',
            'icon': 'accounting-icon',
            'keywords': ['accounting', 'bookkeeping', 'financial', 'ledger']
        },
        'gst': {
            'name': 'GST Management',
            'url': '/gst/dashboard',
            'icon': 'gst-icon',
            'keywords': ['gst', 'tax', 'compliance', 'filing']
        },
        'hr': {
            'name': 'Human Resources',
            'url': '/hr/dashboard',
            'icon': 'hr-icon',
            'keywords': ['hr', 'human', 'resources', 'employee']
        },
        'inventory': {
            'name': 'Inventory Management',
            'url': '/inventory/dashboard',
            'icon': 'inventory-icon',
            'keywords': ['inventory', 'stock', 'warehouse', 'product']
        }
    }
    
    # Check user's module subscriptions
    for context in user_contexts:
        subscriptions = ModuleSubscription.objects.filter(
            context=context,
            status__in=['active', 'trial']
        ).select_related('module')
        
        for subscription in subscriptions:
            module = subscription.module
            module_name_lower = module.name.lower()
            
            # Match module to service
            for service_key, service_info in service_mapping.items():
                # Check if module matches service
                if (service_key in module_name_lower or 
                    any(keyword in module_name_lower for keyword in service_info['keywords'])):
                    
                    available_services.append({
                        'service_key': service_key,
                        'service_name': service_info['name'],
                        'redirect_url': service_info['url'],
                        'icon': service_info['icon'],
                        'context_id': context.id,
                        'context_name': context.name,
                        'subscription_status': subscription.status
                    })
                    break
    
    # Always add dashboard
    available_services.append({
        'service_key': 'dashboard',
        'service_name': 'Main Dashboard',
        'redirect_url': '/dashboard',
        'icon': 'dashboard-icon',
        'context_id': None,
        'context_name': 'All Contexts',
        'subscription_status': 'active'
    })
    
    # Remove duplicates based on service_key + context_id combination
    seen_services = set()
    unique_services = []
    for service in available_services:
        # Create unique key combining service_key and context_id
        unique_key = f"{service['service_key']}_{service.get('context_id', 'none')}"
        if unique_key not in seen_services:
            seen_services.add(unique_key)
            unique_services.append(service)
    
    return unique_services


# =============================================================================
# ACCOUNTS LOGIN ENDPOINTS
# =============================================================================

@extend_schema(
    operation_id='accounts_login',
    summary='Unified Accounts Login',
    description='''
    Enhanced central login endpoint that handles multiple authentication methods:
    
    **Authentication Methods:**
    1. **Email/Password Login** - Traditional login with email and password
    2. **Google OAuth Login** - Social login using Google OAuth token
    
    **Features:**
    - Service detection from URL/Referer header
    - Automatic context switching
    - Available services detection
    - Smart routing after login
    - Cross-subdomain cookie support
    
    **Response includes:**
    - JWT access and refresh tokens
    - User profile information
    - Active context details
    - Available services list
    - Module subscriptions
    - Service requests
    ''',
    tags=['Authentication'],
    request={
        'application/json': {
            'type': 'object',
            'properties': {
                'email': {
                    'type': 'string', 
                    'format': 'email', 
                    'description': 'User email address',
                    'example': 'user@example.com'
                },
                'password': {
                    'type': 'string', 
                    'description': 'User password',
                    'example': 'SecurePassword123!'
                },
                'google_token': {
                    'type': 'string', 
                    'description': 'Google OAuth access token (for Google OAuth login)',
                    'example': 'ya29.a0AfH6SMC...'
                }
            },
            'oneOf': [
                {
                    'required': ['email', 'password'],
                    'title': 'Email/Password Login'
                },
                {
                    'required': ['google_token'],
                    'title': 'Google OAuth Login'
                }
            ]
        }
    },
    responses={
        200: {
            'description': 'Login successful',
            'content': {
                'application/json': {
                    'type': 'object',
                    'properties': {
                        'message': {'type': 'string', 'example': 'Login successful'},
                        'access_token': {'type': 'string', 'example': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...'},
                        'refresh_token': {'type': 'string', 'example': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...'},
                        'user': {
                            'type': 'object',
                            'properties': {
                                'id': {'type': 'integer', 'example': 123},
                                'email': {'type': 'string', 'example': 'user@example.com'},
                                'mobile_number': {'type': 'string', 'example': '+1234567890'},
                                'status': {'type': 'string', 'example': 'active'},
                                'registration_completed': {'type': 'boolean', 'example': True},
                                'is_super_admin': {'type': 'boolean', 'example': False}
                            }
                        },
                        'active_context': {
                            'type': 'object',
                            'properties': {
                                'id': {'type': 'integer', 'example': 456},
                                'name': {'type': 'string', 'example': 'My Business'},
                                'context_type': {'type': 'string', 'enum': ['personal', 'business'], 'example': 'business'},
                                'status': {'type': 'string', 'example': 'active'},
                                'profile_status': {'type': 'string', 'example': 'complete'},
                                'business_id': {'type': 'integer', 'example': 789}
                            }
                        },
                        'all_contexts': {
                            'type': 'array',
                            'items': {
                                'type': 'object',
                                'properties': {
                                    'id': {'type': 'integer'},
                                    'name': {'type': 'string'},
                                    'context_type': {'type': 'string'},
                                    'is_active': {'type': 'boolean'}
                                }
                            }
                        },
                        'user_role': {
                            'type': 'object',
                            'properties': {
                                'id': {'type': 'integer', 'example': 1},
                                'name': {'type': 'string', 'example': 'Owner'},
                                'role_type': {'type': 'string', 'example': 'owner'},
                                'description': {'type': 'string', 'example': 'Business owner with full access'}
                            }
                        },
                        'available_services': {
                            'type': 'array',
                            'items': {'type': 'string'},
                            'example': ['payroll', 'accounting', 'gst']
                        },
                        'detected_service': {
                            'type': 'string',
                            'example': 'payroll',
                            'description': 'Service detected from URL/Referer'
                        },
                        'redirect_url': {
                            'type': 'string',
                            'example': 'https://payroll.tarafirst.com/dashboard',
                            'description': 'URL to redirect after login'
                        },
                        'module_subscriptions': {
                            'type': 'array',
                            'items': {
                                'type': 'object',
                                'properties': {
                                    'module_name': {'type': 'string'},
                                    'plan_name': {'type': 'string'},
                                    'status': {'type': 'string'}
                                }
                            }
                        },
                        'service_requests': {
                            'type': 'array',
                            'items': {
                                'type': 'object',
                                'properties': {
                                    'id': {'type': 'integer'},
                                    'service_name': {'type': 'string'},
                                    'status': {'type': 'string'}
                                }
                            }
                        }
                    }
                }
            }
        },
        400: {
            'description': 'Bad Request - Missing or invalid parameters',
            'content': {
                'application/json': {
                    'type': 'object',
                    'properties': {
                        'error': {'type': 'string', 'example': 'Email and password are required'}
                    }
                }
            }
        },
        401: {
            'description': 'Unauthorized - Invalid credentials or inactive account',
            'content': {
                'application/json': {
                    'type': 'object',
                    'properties': {
                        'error': {'type': 'string', 'example': 'Invalid credentials'}
                    }
                }
            }
        },
        500: {
            'description': 'Internal Server Error',
            'content': {
                'application/json': {
                    'type': 'object',
                    'properties': {
                        'error': {'type': 'string', 'example': 'Login failed: Internal server error'}
                    }
                }
            }
        }
    },
    examples=[
        OpenApiExample(
            'Email/Password Login',
            summary='Traditional login with email and password',
            description='Login using email and password credentials',
            value={
                'email': 'user@example.com',
                'password': 'SecurePassword123!'
            }
        ),
        OpenApiExample(
            'Google OAuth Login',
            summary='Social login with Google OAuth',
            description='Login using Google OAuth access token',
            value={
                'google_token': 'ya29.a0AfH6SMC_example_google_access_token_here'
            }
        )
    ]
)
@api_view(['POST'])
@permission_classes([AllowAny])
def accounts_login(request):
    """
    Enhanced accounts central login endpoint
    Handles both email/password AND Google OAuth login
    """
    try:
        # Check if this is Google OAuth login
        google_token = request.data.get('google_token')
        if google_token:
            return handle_google_oauth_login(request)
        
        # Regular email/password login (existing logic)
        email = request.data.get('email')
        password = request.data.get('password')
        
        if not email or not password:
            return Response({
                'error': 'Email and password are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Authenticate user
        user = authenticate(request, email=email, password=password)
        
        if not user:
            return Response({
                'error': 'Invalid credentials'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        if not user.is_active:
            return Response({
                'error': 'Account is deactivated'
            }, status=status.HTTP_401_UNAUTHORIZED)

        # Generate Django built-in JWT tokens
        refresh = RefreshToken.for_user(user)
        access_token = refresh.access_token
        refresh_token = str(refresh)
        
        # Detect requested service from URL/Referer
        detected_service = detect_service_from_url(request)
        
        # Get user's available services
        available_services = get_user_available_services(user)
        
        # Check if user has access to the SPECIFIC detected service in CURRENT ACTIVE CONTEXT
        # Get user's current active context
        try:
            user_session = user.get_active_session()
            active_context_id = user_session.active_context.id if user_session and user_session.active_context else None
        except:
            active_context_id = None
        
        # Filter available services to only those in the current active context
        active_context_services = [
            service for service in available_services 
            if service.get('context_id') == active_context_id
        ]
        
        # Check access based on current active context only
        user_has_access = any(
            service['service_key'] == detected_service['service_key'] 
            for service in active_context_services
        )

        
        if user_has_access:
            final_redirect_url = detected_service['redirect_url']
        else:
            # Redirect to first available service or dashboard
            if available_services:
                final_redirect_url = available_services[0]['redirect_url']
            else:
                final_redirect_url = '/dashboard'
        
        # Get user's organization data for response
        try:
            user_session = user.get_active_session()
            context = user_session.active_context
            organization_id = context.business.id if context and context.business else None
            context_id = context.id if context else None
            business_name = context.business.nameOfBusiness if context and context.business else None
            business_id = context.business.id if context and context.business else None
        except:
            organization_id = None
            context_id = None
            business_name = None
            business_id = None
        # Add org_id to refresh token for multi-tenant support
        print(business_id)
        refresh['org_id'] = business_id
        access_token = refresh.access_token
        refresh_token = str(refresh)


        
        # Accounts response with organization data
        response_data = {
            'success': True,
            'message': 'Login successful',
            'access_token': str(access_token),
            'refresh_token': refresh_token,
            'expires_in': 3600,  # 1 hour
            'token_type': 'Bearer',
            'user': {
                'id': user.id,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'is_active': user.is_active,
                'organization_id': organization_id,
                'context_id': context_id,
                'business_name': business_name
            },
            'service_routing': {
                'detected_service': detected_service,
                'available_services': available_services,
                'active_context_services': active_context_services,
                'active_context_id': active_context_id,
                'final_redirect_url': final_redirect_url,
                'has_access_to_requested': user_has_access
            }
        }
        
        # Create response with cookie support
        response = Response(response_data, status=status.HTTP_200_OK)
        
        # Simple cookie settings for local testing
        cookie_domain = None    # No domain restriction - works everywhere
        cookie_secure = False   # Allow HTTP for local testing
        
        # Set environment-aware cookies
        response.set_cookie(
            'access_token',
            str(access_token),
            domain=cookie_domain,                # None for local, .tarafirst.com for production
            secure=cookie_secure,                # False for local, True for production
            httponly=True,                       # No JS access (XSS protection)
            samesite='Lax',                     # CSRF protection
            max_age=43200                       # 12 hours
        )

        response.set_cookie(
            'refresh_token',
            refresh_token,
            domain=cookie_domain,                # None for local, .tarafirst.com for production
            secure=cookie_secure,                # False for local, True for production
            httponly=True,                       # No JS access (XSS protection)
            samesite='Lax',                     # CSRF protection
            max_age=86400                       # 24 hours
        )

        # Set user context cookie for frontend state management
        response.set_cookie(
            'user_context',
            str(context_id) if context_id else '',
            domain=cookie_domain,
            secure=cookie_secure,
            httponly=False,                      # Allow JS access for context switching
            samesite='Lax',
            max_age=86400
        )

        # Set active service cookie for service detection
        response.set_cookie(
            'active_service',
            detected_service.get('service_key', ''),
            domain=cookie_domain,
            secure=cookie_secure,
            httponly=False,                      # Allow JS access for service routing
            samesite='Lax',
            max_age=86400
        )

        # Set organization cookie for multi-tenant support
        response.set_cookie(
            'organization_id',
            str(organization_id) if organization_id else '',
            domain=cookie_domain,
            secure=cookie_secure,
            httponly=False,                      # Allow JS access for organization context
            samesite='Lax',
            max_age=86400
        )
        
        return response
        
    except Exception as e:
        return Response({
            'error': f'Login failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def accounts_service_selection(request):
    """
    Accounts service selection page
    Shows available services to the user
    """
    try:
        # Get all available services (for unauthenticated users)
        all_services = [
            {
                'service_key': 'payroll',
                'service_name': 'Payroll Management',
                'description': 'Employee payroll and attendance management',
                'icon': 'payroll-icon',
                'url': '/payroll/login'
            },
            {
                'service_key': 'invoicing',
                'service_name': 'Invoice Management', 
                'description': 'Invoice creation and payment tracking',
                'icon': 'invoice-icon',
                'url': '/invoicing/login'
            },
            {
                'service_key': 'accounting',
                'service_name': 'Accounting & Books',
                'description': 'Financial accounting and bookkeeping',
                'icon': 'accounting-icon',
                'url': '/accounting/login'
            },
            {
                'service_key': 'gst',
                'service_name': 'GST Management',
                'description': 'GST filing and tax compliance',
                'icon': 'gst-icon',
                'url': '/gst/login'
            },
            {
                'service_key': 'hr',
                'service_name': 'Human Resources',
                'description': 'Employee management and HR processes',
                'icon': 'hr-icon',
                'url': '/hr/login'
            },
            {
                'service_key': 'inventory',
                'service_name': 'Inventory Management',
                'description': 'Stock and warehouse management',
                'icon': 'inventory-icon',
                'url': '/inventory/login'
            }
        ]
        
        return Response({
            'success': True,
            'services': all_services,
            'login_url': '/user_management/auth/zoho-login/'
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({
            'error': f'Failed to load services: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([AllowAny])
def accounts_detect_service(request):
    """
    Detect service from request (for frontend pre-login routing)
    """
    try:
        detected_service = detect_service_from_url(request)
        
        return Response({
            'success': True,
            'detected_service': detected_service
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({
            'error': f'Service detection failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def zoho_style_available_services(request):
    """
    Get available services for authenticated user
    """
    try:
        # Check if user is authenticated
        auth_header = request.META.get('HTTP_AUTHORIZATION')
        if not auth_header or not auth_header.startswith('Bearer '):
            return Response({
                'error': 'Authentication required'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        # Get user from token (simplified - you might want to add proper token validation)
        # This is a placeholder - implement proper JWT token validation
        user = request.user if hasattr(request, 'user') and request.user.is_authenticated else None
        
        if not user:
            return Response({
                'error': 'Invalid or expired token'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        # Get user's available services
        available_services = get_user_available_services(user)
        
        return Response({
            'success': True,
            'available_services': available_services
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({
            'error': f'Failed to get services: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# =============================================================================
# ZOHO-STYLE REDIRECT HANDLERS
# =============================================================================

@api_view(['GET'])
@permission_classes([AllowAny])
def zoho_style_service_redirect(request, service_name):
    """
    Handle service-specific login redirects (like /payroll/login)
    """
    try:
        # Detect the service
        detected_service = detect_service_from_url(request)
        
        # Return redirect information
        return Response({
            'success': True,
            'service': detected_service,
            'login_url': '/user_management/auth/accounts-login/',
            'message': f'Redirecting to {detected_service["service_name"]} login'
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({
            'error': f'Redirect failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# =============================================================================
# ACCOUNTS FRONTEND INTEGRATION
# =============================================================================

def accounts_frontend_integration():
    """
    Frontend integration examples for Accounts system
    """
    return {
        'login_flow': {
            'step_1': 'User goes to /payroll/login',
            'step_2': 'Frontend detects service and shows "Login to Payroll"',
            'step_3': 'User enters credentials',
            'step_4': 'POST to /user_management/auth/accounts-login/',
            'step_5': 'Backend returns tokens + redirect URL',
            'step_6': 'Frontend redirects to /payroll/dashboard'
        },
        'service_selection': {
            'step_1': 'User goes to /login',
            'step_2': 'Frontend shows service selection page',
            'step_3': 'User clicks on desired service',
            'step_4': 'Frontend redirects to /service/login',
            'step_5': 'Continue with login flow'
        },
        'api_endpoints': {
            'login': '/user_management/auth/accounts-login/',
            'service_selection': '/user_management/auth/services/',
            'detect_service': '/user_management/auth/detect-service/',
            'available_services': '/user_management/auth/user-services/'
        }
    }


# =============================================================================
# GOOGLE OAUTH INTEGRATION
# =============================================================================

def handle_google_oauth_login(request):
    """
    Handle Google OAuth login within the accounts system
    """
    try:
        google_token = request.data.get('google_token')
        
        if not google_token:
            return Response({
                'error': 'Google token is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Verify Google token and get user info
        google_user_info = verify_google_token(google_token)
        
        if not google_user_info:
            return Response({
                'error': 'Invalid Google token'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        # Extract user data from Google
        email = google_user_info.get('email')
        google_id = google_user_info.get('id')
        name = google_user_info.get('name')
        
        if not email or not google_id:
            return Response({
                'error': 'Invalid user data from Google'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Handle user creation/linking (using existing logic)
        user = handle_google_user_in_accounts(email, google_id, name)
        
        if not user:
            return Response({
                'error': 'Failed to create or link user account'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Continue with your existing login flow (same as regular login)
        return generate_accounts_login_response(request, user)
        
    except Exception as e:
        logger.exception("Google OAuth login failed in accounts system")
        return Response({
            'error': f'Google OAuth login failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def verify_google_token(google_token):
    """
    Verify Google token and return user info
    """
    try:
        response = requests.get(
            f'https://www.googleapis.com/oauth2/v2/userinfo?access_token={google_token}'
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Google API error: {response.status_code}")
            return None
            
    except Exception as e:
        logger.exception("Error verifying Google token")
        return None


def handle_google_user_in_accounts(email, google_id, name):
    """
    Handle Google user creation or linking within accounts system
    """
    try:
        # Check if user already exists by email
        try:
            existing_user = User.objects.get(email=email)
            
            # User exists - link Google account
            if existing_user.google_user_id:
                # User already has Google linked
                if existing_user.google_user_id != google_id:
                    logger.error(f"User {email} already has different Google account linked")
                    return None
                # Same Google account, update name if needed
                existing_user.google_name = name
                existing_user.auth_provider = 'both' if existing_user.has_usable_password() else 'google'
                existing_user.save()
                return existing_user
            else:
                # Link Google to existing user
                existing_user.google_user_id = google_id
                existing_user.google_name = name
                existing_user.auth_provider = 'both' if existing_user.has_usable_password() else 'google'
                existing_user.save()
                logger.info(f"Linked Google account to existing user: {email}")
                return existing_user
                
        except User.DoesNotExist:
            # User doesn't exist - create new user (like standard registration)
            new_user = User.objects.create(
                email=email,
                google_user_id=google_id,
                google_name=name,
                auth_provider='google',
                status='active',
                is_active=True
            )
            logger.info(f"Created new Google OAuth user: {email}")
            return new_user
            
    except Exception as e:
        logger.exception(f"Error handling Google user: {email}")
        return None


def generate_accounts_login_response(request, user):
    """
    Generate the same login response as your existing accounts_login function
    """
    try:
        # Generate Django built-in JWT tokens (same as your existing code)
        refresh = RefreshToken.for_user(user)
        access_token = refresh.access_token
        refresh_token = str(refresh)
        
        # Detect requested service from URL/Referer (same as your existing code)
        detected_service = detect_service_from_url(request)
        
        # Get user's available services (same as your existing code)
        available_services = get_user_available_services(user)
        
        # Get user's current active context (same as your existing code)
        try:
            user_session = user.get_active_session()
            active_context_id = user_session.active_context.id if user_session and user_session.active_context else None
        except:
            active_context_id = None
        
        # Return the same response format as your existing login
        return Response({
            'message': 'Login successful',
            'access_token': str(access_token),
            'refresh_token': refresh_token,
            'user': {
                'id': user.id,
                'email': user.email,
                'name': user.google_name or user.first_name,
                'auth_provider': user.auth_provider
            },
            'detected_service': detected_service,
            'available_services': available_services,
            'active_context_id': active_context_id
        })
        
    except Exception as e:
        logger.exception("Error generating accounts login response")
        return Response({
            'error': 'Failed to generate login response'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

