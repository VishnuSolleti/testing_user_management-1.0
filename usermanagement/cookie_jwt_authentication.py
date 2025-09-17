"""
COOKIE-BASED JWT AUTHENTICATION
===============================

Custom JWT authentication class that reads tokens from cookies
for seamless microservices authentication.
"""

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework.authentication import CSRFCheck
from rest_framework import exceptions
from django.contrib.auth.models import AnonymousUser
from django.utils.translation import gettext_lazy as _
import logging

logger = logging.getLogger(__name__)


class CookieJWTAuthentication(JWTAuthentication):
    """
    Custom JWT authentication that reads tokens from cookies instead of headers
    Perfect for microservices architecture with cross-subdomain support
    """
    
    def authenticate(self, request):
        """
        Authenticate using JWT token from cookies
        """
        # Try to get token from cookie first
        raw_token = request.COOKIES.get('access_token')
        
        if raw_token is None:
            # Fallback to Authorization header for API clients
            header = self.get_header(request)
            if header is None:
                return None
            raw_token = self.get_raw_token(header)
            if raw_token is None:
                return None

        # Validate the token
        validated_token = self.get_validated_token(raw_token)
        user = self.get_user(validated_token)
        
        return (user, validated_token)

    def get_validated_token(self, raw_token):
        """
        Validates an encoded JSON web token and returns a validated token
        wrapper object.
        """
        messages = []
        for AuthToken in self.get_token_types():
            try:
                return AuthToken(raw_token)
            except TokenError as e:
                messages.append({
                    'token_class': AuthToken.__name__,
                    'token_type': AuthToken.token_type,
                    'message': e.args[0],
                })

        raise InvalidToken({
            'detail': _('Given token not valid for any token type'),
            'messages': messages,
        })


class CookieJWTAuthenticationWithRefresh(CookieJWTAuthentication):
    """
    Extended cookie JWT authentication with automatic token refresh
    """
    
    def authenticate(self, request):
        """
        Authenticate with automatic token refresh if access token is expired
        """
        try:
            # Try normal authentication first
            return super().authenticate(request)
        except InvalidToken as e:
            # If access token is invalid/expired, try to refresh
            return self.attempt_token_refresh(request)
    
    def attempt_token_refresh(self, request):
        """
        Attempt to refresh the access token using refresh token from cookie
        """
        refresh_token = request.COOKIES.get('refresh_token')
        
        if not refresh_token:
            return None
        
        try:
            from rest_framework_simplejwt.tokens import RefreshToken
            
            # Validate refresh token and generate new access token
            refresh = RefreshToken(refresh_token)
            new_access_token = str(refresh.access_token)
            
            # Validate the new access token
            validated_token = self.get_validated_token(new_access_token)
            user = self.get_user(validated_token)
            
            # Set the new token in response (will be handled by middleware)
            request._new_access_token = new_access_token
            
            return (user, validated_token)
            
        except TokenError as e:
            logger.warning(f"Token refresh failed: {e}")
            return None


class TokenRefreshMiddleware:
    """
    Middleware to set new access token cookie when token is refreshed
    """
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        
        # If a new access token was generated during authentication, set it as cookie
        if hasattr(request, '_new_access_token'):
            response.set_cookie(
                'access_token',
                request._new_access_token,
                domain='.dev-backend.tarafirst.com',
                secure=True,
                httponly=True,
                samesite='Lax',
                max_age=43200  # 12 hours
            )
            
        return response


class CookieCSRFMiddleware:
    """
    CSRF protection middleware for cookie-based authentication
    """
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip CSRF for API endpoints with proper authentication
        if request.path.startswith('/user_management/') and request.COOKIES.get('access_token'):
            request._dont_enforce_csrf_checks = True
            
        return self.get_response(request)
