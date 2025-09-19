from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import Role, Context, Users, UserProfile
from django.shortcuts import get_object_or_404
from .serializers import RoleSerializer, RoleDetailSerializer, ContextWithRolesSerializer


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_role(request):
    """
    Create a new role for a specific context
    """
    context_id = request.data.get('context_id')
    print(context_id)
    if not context_id:
        return Response({
            'status': 'error',
            'message': 'context_id is required'
        }, status=status.HTTP_400_BAD_REQUEST)

    try:
        context = Context.objects.get(id=context_id)
        print(context)

        # Prepare role data
        role_data = {
            'name': request.data.get('name'),
            'context': context.id,
            'context_type': context.context_type,
            'role_type': request.data.get('role_type', 'custom'),
            'description': request.data.get('description', ''),
            'is_system_role': False,
            'is_default_role': False
        }

        # Validate based on context type
        if context.context_type == 'personal':
            if role_data['role_type'] != 'owner':
                return Response({
                    'status': 'error',
                    'message': 'Personal context can only have owner role type'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Check if personal owner role already exists
            if Role.objects.filter(context=context, role_type='owner').exists():
                return Response({
                    'status': 'error',
                    'message': 'Personal owner role already exists'
                }, status=status.HTTP_400_BAD_REQUEST)

        elif context.context_type == 'business':
            # For business context, validate role type
            if role_data['role_type'] not in ['owner', 'admin', 'manager', 'employee', 'custom']:
                return Response({
                    'status': 'error',
                    'message': 'Invalid role type for business context'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Check if this is a duplicate role name in the business context
            if Role.objects.filter(
                    context=context,
                    name=role_data['name']
            ).exists():
                return Response({
                    'status': 'error',
                    'message': 'Role with this name already exists in business context'
                }, status=status.HTTP_400_BAD_REQUEST)

        serializer = RoleSerializer(data=role_data)
        if serializer.is_valid():
            serializer.save()
            return Response({
                'status': 'success',
                'message': f'Role created successfully for {context.context_type} context',
                'data': serializer.data
            }, status=status.HTTP_201_CREATED)
        return Response({
            'status': 'error',
            'message': 'Invalid data',
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
    except Context.DoesNotExist:
        return Response({
            'status': 'error',
            'message': 'Context not found'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_roles(request):
    """
    List roles with context-specific filtering
    """
    context_id = request.query_params.get('context_id')
    context_type = request.query_params.get('context_type')
    role_type = request.query_params.get('role_type')
    include_system = request.query_params.get('include_system', 'false').lower() == 'true'
    include_default = request.query_params.get('include_default', 'true').lower() == 'true'

    roles = Role.objects.all()

    if context_id:
        try:
            context = Context.objects.get(id=context_id)
            roles = roles.filter(context=context)
        except Context.DoesNotExist:
            return Response({
                'status': 'error',
                'message': 'Context not found'
            }, status=status.HTTP_404_NOT_FOUND)
    elif context_type:
        roles = roles.filter(context_type=context_type)

    if role_type:
        roles = roles.filter(role_type=role_type)
    if not include_system:
        roles = roles.filter(is_system_role=False)
    if not include_default:
        roles = roles.filter(is_default_role=False)

    serializer = RoleDetailSerializer(roles, many=True)
    return Response({
        'status': 'success',
        'data': serializer.data
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_role(request, role_id):
    """
    Get a specific role by ID
    """
    try:
        role = Role.objects.get(id=role_id)
        serializer = RoleDetailSerializer(role)
        return Response({
            'status': 'success',
            'data': serializer.data
        })
    except Role.DoesNotExist:
        return Response({
            'status': 'error',
            'message': 'Role not found'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_role(request, role_id):
    """
    Update a specific role
    """
    try:
        role = Role.objects.get(id=role_id)

        # Prevent modification of system roles
        if role.is_system_role:
            return Response({
                'status': 'error',
                'message': 'System roles cannot be modified'
            }, status=status.HTTP_403_FORBIDDEN)

        # Validate context-specific rules
        if role.context_type == 'personal' and request.data.get('role_type') != 'owner':
            return Response({
                'status': 'error',
                'message': 'Personal context can only have owner role type'
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer = RoleSerializer(role, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                'status': 'success',
                'message': 'Role updated successfully',
                'data': serializer.data
            })
        return Response({
            'status': 'error',
            'message': 'Invalid data',
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
    except Role.DoesNotExist:
        return Response({
            'status': 'error',
            'message': 'Role not found'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_role(request, role_id):
    """
    Delete a specific role
    """
    try:
        role = Role.objects.get(id=role_id)

        # Prevent deletion of system roles
        if role.is_system_role:
            return Response({
                'status': 'error',
                'message': 'System roles cannot be deleted'
            }, status=status.HTTP_403_FORBIDDEN)

        role.delete()
        return Response({
            'status': 'success',
            'message': 'Role deleted successfully'
        })
    except Role.DoesNotExist:
        return Response({
            'status': 'error',
            'message': 'Role not found'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def initialize_system_roles(request):
    """
    Initialize system-defined roles
    """
    try:
        Role.create_system_roles()
        return Response({
            'status': 'success',
            'message': 'System roles initialized successfully'
        })
    except Exception as e:
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def initialize_default_roles(request):
    """
    Initialize default roles in the system
    """
    try:
        Role.create_default_roles()
        return Response({
            'status': 'success',
            'message': 'Default roles initialized successfully'
        })
    except Exception as e:
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_context_roles(request):
    """
    Create roles for a specific context based on default roles
    """
    context_id = request.data.get('context_id')
    if not context_id:
        return Response({
            'status': 'error',
            'message': 'context_id is required'
        }, status=status.HTTP_400_BAD_REQUEST)

    try:
        context = Context.objects.get(id=context_id)
        Role.create_context_roles(context)
        return Response({
            'status': 'success',
            'message': f'Roles created successfully for {context.name}'
        })
    except Context.DoesNotExist:
        return Response({
            'status': 'error',
            'message': 'Context not found'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_context_roles(request):
    """
    List all roles under a specific context ID
    """
    try:
        context_id = request.query_params.get('context_id')
        if not context_id:
            return Response({
                'status': 'error',
                'message': 'context_id query param is required.'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            context_id = int(context_id)
        except ValueError:
            return Response({
                'status': 'error',
                'message': 'context_id must be an integer.'
            }, status=status.HTTP_400_BAD_REQUEST)

        context = Context.objects.get(id=context_id)
        serializer = ContextWithRolesSerializer(context)
        return Response({
            'status': 'success',
            'context': serializer.data
        })

    except Context.DoesNotExist:
        return Response({
            'status': 'error',
            'message': 'Context not found'
        }, status=status.HTTP_404_NOT_FOUND)

    except Exception as e:
        import traceback
        return Response({
            'status': 'error',
            'message': 'Something went wrong.',
            'details': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_role_by_context(request):
    """
    Get a role by its name within a specific context
    """
    role_name = request.query_params.get('role_name')
    context_id = request.query_params.get('context_id')

    if not role_name or not context_id:
        return Response({
            'status': 'error',
            'message': 'role_name and context_id query params are required.'
        }, status=status.HTTP_400_BAD_REQUEST)

    try:
        context = Context.objects.get(id=context_id)
        role = Role.objects.get(name__iexact=role_name, context=context, context_type='business')
        serializer = RoleSerializer(role)
        return Response(serializer.data)
    except Context.DoesNotExist:
        return Response({
            'status': 'error',
            'message': 'Context not found'
        }, status=status.HTTP_404_NOT_FOUND)
    except Role.DoesNotExist:
        return Response({
            'status': 'error',
            'message': 'Role not found in the specified context'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
def bulk_user_details(request):
    """
    Retrieve user details (first name, last name, or email fallback) for multiple users.

    **Authentication:**
    - This endpoint does not enforce authentication by default (depends on project settings).
      If authentication is enabled, a valid token must be provided in the request.

    **Request Method:**
    - POST

    **Request Body:**
    - JSON object with the following field:
      - `user_ids` (list of integers, required):
        A list of user IDs for which details need to be retrieved.

      Example:
      ```json
      {
          "user_ids": [1, 2, 3]
      }
      ```

    **Functionality:**
    - For each user ID in the request:
      - Fetch the corresponding `Users` object.
      - Attempt to retrieve its related `UserProfile` object (one-to-one relationship).
        - If a profile exists, use `profile.first_name` and `profile.last_name`.
        - If no profile exists, fallback to using the `user.email` as the `first_name`
          and leave `last_name` empty.

    **Response:**
    - 200 OK:
      Returns a list of user details. Each object contains:
      - `id` (int): The user's ID.
      - `first_name` (string): Either the profile's first name or email (if no profile exists).
      - `last_name` (string): The profile's last name, or empty string if unavailable.

      Example:
      ```json
      [
          {
              "id": 1,
              "first_name": "John",
              "last_name": "Doe"
          },
          {
              "id": 2,
              "first_name": "jane@example.com",
              "last_name": ""
          }
      ]
      ```

    **Error Handling:**
    - If a user does not have a `UserProfile`, the API safely falls back to email without raising errors.
    - If `user_ids` is missing or empty, the API returns an empty list.

    **Use Case:**
    - Useful for bulk fetching user display names for showing in dropdowns,
      tables, or team assignments where multiple user IDs need to be resolved at once.
    """
    user_ids = request.data.get("user_ids", [])
    users = Users.objects.filter(id__in=user_ids)

    results = []
    for user in users:
        try:
            profile = user.userprofile  # One-to-one relation
            first_name = profile.first_name if profile.first_name else ""
            last_name = profile.last_name if profile.last_name else ""
        except UserProfile.DoesNotExist:
            # Fallback when no UserProfile exists
            first_name = user.email
            last_name = ""

        results.append({
            "id": user.id,
            "first_name": first_name if first_name else user.email,
            "last_name": last_name,
        })

    return Response(results)


@api_view(['GET'])
def get_user_name(request, user_id):
    """
    Retrieve the full name (first + last) of a single user.
    Falls back to email if no profile exists.

    **Request Method:**
    - GET

    **Path Parameter:**
    - `user_id` (int, required)

      Example:
      ```
      GET /api/users/5/name/
      ```

    **Response:**
    - 200 OK:
      Returns a string with the user's name.
      Example:
      ```
      "Alice Smith"
      ```

    - 404 Not Found:
      If the user does not exist.
    """
    user = get_object_or_404(Users, id=user_id)

    try:
        profile = user.userprofile  # One-to-one relation
        first_name = profile.first_name or ""
        last_name = profile.last_name or ""
        full_name = f"{first_name} {last_name}".strip()
    except UserProfile.DoesNotExist:
        full_name = user.email

    # Instead of JSON object, return just the name
    return Response(full_name)


