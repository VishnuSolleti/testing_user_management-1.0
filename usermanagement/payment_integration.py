# views.py

import razorpay
from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from .models import *
from django.utils import timezone
from datetime import timedelta
from Tara.settings.default import RAZORPAY_CLIENT_ID, RAZORPAY_CLIENT_SECRET
from .rate_limit_decorator import rate_limit

# Initialize Razorpay client
client = razorpay.Client(auth=(RAZORPAY_CLIENT_ID, RAZORPAY_CLIENT_SECRET))


@api_view(['POST'])
@rate_limit(key='ip', rate='10/h', message='Too many order creation attempts from your IP. Try again in 1 hour.')
@rate_limit(key=lambda req: req.user.id if req.user.is_authenticated else 'anonymous', rate='5/h', message='Too many orders per user. Try again in 1 hour.')
def create_order(request):
    """Create Razorpay Order and Save PaymentInfo"""
    try:
        context_id = request.data.get('context_id')
        plan_id = request.data.get('plan_id')
        suite_subscription_id = request.data.get('suite_subscription_id', None)  # Optional
        added_by_id = request.data.get('added_by_id')  # Required (User who initiated)

        if not all([context_id, plan_id, added_by_id]):
            return Response({'error': 'Missing required fields'}, status=status.HTTP_400_BAD_REQUEST)

        context = Context.objects.get(id=context_id)
        plan = SubscriptionPlan.objects.get(id=plan_id)
        added_by = Users.objects.get(id=added_by_id)
        suite_subscription = None
        if suite_subscription_id:
            suite_subscription = ContextSuiteSubscription.objects.get(id=suite_subscription_id)

        amount = Decimal(str(plan.base_price))  # Force Decimal
        currency = 'INR'
        amount_paise = int(float(amount) * 100)

        # Create order on Razorpay
        razorpay_order = client.order.create({
            'amount': amount_paise,
            'currency': 'INR',
            'payment_capture': 1,
            'notes': {
                'type': 'module',  # <-- Required for webhook to route correctly
                'plan_id': str(plan.id),
                'context_id': str(context.id),
                'added_by': str(added_by.id)
            }
        })

        # Save PaymentInfo
        payment_info = PaymentInfo.objects.create(
            context=context,
            plan=plan,
            suite_subscription=suite_subscription,
            amount=amount,
            currency=currency,
            razorpay_order_id=razorpay_order['id'],
            raw_response=razorpay_order,
            added_by=added_by
        )

        return Response({
            'order_id': razorpay_order['id'],
            'amount': amount_paise,
            'currency': currency,
            'key_id': RAZORPAY_CLIENT_ID,
        })

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@rate_limit(key='ip', rate='20/h', message='Too many payment verification attempts from your IP. Try again in 1 hour.')
@rate_limit(key=lambda req: req.user.id if req.user.is_authenticated else 'anonymous', rate='15/h', message='Too many payment verifications per user. Try again in 1 hour.')
def verify_payment(request):
    """Verify Razorpay Payment Only (No Subscription Creation Yet)"""
    try:
        razorpay_order_id = request.data.get('razorpay_order_id')
        razorpay_payment_id = request.data.get('razorpay_payment_id')
        razorpay_signature = request.data.get('razorpay_signature')

        if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
            return Response({'error': 'Missing Razorpay details.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            payment_info = PaymentInfo.objects.get(razorpay_order_id=razorpay_order_id)
        except PaymentInfo.DoesNotExist:
            return Response({'error': 'Invalid Order ID'}, status=status.HTTP_400_BAD_REQUEST)

        # Verify Signature
        params_dict = {
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        }

        try:
            client.utility.verify_payment_signature(params_dict)
        except razorpay.errors.SignatureVerificationError:
            payment_info.status = 'failed'
            payment_info.failure_reason = 'Invalid Signature'
            payment_info.save()
            return Response({'error': 'Payment verification failed.'}, status=status.HTTP_400_BAD_REQUEST)

        # If Signature Valid
        payment_info.status = 'paid'
        payment_info.razorpay_payment_id = razorpay_payment_id
        payment_info.razorpay_signature = razorpay_signature
        payment_info.payment_captured = True
        payment_info.save()

        return Response({'success': True, 'message': 'Payment verified successfully.'})

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

