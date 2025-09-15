"""
Reusable rate limiting decorator for Django views.
Simple, clean, and looks like Django's built-in decorators.
"""

from functools import wraps
from django.core.cache import cache
from rest_framework.response import Response
from rest_framework import status
import hashlib


def get_client_ip(request):
    """Get the client's IP address from request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', '127.0.0.1')
    return ip


def is_rate_limited(identifier, limit=5, window_hours=1):
    """Check if an identifier has exceeded the rate limit."""
    cache_key = f"rate_limit_{hashlib.md5(identifier.encode()).hexdigest()}"
    current_count = cache.get(cache_key, 0)
    
    if current_count >= limit:
        return True
    
    cache.set(cache_key, current_count + 1, timeout=window_hours * 3600)
    return False


def rate_limit(key='ip', rate='5/h', message=None):
    """
    Rate limiting decorator for Django views.
    
    Usage:
        @rate_limit(key='ip', rate='5/h')
        @api_view(['POST'])
        def my_view(request):
            return Response({'success': True})
            
        @rate_limit(key='email', rate='3/h', message='Too many requests for this email')
        @api_view(['POST']) 
        def my_view(request):
            return Response({'success': True})
    
    Args:
        key: 'ip', 'email', or custom function
        rate: 'limit/period' where period is 'h' (hour), 'm' (minute), 'd' (day)
        message: Custom error message
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Parse rate limit
            try:
                limit_str, period = rate.split('/')
                limit = int(limit_str)
                
                # Convert period to hours
                if period == 'h':
                    window_hours = 1
                elif period == 'm':
                    window_hours = 1/60  # Convert minutes to hours
                elif period == 'd':
                    window_hours = 24
                else:
                    window_hours = 1  # Default to 1 hour
                    
            except ValueError:
                # Invalid rate format, default to 5/h
                limit = 5
                window_hours = 1
            
            # Get identifier based on key type
            if key == 'ip':
                identifier = f"rate_limit_ip_{get_client_ip(request)}"
                default_message = f"Too many requests from your IP. Limit: {rate}. Try again later."
                
            elif key == 'email':
                email = request.data.get('email', 'unknown')
                identifier = f"rate_limit_email_{email}"
                default_message = f"Too many requests for {email}. Limit: {rate}. Try again later."
                
            elif callable(key):
                # Custom function to generate identifier
                identifier = f"rate_limit_custom_{key(request)}"
                default_message = f"Too many requests. Limit: {rate}. Try again later."
                
            else:
                # Treat as string identifier
                identifier = f"rate_limit_{key}"
                default_message = f"Too many requests. Limit: {rate}. Try again later."
            
            # Check rate limit
            if is_rate_limited(identifier, limit=limit, window_hours=window_hours):
                error_message = message or default_message
                
                # Calculate retry time
                if period == 'h':
                    retry_after = "1 hour"
                elif period == 'm':
                    retry_after = "1 minute"
                elif period == 'd':
                    retry_after = "1 day"
                else:
                    retry_after = "later"
                
                return Response({
                    'error': error_message,
                    'detail': f'Rate limit exceeded. Try again {retry_after}.',
                    'retry_after': retry_after,
                    'limit': rate
                }, status=status.HTTP_429_TOO_MANY_REQUESTS)
            
            # If not rate limited, proceed with the original view
            return view_func(request, *args, **kwargs)
        
        return wrapper
    return decorator


def rate_limit_login(rate='5/h'):
    """
    Special rate limiting decorator for login endpoints.
    Handles both IP and failed email attempts.
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Parse rate
            try:
                limit_str, period = rate.split('/')
                limit = int(limit_str)
                window_hours = 1 if period == 'h' else (1/60 if period == 'm' else 24)
            except ValueError:
                limit = 5
                window_hours = 1
            
            # Check IP rate limit (higher limit for login)
            ip = get_client_ip(request)
            if is_rate_limited(f"login_ip_{ip}", limit=limit*2, window_hours=window_hours):  # 2x limit for IP
                return Response({
                    'error': f'Too many login attempts from your IP. Limit: {limit*2}/{period}. Try again later.',
                    'retry_after': '1 hour' if period == 'h' else '1 minute',
                    'limit': f'{limit*2}/{period}'
                }, status=status.HTTP_429_TOO_MANY_REQUESTS)
            
            # Execute the view
            response = view_func(request, *args, **kwargs)
            
            # If login failed (401), apply email-based rate limiting
            if response.status_code == status.HTTP_401_UNAUTHORIZED:
                email = request.data.get('email', 'unknown')
                if is_rate_limited(f"failed_login_{email}", limit=limit, window_hours=window_hours):
                    return Response({
                        'error': f'Too many failed login attempts for {email}. Try again later.',
                        'detail': f'Failed login limit: {rate}. Try again in 1 hour.',
                        'retry_after': '1 hour',
                        'limit': rate
                    }, status=status.HTTP_429_TOO_MANY_REQUESTS)
            
            return response
        
        return wrapper
    return decorator