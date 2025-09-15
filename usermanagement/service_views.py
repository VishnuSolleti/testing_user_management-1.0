from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import json
from django.db import transaction
from django.utils import timezone
from .models import Module, SubscriptionPlan, Role, UserFeaturePermission
from .serializers import (
    ModuleSerializer, SubscriptionPlanSerializer, RoleSerializer,
    UserFeaturePermissionSerializer, ModuleDetailSerializer,
    SubscriptionPlanSerializer, RoleDetailSerializer,
    UserFeaturePermissionSerializer
)
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from distutils.util import strtobool
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from .service_serializers import *
from django.db import models


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def service_list_create(request):
    if request.method == 'GET':
        services = Service.objects.all()
        serializer = ServiceSerializer(services, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        serializer = ServiceSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([AllowAny])
def service_detail(request, service_id):
    try:
        service = Service.objects.get(id=service_id)
    except Service.DoesNotExist:
        return Response({'error': 'Service not found'}, status=404)

    if request.method == 'GET':
        serializer = ServiceSerializer(service)
        return Response(serializer.data)

    elif request.method == 'PUT':
        serializer = ServiceSerializer(service, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({'message': 'Service updated successfully', 'data': serializer.data})
        return Response(serializer.errors, status=400)

    elif request.method == 'DELETE':
        service.delete()
        return Response({'message': 'Service deleted'})


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def service_plan_list_create(request, service_id):
    try:
        service = Service.objects.get(id=service_id)
    except Service.DoesNotExist:
        return Response({'error': 'Service not found'}, status=404)

    if request.method == 'GET':
        plans = service.plans.all()
        serializer = ServicePlanSerializer(plans, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        data = request.data.copy()
        data['service'] = service.id
        serializer = ServicePlanSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([AllowAny])
def service_plan_detail(request, plan_id):
    try:
        plan = ServicePlan.objects.get(id=plan_id)
    except ServicePlan.DoesNotExist:
        return Response({'error': 'Plan not found'}, status=404)

    if request.method == 'GET':
        serializer = ServicePlanSerializer(plan)
        return Response(serializer.data)

    elif request.method == 'PUT':
        serializer = ServicePlanSerializer(plan, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({'message': 'Plan updated successfully', 'data': serializer.data})
        return Response(serializer.errors, status=400)

    elif request.method == 'DELETE':
        plan.delete()
        return Response({'message': 'Plan deleted'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_context_service_requests(request,pk):
    """
    Retrieve all service requests for a specific context.
    
    Query parameters:
    - context_id: ID of the context to get service requests for
    """

    try:
        # Verify context exists and user has access
        try:
            context = Context.objects.get(pk=pk)
            # Check if user has access to this context
            if not Users.objects.filter(id=request.user.id).exists():
                return Response(
                    {"error": "You do not have permission to access this context."},
                    status=status.HTTP_403_FORBIDDEN
                )
        except Context.DoesNotExist:
            return Response(
                {"error": "Context not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get all service requests for this context
        service_requests = ServiceRequest.objects.filter(context_id=pk).order_by('-id')
        
        # Serialize the data
        serializer = ServiceRequestSerializer(service_requests, many=True)
        
        return Response(serializer.data, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([AllowAny])
def get_services_by_type(request):
    """
    Retrieve services based on the specified context type.

    Query parameters:
    - type: 'business' or 'personal'

    If type is 'business', returns services with types 'Business'
    If type is 'personal', returns services with types 'Personal'
    """
    context_type = request.query_params.get('type', '')
    
    # Capitalize the first letter if input is lowercase
    if context_type.lower() in ['business', 'personal']:
        context_type = context_type.capitalize()
    
    if not context_type or context_type not in ['Business', 'Personal']:
        return Response(
            {"error": "Please provide a valid type parameter ('business' or 'personal')"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    services = Service.objects.filter(type=context_type, is_active=True)
    serializer = ServiceSerializer(services, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)

