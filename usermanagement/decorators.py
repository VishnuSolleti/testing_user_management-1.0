from functools import wraps
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from .utils import validate_user_permissions


def require_permissions(module_id, required_actions=None):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            try:
                auth_header = request.META.get('HTTP_AUTHORIZATION', '')
                if not auth_header.startswith('Bearer '):
                    return Response({
                        "success": False,
                        "error": "Authorization header missing or invalid format."
                    }, status=status.HTTP_401_UNAUTHORIZED)

                token = auth_header.split(' ')[1]
                jwt_authenticator = JWTAuthentication()
                validated_token = jwt_authenticator.get_validated_token(token)

                user_context_role_id = validated_token.get('user_context_role', None)

                if not user_context_role_id:
                    return Response(
                        {"success": False, "error": "user_context_role not found in token."},
                        status=status.HTTP_403_FORBIDDEN
                    )

                # Validate permissions
                is_valid, response = validate_user_permissions(
                    user_context_role_id=user_context_role_id,
                    module_id=module_id,
                    required_actions=required_actions
                )

                if not is_valid:
                    return response

                return view_func(request, *args, **kwargs)

            except (InvalidToken, TokenError) as e:
                return Response({
                    "success": False,
                    "error": "Token is invalid or expired.",
                    "details": str(e)
                }, status=status.HTTP_401_UNAUTHORIZED)

            except Exception as e:
                return Response({
                    "success": False,
                    "error": "An unexpected error occurred.",
                    "details": str(e)
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return wrapped_view

    return decorator
