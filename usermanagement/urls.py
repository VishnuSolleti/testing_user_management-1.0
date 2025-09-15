from django.urls import path
from . import views
from . import subscription_views
from . import roles_views
from . import feature_views
from . import business_registration_api
from . import login_api
from . import suite_upgradation
from . import standard_registration
from . import switch_context
from . import other_factors
from . import context_business_subscription
from . import personal_context_registration
from . import add_team_business
from . import module_subscription_upgrade
from . import payment_integration
from . import payment_webhooks
from . import service_views
from . import service_registration_process
from . import service_payment
from . import create_service_request
from . import accounts_registration
from . import accounts_auth
from . import user_context_permissions


urlpatterns = [
    # Registration endpoints
    # path('register/module', views.register_from_module, name='register_from_module'),
    # path('register/service', views.register_from_service, name='register_from_service'),
    # path('register/standard', views.register_standard, name='register_standard'),
    # path('register/complete', views.complete_registration, name='complete_registration'),
    # # New comprehensive business module registration endpoint
    # path('register/business-module', views.register_business_module, name='register_business_module'),
    path('request-otp/', views.request_otp, name='request-otp'),

    # Comprehensive business registration with module subscription and feature permissions
    path('register/business-with-module/', business_registration_api.register_business,
         name='register_business_with_module'),

    path('register/register_user_with_service/', service_registration_process.register_user_with_service,
             name='register_user_with_service'),

    path('register/add-another-context/', business_registration_api.add_another_context, name='add_another_context'),

    # Context registration for business
    path('business/create/', context_business_subscription.create_business_context, name='create-business-context'),
    path('business/subscription/add/', context_business_subscription.add_subscription_to_business,
         name='add-subscription-to-business'),
    path('context-subscriptions/<int:pk>/', context_business_subscription.get_module_subscriptions,
         name='get-context-subscriptions'),

    # Personal context registration
    path('api/context/personal/create/', personal_context_registration.create_personal_context,
         name='create-personal-context'),


    # Authentication endpoints
    path('auth/login', login_api.login_user, name='login_user'),
    path('auth/refresh-token', login_api.refresh_token, name='refresh_token'),

    # Standard Registration Process endpoints
    path('register/standard', standard_registration.initial_registration, name='initial_registration'),

    # get user permissions based on context role and module id
    path('permissions/user/', business_registration_api.get_user_permissions, name='get-user-permissions'),

    # Context Selection for Standard Registration
    path('select-context', standard_registration.select_context, name='select_context'),

    # suite upgradation
    path('subscriptions/upgrade-to-suite', suite_upgradation.upgrade_to_suite, name='upgrade_to_suite'),

    # Refresh token view
    path('refresh-token', standard_registration.token_refresh, name='refresh-token'),

    # Refresh token view
    path("switch-context/", switch_context.switch_user_context, name="switch_user_context"),

    # Admin API endpoints for Module Management
    path('modules', views.create_module, name='create_module'),
    path('modules/list', views.list_modules, name='list_modules'),
    path('modules/<int:module_id>', views.update_module, name='update_module'),
    path('modules/<int:module_id>/delete/', views.delete_module, name='delete_module'),
    path('modules/name/', views.get_modules_by_name, name='get_modules_by_name'),

    # Admin API endpoints for Subscription Plan Management
    path('subscription-plans', subscription_views.create_subscription_plan, name='create_subscription_plan'),
    path('subscription-plans/list/', subscription_views.list_subscription_plans,
         name='list_subscription_plans'),
    path('subscription-plans/<int:plan_id>/', subscription_views.get_subscription_plan,
         name='get_subscription_plan'),
    path('subscription-plans/<int:plan_id>/update/', subscription_views.update_subscription_plan,
         name='update_subscription_plan'),
    path('subscription-plans/<int:plan_id>/delete/', subscription_views.delete_subscription_plan,
         name='delete_subscription_plan'),

    # Admin API endpoints for Role Management

    path('roles', roles_views.create_role, name='create_role'),
    path('roles/list', roles_views.list_roles, name='list_roles'),
    path('roles/<int:role_id>', roles_views.get_role, name='get_role'),
    path('roles/<int:role_id>/update/', roles_views.update_role, name='update_role'),
    path('api/roles/<int:role_id>/delete/', roles_views.delete_role, name='delete_role'),
    path('roles/by-context', roles_views.get_role_by_context, name='get_role_by_context'),

    # Admin API endpoints for Module Permission Management
    path('module-permissions/', views.create_module_permission, name='create_module_permission'),
    path('module-permissions/list', views.list_module_permissions, name='list_module_permissions'),
    path('module-permissions/<int:permission_id>/', views.update_module_permission,
         name='update_module_permission'),
    path('module-permissions/<int:permission_id>/delete/', views.delete_module_permission,
         name='delete_module_permission'),

    # ModuleFeature URLs
    path('module-features', feature_views.list_module_features, name='list_module_features'),
    path('module-features/create', feature_views.create_module_feature, name='create_module_feature'),
    path('module-features/<int:pk>', feature_views.manage_module_feature, name='manage_module_feature'),
    path('module-features/by-module/<int:module_id>', feature_views.list_module_features_by_module,
         name='list_module_features_by_module'),

    # UserFeaturePermission URLs
    path('user-feature-permissions', feature_views.list_user_feature_permissions,
         name='list_user_feature_permissions'),
    path('user-feature-permissions/create', feature_views.create_user_feature_permission,
         name='create_user_feature_permission'),
    path('user-feature-permissions/bulk-create', feature_views.bulk_create_user_feature_permissions,
         name='bulk_create_user_feature_permissions'),
    path('user-feature-permissions/<int:pk>', feature_views.manage_user_feature_permission,
         name='manage_user_feature_permission'),
    path('user-feature-permissions/user-context-role/<int:user_context_role_id>/bulk-update/',
         feature_views.bulk_update_user_context_role_permissions,
         name='bulk_update_user_context_role_permissions'),

    # Filtered UserFeaturePermission URLs
    path('user-feature-permissions/by-role/<int:user_context_role_id>',
         feature_views.get_user_feature_permissions_by_role,
         name='get_user_feature_permissions_by_role'),

    path('user-feature-permissions/by-module/<int:module_id>',
         feature_views.get_user_feature_permissions_by_module,
         name='get_user_feature_permissions_by_module'),

    path('user-feature-permissions/by-feature/<str:feature_code>',
         feature_views.get_user_feature_permissions_by_feature,
         name='get_user_feature_permissions_by_feature'),

    path('module-features/bulk-create', feature_views.bulk_create_module_features,
         name='bulk_create_module_features'),

    path('context/<int:context_id>/module-features', feature_views.get_context_module_features,
         name='get-context-module-features'),

    # Reverted Api views As per the data

    path('users/stats/', other_factors.DynamicUserStatsAPIView.as_view(), name='user-stats'),
    path('users/by-type/', other_factors.UsersByDynamicTypeAPIView.as_view(), name='users-by-type'),

    path('user/search', personal_context_registration.search_user_by_email, name='search-user-by-email'),

    path('change-password/', other_factors.ChangePasswordView.as_view(), name='change-password'),
    path('visa-users/', other_factors.visa_users_creation, name='visa_users_creation'),
    path('activate', other_factors.ActivateUserView.as_view(), name='activate'),
    path('protected/', other_factors.TestProtectedAPIView.as_view(), name='test_protected'),
    # Forgot password view
    path('forgot-password/', other_factors.ForgotPasswordView.as_view(), name='forgot-password'),

    path('document_view', other_factors.documents_view, name='get_gst_document_url'),

    # Reset password view
    path('reset-password', other_factors.ResetPasswordView.as_view(), name='reset-password'),

    # Refresh token view
    path('refresh-token/', other_factors.RefreshTokenView.as_view(), name='refresh-token'),

    path('users-kyc/', other_factors.UsersKYCListView.as_view(), name='user-kyc-list'),

    # URL for retrieving, updating, and deleting specific user details
    path('users-kyc/<int:pk>', other_factors.UsersKYCDetailView.as_view(), name='user-kyc-detail'),

    # firm urls
    path('firmkyc/', other_factors.FirmKYCView.as_view(), name='firmkyc'),

    path('update-users-info', other_factors.partial_update_user, name='partial_update_user'),

    # Business urls
    path('businesses/', other_factors.business_list, name='business-list'),
    path('businesses/<int:pk>/', other_factors.business_detail, name='business-detail'),
    # Business list By Client
    path('businesses-by-client/', other_factors.business_list_by_client, name='business-list-by-client'),

    # Manage Corporate Entities
    # path('corporate-entity/', manage_corporate_entity, name='manage_corporate_entities'),

    path('corporate', other_factors.manage_corporate_entity, name='manage_corporate_entity'),

    path('corporate-details', other_factors.corporate_details, name='corporate_details'),

    path('user-search', other_factors.user_search, name='user_Search'),

    # Adding GST Details
    path('gst-details/', other_factors.gst_details_list_create, name='gst-details-list-create'),
    path('gst-details/<int:pk>/', other_factors.gst_details_detail, name='gst-details-detail'),
    path('gst-details/by-business/<int:business_id>/', other_factors.business_with_gst_details,
         name='gst-details-by-business'),

    path('services/', other_factors.ServicesMasterDataListAPIView.as_view()),  # For GET (list) and POST

    path('services/<int:pk>/', other_factors.ServicesMasterDataDetailAPIView.as_view()),  # For GET PUT, DELETE

    # Endpoint for specific visa application actions (GET, PUT, DELETE)
    path('visa-applicants/<int:pk>/', other_factors.VisaApplicationDetailAPIView.as_view(),
         name='visa-applications-detail-update-delete'),

    path('visa-servicetasks/', other_factors.manage_visa_applications, name='manage_visa_applications'),

    path('visa-clients/', other_factors.get_visa_clients_users_list, name='visa_clients_list'),

    path('visa-clients/dashboard-status/', other_factors.service_status, name='service-status'),

    path('visa-applicants/all-tasks-data/', other_factors.all_service_data, name='all_service_data'),

    path('service-details/<int:pk>/', other_factors.ServiceDetailsAPIView.as_view(), name='service-details'),

    path("contact", other_factors.create_contact, name="create_contact"),

    path("contacts", other_factors.list_contacts_by_date, name="list_contacts_by_specific_day"),

    path("list-contacts/", other_factors.list_contacts, name="list_contacts"),

    path("contact/<int:pk>", other_factors.contact_detail, name="get_contact_by_id"),

    path("consultation", other_factors.create_consultation, name="create-consultation"),

    path("list-consultations/", other_factors.list_consultation, name="list-consultations"),

    path("booked-consultations/", other_factors.booked_time_slots, name="booked-time-slots"),

    path("consultations", other_factors.list_consultations, name="list-consultations-by-date"),

    path("consultation/<int:pk>", other_factors.consultation_detail, name="get-consultation-by-id"),

    # Add Team members and invitation acceptance
    path('team/invitation/accept/', add_team_business.accept_team_invitation, name='accept-team-invitation'),
    path('team/member/add/', add_team_business.add_team_member_to_business, name='add-team-member'),

    # Context Business Data
    path('user/contexts', add_team_business.get_user_contexts, name='get-user-contexts'),

    # List all users in a context
    path('context/users', add_team_business.list_context_users, name='list-context-users'),

    path('business/context', add_team_business.get_business_context_data, name='get-business-context-data'),


    path('context-roles/list', roles_views.list_context_roles, name='list-context-roles'),

    path('context/<int:context_id>/subscriptions/', personal_context_registration.get_context_subscriptions,
         name='get_context_subscriptions'),


    # Module Subscription Upgrade
    path('module-context-subscription/upgrade/', module_subscription_upgrade.upgrade_module_subscription,
         name='upgrade_subscription'),


    path('create-order/', payment_integration.create_order, name='create_order'),
    path('verify-payment/', payment_integration.verify_payment, name='verify_payment'),
    path('webhooks/razorpay/', payment_webhooks.razorpay_webhook, name='razorpay_webhook'),

    # TDS Details URLs
    path('tds-details/', other_factors.tds_details_list_create, name='tds-details-list-create'),
    path('tds-details/<int:pk>/', other_factors.tds_details_detail, name='tds-details-detail'),

    #Bank Details URLs
    path('bank-details/', other_factors.bank_details_list_create, name='bank-details-list-create'),
    path('bank-details/<int:pk>/', other_factors.bank_details_detail, name='bank-details-detail'),

    #KeyManagerialPersonnel(KMP) Details URLs
    path('kmp-details/', other_factors.kmp_list_create, name='kmp-details-list-create'),
    path('kmp-details/<int:pk>/', other_factors.kmp_detail, name='kmp-details-detail'),

    # License Details URLs
    path('license-details/', other_factors.license_details_list_create, name='license-details-list-create'),
    path('license-details/<int:pk>/', other_factors.license_details_detail, name='license-details-detail'),

    # DSC Details URLs
    path('dsc-details/', other_factors.dsc_details_list_create, name='dsc-details-list-create'),
    path('dsc-details/<int:pk>/', other_factors.dsc_details_detail, name='dsc-details-detail'),

    path('feature-services/', service_views.service_list_create),
    path('feature-services/<int:service_id>', service_views.service_detail),
    path('feature-services/<int:service_id>/plans/', service_views.service_plan_list_create),
    path('feature-service-plans/<int:plan_id>', service_views.service_plan_detail),

    path('service-payment/create-order/', service_payment.create_razorpay_order_for_services,
         name='create_razorpay_order'),
    path('service-payment/webhooks/', service_payment.unified_razorpay_webhook, name='service_razorpay_webhook'),

    path('service-request/create/', create_service_request.create_new_service_request, name='create-service-request'),

    path('service-request/<int:service_request_id>/assignment/',
         create_service_request.manage_service_request_assignment,
         name='service-request-assignment'),

    path('user-service-requests/', create_service_request.user_service_requests, name='user-service-requests'),
    path('admin-service-requests', create_service_request.superadmin_service_requests, name='superadmin-service-requests'),

    # User detail
    path('users/<int:pk>/', other_factors.user_detail, name='user-detail'),

    path('service-payments-history', service_payment.get_service_payment_history, name='service-payment-history'),

    path('module-payment-history', payment_webhooks.payment_history, name='payment-history'),
    
    # Get service requests by context

    path('context-service-requests/<int:pk>/', service_views.get_context_service_requests,
         name='get-context-service-requests'),

    path('payment-history', payment_webhooks.unified_payment_history, name='unified-payment-history'),

    path('services-by-type', service_views.get_services_by_type, name='get-services-by-type'),

    path('branches/', other_factors.branch_list_create, name='branch-list-create'),
    path('branches/<int:pk>/', other_factors.branch_detail, name='branch-detail'),

    path('happy-coder/', views.happy_coder, name='happy_coder'),

    # Business Logo Upload Api
    path('business-logo/', other_factors.upload_business_logo, name='upload_business_logo'),
    path('business-logo/<int:pk>/', other_factors.business_logo_detail, name='business_logo_detail'),

    path("usage-summary/<int:context_id>/", views.get_usage_summary_by_context, name="usage-summary-by-context"),

    # # Accounts unified registration system
    # path('register/', include('usermanagement.accounts_registration_urls')),
    path('register/accounts/', accounts_registration.accounts_register, name='accounts_register'),

    path('auth/accounts-login/', accounts_auth.accounts_login, name='accounts_login'),

    # User Context and Permissions APIs
    path('user/current-session/', user_context_permissions.get_current_user_session, name='get_current_user_session'),
    path('user/contexts/', user_context_permissions.list_user_contexts, name='list_user_contexts'),
    path('user/permissions-summary/', user_context_permissions.get_user_permissions_summary, name='get_user_permissions_summary'),
    path('module/<int:module_id>/permissions/', user_context_permissions.get_module_permissions, name='get_module_permissions'),
    path('module/<int:module_id>/access/', user_context_permissions.check_module_access, name='check_module_access'),


    path('employee/create', standard_registration.user_registration_create_for_employee,
                                                                        name='user_registration_create_for_employee'),
    path('context/business', business_registration_api.get_context_details_using_business,
                                                                            name='get-context-details-using-business'),
    path('get-user-context-role/', user_context_permissions.get_user_context_role, name='get_user_context_role'),
    path('create-user-context-role/', user_context_permissions.create_user_context_role, name='create_user_context_role'),
    path('get-user-context-module-features/', feature_views.get_user_context_module_features,
                                                                                name='get_user_context_module_features'),
    path('module-subscriptions/', subscription_views.get_active_module_subscriptions, name='get_module_subscriptions'),
    path('role/create', feature_views.create_role_for_employee, name= 'create_role_for_employee'),
    path('subscription-cycles', subscription_views.get_subscription_cycle, name='get_subscription_cycle'),
    path('get-module-usage-cycle/', subscription_views.get_module_usage_cycle, name='get_module_usage_cycle'),
    path('module-usage-cycle/update', subscription_views.update_module_usage_cycle, name='update_module_usage_cycle')

]
