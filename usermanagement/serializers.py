from rest_framework import serializers
from .models import (
    Users, Context, Module, Role, UserContextRole,
    UserFeaturePermission, SubscriptionPlan, ModuleSubscription,Branch, BusinessLogo
)
from .models import *
from django.utils.timezone import now
import re
from datetime import date


class UserSerializer(serializers.ModelSerializer):
    """Serializer for the Users model"""

    # New fields (read-only, pulled from related models/properties)
    full_name = serializers.SerializerMethodField(read_only=True)
    mobile_number = serializers.CharField(read_only=True)
    registration_flow = serializers.CharField(read_only=True)

    class Meta:
        model = Users
        fields = [
            'id',
            'email',
            'created_at',
            'status',
            'service_request',
            'created_by',
            'is_active',
            'is_super_admin',
            'full_name',
            'mobile_number',
            'registration_flow',
        ]
        read_only_fields = [
            'id',
            'created_at',
            'is_super_admin',
            'full_name',
            'mobile_number',
            'registration_flow',
        ]
        extra_kwargs = {
            'password': {'write_only': True}
        }

    def create(self, validated_data):
        """Override create method to properly handle password hashing"""
        password = validated_data.pop('password', None)
        user = super().create(validated_data)
        if password:
            user.set_password(password)
            user.save()
        return user

    # --------------------------
    # Custom field definitions
    # --------------------------
    @staticmethod
    def get_full_name(obj):
        """Combine first_name and last_name from UserProfile"""
        first = obj.first_name or ""
        last = obj.last_name or ""
        return f"{first} {last}".strip() if first or last else None


class ContextSerializer(serializers.ModelSerializer):
    """Serializer for the Context model"""

    class Meta:
        model = Context
        fields = ['id', 'name', 'context_type', 'status', 'profile_status', 'is_platform_context']


class ModuleSerializer(serializers.ModelSerializer):
    """Serializer for the Module model"""
    is_active = serializers.BooleanField(default=True)

    class Meta:
        model = Module
        fields = ['id', 'name', 'category', 'description', 'context_type', 'is_active']


class RoleSerializer(serializers.ModelSerializer):
    """Serializer for the Role model"""

    class Meta:
        model = Role
        fields = ['id', 'name', 'description', 'context_type', 'context']
        read_only_fields = ['id']


class UserContextRoleSerializer(serializers.ModelSerializer):
    """Serializer for the UserContextRole model"""

    class Meta:
        model = UserContextRole
        fields = ['id', 'user', 'context', 'role', 'created_at']
        read_only_fields = ['id', 'created_at']


class UserFeaturePermissionSerializer(serializers.ModelSerializer):
    """Serializer for the UserModulePermission model"""

    class Meta:
        model = UserFeaturePermission
        fields = ['id', 'user_context_role', 'module', 'permissions']
        read_only_fields = ['id']


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    """Serializer for SubscriptionPlan model"""
    features_enabled = serializers.JSONField(default={})

    class Meta:
        model = SubscriptionPlan
        fields = [
            'id', 'module', 'suite', 'name', 'description', 'plan_type',
            'base_price',  'billing_cycle_days', 'is_active', 'features_enabled',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, data):
        """
        Custom validation for subscription plan data
        """
        # Validate plan type and pricing
        if data.get('plan_type') == 'trial':
            if data.get('base_price') != 0:
                raise serializers.ValidationError(
                    "Trial plans must have zero base price and price per unit"
                )

        # Validate billing cycle days is positive
        if data.get('billing_cycle_days', 0) <= 0:
            raise serializers.ValidationError(
                "Billing cycle days must be positive"
            )

        return data


class SubscriptionPlanDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for SubscriptionPlan with related data"""
    module_name = serializers.CharField(source='module.name', read_only=True)
    active_subscriptions_count = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionPlan
        fields = [
            'id', 'module', 'module_name', 'name', 'description', 'plan_type',
            'base_price', 'usage_unit', 'free_tier_limit',
            'price_per_unit', 'billing_cycle_days', 'is_active',
            'created_at', 'updated_at', 'active_subscriptions_count'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'active_subscriptions_count']

    def get_active_subscriptions_count(self, obj):
        """Get count of active subscriptions for this plan"""
        return obj.module_subscriptions.filter(
            status__in=['trial', 'active', 'pending_renewal']
        ).count()


class ModuleSubscriptionSerializer(serializers.ModelSerializer):
    """Serializer for ModuleSubscription model"""
    plan_details = SubscriptionPlanSerializer(source='plan', read_only=True)
    context_name = serializers.CharField(source='context.name', read_only=True)
    module_name = serializers.CharField(source='module.name', read_only=True)

    class Meta:
        model = ModuleSubscription
        fields = [
            'id', 'context', 'context_name', 'module', 'module_name',
            'plan', 'plan_details', 'status', 'start_date', 'end_date',
            'auto_renew', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'created_at', 'updated_at', 'plan_details',
            'context_name', 'module_name'
        ]

    def validate(self, data):
        """
        Custom validation for module subscription data
        """
        # Check if context and module exist
        if 'context' in data and 'module' in data:
            # Check if this module is already subscribed in this context
            existing = ModuleSubscription.objects.filter(
                context=data['context'],
                module=data['module']
            )
            if self.instance:  # If updating existing subscription
                existing = existing.exclude(id=self.instance.id)
            if existing.exists():
                raise serializers.ValidationError(
                    "This module is already subscribed in this context"
                )

        # Validate end date is after start date
        if 'start_date' in data and 'end_date' in data:
            if data['end_date'] <= data['start_date']:
                raise serializers.ValidationError(
                    "End date must be after start date"
                )

        return data


class ModuleSubscriptionDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for ModuleSubscription with related data"""
    plan_details = SubscriptionPlanDetailSerializer(source='plan', read_only=True)
    context_details = serializers.SerializerMethodField()
    module_details = serializers.SerializerMethodField()
    days_remaining = serializers.SerializerMethodField()
    current_price = serializers.SerializerMethodField()

    class Meta:
        model = ModuleSubscription
        fields = [
            'id', 'context', 'context_details', 'module', 'module_details',
            'plan', 'plan_details', 'status', 'start_date', 'end_date',
            'auto_renew', 'current_usage', 'last_usage_update',
            'created_at', 'updated_at', 'days_remaining', 'current_price'
        ]
        read_only_fields = [
            'id', 'created_at', 'updated_at', 'plan_details',
            'context_details', 'module_details', 'last_usage_update',
            'days_remaining', 'current_price'
        ]

    def get_context_details(self, obj):
        """Get context details"""
        return {
            'id': obj.context.id,
            'name': obj.context.name,
            'context_type': obj.context.context_type
        }

    def get_module_details(self, obj):
        """Get module details"""
        return {
            'id': obj.module.id,
            'name': obj.module.name,
            'description': obj.module.description
        }

    def get_days_remaining(self, obj):
        """Get days remaining in subscription"""
        return obj.days_remaining()

    def get_current_price(self, obj):
        """Get current price based on usage"""
        return obj.calculate_current_price()


# Nested serializers for more detailed responses

class UserDetailSerializer(UserSerializer):
    """Detailed serializer for Users with nested relationships"""
    active_context = ContextSerializer(read_only=True)

    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + ['context_roles', 'module_permissions']

    def to_representation(self, instance):
        """Customize the representation to include nested data"""
        representation = super().to_representation(instance)

        # Add context roles
        context_roles = []
        for context_role in instance.context_roles.all():
            role_data = {
                'id': context_role.id,
                'context': context_role.context.name,
                'role': context_role.role.name,
                'created_at': context_role.created_at
            }
            context_roles.append(role_data)
        representation['context_roles'] = context_roles

        # Add module permissions
        module_permissions = []
        for context_role in instance.context_roles.all():
            for permission in context_role.module_permissions.all():
                permission_data = {
                    'id': permission.id,
                    'module': permission.module.name,
                    'permissions': permission.permissions
                }
                module_permissions.append(permission_data)
        representation['module_permissions'] = module_permissions

        return representation


class ContextDetailSerializer(ContextSerializer):
    """Detailed serializer for Context with nested relationships"""
    owner_user = UserSerializer(read_only=True)

    class Meta(ContextSerializer.Meta):
        fields = ContextSerializer.Meta.fields + ['users', 'subscriptions']

    def to_representation(self, instance):
        """Customize the representation to include nested data"""
        representation = super().to_representation(instance)

        # Add users
        users = []
        for user in instance.users.all():
            user_data = {
                'id': user.id,
                'email': user.email,
                'status': user.status
            }
            users.append(user_data)
        representation['users'] = users

        # Add subscriptions
        subscriptions = []
        for subscription in instance.subscriptions.all():
            subscription_data = {
                'id': subscription.id,
                'module': subscription.module.name,
                'plan': subscription.plan.name,
                'status': subscription.status,
                'start_date': subscription.start_date,
                'end_date': subscription.end_date
            }
            subscriptions.append(subscription_data)
        representation['subscriptions'] = subscriptions

        return representation


class AddressSerializer(serializers.Serializer):
    address_line1 = serializers.CharField(max_length=255, required=False, allow_blank=True)
    address_line2 = serializers.CharField(max_length=255, required=False, allow_blank=True)
    address_line3 = serializers.CharField(max_length=255, required=False, allow_blank=True)
    pincode = serializers.IntegerField(required=False, allow_null=True)
    state = serializers.CharField(max_length=20, required=False, allow_blank=True)
    city = serializers.CharField(max_length=20, required=False, allow_blank=True)
    country = serializers.CharField(max_length=20, required=False)


class ModuleDetailSerializer(ModuleSerializer):
    """Detailed serializer for Module with nested relationships"""

    class Meta(ModuleSerializer.Meta):
        fields = ModuleSerializer.Meta.fields + ['subscriptions', 'permissions']

    def to_representation(self, instance):
        """Customize the representation to include nested data"""
        representation = super().to_representation(instance)

        # Add subscriptions
        subscriptions = []
        for subscription in instance.subscriptions.all():
            subscription_data = {
                'id': subscription.id,
                'context': subscription.context.name,
                'plan': subscription.plan.name,
                'status': subscription.status,
                'start_date': subscription.start_date,
                'end_date': subscription.end_date
            }
            subscriptions.append(subscription_data)
        representation['subscriptions'] = subscriptions

        # Add permissions
        permissions = []
        for permission in instance.permissions.all():
            permission_data = {
                'id': permission.id,
                'user_context_role': {
                    'id': permission.user_context_role.id,
                    'user': permission.user_context_role.user.email,
                    'context': permission.user_context_role.context.name,
                    'role': permission.user_context_role.role.name
                },
                'permissions': permission.permissions
            }
            permissions.append(permission_data)
        representation['permissions'] = permissions

        return representation


class RoleDetailSerializer(RoleSerializer):
    """Detailed serializer for Role with nested relationships"""

    class Meta(RoleSerializer.Meta):
        fields = RoleSerializer.Meta.fields + ['user_context_roles']

    def to_representation(self, instance):
        """Customize the representation to include nested data"""
        representation = super().to_representation(instance)

        # Add user context roles
        user_context_roles = []
        for user_context_role in instance.user_context_roles.all():
            user_context_role_data = {
                'id': user_context_role.id,
                'user': user_context_role.user.email,
                'context': user_context_role.context.name,
                'created_at': user_context_role.created_at
            }
            user_context_roles.append(user_context_role_data)
        representation['user_context_roles'] = user_context_roles

        return representation


class ModuleFeatureSerializer(serializers.ModelSerializer):
    module_name = serializers.CharField(source='module.name', read_only=True)

    class Meta:
        model = ModuleFeature
        fields = ['id', 'module', 'module_name', 'service', 'action', 'label']
        read_only_fields = ['id']

    def validate(self, data):
        # Validate that the action is one of the allowed values
        allowed_actions = [
            'create', 'read', 'update', 'delete', 'approve',
            'send', 'print', 'export', 'cancel', 'void', 'reconcile', 'generate_report'
        ]
        if data['action'] not in allowed_actions:
            raise serializers.ValidationError({
                'action': f'Action must be one of: {", ".join(allowed_actions)}'
            })
        return data


class UserFeaturePermissionSerializer(serializers.ModelSerializer):
    user_context_role_name = serializers.CharField(source='user_context_role.role.name', read_only=True)
    module_name = serializers.CharField(source='module.name', read_only=True)

    class Meta:
        model = UserFeaturePermission
        fields = ['id', 'user_context_role', 'user_context_role_name', 'module', 'module_name', 'actions']
        read_only_fields = ['id']


class UserActivationSerializer(serializers.Serializer):
    token = serializers.CharField()


class LogoSerializer(serializers.ModelSerializer):
    logo = serializers.FileField(allow_null=True, required=False)

    class Meta:
        model = BusinessLogo
        fields = '__all__'

    def create(self, validated_data):
        """
        Create and return a new `Business` instance, given the validated data.
        """
        instance = self.Meta.model(**validated_data)
        instance.save()
        return instance

    def update(self, instance, validated_data):
        """
        Update and return an existing `Business` instance, given the validated data.
        """
        [setattr(instance, k, v) for k, v in validated_data.items()]
        instance.save()
        return instance


class BusinessSerializer(serializers.ModelSerializer):
    entityType = serializers.CharField(max_length=50, required=False)
    pan = serializers.CharField(max_length=15, required=False, default=None)
    headOffice = serializers.JSONField(default=dict)
    logos = LogoSerializer(read_only=True)

    class Meta:
        model = Business
        fields = '__all__'

    def create(self, validated_data):
        """
        Create and return a new `Business` instance, given the validated data.
        """
        instance = self.Meta.model(**validated_data)
        instance.save()
        return instance

    def update(self, instance, validated_data):
        """
        Update and return an existing `Business` instance, given the validated data.
        """
        [setattr(instance, k, v) for k, v in validated_data.items()]
        instance.save()
        return instance


class GSTDetailsSerializer(serializers.ModelSerializer):
    gst_document = serializers.FileField(allow_null=True, required=False)
    lut_letter = serializers.FileField(allow_null=True, required=False)
    valid_date = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    class Meta:
        model = GSTDetails
        fields = '__all__'

    def create(self, validated_data):
        """
        Create and return a new `Business` instance, given the validated data.
        """
        instance = self.Meta.model(**validated_data)
        instance.save()
        return instance

    def update(self, instance, validated_data):
        """
        Update and return an existing `Business` instance, given the validated data.
        """
        [setattr(instance, k, v) for k, v in validated_data.items()]
        instance.save()
        return instance

    def get_financial_year_end_date(self, dob):
        """Helper method to calculate March 31st of the financial year based on DOB."""
        if dob:
            year = dob.year
            month = dob.month
            financial_year = year + 1 if month >= 4 else year
            return date(financial_year, 3, 31)
        return None

    def get_valid_date(self, obj):
        fy_end_date = self.get_financial_year_end_date(obj.dob)
        return fy_end_date.strftime("%d-%m-%Y") if fy_end_date else None

    def get_status(self, obj):
        fy_end_date = self.get_financial_year_end_date(obj.dob)
        if fy_end_date:
            return "active" if fy_end_date > date.today() else "expired"
        return None



class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = '__all__'


class TDSDetailsSerializer(serializers.ModelSerializer):
    authorized_personal_Details = serializers.JSONField(required=False, allow_null=True)
    income_tax_details = serializers.JSONField(required=False, allow_null=True)

    class Meta:
        model = TDSDetails
        fields = '__all__'

    def create(self, validated_data):
        """
        Create and return a new `TDSDetails` instance, given the validated data.
        """
        instance = self.Meta.model(**validated_data)
        instance.save()
        return instance

    def update(self, instance, validated_data):
        """
        Update and return an existing `TDSDetails` instance, given the validated data.
        """
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


class LicenseDetailsSerializer(serializers.ModelSerializer):
    """
    Serializer for LicenseDetails model for listing and creating operations.
    """

    class Meta:
        model = LicenseDetails
        fields = '__all__'

    def validate(self, data):
        """
        Validate the license details data.
        """
        # Check if date_of_expiry is after date_of_issue
        if data.get('date_of_issue') and data.get('date_of_expiry'):
            if data['date_of_expiry'] <= data['date_of_issue']:
                raise serializers.ValidationError("Expiry date must be after issue date")
        return data

    def create(self, validated_data):
        """
        Create a new LicenseDetails instance with proper handling of the license document.
        """
        try:
            # Create the license details instance
            license_details = LicenseDetails.objects.create(**validated_data)
            return license_details
        except Exception as e:
            raise serializers.ValidationError(f"Error creating license details: {str(e)}")

    def update(self, instance, validated_data):
        """
        Update an existing LicenseDetails instance.
        """
        try:
            # Update each field in the instance
            for attr, value in validated_data.items():
                setattr(instance, attr, value)

            # Save the updated instance
            instance.save()
            return instance
        except Exception as e:
            raise serializers.ValidationError(f"Error updating license details: {str(e)}")


class DSCDetailsSerializer(serializers.ModelSerializer):
    """
    Serializer for DSCDetails model for listing and creating operations.
    """

    class Meta:
        model = DSCDetails
        fields = '__all__'

    def validate(self, data):
        """
        Validate the DSC details data.
        """
        # Check if date_of_expiry is after date_of_issue
        if data.get('date_of_issue') and data.get('date_of_expiry'):
            if data['date_of_expiry'] <= data['date_of_issue']:
                raise serializers.ValidationError("Expiry date must be after issue date")

        return data

    def create(self, validated_data):
        """
        Create a new DSCDetails instance.
        """
        try:
            dsc_details = DSCDetails.objects.create(**validated_data)
            return dsc_details
        except Exception as e:
            raise serializers.ValidationError(f"Error creating DSC details: {str(e)}")

    def update(self, instance, validated_data):
        """
        Update an existing DSCDetails instance.
        """
        try:
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()
            return instance
        except Exception as e:
            raise serializers.ValidationError(f"Error updating DSC details: {str(e)}")


class BankDetailsSerializer(serializers.ModelSerializer):
    """
    Serializer for BankDetails model for listing and creating operations.
    """

    class Meta:
        model = BankDetails
        fields = '__all__'

    def validate(self, data):
        """
        Validate the bank details data.
        """
        # Validate IFSC code format (11 characters, alphanumeric)
        if data.get('ifsc_code'):
            if not re.match(r'^[A-Z]{4}0[A-Z0-9]{6}$', data['ifsc_code']):
                raise serializers.ValidationError("Invalid IFSC code format")

        # Validate SWIFT code format (8 or 11 characters, alphanumeric)
        if data.get('swift_code'):
            if not re.match(r'^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$', data['swift_code']):
                raise serializers.ValidationError("Invalid SWIFT code format")

        # Validate account number (numeric, 9-18 digits)
        if data.get('account_number'):
            if not re.match(r'^\d{9,18}$', data['account_number']):
                raise serializers.ValidationError("Invalid account number format")

        return data

    def create(self, validated_data):
        """
        Create a new BankDetails instance.
        """
        try:
            bank_details = BankDetails.objects.create(**validated_data)
            return bank_details
        except Exception as e:
            raise serializers.ValidationError(f"Error creating bank details: {str(e)}")

    def update(self, instance, validated_data):
        """
        Update an existing BankDetails instance.
        """
        try:
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()
            return instance
        except Exception as e:
            raise serializers.ValidationError(f"Error updating bank details: {str(e)}")


class KeyManagerialPersonnelSerializer(serializers.ModelSerializer):
    """
    Serializer for KeyManagerialPersonnel model for listing and creating operations.
    """

    class Meta:
        model = KeyManagerialPersonnel
        fields = '__all__'

    def validate(self, data):
        """
        Validate the KMP details data.
        """
        # Validate PAN number format if provided
        if data.get('pan_number'):
            if not re.match(r'^[A-Z]{5}[0-9]{4}[A-Z]{1}$', data['pan_number']):
                raise serializers.ValidationError("Invalid PAN number format")

        # Validate status if provided
        if data.get('status'):
            allowed_statuses = ['active', 'inactive', 'resigned']
            if data['status'] not in allowed_statuses:
                raise serializers.ValidationError(f"Status must be one of: {', '.join(allowed_statuses)}")

        return data

    def create(self, validated_data):
        """
        Create a new KeyManagerialPersonnel instance.
        """
        try:
            kmp = KeyManagerialPersonnel.objects.create(**validated_data)
            return kmp
        except Exception as e:
            raise serializers.ValidationError(f"Error creating KMP details: {str(e)}")

    def update(self, instance, validated_data):
        """
        Update an existing KeyManagerialPersonnel instance.
        """
        try:
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()
            return instance
        except Exception as e:
            raise serializers.ValidationError(f"Error updating KMP details: {str(e)}")

class BusinessUserSerializer(serializers.ModelSerializer):
    entityType = serializers.CharField(max_length=50, required=False)
    pan = serializers.CharField(max_length=15, required=True)
    headOffice = serializers.JSONField(default=dict)
    gst_details = GSTDetailsSerializer(many=True, read_only=True)
    branches = BranchSerializer(many=True, read_only=True)

    class Meta:
        model = Business
        fields = '__all__'


class UserBusinessRetrieveSerializer(serializers.ModelSerializer):

    class Meta:
        model = Business
        fields = ['id', 'nameOfBusiness', 'entityType', 'client']


class BusinessWithGSTSerializer(serializers.ModelSerializer):
    gst_details = GSTDetailsSerializer(many=True, read_only=True)
    headOffice = serializers.JSONField(default=dict)

    class Meta:
        model = Business
        fields = ['id', 'nameOfBusiness', 'entityType', 'registrationNumber', 'pan', 'mobile_number', 'legal_name',
                  'email', 'dob_or_incorp_date', 'gst_details', 'headOffice', 'headOffice', 'business_nature']


class UserBusinessSerializer(serializers.ModelSerializer):
    date_joined = serializers.SerializerMethodField()
    business = serializers.SerializerMethodField()

    class Meta:
        model = Users
        fields = [
            'id', 'user_name', 'email', 'mobile_number',
            'first_name', 'last_name', 'user_type',
            'is_active', 'date_joined', 'business'
        ]

    def get_date_joined(self, obj):
        return obj.date_joined.strftime('%d-%m-%Y')  # Format as dd-mm-yyyy

    def get_business(self, obj):
        # Fetch related Business objects
        businesses = obj.business_clients_id.all()
        return BusinessWithGSTSerializer(businesses, many=True).data


class UsersKYCSerializer(serializers.ModelSerializer):
    address = AddressSerializer(required=True)

    class Meta:
        model = UserKYC
        fields = [
            'id', 'user', 'pan_number', 'aadhaar_number', 'date',
            'icai_number', 'address', 'name', 'have_firm'
        ]
        read_only_fields = ['user']

    def validate(self, data):
        have_firm = data.get('have_firm', False)
        icai_number = data.get('icai_number')

        # Enforce ICAI number if the user has a firm
        if have_firm and not icai_number:
            raise serializers.ValidationError({
                "icai_number": "ICAI Number is required when 'have_firm' is true."
            })

        # Prevent ICAI number if user has no firm
        if not have_firm and icai_number:
            raise serializers.ValidationError({
                "icai_number": "ICAI Number must not be provided when 'have_firm' is false."
            })

        return data

    def create(self, validated_data):
        address_data = validated_data.pop('address', {})
        user = self.context['request'].user
        return UserKYC.objects.create(address=address_data, **validated_data)


    def update(self, instance, validated_data):
        address_data = validated_data.pop('address', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if address_data is not None:
            instance.address = address_data

        instance.save()
        return instance


class FirmKYCSerializer(serializers.ModelSerializer):
    address = AddressSerializer(required=False)

    class Meta:
        model = FirmKYC
        fields = [
            'user', 'firm_name', 'firm_registration_number', 'firm_email', 'firm_mobile_number',
            'number_of_firm_partners', 'address'
        ]
        read_only_fields = ['user']

    def create(self, validated_data):
        """
        Create a new `UserKYC` instance.
        """
        # Check if 'address' is present in validated_data
        if 'address' not in validated_data:
            # If not present, set default address values
            validated_data['address'] = {
                "address_line1": None,
                "address_line2": None,
                "address_line3": None,
                "pincode": None,
                "state": None,
                "city": None,
                "country": None
            }

        # Create and save the UserKYC instance
        user_details = FirmKYC.objects.create(**validated_data)

        return user_details


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Users
        fields = ['user_name', 'email', 'mobile_number', 'user_type', 'first_name', 'last_name', 'is_active']
        # You can modify this list based on the fields you want to allow updating

    def update(self, instance, validated_data):
        # Perform the actual update for the instance
        return super().update(instance, validated_data)


class ServicesMasterDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServicesMasterData
        fields = '__all__'


class ServiceDetailsSerializer(serializers.ModelSerializer):
    service_type = serializers.PrimaryKeyRelatedField(queryset=ServicesMasterData.objects.all())
    visa_application = serializers.PrimaryKeyRelatedField(queryset=VisaApplications.objects.all(), required=True)  # Include this line
    service_name = serializers.ReadOnlyField(source='service_type.service_name')
    last_updated_date = serializers.SerializerMethodField()

    class Meta:
        model = ServiceDetails
        fields = ['id', 'service_type', 'service_name', 'date', 'status', 'comments', 'quantity',
                  'visa_application', 'last_updated_date']  # Ensure service_name is included

    def get_last_updated_date(self, obj):
        if obj.last_updated:
            # Get only the date part from the datetime field
            return obj.last_updated.date()
        return None


class VisaApplicationsSerializer(serializers.ModelSerializer):
    # services = ServiceDetailsSerializer(many=True)

    class Meta:
        model = VisaApplications
        fields = "__all__"


class IndividualServiceDetailsSerializer(serializers.ModelSerializer):
    service_type = serializers.PrimaryKeyRelatedField(queryset=ServicesMasterData.objects.all())
    visa_application = serializers.PrimaryKeyRelatedField(queryset=VisaApplications.objects.all(), required=True)  # Include this line
    service_name = serializers.ReadOnlyField(source='service_type.service_name')
    last_updated_date = serializers.SerializerMethodField()

    class Meta:
        model = ServiceDetails
        fields = ['id', 'service_type', 'service_name', 'date', 'status', 'comments', 'quantity',
                  'visa_application', 'last_updated_date']  # Ensure service_name is included

    def get_last_updated_date(self, obj):
        if obj.last_updated:
            # Get only the date part from the datetime field
            return obj.last_updated.date()
        return None


class VisaApplicationsGetSerializer(serializers.ModelSerializer):
    services = IndividualServiceDetailsSerializer(many=True)
    email = serializers.SerializerMethodField()
    mobile_number = serializers.SerializerMethodField()

    class Meta:
        model = VisaApplications
        fields = "__all__"

    def get_email(self, obj):
        # Assuming the related User model has the email field
        return obj.user.email if obj.user else None

    def get_mobile_number(self, obj):
        # Assuming the related User model has the mobile_number field
        return obj.user.mobile_number if obj.user else None

class VisaClientUserListSerializer(serializers.ModelSerializer):
    services = ServiceDetailsSerializer(many=True)
    email = serializers.SerializerMethodField()
    mobile_number = serializers.SerializerMethodField()
    first_name = serializers.SerializerMethodField()
    last_name = serializers.SerializerMethodField()
    user = serializers.SerializerMethodField()

    class Meta:
        model = VisaApplications
        fields = "__all__"  # Ensure this includes any fields from `VisaApplications` needed

    def get_email(self, obj):
        # Assuming the related User model has the email field
        return obj.user.email if obj.user else None

    def get_mobile_number(self, obj):
        # Assuming the related User model has the mobile_number field
        return obj.user.mobile_number if obj.user else None

    def get_first_name(self, obj):
        # Assuming the related User model has the email field
        return obj.user.first_name if obj.user else None

    def get_last_name(self, obj):
        # Assuming the related User model has the mobile_number field
        return obj.user.last_name if obj.user else None

    def get_user(self, obj):
        # Assuming the related User model has the mobile_number field
        return obj.user.id if obj.user else None


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = "__all__"

    def validate_email(self, value):
        """ Ensure only one request per email per day """
        today = now().date()  # Get today's date
        if Contact.objects.filter(email=value, created_date=today).exists():
            raise serializers.ValidationError("You can only submit one request per day.")
        return value


class ConsultationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Consultation
        fields = "__all__"

    def validate_time(self, value):
        """ Ensure time is stored in HH:MM format only (remove seconds) """
        return value.replace(second=0)

    def validate(self, data):
        """ Prevent duplicate bookings for the same date, time slot, and email """
        email = data.get("email")
        date = data.get("date")
        time = data.get("time")

        # Check if the same email has already booked this slot
        if Consultation.objects.filter(email=email, date=date, time=time).exists():
            raise serializers.ValidationError(
                {"time": "This time slot is already booked. Please select a different slot."}
            )

        return data


class ContextRoleSerializer(serializers.ModelSerializer):
    """Serializer for listing roles with user count in a context"""
    user_count = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = ['id', 'name', 'role_type', 'description', 'is_system_role', 'is_default_role', 'user_count']

    def get_user_count(self, obj):
        """Get the count of users with this role in the context"""
        context = self.context.get('context')
        if not context:
            return 0

        return UserContextRole.objects.filter(
            context=context,
            role=obj,
            status='active'
        ).count()


class ContextWithRolesSerializer(serializers.ModelSerializer):
    """Serializer for context with its roles"""
    roles = ContextRoleSerializer(many=True, read_only=True)

    class Meta:
        model = Context
        fields = ['id', 'name', 'context_type', 'roles']


class ServicePaymentInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServicePaymentInfo
        fields = '__all__'


class PaymentInfoSerializer(serializers.ModelSerializer):
    plan_name = serializers.SerializerMethodField()
    suite_name = serializers.SerializerMethodField()

    class Meta:
        model = PaymentInfo
        fields = [
            'id',
            'razorpay_order_id',
            'razorpay_payment_id',
            'amount',
            'currency',
            'status',
            'payment_method',
            'card_last4',
            'payment_captured',
            'plan_name',
            'suite_name',
            'created_at'
        ]

    def get_plan_name(self, obj):
        return obj.plan.name if obj.plan else None

    def get_suite_name(self, obj):
        return obj.suite_subscription.name if obj.suite_subscription else None