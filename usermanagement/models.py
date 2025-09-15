from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models
from django.utils import timezone
from django.conf import settings
from dateutil.relativedelta import relativedelta
from Tara.settings.default import *
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from cryptography.fernet import Fernet
from django.contrib.postgres.fields import ArrayField
from django.db.models import JSONField
from .helpers import *
from django.core.validators import RegexValidator
from decimal import Decimal, InvalidOperation
from decimal import Decimal, ROUND_HALF_UP
from storages.backends.s3boto3 import S3Boto3Storage
from Tara.settings.default import AWS_PRIVATE_BUCKET_NAME


class PrivateS3Storage(S3Boto3Storage):
    bucket_name = AWS_PRIVATE_BUCKET_NAME
    custom_domain = f"{AWS_PRIVATE_BUCKET_NAME}.s3.amazonaws.com"  # Default S3 domain or your custom domain
    file_overwrite = True  # Allow file overwrite (optional)

YES_NO_CHOICES = [
        ('yes', 'Yes'),
        ('no', 'No'),
        ('na', 'NA'),
    ]

KEY = b'zSwtDDLJp6Qkb9CMCJnVeOzAeSJv-bA3VYNCy5zM-b4='  # Fernet key
cipher = Fernet(KEY)


class PendingUserOTP(models.Model):
    email = models.EmailField(unique=True)
    otp_code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def is_expired(self):
        return timezone.now() > self.expires_at


class EncryptedField(models.TextField):  # Inherit from TextField to map to varchar/text
    description = "Field that encrypts/decrypts data"

    def get_prep_value(self, value):
        if value is None:
            return None
        try:
            return cipher.encrypt(value.encode()).decode()
        except Exception as e:
            print(f"[Encryption Error] {str(e)}")
            return None

    def from_db_value(self, value, expression, connection):
        if value is None:
            return None
        try:
            return cipher.decrypt(value.encode()).decode()
        except Exception as e:
            print(f"[Decryption Error] {str(e)}")
            return None

    def to_python(self, value):
        """Decrypt for forms/admin/etc"""
        if value is None:
            return None
        try:
            return cipher.decrypt(value.encode()).decode()
        except Exception:
            return value  # already decrypted (e.g. admin form)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        # Include any special arguments here
        return name, path, args, kwargs


class CustomAccountManager(BaseUserManager):
    def create_user(self, email=None, password=None,
                    created_by=None, **extra_fields):

        # Ensure a username is provided and is unique
        if not email:
            raise ValueError("Username must be provided.")
        if self.model.objects.filter(email=email).exists():
            raise ValueError("A user with this email already exists.")

        # Normalize email if provided
        email = self.normalize_email(email) if email else None

        # Create user instance
        user = self.model(
            email=email,
            created_by=created_by,
            **extra_fields
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email=None, password=None, **extra_fields):
        # Ensure required fields for superuser
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_staff', True)
        return self.create_user(email=email, password=password, **extra_fields)


class Context(models.Model):
    name = models.CharField(max_length=255)
    context_type = models.CharField(
        max_length=20,
        choices=[('personal', 'Personal'), ('business', 'Business')]
    )
    owner_user = models.ForeignKey(
        'Users',
        on_delete=models.CASCADE,
        related_name='owned_contexts'
    )
    business = models.OneToOneField(
        'Business',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='contexts'
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Active'),
            ('suspended', 'Suspended'),
            ('archived', 'Archived')
        ],
        default='active'
    )
    profile_status = models.CharField(
        max_length=40,
        choices=[
            ('incomplete', 'Incomplete'),
            ('pending_business_details', 'Pending Business Details'),
            ('complete', 'Complete')
        ],
        default='incomplete'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    metadata = models.JSONField(default=dict, blank=True)
    is_platform_context = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} - {self.context_type}"

    def clean(self):
        if self.context_type == 'business':
            if not self.business and self.profile_status != 'pending_business_details':
                raise ValidationError({
                    'business': 'Business context must be associated with a Business record or '
                                'be in pending_business_details status.'
                })
        elif self.context_type == 'personal' and self.business:
            raise ValidationError({
                'business': 'Personal context cannot be associated with a Business record.'
            })

    def validate_profile_completion(self):
        if self.context_type == 'business':
            if self.business and self._is_business_complete():
                self.profile_status = 'complete'
            else:
                self.profile_status = 'pending_business_details'
        elif self.context_type == 'personal':
            if hasattr(self.owner_user, 'userkyc') and self.owner_user.userkyc.is_completed:
                self.profile_status = 'complete'
            else:
                self.profile_status = 'incomplete'

    def _is_business_complete(self):
        required_fields = [
            'nameOfBusiness',
            'registrationNumber',
            'entityType',
            'pan',
            'business_nature',
            'legal_name',
            'mobile_number',
            'email',
            'dob_or_incorp_date',
            'headOffice'
        ]
        for field in required_fields:
            value = getattr(self.business, field, None)
            if not value:
                return False
        return True

    def save(self, *args, **kwargs):
        if self.context_type == 'business' and self.pk is None:
            self.profile_status = 'pending_business_details'

        self.validate_profile_completion()
        self.full_clean()
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if is_new:
            self.create_default_roles()

    def create_default_roles(self):
        if self.context_type == 'personal':
            Role.objects.get_or_create(
                name="Owner",
                context=self,
                context_type='personal',
                role_type='owner',
                defaults={
                    "description": "Personal account owner with full access",
                    "is_system_role": True,
                    "is_default_role": True
                }
            )
        else:
            business_roles = [
                {
                    "name": "Owner",
                    "role_type": "owner",
                    "description": "Business owner with full access to all features"
                },
                {
                    "name": "Administrator",
                    "role_type": "admin",
                    "description": "Business administrator with full access to all modules"
                },
                {
                    "name": "Manager",
                    "role_type": "manager",
                    "description": "Business manager with elevated permissions"
                },
                {
                    "name": "Employee",
                    "role_type": "employee",
                    "description": "Regular employee with basic access"
                }
            ]
            for role_data in business_roles:
                Role.objects.get_or_create(
                    name=role_data["name"],
                    context=self,
                    context_type='business',
                    role_type=role_data["role_type"],
                    defaults={
                        "description": role_data["description"],
                        "is_system_role": True,
                        "is_default_role": True
                    }
                )

    def get_business_details(self):
        if self.context_type == 'business':
            if self.business:
                return {
                    'name': self.business.nameOfBusiness,
                    'registration_number': self.business.registrationNumber,
                    'entity_type': self.business.entityType,
                    'pan': self.business.pan,
                    'business_nature': self.business.business_nature,
                    'legal_name': self.business.legal_name,
                    'mobile_number': self.business.mobile_number,
                    'email': self.business.email,
                    'dob_or_incorp_date': self.business.dob_or_incorp_date,
                    'head_office': self.business.headOffice,
                    'profile_status': self.profile_status
                }
            else:
                return {
                    'profile_status': self.profile_status,
                    'message': 'Business details pending'
                }
        return None


class Users(AbstractBaseUser):
    """
    Users Model - Authentication Only
    =================================
    
    This model now only handles authentication and core user management.
    Personal information, session data, and registration tracking have been
    moved to separate focused models:
    
    - UserProfile: first_name, last_name, mobile_number
    - UserSession: active_context, session management
    - UserRegistration: registration_flow, initial_selection, registration_completed
    """
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(
        max_length=10,
        choices=[
            ('active', 'Active'),
            ('inactive', 'Inactive'),
            ('invited', 'Invited')
        ],
        default='active'
    )
    service_request = models.CharField(max_length=40, null=True, blank=True, default=None)
    created_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_users'
    )
    is_active = models.BooleanField(default=False, help_text="Indicates if the user account is active")
    is_super_admin = models.BooleanField(default=False, editable=False)
    
    # REMOVED FIELDS (now handled by separate models):
    # - mobile_number → UserProfile.mobile_number
    # - active_context → UserSession.active_context
    # - registration_flow → UserRegistration.registration_flow
    # - initial_selection → UserRegistration.initial_selection
    # - registration_completed → UserRegistration.registration_completed
    # - first_name → UserProfile.first_name
    # - last_name → UserProfile.last_name

    objects = CustomAccountManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.email

    # =============================================================================
    # BACKWARD COMPATIBILITY PROPERTIES - ACCESS NEW MODELS THROUGH OLD FIELD NAMES
    # =============================================================================

    @property
    def first_name(self):
        """Backward compatibility: Access first_name from UserProfile"""
        try:
            return self.userprofile.first_name
        except UserProfile.DoesNotExist:
            return None

    @property
    def last_name(self):
        """Backward compatibility: Access last_name from UserProfile"""
        try:
            return self.userprofile.last_name
        except UserProfile.DoesNotExist:
            return None
    
    @property
    def mobile_number(self):
        """Backward compatibility: Access mobile_number from UserProfile"""
        try:
            return self.userprofile.mobile_number
        except UserProfile.DoesNotExist:
            return None

    @property
    def active_context(self):
        """Backward compatibility: Access active_context from default UserSession"""
        try:
            # First try to get from default session
            default_session = self.get_default_session()
            if default_session:
                return default_session.active_context
            
            # Fallback to active session if no default session
            active_session = self.usersessions.filter(is_active=True).first()
            return active_session.active_context if active_session else None
        except UserSession.DoesNotExist:
            return None

    @property
    def registration_completed(self):
        """Backward compatibility: Access registration_completed from UserRegistration"""
        try:
            return self.userregistration.registration_completed
        except UserRegistration.DoesNotExist:
            return False

    @property
    def registration_flow(self):
        """Backward compatibility: Access registration_flow from UserRegistration"""
        try:
            return self.userregistration.registration_flow
        except UserRegistration.DoesNotExist:
            return None

    @property
    def initial_selection(self):
        """Backward compatibility: Access initial_selection from UserRegistration"""
        try:
            return self.userregistration.initial_selection
        except UserRegistration.DoesNotExist:
            return None
    
    # =============================================================================
    # CONVENIENCE METHODS FOR NEW MODELS
    # =============================================================================
    
    def get_profile(self):
        """Get or create UserProfile for this user"""
        profile, created = UserProfile.objects.get_or_create(
            user=self,
            defaults={'first_name': None, 'last_name': None, 'mobile_number': None}
        )
        return profile
    
    def get_registration(self):
        """Get or create UserRegistration for this user"""
        registration, created = UserRegistration.objects.get_or_create(
            user=self,
            defaults={
                'registration_flow': None,
                'initial_selection': None,
                'registration_completed': False,
                'registration_status': 'incomplete',
                'steps_completed': [],
                'last_step_completed': None
            }
        )
        return registration
    
    def get_active_session(self):
        """Get or create active UserSession for this user"""
        session, created = UserSession.objects.get_or_create(
            user=self,
            is_active=True,
            defaults={'active_context': None, 'session_data': {}}
        )
        return session
    
    def get_default_session(self):
        """Get the default session for this user"""
        try:
            return self.usersessions.filter(default_session=True).first()
        except UserSession.DoesNotExist:
            return None
    
    def set_default_session(self, session):
        """Set a session as the default (unset others)"""
        # Unset all other default sessions
        self.usersessions.filter(default_session=True).update(default_session=False)
        # Set this session as default
        session.default_session = True
        session.save()
        return session
    
    def set_active_context(self, context):
        """Set active context for this user"""
        session = self.get_active_session()
        session.active_context = context
        session.save()
        return session


# =============================================================================
# NEW FOCUSED MODELS - DIVIDED FROM USERS MODEL
# =============================================================================

class UserProfile(models.Model):
    """
    UserProfile: Handles personal information
    Moved from Users model: first_name, last_name, mobile_number
    """
    user = models.OneToOneField(
        Users, 
        on_delete=models.CASCADE, 
        related_name='userprofile'
    )
    first_name = models.CharField(max_length=40, null=True, blank=True, default=None)
    last_name = models.CharField(max_length=40, null=True, blank=True, default=None)
    mobile_number = models.CharField(max_length=15, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.user.email}"

    @property
    def full_name(self):
        """Return full name combining first and last name"""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        elif self.first_name:
            return self.first_name
        elif self.last_name:
            return self.last_name
        return ""


class UserSession(models.Model):
    """
    UserSession: Handles active context and session management
    Moved from Users model: active_context
    """
    user = models.ForeignKey(
        Users, 
        on_delete=models.CASCADE, 
        related_name='usersessions'
    )
    active_context = models.ForeignKey(
        Context,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='active_sessions'
    )
    is_active = models.BooleanField(default=True, help_text="Indicates if this is the current active session")
    default_session = models.BooleanField(default=False, help_text="Indicates if this is the default session for the user")
    session_data = models.JSONField(default=dict, blank=True, help_text="Additional session-specific data")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Ensure only one active session per user and only one default session per user
        constraints = [
            models.UniqueConstraint(
                fields=['user'], 
                condition=models.Q(is_active=True),
                name='unique_active_session_per_user'
            ),
            models.UniqueConstraint(
                fields=['user'], 
                condition=models.Q(default_session=True),
                name='unique_default_session_per_user'
            )
        ]

    def __str__(self):
        context_name = self.active_context.name if self.active_context else "No Context"
        return f"{self.user.email} - {context_name} (Active: {self.is_active}, Default: {self.default_session})"

    def save(self, *args, **kwargs):
        # If setting this session as active, deactivate all other sessions for this user
        if self.is_active:
            UserSession.objects.filter(user=self.user, is_active=True).exclude(pk=self.pk).update(is_active=False)
        
        # If setting this session as default, unset all other default sessions for this user
        if self.default_session:
            UserSession.objects.filter(user=self.user, default_session=True).exclude(pk=self.pk).update(default_session=False)
        
        super().save(*args, **kwargs)


class UserRegistration(models.Model):
    """
    UserRegistration: Handles registration status and flow tracking
    Moved from Users model: registration_flow, initial_selection, registration_completed
    """
    REGISTRATION_STATUS_CHOICES = [
        ('incomplete', 'Incomplete'),
        ('pending_verification', 'Pending Verification'),
        ('completed', 'Completed'),
        ('onboarded', 'Onboarded')
    ]
    
    user = models.OneToOneField(
        Users, 
        on_delete=models.CASCADE, 
        related_name='userregistration'
    )
    
    # Moved from Users model
    registration_flow = models.CharField(
        max_length=20,
        choices=[
            ('module', 'Module-based'),
            ('service', 'Service-based'),
            ('standard', 'Standard')
        ],
        null=True,
        blank=True,
        help_text="Tracks which registration flow the user started from"
    )
    initial_selection = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="The initial module or service the user selected during registration"
    )
    registration_completed = models.BooleanField(
        default=False,
        help_text="Indicates if the user has completed the registration process"
    )
    
    # New fields for better tracking
    registration_status = models.CharField(
        max_length=30,
        choices=REGISTRATION_STATUS_CHOICES,
        default='incomplete',
        help_text="Current status of the registration process"
    )
    steps_completed = models.JSONField(
        default=list, 
        blank=True,
        help_text="List of registration steps completed (e.g., ['email_verified', 'profile_created'])"
    )
    last_step_completed = models.CharField(
        max_length=50, 
        null=True, 
        blank=True,
        help_text="Last registration step completed"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email} - {self.registration_status}"
    
    def mark_step_completed(self, step_name):
        """Mark a registration step as completed"""
        if step_name not in self.steps_completed:
            self.steps_completed.append(step_name)
            self.last_step_completed = step_name
        self.save()
        
    def is_step_completed(self, step_name):
        """Check if a registration step is completed"""
        return step_name in self.steps_completed
    
    def get_registration_progress(self):
        """Get registration progress percentage"""
        total_steps = ['email_verified', 'profile_created', 'context_created', 'kyc_completed']
        completed_steps = len([step for step in total_steps if step in self.steps_completed])
        return (completed_steps / len(total_steps)) * 100


# =============================================================================
# SIGNALS TO AUTOMATICALLY CREATE NEW MODELS
# =============================================================================

@receiver(post_save, sender=Users)
def create_user_related_models(sender, instance, created, **kwargs):
    """
    Automatically create UserProfile, UserSession, and UserRegistration when a new User is created
    """
    if created:
        # Create UserProfile
        UserProfile.objects.get_or_create(
            user=instance,
            defaults={
                'first_name': None,
                'last_name': None,
                'mobile_number': None
            }
        )
        
        # Create UserRegistration
        UserRegistration.objects.get_or_create(
            user=instance,
            defaults={
                'registration_flow': None,
                'initial_selection': None,
                'registration_completed': False,
                'registration_status': 'incomplete',
                'steps_completed': [],
                'last_step_completed': None
            }
        )
        
        # Create default UserSession
        user_session, created = UserSession.objects.get_or_create(
            user=instance,
            is_active=True,
            defaults={
                'active_context': None,
                'default_session': True,  # Set as default session
                'session_data': {}
            }
        )
        
        # If session already existed, make sure it's the default
        if not created and not user_session.default_session:
            user_session.default_session = True
            user_session.save()


class Module(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    category = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Optional category label. You can define choices later."
    )
    context_type = models.CharField(
        max_length=20,
        choices=[
            ('personal', 'Personal'),
            ('business', 'Business')
        ]
    )

    # Replace BooleanField with CharField
    is_active = models.BooleanField(default=False, help_text="Indicates if the module is active")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Service(models.Model):  # Use singular 'Service'
    name = models.CharField(max_length=255)
    group_key = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    type = models.CharField(max_length=30, null=True, blank=True)
    is_active = models.BooleanField(default=False, help_text="Indicates if the service is active")
    label = models.CharField(max_length=100, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class ServicePlan(models.Model):
    PLAN_TYPE_CHOICES = [
        ('fixed', 'Fixed'),
        ('range', 'Range'),
        ('custom', 'Custom Quote'),
        ('success_based', 'Success Based'),
    ]

    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='plans')
    name = models.CharField(max_length=100)
    plan_type = models.CharField(max_length=20, choices=PLAN_TYPE_CHOICES)
    description = models.TextField(null=True, blank=True)
    amount = models.FloatField(null=True, blank=True)         # For fixed price
    min_amount = models.FloatField(null=True, blank=True)      # For range price
    max_amount = models.FloatField(null=True, blank=True)      # For range price
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.service.name} - {self.name}"

    def display_price(self):
        if self.plan_type == 'fixed' and self.amount is not None:
            return f"₹{self.amount}"
        elif self.plan_type == 'range' and self.min_amount is not None and self.max_amount is not None:
            return f"₹{self.min_amount}–₹{self.max_amount}"
        elif self.plan_type == 'custom':
            return "Custom Quote"
        elif self.plan_type == 'success_based':
            return "Success-Based"
        return "Contact for Pricing"


class ServiceRequest(models.Model):
    SERVICE_STATUS_CHOICES = [
        ('initiated', 'Initiated'),
        ('payment_pending', 'Payment Pending'),
        ('paid', 'Paid'),
        ('documents_pending', 'Documents Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
    ]
    PRIORITY_STATUS_CHOICES = [
        ('critical', 'Critical'),
        ('medium', 'Medium'),
        ('low', 'Low'),
        ('high', 'High'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    service = models.ForeignKey(Service, on_delete=models.CASCADE)  # ✅ actual field
    plan = models.ForeignKey('ServicePlan', on_delete=models.SET_NULL, null=True, blank=True)
    context = models.ForeignKey('Context', null=True, blank=True, on_delete=models.SET_NULL)

    status = models.CharField(max_length=20, choices=SERVICE_STATUS_CHOICES, default='initiated')
    payment_order_id = models.CharField(max_length=100, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    assignee = models.ForeignKey(Users, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='service_request_assignee', default=None)
    reviewer = models.ForeignKey(Users, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='service_request_reviewer', default=None)
    due_date = models.DateField(default=None, null=True)
    priority = models.CharField(max_length=20, choices=PRIORITY_STATUS_CHOICES, default='low')

    def is_personal(self):
        return self.context is None

    def __str__(self):
        return f"{self.user.email} - {self.service.name if self.service else 'No Service'}"


class ServicePaymentInfo(models.Model):
    PAYMENT_STATUS = [
        ('initiated', 'Initiated'),
        ('captured', 'Captured'),
        ('failed', 'Failed'),
    ]

    user = models.ForeignKey(Users, on_delete=models.CASCADE)
    context = models.ForeignKey(Context, on_delete=models.CASCADE)
    service_request = models.ForeignKey('ServiceRequest', on_delete=models.CASCADE)
    plan = models.ForeignKey('ServicePlan', on_delete=models.CASCADE, null=True, blank=True)

    razorpay_order_id = models.CharField(max_length=100)
    razorpay_payment_id = models.CharField(max_length=100, null=True, blank=True)
    amount = models.FloatField()
    currency = models.CharField(max_length=10, default='INR')

    status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='initiated')
    method = models.CharField(max_length=50, null=True, blank=True)
    captured = models.BooleanField(default=False, help_text="Indicates if the payment has been captured")
    failure_reason = models.TextField(null=True, blank=True)

    is_latest = models.BooleanField(default=True)  # ✅ New field to track active order
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"ServiceRequest #{self.id} - {self.status}"


class Role(models.Model):
    name = models.CharField(max_length=100)
    context = models.ForeignKey(Context, on_delete=models.CASCADE, related_name='roles')
    context_type = models.CharField(
        max_length=20,
        choices=[
            ('personal', 'Personal'),
            ('business', 'Business')
        ]
    )
    role_type = models.CharField(
        max_length=20,
        choices=[
            ('owner', 'Owner'),
            ('admin', 'Administrator'),
            ('manager', 'Manager'),
            ('employee', 'Employee'),
            ('custom', 'Custom')
        ]
    )
    description = models.TextField(blank=True, null=True)
    is_system_role = models.BooleanField(default=False)
    is_default_role = models.BooleanField(default=False)  # To identify default roles
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['name', 'context']
        ordering = ['context_type', 'role_type', 'name']

    def __str__(self):
        return f"{self.name} ({self.context_type})"

    @classmethod
    def create_default_roles(cls):
        """Create default roles that are available for all contexts"""
        # Personal context default roles
        personal_roles = [
            {
                "name": "Owner",
                "context_type": "personal",
                "role_type": "owner",
                "description": "Personal account owner with full access",
                "is_default_role": True
            }
        ]

        # Business context default roles
        business_roles = [
            {
                "name": "Owner",
                "context_type": "business",
                "role_type": "owner",
                "description": "Business owner with full access to all features",
                "is_default_role": True
            },
            {
                "name": "Administrator",
                "context_type": "business",
                "role_type": "admin",
                "description": "Business administrator with full access to all modules",
                "is_default_role": True
            },
            {
                "name": "Manager",
                "context_type": "business",
                "role_type": "manager",
                "description": "Business manager with elevated permissions",
                "is_default_role": True
            },
            {
                "name": "Employee",
                "context_type": "business",
                "role_type": "employee",
                "description": "Regular employee with basic access",
                "is_default_role": True
            }
        ]

        # Create all default roles
        for role_data in personal_roles + business_roles:
            cls.objects.get_or_create(
                name=role_data["name"],
                context_type=role_data["context_type"],
                role_type=role_data["role_type"],
                defaults={
                    "description": role_data["description"],
                    "is_default_role": True,
                    "is_system_role": True
                }
            )

    @classmethod
    def create_context_roles(cls, context):
        """Create roles for a specific context based on default roles"""
        # Get default roles for this context type
        default_roles = cls.objects.filter(
            context_type=context.context_type,
            is_default_role=True
        )

        # Create context-specific instances of default roles
        for default_role in default_roles:
            cls.objects.get_or_create(
                name=default_role.name,
                context=context,
                context_type=default_role.context_type,
                role_type=default_role.role_type,
                defaults={
                    "description": default_role.description,
                    "is_system_role": True,
                    "is_default_role": True
                }
            )

    @classmethod
    def create_custom_role(cls, context, name, role_type='custom', description=None):
        """Create a custom role for a specific context"""
        return cls.objects.create(
            name=name,
            context=context,
            context_type=context.context_type,
            role_type=role_type,
            description=description,
            is_system_role=False,
            is_default_role=False
        )


class UserContextRole(models.Model):
    PERMISSION_CHOICES = [
        ('create', 'Create'),
        ('read', 'Read'),
        ('update', 'Update'),
        ('delete', 'Delete')
    ]

    user = models.ForeignKey('Users', on_delete=models.CASCADE, related_name='context_roles')
    context = models.ForeignKey(Context, on_delete=models.CASCADE, related_name='user_roles')
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='user_contexts')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    added_by = models.ForeignKey('Users', on_delete=models.CASCADE, related_name='user_context_roles_added')
    STATUS_CHOICES = [
        ("active", "Active"),
        ("invited", "Invited"),
        ("suspended", "Suspended"),
    ]

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")

    class Meta:
        unique_together = ['user', 'context', 'role']

    def __str__(self):
        return f"{self.user.email} - {self.context.name} - {self.role.name}"


class ModuleFeature(models.Model):
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name='features')
    service = models.CharField(max_length=100)  # Employee table
    action = models.CharField(max_length=100)  # e.g. 'create'
    label = models.CharField(max_length=255)  # 'Can Create Employee'

    class Meta:
        unique_together = ('module', 'service', 'action')

    def __str__(self):
        return f"{self.module.name} - {self.service}"


class UserFeaturePermission(models.Model):
    """
    Represents feature permissions for a user within a context and module.
    """
    user_context_role = models.ForeignKey(UserContextRole, on_delete=models.CASCADE, related_name='feature_permissions')
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name='user_permissions')
    actions = models.JSONField(default=list)  # List of service.action combinations
    created_by = models.ForeignKey(Users, on_delete=models.SET_NULL, null=True,
                                   related_name='created_feature_permissions')
    is_active = models.BooleanField(default=True, help_text="Indicates if the permission is currently active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user_context_role', 'module')

    def __str__(self):
        return f"{self.user_context_role.user.email} - {self.module.name}"


class Suite(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    included_modules = models.ManyToManyField(Module, related_name='included_in_suites')
    available_for = models.CharField(
        max_length=20,
        choices=[
            ('personal', 'Personal'),
            ('business', 'Business'),
            ('all', 'All')
        ],
        default='all'
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Active'),
            ('inactive', 'Inactive')
        ],
        default='active'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.suite_id})"

    class Meta:
        ordering = ['name']


class SubscriptionPlan(models.Model):
    PLAN_TYPE_CHOICES = [
        ('trial', 'Trial'),
        ('monthly', 'Monthly'),
        ('annually', 'Annually')
    ]

    module = models.ForeignKey(Module, on_delete=models.CASCADE, null=True, blank=True,
                               related_name='module_subscriptions')
    suite = models.ForeignKey(Suite, on_delete=models.CASCADE, null=True, blank=True,
                              related_name='suite_subscriptions')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    plan_type = models.CharField(max_length=20, choices=PLAN_TYPE_CHOICES)

    # Base pricing
    base_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Base price for the plan")
    # Billing cycle
    billing_cycle_days = models.IntegerField(default=30,
                                             help_text="Number of days in billing cycle")
    features_enabled = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True, help_text="Indicates if the plan is active")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['module', 'name']

    def __str__(self):
        return f"{self.module.name} - {self.name} ({self.plan_type})"

    def calculate_price(self, usage_count):
        """Calculate price based on usage"""
        if self.plan_type == 'trial':
            return 0

        if usage_count <= self.free_tier_limit:
            return self.base_price

        additional_units = usage_count - self.free_tier_limit
        return self.base_price + (additional_units * self.price_per_unit)

    def get_next_renewal_date(self, start_date):
        """Calculate the next renewal date based on billing cycle"""
        return start_date + relativedelta(days=self.billing_cycle_days)


class ContextSuiteSubscription(models.Model):
    context = models.ForeignKey(Context, on_delete=models.CASCADE, related_name='context_subscriptions')
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.CASCADE, related_name='subscription_processed_for')
    status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Active'),
            ('trial', 'Trial'),
            ('expired', 'Expired'),
            ('cancelled', 'Cancelled')
        ],
        default='active'
    )
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    auto_renew = models.BooleanField(default=False, help_text="Indicates if the subscription will auto-renew")
    # New fields for proration
    original_price = models.DecimalField(max_digits=10, decimal_places=2)
    applied_credit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    final_price = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.context.name} - {self.suite.name} ({self.plan.name})"


class PaymentInfo(models.Model):
    context = models.ForeignKey(Context, on_delete=models.CASCADE)

    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name='payment_infos'
    )

    suite_subscription = models.ForeignKey(
        ContextSuiteSubscription,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name='payment_infos'
    )

    amount = models.FloatField()
    currency = models.CharField(max_length=10, default='INR')

    razorpay_order_id = models.CharField(max_length=255, unique=True)
    razorpay_payment_id = models.CharField(max_length=255, blank=True, null=True)
    razorpay_signature = models.TextField(blank=True, null=True)

    payment_method = models.CharField(max_length=50, blank=True, null=True)  # UPI, card, wallet, netbanking etc.
    card_last4 = models.CharField(max_length=4, blank=True, null=True)

    status = models.CharField(max_length=20, choices=(
        ('created', 'Created'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),  # for future refund handling
    ), default='created')

    failure_reason = models.TextField(blank=True, null=True)

    raw_response = models.JSONField(blank=True, null=True)  # full Razorpay order/payment response
    notes = models.JSONField(blank=True, null=True)         # any custom notes from Razorpay

    payment_captured = models.BooleanField(default=False)  # full payment captured?

    added_by = models.ForeignKey(Users, on_delete=models.CASCADE, related_name='payment_infos')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['razorpay_order_id']),
            models.Index(fields=['razorpay_payment_id']),
            models.Index(fields=['context', 'plan'])
        ]

    def __str__(self):
        return f"PaymentInfo {self.razorpay_order_id} - {self.status}"

    def save(self, *args, **kwargs):
        # Before saving, ensure amount is rounded to 2 decimal places
        if self.amount is not None:
            try:
                rounded_amount = Decimal(str(self.amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                self.amount = float(rounded_amount)
            except (TypeError, ValueError, InvalidOperation):
                self.amount = 0.0  # fallback to 0 if something wrong

        super().save(*args, **kwargs)


class ModuleSubscription(models.Model):
    context = models.ForeignKey(Context, on_delete=models.CASCADE, related_name='module_subscriptions')
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name='subscriptions')
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.CASCADE, related_name='module_subscriptions')
    status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Active'),
            ('trial', 'Trial'),
            ('expired', 'Expired'),
            ('cancelled', 'Cancelled')
        ],
        default='active'
    )
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    auto_renew = models.BooleanField(default=False, help_text="Indicates if the subscription will auto-renew")

    # New field to track if this subscription is part of a suite
    via_suite = models.BooleanField(default=False, help_text="Indicates if this subscription is part of a suite")
    suite_subscription = models.ForeignKey(
        ContextSuiteSubscription,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name='module_subscriptions'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    added_by = models.ForeignKey(Users, on_delete=models.CASCADE, related_name='added_subscriptions')

    def __str__(self):
        return f"{self.context.name} - {self.module.name} ({self.plan.name})"


class ModuleAddOn(models.Model):
    subscription = models.ForeignKey(ModuleSubscription, on_delete=models.CASCADE)
    type = models.CharField(max_length=50)  # e.g., 'extra_user', 'extra_gstin'
    quantity = models.IntegerField(default=1)
    price_per_unit = models.FloatField()
    billing_cycle = models.CharField(max_length=10, default="monthly")  # monthly/yearly
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.subscription.context.name} - {self.type} ({self.quantity})"


class SubscriptionCycle(models.Model):
    subscription = models.ForeignKey(ModuleSubscription, on_delete=models.CASCADE, related_name="cycles")
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    amount = models.FloatField()
    is_paid = models.BooleanField(default=False, help_text="Indicates if this cycle has been paid")
    payment_id = models.CharField(max_length=100, null=True, blank=True)
    feature_usage = models.JSONField(
        default=dict,
        help_text="Tracks feature usage quantities during this cycle"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.subscription.context.name} - {self.start_date.date()}"

    def update_feature_usage(self, feature_key, quantity):
        """
        Update usage for a specific feature
        """
        current_usage = self.feature_usage.get(feature_key, 0)
        self.feature_usage[feature_key] = current_usage + quantity
        self.save()

    def save(self, *args, **kwargs):
        # Before saving, ensure amount is rounded to 2 decimal places
        if self.amount is not None:
            try:
                rounded_amount = Decimal(str(self.amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                self.amount = float(rounded_amount)
            except (TypeError, ValueError, InvalidOperation):
                self.amount = 0.0  # fallback to 0 if something wrong

        super().save(*args, **kwargs)


@receiver(post_save, sender=PaymentInfo)
def handle_payment_success(sender, instance, created, **kwargs):
    """
    Handle payment success by creating/updating module subscription and subscription cycle
    """
    # Only proceed if payment is successful and has a plan
    if instance.status == 'paid' and instance.plan:
        try:
            with transaction.atomic():
                # Get or create module subscription
                subscription, created = ModuleSubscription.objects.get_or_create(
                    context=instance.context,
                    plan=instance.plan,
                    defaults={
                        'status': 'active',
                        'start_date': timezone.now(),
                        'end_date': timezone.now() + timedelta(days=instance.plan.billing_cycle_days),
                        'auto_renew': False,  # Default to no auto-renewal
                        'added_by': instance.added_by
                    }
                )

                # If subscription exists, handle upgrade/renewal
                if not created:
                    # End current active cycles
                    active_cycles = SubscriptionCycle.objects.filter(
                        subscription=subscription,
                        end_date__gt=timezone.now()
                    )
                    for cycle in active_cycles:
                        cycle.end_date = timezone.now()
                        cycle.save()

                    # Update subscription with new plan details
                    subscription.plan = instance.plan
                    subscription.status = 'active'
                    subscription.start_date = timezone.now()
                    subscription.end_date = timezone.now() + timedelta(days=instance.plan.billing_cycle_days)
                    subscription.save()

                    # Create new subscription cycle
                    new_cycle = SubscriptionCycle.objects.create(
                        subscription=subscription,
                        start_date=subscription.start_date,
                        end_date=subscription.end_date,
                        amount=round(float(instance.amount), 2),
                        is_paid=True,
                        payment_id=instance.razorpay_payment_id,
                        feature_usage=instance.plan.features_enabled  # Initialize empty feature usage
                    )

        except Exception as e:
            # Log the error but don't raise it to prevent signal failure
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to create/update subscription after payment: {str(e)}")


@receiver(post_save, sender=ModuleSubscription)
def create_subscription_cycle(sender, instance, created, **kwargs):
    if not created:
        return

    try:
        with transaction.atomic():
            # Step 1: Determine is_paid
            if instance.status == 'trial':
                amount = 0.00
                is_paid = True
            else:
                try:
                    amount = round(float(instance.plan.base_price), 2)
                except (TypeError, ValueError):
                    amount = 0.00
                is_paid = amount == 0.00

            if not is_paid:
                return

            # Step 2: Copy features
            features = instance.plan.features_enabled

            # Step 3: Create SubscriptionCycle
            SubscriptionCycle.objects.create(
                subscription=instance,
                start_date=instance.start_date,
                end_date=instance.end_date,
                amount=amount,
                is_paid=is_paid,
                feature_usage=features
            )

    except Exception as e:
        raise Exception(f"SubscriptionCycle creation failed: {str(e)}")


@receiver(post_save, sender=SubscriptionCycle)
def create_module_usage_cycles(sender, instance, created, **kwargs):
    if not created:
        return

    try:
        with transaction.atomic():
            features = instance.feature_usage or {}
            seen_features = set()

            for feature_key, limit in features.items():
                normalized_key = feature_key.lower()

                if normalized_key in seen_features:
                    continue
                seen_features.add(normalized_key)

                limit_str = str(limit).lower()

                if limit_str == "unlimited":
                    actual_count = "unlimited"
                    usage_count = "unlimited"
                elif limit_str.isdigit():
                    actual_count = str(limit)

                    if normalized_key == "users_count":
                        # ✅ Count users linked to the same context and marked active
                        context = instance.subscription.context
                        active_user_count = UserContextRole.objects.filter(
                            context=context,
                            status="active",
                            user__is_active=True  # assumes your 'Users' model has this field
                        ).count()
                        usage_count = str(active_user_count)
                    else:
                        usage_count = "0"
                else:
                    actual_count = None
                    usage_count = "0"

                ModuleUsageCycle.objects.create(
                    cycle=instance,
                    feature_key=feature_key,
                    actual_count=actual_count,
                    usage_count=usage_count
                )
    except Exception as e:
        raise Exception(f"ModuleUsageCycle creation failed: {str(e)}")


class ModuleUsageCycle(models.Model):
    cycle = models.ForeignKey(SubscriptionCycle, on_delete=models.CASCADE, related_name="usages")
    feature_key = models.CharField(max_length=100)  # e.g., 'invoices', 'payrolls'
    # Allow both numbers and the string "unlimited"
    actual_count = models.CharField(max_length=20, null=True, blank=True)
    usage_count = models.CharField(max_length=20, default="0")  # default as string

    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['cycle', 'feature_key']


class UserKYC(models.Model):
    user = models.OneToOneField(Users, on_delete=models.CASCADE, related_name='userkyc')  # `related_name='userkyc'`
    name = models.CharField(max_length=40, blank=False, null=False)
    pan_number = models.CharField(
        max_length=20, blank=True, null=True,
        validators=[
            RegexValidator(
                regex=r'^[A-Z]{5}[0-9]{4}[A-Z]$',
                message='Enter a valid PAN number (e.g., ABCDE1234F)'
            )
        ]
    )
    aadhaar_number = models.CharField(
        max_length=20, blank=True, null=True,
        validators=[
            RegexValidator(
                regex=r'^\d{12}$',
                message='Enter a valid 12-digit Aadhaar number'
            )
        ]
    )
    date = models.DateField(null=True, blank=True)
    icai_number = models.CharField(max_length=15, blank=True, null=True)
    address = models.JSONField(default=dict, null=True, blank=True)
    have_firm = models.BooleanField(default=False)

    @property
    def is_completed(self):
        required_fields = [self.name, self.pan_number, self.aadhaar_number, self.date]

        if self.have_firm:
            required_fields.append(self.icai_number)

        if self.address:
            # Exclude 'address_line2' as it's optional
            required_address_fields = ['address_line1', 'state', 'city', 'country']
            for field in required_address_fields:
                if not self.address.get(field):
                    return False  # If any required address field is missing or empty, return False

        return all(field is not None and field != "" for field in required_fields)

    def __str__(self):
        return f"{self.user.email} - {self.user.user_type}"


@receiver(post_save, sender=UserKYC)
def update_personal_context_on_kyc_complete(sender, instance, **kwargs):
    user = instance.user
    if not instance.is_completed:
        return

    # Update all personal contexts owned by this user
    personal_contexts = Context.objects.filter(owner_user=user, context_type='personal')
    for context in personal_contexts:
        context.profile_status = 'complete'

        # Update metadata with KYC info
        context.metadata['kyc'] = {
            'name': instance.name,
            'pan_number': instance.pan_number,
            'aadhaar_number': instance.aadhaar_number,
            'date': str(instance.date) if instance.date else None,
            'icai_number': instance.icai_number if instance.have_firm else None,
            'address': instance.address if instance.address else {}
        }

        context.save()


class FirmKYC(models.Model):
    user = models.OneToOneField(Users, on_delete=models.CASCADE)
    firm_name = models.CharField(max_length=255, blank=True, null=True)
    firm_registration_number = models.CharField(max_length=40, blank=True, null=True)
    firm_email = models.EmailField(unique=True, null=True, blank=True)
    firm_mobile_number = models.CharField(max_length=40, blank=True, null=True)
    number_of_firm_partners = models.IntegerField()
    address = models.JSONField(default=dict, null=True, blank=True)

    def __str__(self):
        return f"{self.user.email} - {self.firm_registration_number}"


class ServicesMasterData(models.Model):
    service_name = models.CharField(max_length=50, null=False, blank=False)

    def __str__(self):
        return f"{self.service_name}"


class BaseModel(models.Model):
    createdAt = models.DateTimeField(auto_now_add=True)
    updatedAt = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Business(BaseModel):
    entity_choices = [
        ('soleProprietor', 'Sole Proprietor'),
        ('partnershipUnregistered', 'Partnership Unregistered'),
        ('partnershipRegistered', 'Partnership Registered'),
        ('llp', 'LLP'),
        ('huf', 'HUF'),
        ('privateLimitedCompany', 'Private Limited Company'),
        ('publicCompanyListed', 'Public Company Listed'),
        ('publicCompanyUnlisted', 'Public Company Unlisted'),
        ('trust', 'Trust'),
        ('society', 'Society'),
        ('opc', 'OPC'),
        ('others', 'Others (Specify)'),
    ]

    business_nature_choices = [
        ('Agency or Sales House', 'Agency or Sales House'),
        ('Agriculture', 'Agriculture'),
        ('Art and Design', 'Art and Design'),
        ('Automotive', 'Automotive'),
        ('Construction', 'Construction'),
        ('Consulting', 'Consulting'),
        ('Consumer Packaged Goods', 'Consumer Packaged Goods'),
        ('Education', 'Education'),
        ('Engineering', 'Engineering'),
        ('Entertainment', 'Entertainment'),
        ('Financial Services', 'Financial Services'),
        ('Food Services (Restaurants/Fast Food)', 'Food Services (Restaurants/Fast Food)'),
        ('Gaming', 'Gaming'),
        ('Government', 'Government'),
        ('Health Care', 'Health Care'),
        ('Interior Design', 'Interior Design'),
        ('Internal', 'Internal'),
        ('Legal', 'Legal'),
        ('Manufacturing', 'Manufacturing'),
        ('Marketing', 'Marketing'),
        ('Mining and Logistics', 'Mining and Logistics'),
        ('Non-Profit', 'Non-Profit'),
        ('Publishing and Web Media', 'Publishing and Web Media'),
        ('Real Estate', 'Real Estate'),
        ('Retail (E-Commerce and Offline)', 'Retail (E-Commerce and Offline)'),
        ('Services', 'Services'),
        ('Technology', 'Technology'),
        ('Telecommunications', 'Telecommunications'),
        ('Travel/Hospitality', 'Travel/Hospitality'),
        ('Web Designing', 'Web Designing'),
        ('Web Development', 'Web Development'),
        ('Writers', 'Writers'),
        ('Software Services', 'Software Services'),
    ]

    client = models.ForeignKey(Users, on_delete=models.CASCADE, related_name='business_clients_id')
    nameOfBusiness = models.CharField(max_length=200, db_index=True)
    registrationNumber = models.CharField(max_length=120, null=True, blank=True, default=None)
    entityType = models.CharField(max_length=50, null=True, blank=True, default=None)
    headOffice = JSONField(default=dict, null=True, blank=True)
    pan = models.CharField(max_length=15, null=True, blank=True, default=None)
    business_nature = models.CharField(
        max_length=50, choices=business_nature_choices, null=True, blank=True, default=None
    )  # Default as None
    mobile_number = models.CharField(max_length=15, null=True, blank=True, default=None)
    email = models.EmailField(null=True, blank=True, default=None)
    dob_or_incorp_date = models.DateField(null=True, blank=True, default=None)
    is_msme_registered = models.BooleanField(default=False, help_text="Is the business MSME registered?")
    msme_registration_type = models.CharField(max_length=100, null=True, blank=True)
    msme_registration_number = models.CharField(max_length=100, null=True, blank=True)
    legal_name = models.CharField(max_length=100, null=True, blank=True, default=None)


    def clean(self):
        """Validate model data before saving"""
        super().clean()

        # Check if MSME is registered but no registration number provided
        if (self.is_msme_registered == True or self.is_msme_registered == True) and not self.msme_registration_number:
            raise ValidationError({
                'msme_registration_number': 'MSME registration number is required when business is MSME registered.'
            })

    def save(self, *args, **kwargs):
        """Override save to ensure validation happens"""
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return str(self.nameOfBusiness)


class BusinessLogo(BaseModel):
    business = models.OneToOneField(Business, on_delete=models.CASCADE, related_name='logos')
    logo = models.FileField(upload_to=logo_upload_path, null=True, blank=True)

    def __str__(self):
        return f"Logo for {self.business.nameOfBusiness}"


# Branch model to represent multiple branches of a business
class Branch(BaseModel):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='branches')
    branch_name = models.CharField(max_length=100, null=True, blank=True)
    branch_code = models.CharField(max_length=30, null=True, blank=True)

    def __str__(self):
        return f"{self.branch_name} - {self.business.nameOfBusiness}"


# Signals to maintain Context-Business relationship
@receiver(post_save, sender=Context)
def create_or_update_business(sender, instance, created, **kwargs):
    """Create or update Business record when Context is created/updated"""
    if instance.context_type == 'business':
        if created:
            # Create new Business record
            business = Business.objects.create(
                nameOfBusiness=instance.name,
                client=instance.owner_user
            )
            instance.business = business
            instance.save()
        elif instance.business and instance.name != instance.business.nameOfBusiness:
            # Update Business name if Context name changes
            instance.business.nameOfBusiness = instance.name
            instance.business.save()


@receiver(pre_save, sender=Business)
def sync_business_name_with_context(sender, instance, **kwargs):
    """Sync Business name changes back to Context"""
    if instance.pk:  # Only for existing Business records
        try:
            context = instance.contexts.first()
            if context and context.name != instance.nameOfBusiness:
                context.name = instance.nameOfBusiness
                context.save(update_fields=['name'])
        except Exception:
            pass  # Handle any errors silently to prevent business name update from failing


class GSTDetails(BaseModel):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='gst_details')
    gstin = models.CharField(max_length=120, null=True, blank=True)
    legal_name = models.CharField(max_length=120, null=True, blank=True)
    trade_name = models.CharField(max_length=120, null=True, blank=True)
    gst_username = models.CharField(max_length=60, null=True, blank=True)
    gst_password = models.CharField(max_length=20, null=True, blank=True)
    address = models.CharField(max_length=120, null=True, blank=True)
    pincode = models.IntegerField(null=True)
    branch_name = models.CharField(max_length=60, null=True, blank=True, default=None)
    state = models.CharField(max_length=60, null=True, blank=True, default=None)
    authorized_signatory_pan = models.CharField(max_length=60, null=True, blank=True, default=None)
    gst_document = models.FileField(upload_to=gst_document_upload_path, null=True, blank=True,
                                    storage=PrivateS3Storage())
    is_composition_scheme = models.BooleanField(default=False,
                                                help_text="Is the business registered under composition scheme?")
    composition_scheme_percent = models.CharField(max_length=200, null=True, blank=True)
    is_export_sez = models.BooleanField(default=False, help_text="Is the business registered for export under SEZ?")
    lut_reg_no = models.CharField(max_length=100, blank=True)
    dob = models.DateField(null=True, blank=True)
    financial_year = models.CharField(max_length=20, blank=True)
    lut_letter = models.FileField(upload_to=lut_letter_upload_path, null=True, blank=True, storage=PrivateS3Storage())

    class Meta:
        unique_together = ("business", "gstin")

    def __str__(self):
        return f"GST Details for {self.business.nameOfBusiness}"


class TDSDetails(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='tds_details')
    tan_number = models.CharField(max_length=20, null=True, blank=True)
    pan = models.CharField(max_length=20, null=True, blank=True)
    legal_name = models.CharField(max_length=120, null=True, blank=True)
    trade_name = models.CharField(max_length=120, null=True, blank=True)
    location = models.CharField(max_length=120, null=True, blank=True)
    deductor_category = models.CharField(max_length=120, null=True, blank=True)
    deductor_type = models.CharField(max_length=120, null=True, blank=True)
    address = models.CharField(max_length=120, null=True, blank=True)
    pincode = models.IntegerField(null=True)
    state = models.CharField(max_length=60, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    mobile_number = models.CharField(max_length=15, null=True, blank=True)
    tds_username = models.CharField(max_length=60, null=True, blank=True)
    tds_password = models.CharField(max_length=60, null=True, blank=True)
    authorized_personal_Details = models.JSONField(default=dict, null=True, blank=True)
    income_tax_details = models.JSONField(default=dict, null=True, blank=True)

    def __str__(self):
        return f"TDS Details for {self.business.nameOfBusiness}"


class LicenseDetails(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='license_details')
    license_type = models.CharField(max_length=100, null=True, blank=True)
    license_number = models.CharField(max_length=100, null=True, blank=True)
    location = models.CharField(max_length=100, null=True, blank=True)
    date_of_issue = models.DateField(null=True, blank=True)
    date_of_expiry = models.DateField(null=True, blank=True)
    license_document = models.FileField(upload_to=license_document_upload_path, null=True, blank=True,
                                        storage=PrivateS3Storage())

    def __str__(self):
        return f"License Details for {self.business.nameOfBusiness}"


class DSCDetails(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='dsc_details')
    name = models.CharField(max_length=100, null=True, blank=True)
    dsc_type = models.CharField(max_length=100, null=True, blank=True)
    dsc_number = models.CharField(max_length=100, null=True, blank=True)
    issue_authority = models.CharField(max_length=100, null=True, blank=True)
    date_of_issue = models.DateField(null=True, blank=True)
    date_of_expiry = models.DateField(null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    mobile_number = models.CharField(max_length=15, null=True, blank=True)
    location = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return f"DSC Details for {self.business.nameOfBusiness}"


class BankDetails(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='bank_details')
    bank_name = models.CharField(max_length=100, null=True, blank=True)
    account_number = models.CharField(max_length=20, null=True, blank=True)
    branch_name = models.CharField(max_length=100, null=True, blank=True)
    ifsc_code = models.CharField(max_length=11, null=True, blank=True)
    swift_code = models.CharField(max_length=11, null=True, blank=True)

    def __str__(self):
        return f"Bank Details for {self.business.nameOfBusiness}"


class KeyManagerialPersonnel(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='key_managerial_personnel')
    name = models.CharField(max_length=100, null=True, blank=True)
    designation = models.CharField(max_length=100, null=True, blank=True)
    pan_number = models.CharField(max_length=20, null=True, blank=True)
    role = models.CharField(max_length=100, null=True, blank=True)
    status = models.CharField(max_length=20, null=True, blank=True)
    passport_number = models.CharField(max_length=20, null=True, blank=True)

    def __str__(self):
        return f"KMP Details for {self.business.nameOfBusiness}"


class ServiceDetails(models.Model):
    STATUS_CHOICES = [
        ('in progress', 'In Progress'),
        ('created', 'Created'),
        ('completed', 'Completed'),
        ('pending', 'Pending'),
    ]

    service_type = models.ForeignKey(ServicesMasterData, on_delete=models.CASCADE, related_name="service_details")
    date = models.DateField(default=timezone.now)
    status = models.CharField(
        max_length=40,
        choices=STATUS_CHOICES,
        default='pending'
    )
    comments = models.CharField(max_length=256, blank=True, null=True)
    quantity = models.IntegerField(null=False)
    visa_application = models.ForeignKey('VisaApplications', related_name='services', on_delete=models.CASCADE)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Service for {self.visa_application.first_name} {self.visa_application.last_name}"


class VisaApplications(models.Model):
    user = models.ForeignKey(Users, on_delete=models.CASCADE, related_name="visa_applications")
    passport_number = models.CharField(max_length=20, blank=True, null=True)
    purpose = models.CharField(max_length=20, blank=True, null=True)
    visa_type = models.CharField(max_length=15, blank=True, null=True)
    destination_country = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        unique_together = ("user", "purpose", "visa_type", "destination_country")

    def __str__(self):
        return f"{self.user.email} - {self.visa_type}"


class Contact(models.Model):

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('reviewed', 'Reviewed'),
        ('resolved', 'Resolved'),
    ]

    first_name = models.CharField(max_length=40)
    last_name = models.CharField(max_length=40)
    email = models.EmailField()  # No unique constraint
    mobile_number = models.CharField(
        max_length=20,
        validators=[
            RegexValidator(
                regex=r'^\+?\d{10,15}$',
                message="Enter a valid mobile number with 10-15 digits, optionally starting with +"
            )
        ]
    )
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_date = models.DateField(auto_now_add=True)  # Stores only Date (YYYY-MM-DD)
    created_time = models.TimeField(auto_now_add=True)  # Stores only Time (HH:MM:SS)

    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.email}"


class Consultation(models.Model):

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('reviewed', 'Reviewed'),
        ('resolved', 'Resolved'),
    ]

    name = models.CharField(max_length=40)
    email = models.EmailField()  # No unique constraint
    mobile_number = models.CharField(
        max_length=20,
        validators=[
            RegexValidator(
                regex=r'^\+?\d{10,15}$',
                message="Enter a valid mobile number with 10-15 digits, optionally starting with +"
            )
        ]
    )
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    date = models.DateField()
    time = models.TimeField()
    created_date = models.DateField(auto_now_add=True)  # Stores only Date (YYYY-MM-DD)
    created_time = models.TimeField(auto_now_add=True)  # Stores only Time (HH:MM:SS)

    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.email}"


@receiver(post_save, sender=Business)
def update_gst_tds_on_business_change(sender, instance, created, **kwargs):
    if created:
        return

    try:
        original = Business.objects.only("nameOfBusiness", "legal_name").get(pk=instance.pk)
    except Business.DoesNotExist:
        return

    updates = {}
    updates["trade_name"] = instance.nameOfBusiness
    updates["legal_name"] = instance.legal_name

    if updates:
        GSTDetails.objects.filter(business=instance).update(**updates)
        TDSDetails.objects.filter(business=instance).update(**updates)
