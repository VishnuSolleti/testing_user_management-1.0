from rest_framework import serializers
from .models import Service, ServicePlan, Users, Context, ServiceRequest


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = '__all__'


class ServicePlanSerializer(serializers.ModelSerializer):
    service = serializers.PrimaryKeyRelatedField(queryset=Service.objects.all())
    amount = serializers.FloatField(allow_null=True, default=None)  # For fixed price
    min_amount = serializers.FloatField(allow_null=True, default=None)  # For range price
    max_amount = serializers.FloatField(allow_null=True, default=None)

    class Meta:
        model = ServicePlan
        fields = '__all__'


class ServiceRequestCreateSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    service_id = serializers.IntegerField()
    plan_id = serializers.IntegerField(required=False, allow_null=True)
    context_id = serializers.IntegerField(required=False, allow_null=True)

    def create(self, validated_data):
        user = Users.objects.get(id=validated_data['user_id'])
        service = Service.objects.get(id=validated_data['service_id'])
        plan = ServicePlan.objects.get(id=validated_data['plan_id']) if validated_data.get('plan_id') else None
        context = Context.objects.get(id=validated_data['context_id']) if validated_data.get('context_id') else None

        return ServiceRequest.objects.create(
            user=user,
            service=service,
            plan=plan,
            context=context,
            status='initiated'
        )


class UserDisplaySerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = Users
        fields = ['id', 'full_name']

    def get_full_name(self, obj):
        parts = [obj.first_name, obj.last_name]
        # Filter out None or empty strings, then join with space
        return " ".join(part for part in parts if part).strip()


class ServiceRequestSerializer(serializers.ModelSerializer):
    service_name = serializers.ReadOnlyField(source='service.name')
    service_label = serializers.ReadOnlyField(source='service.label')
    plan_name = serializers.ReadOnlyField(source='plan.name')
    user = UserDisplaySerializer(read_only=True)
    assignee = UserDisplaySerializer(read_only=True)
    reviewer = UserDisplaySerializer(read_only=True)

    class Meta:
        model = ServiceRequest
        fields = ['id', 'user', 'service', 'service_name', 'plan', 'plan_name', 
                  'context', 'status', 'payment_order_id', 'created_at', 'updated_at', 'assignee', 'reviewer', 'service_label']
