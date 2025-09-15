from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from rest_framework.response import Response
from .models import ServiceRequest, Service, ServicePlan, Context  # Adjust as per your app
from .serializers import *
import razorpay
from Tara.settings.default import RAZORPAY_CLIENT_ID, RAZORPAY_CLIENT_SECRET
from .service_serializers import *  # Optional if using serializer
from django.shortcuts import get_object_or_404
from django.db.models import Q
from .rate_limit_decorator import rate_limit
# Initialize Razorpay client
client = razorpay.Client(auth=(RAZORPAY_CLIENT_ID, RAZORPAY_CLIENT_SECRET))

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@rate_limit(key='ip', rate='10/h', message='Too many service requests. Try again in 1 hour.')
def create_new_service_request(request):
    """
    API endpoint to create a new ServiceRequest using serializer's save()
    """
    service_id = request.data.get('service_id')
    context_id = request.data.get('context_id')
    plan_id = request.data.get('plan_id')
    added_by_id = request.data.get('user_id')
    if not all([service_id, context_id, plan_id, added_by_id]):
        return Response({'error': 'Missing required fields'}, status=400)
    try:
        context = Context.objects.get(id=context_id)
        plan = ServicePlan.objects.get(id=plan_id)
        added_by = Users.objects.get(id=added_by_id)
        service = Service.objects.get(id=service_id)
    except (Context.DoesNotExist, ServicePlan.DoesNotExist, Users.DoesNotExist, Service.DoesNotExist) as e:
        return Response({'error': str(e)}, status=404)

    data = {
        "context_id": context_id,
        "service_id": service_id,
        "user_id": added_by_id,
        "plan_id": plan_id,
    }

    serializer = ServiceRequestCreateSerializer(data=data)
    if not serializer.is_valid():
        return Response({'error': serializer.errors}, status=400)

    try:
        request_obj = serializer.save()

        try:
            service_request = ServiceRequest.objects.get(id=request_obj.id)

            if service_request.status != 'initiated':
                return Response({"error": "Payment not allowed. Service already processed."},
                                status=status.HTTP_400_BAD_REQUEST)

            if plan.service.id != service_request.service.id:
                return Response({"error": "Selected plan does not belong to the requested service."},
                                status=status.HTTP_400_BAD_REQUEST)

            # Update plan selection
            service_request.plan = plan
            service_request.save()

            amount = int(plan.amount * 100) if plan.amount else int(plan.max_amount * 100)  # Convert to paise

            try:
                old_payments = ServicePaymentInfo.objects.filter(
                    service_request=service_request.id,
                    status__iexact='initiated',
                    captured=False,
                    is_latest=True
                )
                print("[DEBUG] About to check if old payments exist")
                if old_payments.exists():
                    print("[DEBUG] Old payments found, updating...")
                    old_payments.update(is_latest=False)
                else:
                    print("[DEBUG] No old payments to update.")
            except Exception as e:
                print("EXCEPTION OCCURRED:", str(e))
                import traceback
                print(traceback.format_exc())

            # ✅ Step 2: Create a new Razorpay order
            razorpay_order = client.order.create({
                "amount": amount,
                "currency": "INR",
                "payment_capture": 1,
                "notes": {
                    "type": "service",
                    "service_payment_id": str(service_request.id),
                    "context_id": str(context.id),
                    "added_by": str(added_by.id)
                }
            })

            # ✅ Step 3: Save new payment info
            order_id = razorpay_order.get('id')
            if not order_id:
                raise ValueError("Razorpay order creation failed: no order ID returned.")

            serializer = ServicePaymentInfoSerializer(data={
                'user': added_by.id,
                'service_request': service_request.id,
                'plan': plan.id,
                'context': context.id,
                'amount': plan.amount if plan.amount else plan.max_amount,
                'razorpay_order_id': order_id,
                'status': 'initiated',
                'is_latest': True
            })

            if serializer.is_valid():
                serializer.save()
                print("[DEBUG] Payment info created:", serializer.data)
            else:
                print("[ERROR] Payment creation failed:", serializer.errors)
                return Response({"error": serializer.errors}, status=400)

            return Response({
                "message": "Razorpay order created successfully.",
                'service_request_id': request_obj.id,
                "order_id": razorpay_order['id'],
                "amount": amount,
                "currency": "INR",
                "key_id": RAZORPAY_CLIENT_ID,

            }, status=status.HTTP_200_OK)

        except ServiceRequest.DoesNotExist:
            return Response({"error": "ServiceRequest not found."}, status=status.HTTP_404_NOT_FOUND)
        except ServicePlan.DoesNotExist:
            return Response({"error": "ServicePlan not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": f"Failed to create Razorpay order: {str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    except (Service.DoesNotExist, ServicePlan.DoesNotExist, Context.DoesNotExist, Users.DoesNotExist) as e:
        return Response({'error': str(e)}, status=404)
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return Response({'error': str(e)}, status=500)


@api_view(['GET', 'PUT', 'DELETE'])
def manage_service_request_assignment(request, service_request_id):
    """
    GET: Returns the assignee and reviewer for a service request.
    PUT: Updates the assignee and/or reviewer fields.
         Expected JSON body: {"assignee_id": <int or null>, "reviewer_id": <int or null>}
    DELETE: Removes (nullifies) the assignee and reviewer fields.
    """

    service_request = get_object_or_404(ServiceRequest, id=service_request_id)

    # GET - Retrieve assignee and reviewer
    if request.method == 'GET':
        return Response({
            "id": service_request.id,
            "assignee": {
                "id": service_request.assignee.id,
                "email": service_request.assignee.email,
                "name": f"{service_request.assignee.first_name} {service_request.assignee.last_name}"
            } if service_request.assignee else None,
            "reviewer": {
                "id": service_request.reviewer.id,
                "email": service_request.reviewer.email,
                "name": f"{service_request.reviewer.first_name} {service_request.reviewer.last_name}"
            } if service_request.reviewer else None
        }, status=status.HTTP_200_OK)

    # PUT - Update assignee and/or reviewer
    elif request.method == 'PUT':
        assignee_id = request.data.get('assignee_id')
        reviewer_id = request.data.get('reviewer_id')

        original_assignee = service_request.assignee
        original_reviewer = service_request.reviewer

        # Validate and assign assignee
        if assignee_id is not None:
            if assignee_id == "":
                service_request.assignee = None
            else:
                assignee = Users.objects.filter(id=assignee_id).first()
                if not assignee:
                    return Response({"error": "Assignee user not found."}, status=status.HTTP_400_BAD_REQUEST)
                service_request.assignee = assignee

        # Validate and assign reviewer
        if reviewer_id is not None:
            if reviewer_id == "":
                service_request.reviewer = None
            else:
                reviewer = Users.objects.filter(id=reviewer_id).first()
                if not reviewer:
                    return Response({"error": "Reviewer user not found."}, status=status.HTTP_400_BAD_REQUEST)
                service_request.reviewer = reviewer
        service_name = service_request.service.name.lower()
        service_request.due_date = due_dates.get(service_name)
        status_ = request.data.get('status')
        if status_:
            if status_ not in ['initiated', 'paid', 'in progress', 'completed', 'rejected']:
                return Response({"error": "Invalid status."}, status=status.HTTP_400_BAD_REQUEST)
            service_request.status = status_
            service_request.save()
        service_request.save(update_fields=['assignee', 'reviewer','due_date'])

        # Condition: Status must be "paid" and new assignee or reviewer is added
        if service_request.status == "paid" and (service_request.assignee or service_request.reviewer):
            slug = service_request.service.name.lower()
            task_names = SERVICE_TASK_MAP.get(slug, [])

            for task_name in task_names:
                # Prevent duplicates: only create if task with same name and service_request doesn't exist
                if not ServiceTask.objects.filter(
                        service_request=service_request,
                        service_type=slug,
                        category_name=task_name
                ).exists():
                    ServiceTask.objects.create(
                        service_request=service_request,
                        service_type=slug,
                        category_name=task_name,
                        client=service_request.user,
                        assignee=service_request.assignee,
                        reviewer=service_request.reviewer,
                        status='yet to be started',
                        due_date=service_request.due_date,
                        priority=service_request.priority

                    )

        return Response({"message": "Assignment updated successfully and tasks created if eligible."},
                        status=status.HTTP_200_OK)

    # DELETE - Unassign assignee and reviewer
    elif request.method == 'DELETE':
        service_request.assignee = None
        service_request.reviewer = None
        service_request.save(update_fields=['assignee', 'reviewer'])
        return Response(
            {"message": "Assignee and reviewer removed successfully."},
            status=status.HTTP_200_OK
        )


@api_view(['GET'])
def user_service_requests(request):
    user = request.user
    context_id = request.query_params.get('context_id')

    if not context_id:
        # Get user's active context from UserSession
        try:
            user_session = user.get_active_session()
            context_id = user_session.active_context.id if user_session and user_session.active_context else None
        except:
            context_id = None

    # 1. Requests created by the user & match context
    user_created = Q(user=user) & Q(context_id=context_id) if context_id else Q(user=user)

    # 2. Requests where the user is assignee or reviewer (regardless of context)
    assigned_or_reviewed = Q(assignee=user) | Q(reviewer=user)

    service_requests = ServiceRequest.objects.filter(
        user_created | assigned_or_reviewed
    ).distinct()

    serializer = ServiceRequestSerializer(service_requests, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
def superadmin_service_requests(request):
    user = request.user

    if not user.is_super_admin:
        return Response({"error": "You are not authorized to view this."}, status=status.HTTP_403_FORBIDDEN)

    assigned_param = request.query_params.get('assigned')
    if assigned_param is None:
        return Response(
            {"error": "Query param 'assigned' is required (true or false)."},
            status=status.HTTP_400_BAD_REQUEST
        )

    assigned = assigned_param.lower() == 'true'

    if assigned:
        queryset = ServiceRequest.objects.filter(assignee__isnull=False, reviewer__isnull=False)
    else:
        queryset = ServiceRequest.objects.filter(models.Q(assignee__isnull=True) | models.Q(reviewer__isnull=True))

    serializer = ServiceRequestSerializer(queryset, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)