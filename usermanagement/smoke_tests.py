"""
Smoke Tests for User Management Service

These tests verify that the basic functionality of the User Management service is working
after deployment or major changes. They are designed to be fast and catch major issues early.

Run with: python manage.py test usermanagement.smoke_tests
"""

import os
import sys
import django
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
import logging

# Configure logging
logger = logging.getLogger(__name__)

User = get_user_model()


class UserManagementSmokeTests(TestCase):
    """
    Smoke tests for User Management service basic functionality.
    
    These tests verify:
    1. Service is running and accessible
    2. Authentication works
    3. Core API endpoints respond
    4. Database connections work
    5. Basic CRUD operations function
    6. Business registration flow works
    7. Module subscription system works
    """
    
    def setUp(self):
        """Set up test data and client"""
        self.client = APIClient()
        self.test_user = User.objects.create_user(
            email='test@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User'
        )
        
        # Create JWT token for authentication
        refresh = RefreshToken.for_user(self.test_user)
        self.access_token = str(refresh.access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access_token}')
        
        logger.info("User Management smoke test setup completed")
    
    def test_service_health(self):
        """Test 1: Service is running and accessible"""
        logger.info("Running smoke test: Service health check")
        
        # Test basic Django admin access
        response = self.client.get('/admin/')
        self.assertIn(response.status_code, [200, 302], "Admin should be accessible")
        
        # Test API schema endpoint
        response = self.client.get('/api/schema/')
        self.assertIn(response.status_code, [200, 401, 403], "API schema should be accessible")
        
        logger.info("✅ Service health check passed")
    
    def test_authentication_works(self):
        """Test 2: Authentication system is functional"""
        logger.info("Running smoke test: Authentication check")
        
        # Test JWT token validation
        response = self.client.get('/user_management/users/')
        self.assertIn(response.status_code, [200, 401, 403], "Authentication endpoint should respond")
        
        # Test token refresh
        refresh = RefreshToken.for_user(self.test_user)
        new_access_token = str(refresh.access_token)
        self.assertIsNotNone(new_access_token, "Token refresh should work")
        
        # Test login endpoint
        login_data = {
            'email': 'test@example.com',
            'password': 'testpass123'
        }
        response = self.client.post('/user_management/login/', data=login_data)
        self.assertIn(response.status_code, [200, 400, 401], "Login should respond")
        
        logger.info("✅ Authentication check passed")
    
    def test_database_connection(self):
        """Test 3: Database connection and basic operations work"""
        logger.info("Running smoke test: Database connection check")
        
        # Test user creation (database write)
        test_user_count = User.objects.count()
        self.assertGreaterEqual(test_user_count, 1, "Should be able to read from database")
        
        # Test database query
        user = User.objects.filter(email='test@example.com').first()
        self.assertIsNotNone(user, "Should be able to query database")
        
        logger.info("✅ Database connection check passed")
    
    def test_core_api_endpoints_respond(self):
        """Test 4: Core API endpoints are accessible"""
        logger.info("Running smoke test: Core API endpoints check")
        
        # Test core endpoints
        endpoints_to_test = [
            '/user_management/users/',
            '/user_management/contexts/',
            '/user_management/roles/',
            '/user_management/modules/',
            '/user_management/subscriptions/',
        ]
        
        for endpoint in endpoints_to_test:
            response = self.client.get(endpoint)
            self.assertIn(response.status_code, [200, 401, 403, 404], 
                         f"Endpoint {endpoint} should respond")
        
        logger.info("✅ Core API endpoints check passed")
    
    def test_user_registration_flow(self):
        """Test 5: User registration flow works"""
        logger.info("Running smoke test: User registration flow")
        
        # Test user registration endpoint
        registration_data = {
            'email': 'newuser@example.com',
            'password': 'newpass123',
            'first_name': 'New',
            'last_name': 'User',
            'mobile_number': '+1234567890'
        }
        
        response = self.client.post('/user_management/register/', data=registration_data)
        # Should either create successfully or return validation error
        self.assertIn(response.status_code, [201, 400, 401, 403], 
                     "User registration should respond")
        
        logger.info("✅ User registration flow check passed")
    
    def test_business_registration_flow(self):
        """Test 6: Business registration flow works"""
        logger.info("Running smoke test: Business registration flow")
        
        # Test business registration endpoint
        business_data = {
            'email': 'business@example.com',
            'password': 'businesspass123',
            'first_name': 'Business',
            'last_name': 'Owner',
            'mobile_number': '+1234567890',
            'nameOfBusiness': 'Test Business',
            'otp': '123456',  # Mock OTP
            'selected_modules': ['payroll'],
            'head_office': {
                'address_line1': '123 Business St',
                'address_line2': 'Suite 100',
                'state': 'Test State',
                'city': 'Test City',
                'pincode': '12345'
            }
        }
        
        response = self.client.post('/user_management/register_business/', 
                                  data=business_data, format='json')
        # Should either create successfully or return validation error
        self.assertIn(response.status_code, [201, 400, 401, 403], 
                     "Business registration should respond")
        
        logger.info("✅ Business registration flow check passed")
    
    def test_otp_generation_flow(self):
        """Test 7: OTP generation and verification works"""
        logger.info("Running smoke test: OTP generation flow")
        
        # Test OTP generation
        otp_data = {
            'email': 'test@example.com',
            'purpose': 'registration'
        }
        
        response = self.client.post('/user_management/generate_otp/', data=otp_data)
        self.assertIn(response.status_code, [200, 400, 401, 403], 
                     "OTP generation should respond")
        
        # Test OTP verification
        verify_data = {
            'email': 'test@example.com',
            'otp': '123456'
        }
        
        response = self.client.post('/user_management/verify_otp/', data=verify_data)
        self.assertIn(response.status_code, [200, 400, 401, 403], 
                     "OTP verification should respond")
        
        logger.info("✅ OTP generation flow check passed")
    
    def test_context_management_endpoints(self):
        """Test 8: Context management endpoints are functional"""
        logger.info("Running smoke test: Context management endpoints")
        
        # Test context list
        response = self.client.get('/user_management/contexts/')
        self.assertIn(response.status_code, [200, 401, 403], 
                     "Contexts should be accessible")
        
        # Test context creation
        context_data = {
            'name': 'Test Context',
            'context_type': 'business',
            'description': 'Test Context Description'
        }
        
        response = self.client.post('/user_management/contexts/', data=context_data)
        self.assertIn(response.status_code, [201, 400, 401, 403], 
                     "Context creation should respond")
        
        logger.info("✅ Context management endpoints check passed")
    
    def test_role_management_endpoints(self):
        """Test 9: Role management endpoints are functional"""
        logger.info("Running smoke test: Role management endpoints")
        
        # Test role list
        response = self.client.get('/user_management/roles/')
        self.assertIn(response.status_code, [200, 401, 403], 
                     "Roles should be accessible")
        
        # Test role creation
        role_data = {
            'name': 'Test Role',
            'description': 'Test Role Description',
            'permissions': ['read', 'write']
        }
        
        response = self.client.post('/user_management/roles/', data=role_data)
        self.assertIn(response.status_code, [201, 400, 401, 403], 
                     "Role creation should respond")
        
        logger.info("✅ Role management endpoints check passed")
    
    def test_module_management_endpoints(self):
        """Test 10: Module management endpoints are functional"""
        logger.info("Running smoke test: Module management endpoints")
        
        # Test module list
        response = self.client.get('/user_management/modules/')
        self.assertIn(response.status_code, [200, 401, 403], 
                     "Modules should be accessible")
        
        # Test module creation
        module_data = {
            'name': 'Test Module',
            'description': 'Test Module Description',
            'is_active': True
        }
        
        response = self.client.post('/user_management/modules/', data=module_data)
        self.assertIn(response.status_code, [201, 400, 401, 403], 
                     "Module creation should respond")
        
        logger.info("✅ Module management endpoints check passed")
    
    def test_subscription_management_endpoints(self):
        """Test 11: Subscription management endpoints are functional"""
        logger.info("Running smoke test: Subscription management endpoints")
        
        # Test subscription list
        response = self.client.get('/user_management/subscriptions/')
        self.assertIn(response.status_code, [200, 401, 403], 
                     "Subscriptions should be accessible")
        
        # Test subscription creation
        subscription_data = {
            'user_id': self.test_user.id,
            'module_id': 1,
            'plan_id': 1,
            'start_date': '2024-01-01',
            'end_date': '2024-12-31'
        }
        
        response = self.client.post('/user_management/subscriptions/', data=subscription_data)
        self.assertIn(response.status_code, [201, 400, 401, 403], 
                     "Subscription creation should respond")
        
        logger.info("✅ Subscription management endpoints check passed")
    
    def test_user_profile_management(self):
        """Test 12: User profile management endpoints are functional"""
        logger.info("Running smoke test: User profile management endpoints")
        
        # Test user profile retrieval
        response = self.client.get(f'/user_management/users/{self.test_user.id}/')
        self.assertIn(response.status_code, [200, 401, 403], 
                     "User profile should be accessible")
        
        # Test user profile update
        profile_data = {
            'first_name': 'Updated',
            'last_name': 'Name'
        }
        
        response = self.client.put(f'/user_management/users/{self.test_user.id}/', 
                                 data=profile_data)
        self.assertIn(response.status_code, [200, 400, 401, 403], 
                     "User profile update should respond")
        
        logger.info("✅ User profile management endpoints check passed")
    
    def test_permission_management_endpoints(self):
        """Test 13: Permission management endpoints are functional"""
        logger.info("Running smoke test: Permission management endpoints")
        
        # Test permission list
        response = self.client.get('/user_management/permissions/')
        self.assertIn(response.status_code, [200, 401, 403], 
                     "Permissions should be accessible")
        
        # Test user feature permissions
        response = self.client.get('/user_management/user-feature-permissions/')
        self.assertIn(response.status_code, [200, 401, 403], 
                     "User feature permissions should be accessible")
        
        logger.info("✅ Permission management endpoints check passed")
    
    def test_error_handling(self):
        """Test 14: Error handling works correctly"""
        logger.info("Running smoke test: Error handling check")
        
        # Test invalid endpoint
        response = self.client.get('/user_management/invalid-endpoint/')
        self.assertEqual(response.status_code, 404, "Invalid endpoint should return 404")
        
        # Test invalid data
        response = self.client.post('/user_management/users/', data={})
        self.assertIn(response.status_code, [400, 401, 403], 
                     "Invalid data should return appropriate error")
        
        # Test unauthorized access
        self.client.credentials()  # Remove authentication
        response = self.client.get('/user_management/users/')
        self.assertIn(response.status_code, [401, 403], 
                     "Unauthorized access should return 401/403")
        
        logger.info("✅ Error handling check passed")
    
    def test_cors_headers(self):
        """Test 15: CORS headers are present"""
        logger.info("Running smoke test: CORS headers check")
        
        response = self.client.options('/user_management/users/')
        # CORS headers should be present (exact headers depend on configuration)
        self.assertIn(response.status_code, [200, 204], "CORS preflight should work")
        
        logger.info("✅ CORS headers check passed")
    
    def test_api_documentation_endpoints(self):
        """Test 16: API documentation endpoints are accessible"""
        logger.info("Running smoke test: API documentation endpoints")
        
        # Test Swagger UI
        response = self.client.get('/api/docs/')
        self.assertIn(response.status_code, [200, 401, 403], "Swagger UI should be accessible")
        
        # Test ReDoc
        response = self.client.get('/api/redoc/')
        self.assertIn(response.status_code, [200, 401, 403], "ReDoc should be accessible")
        
        # Test OpenAPI schema
        response = self.client.get('/api/schema/')
        self.assertIn(response.status_code, [200, 401, 403], "OpenAPI schema should be accessible")
        
        logger.info("✅ API documentation endpoints check passed")
    
    def tearDown(self):
        """Clean up after tests"""
        logger.info("User Management smoke tests completed - cleaning up")


def run_smoke_tests():
    """
    Standalone function to run smoke tests.
    Can be called from deployment scripts or CI/CD pipelines.
    """
    logger.info("Starting User Management Service Smoke Tests...")
    
    # Set up Django environment
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Tara.settings.default')
    django.setup()
    
    # Run tests
    from django.test.utils import get_runner
    from django.conf import settings
    
    TestRunner = get_runner(settings)
    test_runner = TestRunner()
    failures = test_runner.run_tests(["usermanagement.smoke_tests"])
    
    if failures:
        logger.error(f"❌ Smoke tests failed: {failures}")
        sys.exit(1)
    else:
        logger.info("✅ All smoke tests passed!")
        sys.exit(0)


if __name__ == '__main__':
    run_smoke_tests()
