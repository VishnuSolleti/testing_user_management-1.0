import razorpay
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from .models import ServiceRequest, ServicePaymentInfo
from Tara.settings.default import RAZORPAY_CLIENT_ID, RAZORPAY_CLIENT_SECRET
import hmac, hashlib
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from .models import ServicePaymentInfo, ServiceRequest, ServicePlan
import json
from rest_framework.permissions import AllowAny
from .serializers import *
from .rate_limit_decorator import rate_limit

# Initialize Razorpay client
client = razorpay.Client(auth=(RAZORPAY_CLIENT_ID, RAZORPAY_CLIENT_SECRET))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@rate_limit(key='ip', rate='10/h', message='Too many service payment attempts. Try again in 1 hour.')
def create_razorpay_order_for_services(request):

    context_id = request.data.get('context_id')
    service_request_id = request.data.get('service_request_id')
    plan_id = request.data.get('plan_id')
    added_by_id = request.data.get('added_by_id')  # Required (User who initiated)

    if not all([service_request_id, plan_id]):
        return Response({"error": "Both service_request_id and plan_id are required."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        service_request = ServiceRequest.objects.get(id=service_request_id)

        if service_request.status != 'initiated':
            return Response({"error": "Payment not allowed. Service already processed."},
                            status=status.HTTP_400_BAD_REQUEST)

        plan = ServicePlan.objects.get(id=plan_id)

        if plan.service.id != service_request.service.id:
            return Response({"error": "Selected plan does not belong to the requested service."},
                            status=status.HTTP_400_BAD_REQUEST)

        # ADD THIS CHECK:
        if plan.plan_type != 'fixed':
            return Response(
                {
                    "error": "Online payment is only available for"
                             "fixed price plans. Please contact support for this plan type."},
                status=status.HTTP_400_BAD_REQUEST
            )
        added_by = Users.objects.get(id=added_by_id)
        context = Context.objects.get(id=context_id)

        # Update plan selection
        service_request.plan = plan
        service_request.save()

        amount = int(plan.amount * 100)  # Amount in paisa

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
            'user': added_by_id,
            'service_request': service_request.id,
            'plan': plan.id,
            'context':context_id,
            'amount': plan.amount,
            'razorpay_order_id': order_id,
            'status': 'initiated',
            'is_latest': True,
        })

        if serializer.is_valid():
            serializer.save()
            print("[DEBUG] Payment info created:", serializer.data)
        else:
            print("[ERROR] Payment creation failed:", serializer.errors)
            return Response({"error": serializer.errors}, status=400)

        return Response({
            "message": "Razorpay order created successfully.",
            "order_id": razorpay_order['id'],
            "amount": amount,
            "currency": "INR",
            "key_id": RAZORPAY_CLIENT_ID
        }, status=status.HTTP_200_OK)

    except ServiceRequest.DoesNotExist:
        return Response({"error": "ServiceRequest not found."}, status=status.HTTP_404_NOT_FOUND)
    except ServicePlan.DoesNotExist:
        return Response({"error": "ServicePlan not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": f"Failed to create Razorpay order: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# @csrf_exempt
# @api_view(['POST'])
# @permission_classes([AllowAny])
# def service_razorpay_webhook(request):
#     try:
#         webhook_secret = "servicetesting"
#         received_sig = request.headers.get('X-Razorpay-Signature')
#         print("[Webhook] Received Signature:", received_sig)
#
#         generated_sig = hmac.new(
#             webhook_secret.encode(),
#             request.body,
#             hashlib.sha256
#         ).hexdigest()
#
#         print("[Webhook] Generated Signature:", generated_sig)
#
#         if not hmac.compare_digest(received_sig, generated_sig):
#             print("[Webhook] Signature mismatch.")
#             return JsonResponse({'error': 'Signature mismatch'}, status=400)
#
#         data = json.loads(request.body)
#         print("[Webhook] Payload received:\n", json.dumps(data, indent=2))
#
#         if data.get('event') == 'payment.captured':
#             entity = data['payload']['payment']['entity']
#             payment_id = entity['id']
#             order_id = entity['order_id']
#             method = entity['method']
#
#             print(f"[Webhook] Payment Captured: payment_id={payment_id}, order_id={order_id}, method={method}")
#
#             payment = ServicePaymentInfo.objects.get(razorpay_order_id=order_id)
#             payment = ServicePaymentInfo.objects.get(razorpay_order_id=order_id)
#
#             payment.razorpay_payment_id = payment_id
#             payment.method = method
#             payment.status = 'captured'
#             payment.captured = 'yes'
#             payment.paid_at = timezone.now()
#             payment.save()
#
#         return JsonResponse({'status': 'ok'})
#
#     except ServicePaymentInfo.DoesNotExist:
#         print(f"[Webhook][ERROR] No payment found for Razorpay order_id: {order_id}")
#         return JsonResponse({'error': 'Payment record not found'}, status=404)
#
#     except Exception as e:
#         import traceback
#         print("[Webhook][ERROR] Exception occurred:", str(e))
#         print(traceback.format_exc())
#         return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def unified_razorpay_webhook(request):
    try:
        print("[Webhook] Received Razorpay webhook")
        webhook_secret = "servicetesting"
        received_sig = request.headers.get('X-Razorpay-Signature')

        generated_sig = hmac.new(
            webhook_secret.encode(),
            request.body,
            hashlib.sha256
        ).hexdigest()

        print(f"[Webhook] Received Signature: {received_sig}")
        print(f"[Webhook] Generated Signature: {generated_sig}")

        if not hmac.compare_digest(received_sig, generated_sig):
            print("[Webhook] Signature mismatch")
            return JsonResponse({'error': 'Signature mismatch'}, status=400)

        data = json.loads(request.body)
        print(f"[Webhook] Payload: {json.dumps(data, indent=2)}")

        if data.get('event') != 'payment.captured':
            print(f"[Webhook] Ignored event: {data.get('event')}")
            return JsonResponse({'status': 'ignored'}, status=200)

        entity = data['payload']['payment']['entity']
        notes = entity.get('notes', {})
        payment_id = entity['id']
        order_id = entity['order_id']
        method = entity['method']

        print(f"[Webhook] Processing payment_id={payment_id}, order_id={order_id}, method={method}, notes={notes}")

        payment_type = notes.get('type')

        if payment_type == 'service':
            return handle_service_payment(order_id, payment_id, method)
        elif payment_type == 'module':
            return handle_module_payment(notes, order_id, payment_id, method)
        else:
            print(f"[Webhook] Unknown payment type: {payment_type}")
            return JsonResponse({'error': 'Unknown payment type'}, status=400)

    except Exception as e:
        import traceback
        print("[Webhook][ERROR]:", traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)


def handle_service_payment(order_id, payment_id, method):
    try:
        print(f"[ServicePayment] Fetching payment for order_id={order_id}")
        payment = ServicePaymentInfo.objects.get(razorpay_order_id=order_id)

        if payment.status == 'captured':
            print(f"[ServicePayment] Already captured for order_id={order_id}")
            return JsonResponse({'status': 'already processed'}, status=200)

        print("[ServicePayment] Marking payment as captured...")
        payment.razorpay_payment_id = payment_id
        payment.method = method
        payment.status = 'captured'
        payment.captured = True
        payment.paid_at = timezone.now()
        payment.save()

        if payment.service_request:
            payment.service_request.status = 'paid'
            payment.service_request.save()
            print(f"[ServicePayment] Updated ServiceRequest #{payment.service_request.id} to paid")

        return JsonResponse({'status': 'service payment processed'})
    except ServicePaymentInfo.DoesNotExist:
        print(f"[ServicePayment][ERROR] ServicePaymentInfo not found for order_id={order_id}")
        return JsonResponse({'error': 'ServicePaymentInfo not found'}, status=404)


def handle_module_payment(notes, order_id, payment_id, method):
    try:
        plan_id = notes.get('plan_id')
        context_id = notes.get('context_id')
        added_by_id = notes.get('added_by')

        if not all([plan_id, context_id, added_by_id]):
            return JsonResponse({'error': 'Missing Razorpay notes (plan_id, context_id, added_by)'}, status=400)

        plan = SubscriptionPlan.objects.get(id=plan_id)
        module = plan.module
        context = Context.objects.get(id=context_id)
        added_by = Users.objects.get(id=added_by_id)
        now = timezone.now()

        with transaction.atomic():
            # Step 1: Update or create subscription
            subscription = ModuleSubscription.objects.filter(
                context=context,
                module=module
            ).first()

            if subscription:
                subscription.plan = plan
                subscription.status = 'active'
                subscription.start_date = now
                subscription.end_date = now + timedelta(days=30)
                subscription.save()

                # End any overlapping cycles
                SubscriptionCycle.objects.filter(
                    subscription=subscription,
                    end_date__gt=now
                ).update(end_date=now)
            else:
                subscription = ModuleSubscription.objects.create(
                    context=context,
                    module=module,
                    plan=plan,
                    status='active',
                    start_date=now,
                    end_date=now + timedelta(days=30),
                    added_by=added_by
                )

            # Step 2: Create subscription cycle
            create_subscription_cycle(subscription)

            # Step 3: Update PaymentInfo
            try:
                payment_info = PaymentInfo.objects.get(razorpay_order_id=order_id)
                payment_info.razorpay_payment_id = payment_id
                payment_info.status = 'paid'
                payment_info.payment_method = method
                payment_info.payment_captured = True
                payment_info.updated_at = now
                payment_info.save()
                print(f"[PaymentInfo] Updated successfully for order_id={order_id}")
            except PaymentInfo.DoesNotExist:
                print(f"[PaymentInfo][WARNING] No PaymentInfo found for Razorpay order_id={order_id}")

        return JsonResponse({'status': 'subscription and payment updated'})

    except (SubscriptionPlan.DoesNotExist, Context.DoesNotExist, Users.DoesNotExist) as e:
        return JsonResponse({'error': str(e)}, status=404)
    except Exception as e:
        import traceback
        print("[Webhook][ModulePayment][ERROR]:", traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)


def create_subscription_cycle(subscription):
    try:
        print(f"[SubscriptionCycle] Creating cycle for subscription id={subscription.id}")

        with transaction.atomic():
            # Initialize feature usage if defined in the plan
            initial_feature_usage = {}
            features = subscription.plan.features_enabled or {}

            for feature_key, config in features.items():
                if isinstance(config, dict) and 'limit' in config:
                    initial_feature_usage[feature_key] = 0

            # End any overlapping cycles
            SubscriptionCycle.objects.filter(
                subscription=subscription,
                end_date__gt=subscription.start_date
            ).update(end_date=subscription.start_date)

            # Create new cycle
            SubscriptionCycle.objects.create(
                subscription=subscription,
                start_date=subscription.start_date,
                end_date=subscription.end_date,
                amount=Decimal(str(subscription.plan.base_price)),
                is_paid=True,
                feature_usage=initial_feature_usage
            )

            print("[SubscriptionCycle] Created successfully")

    except Exception as e:
        import traceback
        print(f"[SubscriptionCycle][ERROR] Failed to create cycle: {str(e)}")
        print(traceback.format_exc())


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_service_payment_history(request):
    """
    Get all service payment records for a user.
    Optional filters: context_id, service_request_id
    """
    user = request.user
    context_id = request.GET.get('context_id')
    service_request_id = request.GET.get('service_request_id')

    payments = ServicePaymentInfo.objects.filter(user=user)

    if context_id:
        payments = payments.filter(service_request__context_id=context_id)

    if service_request_id:
        payments = payments.filter(service_request_id=service_request_id)

    payments = payments.order_by('-created_at')
    serializer = ServicePaymentInfoSerializer(payments, many=True)
    return Response(serializer.data)

