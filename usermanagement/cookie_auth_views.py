"""
COOKIE-BASED AUTHENTICATION VIEWS
=================================

Views for managing cookie-based JWT authentication across microservices
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import extend_schema, OpenApiExample
from django.contrib.auth import get_user_model
import logging

User = get_user_model()
logger = logging.getLogger(__name__)


@extend_schema(
    operation_id='cookie_logout',
    summary='Cookie-Based Logout',
    description='''
    Logout endpoint that properly clears all authentication cookies across microservices.
    
    **Features:**
    - Clears access_token cookie
    - Clears refresh_token cookie  
    - Clears user_context cookie
    - Clears active_service cookie
    - Works across all subdomains
    - Blacklists refresh token for security
    ''',
    tags=['Authentication'],
    responses={
        200: {
            'description': 'Logout successful',
            'content': {
                'application/json': {
                    'type': 'object',
                    'properties': {
                        'message': {'type': 'string', 'example': 'Logout successful'}
                    }
                }
            }
        }
    }
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cookie_logout(request):
    """
    Logout user and clear all authentication cookies
    """
    try:
        # Get tokens from cookies
        refresh_token = request.COOKIES.get('refresh_token')
        access_token = request.COOKIES.get('access_token')
        
        # Blacklist both refresh and access tokens
        tokens_blacklisted = []
        
        # Blacklist refresh token
        if refresh_token:
            try:
                refresh = RefreshToken(refresh_token)
                refresh.blacklist()
                tokens_blacklisted.append('refresh_token')
                logger.info(f"Successfully blacklisted refresh token for user {request.user.id}")
            except Exception as e:
                logger.warning(f"Failed to blacklist refresh token: {e}")
        
        # Blacklist access token
        if access_token:
            try:
                # For access tokens, we need to create a RefreshToken from it and blacklist
                # Since access tokens can't be directly blacklisted, we'll use a different approach
                from rest_framework_simplejwt.tokens import UntypedToken
                from rest_framework_simplejwt.exceptions import TokenError
                
                # Validate the access token first
                validated_token = UntypedToken(access_token)
                
                # Add to blacklist using the token's jti (JWT ID)
                from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
                from rest_framework_simplejwt.utils import aware_utcnow
                
                # Create a blacklist entry for the access token
                jti = validated_token.get('jti')
                if jti:
                    # Find the outstanding token and blacklist it
                    outstanding_token = OutstandingToken.objects.filter(jti=jti).first()
                    if outstanding_token:
                        BlacklistedToken.objects.get_or_create(token=outstanding_token)
                        tokens_blacklisted.append('access_token')
                        logger.info(f"Successfully blacklisted access token for user {request.user.id}")
                
            except Exception as e:
                logger.warning(f"Failed to blacklist access token: {e}")
        
        # Create response
        response = Response({
            'message': 'Logout successful',
            'tokens_blacklisted': tokens_blacklisted
        }, status=status.HTTP_200_OK)
        
        # Clear all authentication cookies
        cookies_to_clear = ['access_token', 'refresh_token', 'user_context', 'active_service', 'organisation_id']
        
        for cookie_name in cookies_to_clear:
            response.set_cookie(
                cookie_name,
                '',
                domain='.tarafirst.com',
                secure=False,  # Match accounts-auth security setting
                httponly=True if cookie_name in ['access_token', 'refresh_token'] else False,
                samesite='Lax',
                max_age=0,  # Expire immediately
                expires='Thu, 01 Jan 1970 00:00:00 GMT'  # Set to past date
            )
        
        return response
        
    except Exception as e:
        logger.error(f"Logout failed: {e}")
        return Response({
            'error': 'Logout failed'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    operation_id='cookie_refresh_token',
    summary='Cookie-Based Token Refresh',
    description='''
    Refresh JWT access token using refresh token from cookies.
    
    **Features:**
    - Reads refresh token from cookie
    - Generates new access token
    - Updates access_token cookie
    - Maintains user session seamlessly
    ''',
    tags=['Authentication'],
    responses={
        200: {
            'description': 'Token refreshed successfully',
            'content': {
                'application/json': {
                    'type': 'object',
                    'properties': {
                        'message': {'type': 'string', 'example': 'Token refreshed successfully'},
                        'access_token': {'type': 'string', 'example': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...'}
                    }
                }
            }
        },
        401: {
            'description': 'Refresh token invalid or expired',
            'content': {
                'application/json': {
                    'type': 'object',
                    'properties': {
                        'error': {'type': 'string', 'example': 'Refresh token invalid or expired'}
                    }
                }
            }
        }
    }
)
@api_view(['POST'])
@permission_classes([AllowAny])
def cookie_refresh_token(request):
    """
    Refresh access token using refresh token from cookies
    """
    try:
        # Get refresh token from cookie
        refresh_token = request.COOKIES.get('refresh_token')
        
        if not refresh_token:
            return Response({
                'error': 'Refresh token not found in cookies'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        # Validate refresh token and generate new access token
        try:
            refresh = RefreshToken(refresh_token)
            new_access_token = str(refresh.access_token)
        except Exception as e:
            return Response({
                'error': 'Refresh token invalid or expired'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        # Create response with new access token
        response = Response({
            'message': 'Token refreshed successfully',
            'access_token': new_access_token
        }, status=status.HTTP_200_OK)
        
        # Update access token cookie with correct domain settings
        response.set_cookie(
            'access_token',
            new_access_token,
            domain='.tarafirst.com',  # Match accounts-auth domain
            secure=False,             # Match accounts-auth security setting
            httponly=True,
            samesite='Lax',
            max_age=43200  # 12 hours
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Token refresh failed: {e}")
        return Response({
            'error': 'Token refresh failed'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    operation_id='check_auth_status',
    summary='Check Authentication Status',
    description='''
    Check if user is authenticated via cookies and return user info.
    
    **Features:**
    - Validates cookie-based authentication
    - Returns user profile information
    - Returns active context details
    - Useful for frontend auth state management
    ''',
    tags=['Authentication'],
    responses={
        200: {
            'description': 'User is authenticated',
            'content': {
                'application/json': {
                    'type': 'object',
                    'properties': {
                        'authenticated': {'type': 'boolean', 'example': True},
                        'user': {
                            'type': 'object',
                            'properties': {
                                'id': {'type': 'integer', 'example': 123},
                                'email': {'type': 'string', 'example': 'user@example.com'},
                                'is_active': {'type': 'boolean', 'example': True}
                            }
                        },
                        'active_context': {'type': 'string', 'example': '456'},
                        'active_service': {'type': 'string', 'example': 'payroll'}
                    }
                }
            }
        },
        401: {
            'description': 'User is not authenticated',
            'content': {
                'application/json': {
                    'type': 'object',
                    'properties': {
                        'authenticated': {'type': 'boolean', 'example': False},
                        'error': {'type': 'string', 'example': 'Not authenticated'}
                    }
                }
            }
        }
    }
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def check_auth_status(request):
    """
    Check authentication status and return user info
    """
    try:
        user = request.user
        user_context = request.COOKIES.get('user_context', '')
        active_service = request.COOKIES.get('active_service', '')
        
        return Response({
            'authenticated': True,
            'user': {
                'id': user.id,
                'email': user.email,
                'is_active': user.is_active,
                'is_super_admin': getattr(user, 'is_super_admin', False)
            },
            'active_context': user_context,
            'active_service': active_service
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({
            'authenticated': False,
            'error': 'Authentication check failed'
        }, status=status.HTTP_401_UNAUTHORIZED)
