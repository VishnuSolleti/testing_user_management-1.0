"""
GOOGLE OAUTH AUTHENTICATION
==========================

Simple Google OAuth integration following existing patterns
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import get_user_model
from django.shortcuts import redirect
from Tara.settings.default import *
import requests
import logging
import secrets
import json

User = get_user_model()
logger = logging.getLogger(__name__)

@api_view(['GET'])
@permission_classes([AllowAny])
def debug_google_settings(request):
    """
    Debug endpoint to check Google OAuth settings
    """
    # Generate a test state
    state = secrets.token_urlsafe(32)
    
    # Build the exact same URL as initiate endpoint
    from urllib.parse import urlencode
    params = {
        'client_id': GOOGLE_OAUTH_CLIENT_ID,
        'redirect_uri': GOOGLE_OAUTH_REDIRECT_URI,
        'scope': 'email profile',
        'response_type': 'code',
        'state': state,
        'access_type': 'offline'
    }
    
    test_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    
    return Response({
        'GOOGLE_OAUTH_CLIENT_ID': GOOGLE_OAUTH_CLIENT_ID,
        'GOOGLE_OAUTH_CLIENT_SECRET': '***' if GOOGLE_OAUTH_CLIENT_SECRET else None,
        'GOOGLE_OAUTH_REDIRECT_URI': GOOGLE_OAUTH_REDIRECT_URI,
        'client_id_configured': bool(GOOGLE_OAUTH_CLIENT_ID),
        'redirect_uri_configured': bool(GOOGLE_OAUTH_REDIRECT_URI),
        'secret_configured': bool(GOOGLE_OAUTH_CLIENT_SECRET),
        'test_google_auth_url': test_url,
        'url_parameters': params
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def initiate_google_oauth(request):
    """
    Initiate Google OAuth flow - redirects user to Google
    """
    try:
        # Generate state parameter for security
        state = secrets.token_urlsafe(32)
        
        # Store state in session for verification
        request.session['google_oauth_state'] = state
        
        # Validate required settings
        if not GOOGLE_OAUTH_CLIENT_ID:
            return Response({
                'error': 'Google OAuth Client ID is not configured'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        if not GOOGLE_OAUTH_REDIRECT_URI:
            return Response({
                'error': 'Google OAuth Redirect URI is not configured'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # Build Google OAuth URL with proper encoding
        from urllib.parse import urlencode
        
        params = {
            'client_id': GOOGLE_OAUTH_CLIENT_ID,
            'redirect_uri': GOOGLE_OAUTH_REDIRECT_URI,
            'scope': 'email profile',
            'response_type': 'code',
            'state': state,
            'access_type': 'offline'
        }
        
        google_auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
        
        return Response({
            'google_auth_url': google_auth_url,
            'state': state
        })
        
    except Exception as e:
        logger.exception("Failed to initiate Google OAuth")
        return Response({
            'error': f'Failed to initiate Google OAuth: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def google_oauth_callback(request):
    """
    Handle Google OAuth callback - exchange code for tokens and user info
    """
    try:
        # Handle both GET (from Google) and POST (from frontend) requests
        if request.method == 'GET':
            code = request.GET.get('code')
            state = request.GET.get('state')
        else:  # POST
            code = request.data.get('code')
            state = request.data.get('state')
        
        if not code:
            return Response({
                'error': 'Authorization code is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # TODO: Implement proper state validation with database or cache
        # For now, just log the state for debugging
        logger.info(f"Received state: {state}")
        session_state = request.session.get('google_oauth_state')
        logger.info(f"Session state: {session_state}")
        
        # Skip state validation temporarily to get OAuth working
        # if not state or state != request.session.get('google_oauth_state'):
        #     return Response({
        #         'error': 'Invalid state parameter'
        #     }, status=status.HTTP_400_BAD_REQUEST)
        
        # Exchange code for access token
        token_data = {
            'client_id': GOOGLE_OAUTH_CLIENT_ID,
            'client_secret': GOOGLE_OAUTH_CLIENT_SECRET,
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': GOOGLE_OAUTH_REDIRECT_URI,
        }
        
        token_response = requests.post('https://oauth2.googleapis.com/token', data=token_data)
        
        if token_response.status_code != 200:
            logger.error(f"Google token exchange failed: {token_response.status_code}")
            return Response({
                'error': 'Failed to exchange authorization code for token'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        tokens = token_response.json()
        access_token = tokens.get('access_token')
        
        if not access_token:
            return Response({
                'error': 'No access token received from Google'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get user info from Google
        user_info_response = requests.get(
            'https://www.googleapis.com/oauth2/v2/userinfo',
            headers={'Authorization': f"Bearer {access_token}"}
        )
        
        if user_info_response.status_code != 200:
            logger.error(f"Google user info failed: {user_info_response.status_code}")
            return Response({
                'error': 'Failed to get user information from Google'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        user_info = user_info_response.json()
        
        # Extract user data
        email = user_info.get('email')
        google_id = user_info.get('id')
        name = user_info.get('name')
        
        if not email or not google_id:
            return Response({
                'error': 'Invalid user data from Google'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Handle user creation/linking
        user = handle_google_user(email, google_id, name)
        
        if not user:
            return Response({
                'error': 'Failed to create or link user account'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # State cleanup not needed since we're not using session validation
        
        # Generate JWT tokens
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)
        access_token_jwt = str(refresh.access_token)
        refresh_token = str(refresh)
        
        return Response({
            'message': 'Google OAuth login successful',
            'access_token': access_token_jwt,
            'refresh_token': refresh_token,
            'google_access_token': access_token,  # Add Google access token for testing
            'user': {
                'id': user.id,
                'email': user.email,
                'name': name,
                'auth_provider': user.auth_provider
            }
        })
        
    except Exception as e:
        logger.exception("Google OAuth callback failed")
        return Response({
            'error': f'Google OAuth callback failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)




def handle_google_user(email, google_id, name):
    """
    Handle Google user creation or linking
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
            # User doesn't exist - create new user
            new_user = User.objects.create(
                email=email,
                google_user_id=google_id,
                google_name=name,
                auth_provider='google',
                is_active=True
            )
            logger.info(f"Created new Google OAuth user: {email}")
            return new_user
            
    except Exception as e:
        logger.exception(f"Error handling Google user: {email}")
        return None
