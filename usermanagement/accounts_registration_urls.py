"""
ACCOUNTS REGISTRATION URL PATTERNS
==================================

URL patterns for the unified Accounts registration system
"""

from django.urls import path
from . import accounts_registration

urlpatterns = [
    # Accounts unified registration
    path('register/accounts/', accounts_registration.accounts_register, name='accounts_register'),
    
    # Registration type selection page
    path('register/types/', accounts_registration.accounts_registration_selection, name='accounts_registration_selection'),
    
    # Registration type detection
    path('register/detect-type/', accounts_registration.accounts_detect_registration_type, name='accounts_detect_registration_type'),
    
    # Registration-specific redirects
    path('register/redirect/<str:registration_type>/', accounts_registration.accounts_registration_redirect, name='accounts_registration_redirect'),
]

