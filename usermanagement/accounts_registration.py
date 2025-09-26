"""
ACCOUNTS UNIFIED REGISTRATION SYSTEM
====================================

This implements a unified registration system that handles:
1. Standard Registration (personal users)
2. Business Registration (business with modules)
3. Service Registration (service-based registration)

All through a single, intelligent endpoint that detects the registration type
and routes accordingly.

Usage:
- User goes to /register → Shows registration type selection
- User goes to /register/business → Business registration flow
- User goes to /register/service → Service registration flow
- User goes to /register/personal → Personal registration flow
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from botocore.exceptions import ClientError
import boto3
import logging
import re
from urllib.parse import urlparse, parse_qs
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes

from .get_login_data import get_login_response
from .models import (
    Context, Role, UserContextRole, Service, ServiceRequest, 
    PendingUserOTP, Module, SubscriptionPlan, ModuleSubscription, Users
)
from Tara.settings.default import *
from .rate_limit_decorator import rate_limit
import requests

logger = logging.getLogger(__name__)
User = get_user_model()


# =============================================================================
# ACCOUNTS REGISTRATION TYPE DETECTION
# =============================================================================

def detect_registration_type_from_url(request):
    """
    Detect registration type from URL (Accounts-style)
    Returns the registration type and configuration
    """
    url_path = request.path.lower().strip()
    referer = request.META.get('HTTP_REFERER', '')
    
    # Accounts-style registration type mappings
    registration_mappings = {
        'business': {
            'patterns': [r'^/register/business', r'^/business/register', r'^/register/company'],
            'registration_flow': 'module',
            'account_type': 'business',
            'description': 'Business Registration with Module Subscription',
            'required_fields': ['email', 'password', 'business_name', 'module_id', 'otp'],
            'optional_fields': ['phone', 'address', 'gst_number']
        },
        'service': {
            'patterns': [r'^/register/service', r'^/service/register', r'^/register/app'],
            'registration_flow': 'service',
            'account_type': 'business',
            'description': 'Service-based Registration',
            'required_fields': ['email', 'password', 'name', 'service_id', 'otp'],
            'optional_fields': ['phone', 'company_name']
        },
        'personal': {
            'patterns': [r'^/register/personal', r'^/personal/register', r'^/register/individual'],
            'registration_flow': 'standard',
            'account_type': 'personal',
            'description': 'Personal User Registration',
            'required_fields': ['email', 'password', 'otp'],
            'optional_fields': ['first_name', 'last_name', 'phone']
        },
        'standard': {
            'patterns': [r'^/register$', r'^/register/$', r'^/signup', r'^/register/standard'],
            'registration_flow': 'standard',
            'account_type': 'personal',
            'description': 'Standard Registration (Default)',
            'required_fields': ['email', 'password', 'otp'],
            'optional_fields': ['first_name', 'last_name', 'phone']
        }
    }
    
    # Check URL path first
    for reg_type, config in registration_mappings.items():
        for pattern in config['patterns']:
            if re.search(pattern, url_path):
                return {
                    'registration_type': reg_type,
                    'registration_flow': config['registration_flow'],
                    'account_type': config['account_type'],
                    'description': config['description'],
                    'required_fields': config['required_fields'],
                    'optional_fields': config['optional_fields'],
                    'detected_from': 'url_path'
                }
    
    # Check referer if no URL match
    if referer:
        parsed_referer = urlparse(referer)
        referer_path = parsed_referer.path.lower()
        
        for reg_type, config in registration_mappings.items():
            for pattern in config['patterns']:
                if re.search(pattern, referer_path):
                    return {
                        'registration_type': reg_type,
                        'registration_flow': config['registration_flow'],
                        'account_type': config['account_type'],
                        'description': config['description'],
                        'required_fields': config['required_fields'],
                        'optional_fields': config['optional_fields'],
                        'detected_from': 'referer'
                    }
    
    # Check request parameters
    reg_type_param = request.data.get('registration_type') or request.data.get('type')
    if reg_type_param:
        reg_type_param = reg_type_param.lower()
        for reg_type, config in registration_mappings.items():
            if reg_type in reg_type_param or reg_type_param in reg_type:
                return {
                    'registration_type': reg_type,
                    'registration_flow': config['registration_flow'],
                    'account_type': config['account_type'],
                    'description': config['description'],
                    'required_fields': config['required_fields'],
                    'optional_fields': config['optional_fields'],
                    'detected_from': 'request_param'
                }
    
    # Default to standard registration
    return {
        'registration_type': 'standard',
        'registration_flow': 'standard',
        'account_type': 'personal',
        'description': 'Standard Registration (Default)',
        'required_fields': ['email', 'password', 'otp'],
        'optional_fields': ['first_name', 'last_name', 'phone'],
        'detected_from': 'default'
    }


# =============================================================================
# ACCOUNTS UNIFIED REGISTRATION ENDPOINT
# =============================================================================

@extend_schema(
    operation_id='accounts_register',
    summary='Unified Accounts Registration',
    description='''
    **Enhanced unified registration endpoint that intelligently handles multiple registration types:**
    
    ### Registration Types:
    1. **Business Registration** - Register business with module subscription
    2. **Service Registration** - Register for specific service access  
    3. **Standard/Personal Registration** - Basic user registration
    4. **Google OAuth Registration** - Social registration using Google
    
    ### Auto-Detection Features:
    - Detects registration type from URL/Referer header
    - Routes to appropriate registration handler
    - Supports OTP verification for email validation
    - Creates appropriate contexts and permissions
    
    ### Business Registration Flow:
    1. Validates OTP and required fields
    2. Creates user account  
    3. Creates business context
    4. Assigns owner role
    5. Creates module subscription (trial)
    6. Sets up permissions
    
    ### Service Registration Flow:
    1. Validates service access
    2. Creates user account
    3. Creates service request
    4. Sets up payment if required
    
    ### Standard Registration Flow:
    1. Creates basic user account
    2. Creates personal context
    3. Assigns basic permissions
    ''',
    tags=['Registration'],
    request={
        'application/json': {
            'type': 'object',
            'properties': {
                'google_token': {
                    'type': 'string',
                    'description': 'Google OAuth access token (for Google OAuth registration)',
                    'example': 'ya29.a0AfH6SMC_example_token'
                },
                'email': {
                    'type': 'string',
                    'format': 'email',
                    'description': 'User email address',
                    'example': 'user@example.com'
                },
                'password': {
                    'type': 'string',
                    'description': 'User password (min 8 characters)',
                    'example': 'SecurePassword123!'
                },
                'first_name': {
                    'type': 'string',
                    'description': 'User first name',
                    'example': 'John'
                },
                'last_name': {
                    'type': 'string',
                    'description': 'User last name',
                    'example': 'Doe'
                },
                'mobile_number': {
                    'type': 'string',
                    'description': 'User mobile number',
                    'example': '+1234567890'
                },
                'otp': {
                    'type': 'string',
                    'description': 'OTP verification code',
                    'example': '123456'
                },
                'business_name': {
                    'type': 'string',
                    'description': 'Business name (for business registration)',
                    'example': 'My Tech Company'
                },
                'module_id': {
                    'type': 'integer',
                    'description': 'Module ID for business subscription',
                    'example': 1
                },
                'service_id': {
                    'type': 'integer',
                    'description': 'Service ID (for service registration)',
                    'example': 5
                },
                'plan_id': {
                    'type': 'integer',
                    'description': 'Service plan ID',
                    'example': 10
                },
                'registration_type': {
                    'type': 'string',
                    'enum': ['business', 'service', 'personal', 'standard'],
                    'description': 'Registration type (auto-detected if not provided)',
                    'example': 'business'
                }
            }
        }
    },
    responses={
        201: {
            'description': 'Registration successful',
            'content': {
                'application/json': {
                    'type': 'object',
                    'properties': {
                        'message': {'type': 'string', 'example': 'Registration successful'},
                        'access_token': {'type': 'string', 'example': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...'},
                        'refresh_token': {'type': 'string', 'example': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...'},
                        'user': {
                            'type': 'object',
                            'properties': {
                                'id': {'type': 'integer', 'example': 123},
                                'email': {'type': 'string', 'example': 'user@example.com'},
                                'registration_flow': {'type': 'string', 'example': 'business'},
                                'registration_completed': {'type': 'boolean', 'example': True}
                            }
                        },
                        'context': {
                            'type': 'object',
                            'properties': {
                                'id': {'type': 'integer', 'example': 456},
                                'name': {'type': 'string', 'example': 'My Tech Company'},
                                'context_type': {'type': 'string', 'example': 'business'},
                                'profile_status': {'type': 'string', 'example': 'complete'}
                            }
                        },
                        'registration_type': {'type': 'string', 'example': 'business'},
                        'detected_from': {'type': 'string', 'example': 'url_path'}
                    }
                }
            }
        },
        400: {
            'description': 'Bad Request - Validation errors',
            'content': {
                'application/json': {
                    'type': 'object',
                    'properties': {
                        'error': {'type': 'string', 'example': 'Invalid OTP or missing required fields'}
                    }
                }
            }
        },
        409: {
            'description': 'Conflict - User already exists',
            'content': {
                'application/json': {
                    'type': 'object',
                    'properties': {
                        'error': {'type': 'string', 'example': 'User already exists with this email'}
                    }
                }
            }
        },
        429: {
            'description': 'Too Many Requests - Rate limit exceeded',
            'content': {
                'application/json': {
                    'type': 'object',
                    'properties': {
                        'error': {'type': 'string', 'example': 'Too many registration attempts. Try again in 1 hour.'}
                    }
                }
            }
        }
    },
    examples=[
        OpenApiExample(
            'Business Registration',
            summary='Register a business with module subscription',
            description='Complete business registration with Payroll module subscription',
            value={
                'email': 'owner@mybusiness.com',
                'password': 'SecurePassword123!',
                'first_name': 'John',
                'last_name': 'Doe',
                'mobile_number': '+1234567890',
                'business_name': 'My Tech Company',
                'module_id': 1,
                'otp': '123456'
            }
        ),
        OpenApiExample(
            'Service Registration',
            summary='Register for a specific service',
            description='Register user for GST Registration service',
            value={
                'email': 'user@example.com',
                'password': 'SecurePassword123!',
                'first_name': 'Jane',
                'last_name': 'Smith',
                'mobile_number': '+1234567890',
                'service_id': 5,
                'plan_id': 10,
                'otp': '654321'
            }
        ),
        OpenApiExample(
            'Standard Registration',
            summary='Basic user registration',
            description='Standard personal user registration',
            value={
                'email': 'user@example.com',
                'password': 'SecurePassword123!',
                'first_name': 'Alice',
                'last_name': 'Johnson',
                'mobile_number': '+1234567890',
                'otp': '789012'
            }
        ),
        OpenApiExample(
            'Google OAuth Registration',
            summary='Register using Google OAuth',
            description='Social registration using Google OAuth token',
            value={
                'google_token': 'ya29.a0AfH6SMC_example_google_access_token_here'
            }
        )
    ]
)
@api_view(['POST'])
@permission_classes([AllowAny])
@rate_limit(key='ip', rate='100/h', message='Too many registration attempts. Try again in 1 hour.')
def accounts_register(request):
    """
    Enhanced accounts unified registration endpoint
    Handles all registration types including Google OAuth registration
    """
    try:
        # Check if this is Google OAuth registration
        google_token = request.data.get('google_token')
        if google_token:
            return handle_google_oauth_registration(request)
        
        # Regular registration flow (existing logic)
        registration_config = detect_registration_type_from_url(request)
        registration_type = registration_config['registration_type']
        
        logger.info(f"Registration type detected: {registration_type} from {registration_config['detected_from']}")
        
        # Route to appropriate registration handler
        if registration_type == 'business':
            return handle_business_registration(request, registration_config)
        elif registration_type == 'service':
            return handle_service_registration(request, registration_config)
        elif registration_type in ['personal', 'standard']:
            return handle_standard_registration(request, registration_config)
        else:
            return Response({
                'error': f'Unknown registration type: {registration_type}'
            }, status=status.HTTP_400_BAD_REQUEST)
            
    except Exception as e:
        logger.exception("Unified registration failed")
        return Response({
            'error': f'Registration failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def handle_business_registration(request, config):
    """
    Handle business registration with module subscription
    """
    try:
        # Extract data
        email = request.data.get('email')
        password = request.data.get('password')
        business_name = request.data.get('business_name')
        module_id = request.data.get('module_id')
        submitted_otp = request.data.get('otp')
        
        # Validate required fields
        required_fields = config['required_fields']
        missing_fields = [field for field in required_fields if not request.data.get(field)]
        
        if missing_fields:
            return Response({
                'error': f'Missing required fields: {", ".join(missing_fields)}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate OTP
        try:
            otp_obj = PendingUserOTP.objects.get(email=email)
        except PendingUserOTP.DoesNotExist:
            return Response({'error': 'OTP not requested for this email'}, status=status.HTTP_400_BAD_REQUEST)
        
        if otp_obj.is_expired():
            return Response({'error': 'OTP expired'}, status=status.HTTP_400_BAD_REQUEST)
        
        if otp_obj.otp_code != submitted_otp:
            return Response({'error': 'Invalid OTP'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate user doesn't exist
        if User.objects.filter(email=email).exists():
            return Response({
                'error': 'User already exists with this email'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate module
        try:
            module = Module.objects.get(id=module_id)
        except Module.DoesNotExist:
            return Response({
                'error': f'Module with ID {module_id} does not exist'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Validate trial plan exists
        trial_plan = SubscriptionPlan.objects.filter(
            module=module, 
            plan_type='trial', 
            is_active=True
        ).first()
        
        if not trial_plan:
            return Response({
                'error': f'No trial plan available for module: {module.name}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Create user and business context
        with transaction.atomic():
            # 1. Create user (only authentication fields)
            user = User.objects.create_user(
                email=email,
                password=password,
                is_active=True,
                status='active',
                is_super_admin=False,
            )
            
            # 2. Create business context
            context = Context.objects.create(
                name=business_name,
                context_type=config['account_type'],
                owner_user=user,
                status='active',
                profile_status='incomplete',
                metadata={'account_type': config['account_type']}
            )
            
            # 3. Create UserSession (active context is now in UserSession)
            from .models import UserSession
            user_session = UserSession.objects.create(
                user=user,
                active_context=context,
                is_active=True,
                default_session=True,  # Set as default since it's their first business context
                session_data={'registration_type': 'business'}
            )
            
            # 4. Update UserRegistration (registration flow is now in UserRegistration)
            from .models import UserRegistration
            user_registration, created = UserRegistration.objects.get_or_create(
                user=user,
                defaults={
                    'registration_flow': config['registration_flow'],
                    'initial_selection': module.name,
                    'registration_completed': False,
                    'registration_status': 'incomplete',
                    'steps_completed': ['user_created', 'context_created']
                }
            )
            if not created:
                # Update existing record
                user_registration.registration_flow = config['registration_flow']
                user_registration.initial_selection = module.name
                user_registration.registration_completed = False
                user_registration.registration_status = 'incomplete'
                user_registration.steps_completed = ['user_created', 'context_created']
                user_registration.save()
            
            # 5. Get or create owner role for this context
            owner_role = Role.objects.get(
                context=context,
                role_type='owner'
            )
            
            # 6. Create user context role (owner)
            user_context_role = UserContextRole.objects.create(
                user=user,
                context=context,
                role=owner_role,
                status='active',
                added_by=user  # Self-registered
            )
            
            # 7. Create module subscription
            ModuleSubscription.objects.create(
                context=context,
                module=module,
                plan=trial_plan,
                status='trial',
                start_date=timezone.now(),
                end_date=timezone.now() + timezone.timedelta(days=trial_plan.billing_cycle_days),
                auto_renew=False,  # Don't auto-renew trial
                added_by=user  # Set the added_by field to the user being registered
            )
            
            # 6. Delete OTP
            otp_obj.delete()
            
            # 7. Get login response
            login_response_data = get_login_response(user)
            
            response = Response({
                'success': True,
                'message': 'Business registration successful',
                'registration_type': 'business',
                'user': login_response_data['user'],
                'access_token': login_response_data['access_token'],
                'refresh_token': login_response_data['refresh_token'],
                'context': {
                    'id': context.id,
                    'name': context.name,
                    'type': context.context_type
                },
                'module': {
                    'id': module.id,
                    'name': module.name
                }
            }, status=status.HTTP_201_CREATED)
            # Cookie settings for cross-subdomain support
            cookie_domain = '.tarafirst.com'  # Works across all subdomains
            cookie_secure = False  # Allow HTTP for testing

            # Debug: Log what domain we're setting
            print(f"DEBUG: Setting cookies with domain={cookie_domain}, secure={cookie_secure}")
            print(f"DEBUG: Request host={request.get_host()}")

            # Set environment-aware cookies
            response.set_cookie(
                'access_token',
                login_response_data['access_token'],
                domain=cookie_domain,  # localhost for testing
                secure=cookie_secure,  # False for HTTP
                httponly=True,  # No JS access (XSS protection)
                samesite='Lax',  # Lax for local testing (works with same domain)
                max_age=43200  # 12 hours
            )

            response.set_cookie(
                'refresh_token',
                login_response_data['refresh_token'],
                domain=cookie_domain,  # localhost for testing
                secure=cookie_secure,  # False for HTTP
                httponly=True,  # No JS access (XSS protection)
                samesite='Lax',  # Lax for local testing
                max_age=86400  # 24 hours
            )

            # Set user context cookie for frontend state management
            response.set_cookie(
                'user_context',
                str(context.id) if context else '',
                domain=cookie_domain,
                secure=cookie_secure,
                httponly=False,  # Allow JS access for context switching
                samesite='Lax',  # Lax for local testing
                max_age=86400
            )

            # Set organization cookie for multi-tenant support
            response.set_cookie(
                'organization_id',
                str(context.business.id) if context else '',
                domain=cookie_domain,
                secure=cookie_secure,
                httponly=False,  # Allow JS access for organization context
                samesite='Lax',  # Lax for local testing
                max_age=86400
            )
            return response
            
    except Exception as e:
        logger.exception("Business registration failed")
        return Response({
            'error': f'Business registration failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def handle_service_registration(request, config):
    """
    Handle service-based registration
    """
    try:
        # Extract data
        email = request.data.get('email')
        password = request.data.get('password')
        name = request.data.get('name')
        service_id = request.data.get('service_id')
        submitted_otp = request.data.get('otp')
        
        # Validate required fields
        required_fields = config['required_fields']
        missing_fields = [field for field in required_fields if not request.data.get(field)]
        
        if missing_fields:
            return Response({
                'error': f'Missing required fields: {", ".join(missing_fields)}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate OTP
        try:
            otp_obj = PendingUserOTP.objects.get(email=email)
        except PendingUserOTP.DoesNotExist:
            return Response({'error': 'OTP not requested for this email'}, status=status.HTTP_400_BAD_REQUEST)
        
        if otp_obj.is_expired():
            return Response({'error': 'OTP expired'}, status=status.HTTP_400_BAD_REQUEST)
        
        if otp_obj.otp_code != submitted_otp:
            return Response({'error': 'Invalid OTP'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate user doesn't exist
        if User.objects.filter(email=email).exists():
            return Response({
                'error': 'User already exists with this email'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate service
        try:
            service = Service.objects.get(id=service_id)
        except Service.DoesNotExist:
            return Response({
                'error': f'Service with ID {service_id} does not exist'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Create user and context
        with transaction.atomic():
            # 1. Create user (only authentication fields)
            user = User.objects.create_user(
                email=email,
                password=password,
                is_active=True,
                status='active',
                is_super_admin=False,
            )
            
            # 2. Create context
            context = Context.objects.create(
                name=name,
                context_type=config['account_type'],
                owner_user=user,
                status='active',
                profile_status='incomplete',
                metadata={'account_type': config['account_type']}
            )
            
            # 3. Create UserSession (active context is now in UserSession)
            from .models import UserSession
            user_session = UserSession.objects.create(
                user=user,
                active_context=context,
                is_active=True,
                default_session=True,  # Set as default since it's their first service context
                session_data={'registration_type': 'service'}
            )
            
            # 4. Update UserRegistration (registration flow is now in UserRegistration)
            from .models import UserRegistration
            user_registration, created = UserRegistration.objects.get_or_create(
                user=user,
                defaults={
                    'registration_flow': config['registration_flow'],
                    'initial_selection': service.name,
                    'registration_completed': False,
                    'registration_status': 'incomplete',
                    'steps_completed': ['user_created', 'context_created']
                }
            )
            if not created:
                # Update existing record
                user_registration.registration_flow = config['registration_flow']
                user_registration.initial_selection = service.name
                user_registration.registration_completed = False
                user_registration.registration_status = 'incomplete'
                user_registration.steps_completed = ['user_created', 'context_created']
                user_registration.save()
            
            # 3. Get or create owner role for this context
            owner_role = Role.objects.get(
                context=context,
                role_type='owner'
            )
            
            # 4. Create user context role (owner)
            user_context_role = UserContextRole.objects.create(
                user=user,
                context=context,
                role=owner_role,
                status='active',
                added_by=user  # Self-registered
            )
            
            # 5. Create service request
            ServiceRequest.objects.create(
                user=user,
                context=context,
                service=service,
                status='initiated'
            )
            
            # 6. Delete OTP
            otp_obj.delete()
            
            # 7. Get login response
            login_response_data = get_login_response(user)
            
            response = Response({
                'success': True,
                'message': 'Service registration successful',
                'registration_type': 'service',
                'user': login_response_data['user'],
                'access_token': login_response_data['access_token'],
                'refresh_token': login_response_data['refresh_token'],
                'context': {
                    'id': context.id,
                    'name': context.name,
                    'type': context.context_type
                },
                'service': {
                    'id': service.id,
                    'name': service.name
                }
            }, status=status.HTTP_201_CREATED)

            # Cookie settings for cross-subdomain support
            cookie_domain = '.tarafirst.com'  # Works across all subdomains
            cookie_secure = False  # Allow HTTP for testing

            # Set environment-aware cookies
            response.set_cookie(
                'access_token',
                login_response_data['access_token'],
                domain=cookie_domain,  # localhost for testing
                secure=cookie_secure,  # False for HTTP
                httponly=True,  # No JS access (XSS protection)
                samesite='Lax',  # Lax for local testing (works with same domain)
                max_age=43200  # 12 hours
            )

            response.set_cookie(
                'refresh_token',
                login_response_data['refresh_token'],
                domain=cookie_domain,  # localhost for testing
                secure=cookie_secure,  # False for HTTP
                httponly=True,  # No JS access (XSS protection)
                samesite='Lax',  # Lax for local testing
                max_age=86400  # 24 hours
            )
            response.set_cookie(
                'service_id',
                str(service.id) if service else '',
                domain=cookie_domain,
                secure=cookie_secure,
                httponly=False,
                samesite='Lax',
                max_age=86400
            )

            return response

            
    except Exception as e:
        logger.exception("Service registration failed")
        return Response({
            'error': f'Service registration failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def handle_standard_registration(request, config):
    """
    Handle standard/personal registration
    """
    try:
        # Extract data
        email = request.data.get('email')
        password = request.data.get('password')
        submitted_otp = request.data.get('otp')
        
        # Validate required fields
        required_fields = config['required_fields']
        missing_fields = [field for field in required_fields if not request.data.get(field)]
        
        if missing_fields:
            return Response({
                'error': f'Missing required fields: {", ".join(missing_fields)}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate OTP
        try:
            otp_obj = PendingUserOTP.objects.get(email=email)
        except PendingUserOTP.DoesNotExist:
            return Response({'error': 'OTP not requested for this email'}, status=status.HTTP_400_BAD_REQUEST)
        
        if otp_obj.is_expired():
            return Response({'error': 'OTP expired'}, status=status.HTTP_400_BAD_REQUEST)
        
        if otp_obj.otp_code != submitted_otp:
            return Response({'error': 'Invalid OTP'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate user doesn't exist
        if User.objects.filter(email=email).exists():
            return Response({
                'error': 'User already exists with this email'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Create user
        with transaction.atomic():
            # 1. Create user (only authentication fields)
            user = User.objects.create(
                email=email,
                status='active',
                is_active=True,
                is_super_admin=False,
            )
            user.set_password(password)
            user.save()
            
            # 2. Update UserRegistration (registration flow is now in UserRegistration)
            from .models import UserRegistration
            user_registration, created = UserRegistration.objects.get_or_create(
                user=user,
                defaults={
                    'registration_flow': config['registration_flow'],
                    'initial_selection': None,  # No initial selection for standard registration
                    'registration_completed': False,
                    'registration_status': 'incomplete',
                    'steps_completed': ['user_created']
                }
            )
            if not created:
                # Update existing record
                user_registration.registration_flow = config['registration_flow']
                user_registration.initial_selection = None
                user_registration.registration_completed = False
                user_registration.registration_status = 'incomplete'
                user_registration.steps_completed = ['user_created']
                user_registration.save()
            
            # Delete OTP
            otp_obj.delete()
            
            # Get login response
            login_response_data = get_login_response(user)
            
            response = Response({
                'success': True,
                'message': 'Standard registration successful',
                'registration_type': 'standard',
                'user': login_response_data['user'],
                'access_token': login_response_data['access_token'],
                'refresh_token': login_response_data['refresh_token']
            }, status=status.HTTP_201_CREATED)

            # Cookie settings for cross-subdomain support
            cookie_domain = '.tarafirst.com'  # Works across all subdomains
            cookie_secure = False  # Allow HTTP for testing

            # Debug: Log what domain we're setting
            print(f"DEBUG: Setting cookies with domain={cookie_domain}, secure={cookie_secure}")
            print(f"DEBUG: Request host={request.get_host()}")

            # Set environment-aware cookies
            response.set_cookie(
                'access_token',
                str(login_response_data['access_token']),
                domain=cookie_domain,  # localhost for testing
                secure=cookie_secure,  # False for HTTP
                httponly=True,  # No JS access (XSS protection)
                samesite='Lax',  # Lax for local testing (works with same domain)
                max_age=43200  # 12 hours
            )

            response.set_cookie(
                'refresh_token',
                login_response_data['refresh_token'],
                domain=cookie_domain,  # localhost for testing
                secure=cookie_secure,  # False for HTTP
                httponly=True,  # No JS access (XSS protection)
                samesite='Lax',  # Lax for local testing
                max_age=86400  # 24 hours
            )

            return response
            
    except Exception as e:
        logger.exception("Standard registration failed")
        return Response({
            'error': f'Standard registration failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# =============================================================================
# ZOHO-STYLE REGISTRATION SELECTION PAGE
# =============================================================================

@api_view(['GET'])
@permission_classes([AllowAny])
def zoho_style_registration_selection(request):
    """
    Zoho-style registration type selection page
    Shows available registration types to the user
    """
    try:
        registration_types = [
            {
                'type': 'business',
                'title': 'Business Registration',
                'description': 'Register your business with module subscriptions',
                'icon': 'business-icon',
                'url': '/register/business',
                'features': [
                    'Module subscriptions',
                    'Team management',
                    'Business context',
                    'Trial periods'
                ]
            },
            {
                'type': 'service',
                'title': 'Service Registration',
                'description': 'Register for specific services',
                'icon': 'service-icon',
                'url': '/register/service',
                'features': [
                    'Service-based access',
                    'Quick setup',
                    'Focused features',
                    'Service requests'
                ]
            },
            {
                'type': 'personal',
                'title': 'Personal Registration',
                'description': 'Register as an individual user',
                'icon': 'personal-icon',
                'url': '/register/personal',
                'features': [
                    'Personal account',
                    'Basic features',
                    'Simple setup',
                    'Individual access'
                ]
            }
        ]
        
        return Response({
            'success': True,
            'registration_types': registration_types,
            'registration_url': '/user_management/register/zoho-style/'
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({
            'error': f'Failed to load registration types: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([AllowAny])
def zoho_style_detect_registration_type(request):
    """
    Detect registration type from request (for frontend pre-registration routing)
    """
    try:
        registration_config = detect_registration_type_from_url(request)
        
        return Response({
            'success': True,
            'registration_config': registration_config
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({
            'error': f'Registration type detection failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# =============================================================================
# ZOHO-STYLE REGISTRATION REDIRECT HANDLERS
# =============================================================================

@api_view(['GET'])
@permission_classes([AllowAny])
def zoho_style_registration_redirect(request, registration_type):
    """
    Handle registration-specific redirects (like /register/business)
    """
    try:
        # Detect the registration type
        registration_config = detect_registration_type_from_url(request)
        
        # Return redirect information
        return Response({
            'success': True,
            'registration_config': registration_config,
            'registration_url': '/user_management/register/zoho-style/',
            'message': f'Redirecting to {registration_config["description"]}'
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({
            'error': f'Registration redirect failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# =============================================================================
# GOOGLE OAUTH REGISTRATION
# =============================================================================

def handle_google_oauth_registration(request):
    """
    Handle Google OAuth registration as standard registration
    """
    try:
        google_token = request.data.get('google_token')
        
        if not google_token:
            return Response({
                'error': 'Google token is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Verify Google token and get user info
        google_user_info = verify_google_token_for_registration(google_token)
        
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
        
        # Check if user already exists
        try:
            existing_user = User.objects.get(email=email)
            return Response({
                'error': 'User with this email already exists. Please use login instead.'
            }, status=status.HTTP_400_BAD_REQUEST)
        except User.DoesNotExist:
            pass  # User doesn't exist, continue with registration
        
        # Create new user with Google OAuth data (following standard registration pattern)
        with transaction.atomic():
            # 1. Create user (following standard registration pattern)
            new_user = User.objects.create(
                email=email,
                google_user_id=google_id,
                google_name=name,
                auth_provider='google',
                status='active',
                is_active=True,
                is_super_admin=False,
            )
            
            # 2. Update UserRegistration (same as standard registration)
            from .models import UserRegistration
            user_registration, created = UserRegistration.objects.get_or_create(
                user=new_user,
                defaults={
                    'registration_flow': 'google_oauth',
                    'initial_selection': None,
                    'registration_completed': True,  # Google OAuth is complete registration
                    'registration_status': 'completed',
                    'steps_completed': ['user_created', 'google_oauth_verified']
                }
            )
            if not created:
                # Update existing record
                user_registration.registration_flow = 'google_oauth'
                user_registration.initial_selection = None
                user_registration.registration_completed = True
                user_registration.registration_status = 'completed'
                user_registration.steps_completed = ['user_created', 'google_oauth_verified']
                user_registration.save()
            
            # 3. Get login response (same as standard registration)
            login_response_data = get_login_response(new_user)
            
            logger.info(f"Created new Google OAuth user: {email}")
            
            response = Response({
                'success': True,
                'message': 'Google OAuth registration successful',
                'registration_type': 'google_oauth',
                'user': login_response_data['user'],
                'access_token': login_response_data['access_token'],
                'refresh_token': login_response_data['refresh_token']
            }, status=status.HTTP_201_CREATED)

            # Cookie settings for cross-subdomain support
            cookie_domain = '.tarafirst.com'  # Works across all subdomains
            cookie_secure = False  # Allow HTTP for testing

            # Debug: Log what domain we're setting
            print(f"DEBUG: Setting cookies with domain={cookie_domain}, secure={cookie_secure}")
            print(f"DEBUG: Request host={request.get_host()}")

            # Set environment-aware cookies
            response.set_cookie(
                'access_token',
                str(login_response_data['access_token']),
                domain=cookie_domain,  # localhost for testing
                secure=cookie_secure,  # False for HTTP
                httponly=True,  # No JS access (XSS protection)
                samesite='Lax',  # Lax for local testing (works with same domain)
                max_age=43200  # 12 hours
            )

            response.set_cookie(
                'refresh_token',
                login_response_data['refresh_token'],
                domain=cookie_domain,  # localhost for testing
                secure=cookie_secure,  # False for HTTP
                httponly=True,  # No JS access (XSS protection)
                samesite='Lax',  # Lax for local testing
                max_age=86400  # 24 hours
            )

            return response
        
    except Exception as e:
        logger.exception("Google OAuth registration failed")
        return Response({
            'error': f'Google OAuth registration failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def verify_google_token_for_registration(google_token):
    """
    Verify Google token and return user info for registration
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
        logger.exception("Error verifying Google token for registration")
        return None
