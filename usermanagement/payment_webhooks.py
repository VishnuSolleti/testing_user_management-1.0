# views.py

import hmac
import hashlib
import json
from decimal import Decimal
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.decorators import api_view, permission_classes
from .models import PaymentInfo, ServicePaymentInfo
from .serializers import PaymentInfoSerializer, ServicePaymentInfoSerializer
from .rate_limit_decorator import rate_limit

@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
@rate_limit(key='ip', rate='100/h', message='Too many webhook requests from your IP. Contact support if this is legitimate.')
def razorpay_webhook(request):
    """Handle Razorpay Webhook Safely."""
    try:
        # Step 1: Parse payload
        webhook_body = request.body
        webhook_data = json.loads(webhook_body)

        print("Webhook Received:", webhook_data)  # (For Debugging)

        # Step 2: Verify Razorpay signature
        webhook_secret = "TaraFirst@2025"  # You must set this in Razorpay settings + Django settings

        received_signature = request.headers.get('X-Razorpay-Signature')
        print(received_signature)
        generated_signature = hmac.new(
            webhook_secret.encode(),
            webhook_body,
            hashlib.sha256
        ).hexdigest()
        print(generated_signature)
        if received_signature != generated_signature:
            return Response({'error': 'Invalid Signature'}, status=400)

        print("signature Verified")

        # Step 3: Handle webhook events
        event = webhook_data.get('event')
        print(event)
        if event == 'payment.captured':
            payment_entity = webhook_data['payload']['payment']['entity']

            razorpay_payment_id = payment_entity['id']
            razorpay_order_id = payment_entity['order_id']
            payment_method = payment_entity.get('method')
            card_id = payment_entity.get('card_id')
            bank = payment_entity.get('bank')
            captured = payment_entity.get('captured', False)
            vpa = payment_entity.get('vpa')
            email = payment_entity.get('email')
            contact = payment_entity.get('contact')

            try:
                payment_intent = PaymentInfo.objects.get(razorpay_order_id=razorpay_order_id)

                payment_intent.status = 'paid'
                payment_intent.razorpay_payment_id = razorpay_payment_id

                # ⭐ New fields you need to populate:
                payment_intent.payment_method = payment_method
                payment_intent.payment_captured = captured

                if bank:
                    payment_intent.bank = bank

                if card_id:
                    payment_intent.card_last4 = card_id[-4:]  # last 4 digits if card_id is available

                if email:
                    payment_intent.customer_email = email

                if contact:
                    payment_intent.customer_contact = contact

                # ⭐ Fix amount if needed (as before)
                if payment_intent.amount and not isinstance(payment_intent.amount, Decimal):
                    payment_intent.amount = Decimal(str(payment_intent.amount))

                payment_intent.save()

                print(f"PaymentInfo {payment_intent.razorpay_order_id} - fully updated and paid")
                return Response({'status': 'Payment Captured & PaymentInfo Updated'})

            except PaymentInfo.DoesNotExist:
                return Response({'error': 'PaymentIntent not found'}, status=404)

        elif event == 'payment.failed':
            payment_entity = webhook_data['payload']['payment']['entity']

            razorpay_order_id = payment_entity['order_id']
            failure_reason = payment_entity.get('error_description', 'Unknown')

            try:
                payment_intent = PaymentInfo.objects.get(razorpay_order_id=razorpay_order_id)

                payment_intent.status = 'failed'
                payment_intent.failure_reason = failure_reason
                # ⭐ Fix amount if needed (as before)
                if payment_intent.amount and not isinstance(payment_intent.amount, Decimal):
                    payment_intent.amount = Decimal(str(payment_intent.amount))

                payment_intent.save()

                return Response({'status': 'Payment Failed & Updated'})

            except PaymentInfo.DoesNotExist:
                return Response({'error': 'PaymentIntent not found'}, status=404)

        else:
            # For now, ignore other events
            return Response({'status': f'Unhandled event {event}'})

    except Exception as e:
        print('Webhook Error:', str(e))
        return Response({'error': str(e)}, status=500)


@api_view(['GET'])
def payment_history(request):
    """
    Returns payment history for a given context (business).
    Requires ?context_id=... as query param.
    """
    context_id = request.query_params.get('context_id')

    if not context_id:
        return Response({"error": "Missing required query param: context_id"}, status=400)

    payments = PaymentInfo.objects.filter(context_id=context_id)

    serializer = PaymentInfoSerializer(payments, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def unified_payment_history(request):
    """
    Get all payment records for a given context:
    - Service payments (via ServicePaymentInfo)
    - Module/suite payments (via PaymentInfo)
    """
    context_id = request.GET.get('context_id')
    if not context_id:
        return Response({"error": "Missing required query param: context_id"}, status=400)

    # --- Service Payments ---
    service_payments = ServicePaymentInfo.objects.filter(service_request__context_id=context_id)
    service_serializer = ServicePaymentInfoSerializer(service_payments.order_by('-created_at'), many=True)

    # --- Module/Suite Payments ---
    module_payments = PaymentInfo.objects.filter(context_id=context_id)
    module_serializer = PaymentInfoSerializer(module_payments.order_by('-created_at'), many=True)

    return Response({
        "context_id": context_id,
        "service_payments": service_serializer.data,
        "module_payments": module_serializer.data
    })

