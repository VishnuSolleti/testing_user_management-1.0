"""
ACCOUNTS URL PATTERNS
====================

URL patterns for the Accounts authentication system
"""

from django.urls import path
from . import accounts_auth

urlpatterns = [
    # Accounts central login
    path('auth/accounts-login/', accounts_auth.accounts_login, name='accounts_login'),
    
    # Service selection page
    path('auth/services/', accounts_auth.accounts_service_selection, name='accounts_service_selection'),
    
    # Service detection
    path('auth/detect-service/', accounts_auth.accounts_detect_service, name='accounts_detect_service'),
    
    # User's available services
    path('auth/user-services/', accounts_auth.accounts_user_services, name='accounts_user_services'),
    
    # Service-specific redirects
    path('auth/redirect/<str:service_name>/', accounts_auth.accounts_service_redirect, name='accounts_service_redirect'),
]

