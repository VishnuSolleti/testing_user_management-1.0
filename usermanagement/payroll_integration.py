"""
Payroll Integration Module for User Management Service

This module handles the integration between User Management and Payroll services
during business registration when the Payroll module is selected.
"""

import requests
import logging
from django.conf import settings
from rest_framework.response import Response
from rest_framework import status

# Configure logging
logger = logging.getLogger(__name__)


def get_internal_service_token():
    """
    Generate or retrieve internal service token for cross-service communication.
    This should be implemented based on your authentication strategy.
    """
    # TODO: Implement proper internal service token generation
    # This could be a JWT token, API key, or other authentication method
    # For now, returning a placeholder
    return "internal_service_token_placeholder"


def create_payroll_org_for_business_registration(context, user, registration_data):
    """
    Create PayrollOrg for business registration using the dedicated endpoint.
    
    Args:
        context: Context object created during business registration
        user: User object created during business registration
        registration_data: Original registration request data
    
    Returns:
        dict: PayrollOrg creation response data
    
    Raises:
        Exception: If PayrollOrg creation fails
    """
    try:
        # Get the business created by the signal
        business = context.business
        if not business:
            raise Exception("Business not found for context - signal may have failed")
        
        # Prepare data for the new PayrollOrg creation endpoint
        payroll_data = {
            'business_id': business.id,
            'business_data': {
                'id': business.id,
                'nameOfBusiness': business.nameOfBusiness,
                'email': user.email,
                'first_name': user.first_name or 'Business',
                'last_name': user.last_name or 'Owner',
                'mobile_number': registration_data.get('mobile_number'),
                'client': user.id,
                'head_office': registration_data.get('head_office', {})
            }
        }
        
        # Get Payroll service URL from settings
        payroll_service_url = getattr(settings, 'PAYROLL_SERVICE_URL', 'http://localhost:8001')
        
        # Call the new dedicated PayrollOrg creation endpoint
        payroll_response = requests.post(
            f"{payroll_service_url}/payroll-org/create-for-registration/",
            json=payroll_data,
            headers={
                'Authorization': f'Bearer {get_internal_service_token()}',
                'Content-Type': 'application/json'
            },
            timeout=30  # 30 second timeout
        )
        
        if payroll_response.status_code != 201:
            error_msg = f"Failed to create PayrollOrg: {payroll_response.text}"
            logger.error(error_msg)
            raise Exception(error_msg)
        
        response_data = payroll_response.json()
        logger.info(f"PayrollOrg created successfully for business_id: {business.id}")
        
        return response_data
        
    except requests.exceptions.RequestException as e:
        error_msg = f"Network error while creating PayrollOrg: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)
    except Exception as e:
        error_msg = f"Error creating PayrollOrg: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)


def check_payroll_org_exists(business_id):
    """
    Check if PayrollOrg already exists for a given business.
    
    Args:
        business_id: ID of the business to check
    
    Returns:
        dict: Response with existence status and details
    """
    try:
        # Get Payroll service URL from settings
        payroll_service_url = getattr(settings, 'PAYROLL_SERVICE_URL', 'http://localhost:8001')
        
        # Call the check endpoint
        response = requests.get(
            f"{payroll_service_url}/payroll-org/check-exists/",
            params={'business_id': business_id},
            headers={
                'Authorization': f'Bearer {get_internal_service_token()}',
                'Content-Type': 'application/json'
            },
            timeout=10  # 10 second timeout
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Failed to check PayrollOrg existence: {response.text}")
            return {'exists': False, 'error': response.text}
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error while checking PayrollOrg existence: {str(e)}")
        return {'exists': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error checking PayrollOrg existence: {str(e)}")
        return {'exists': False, 'error': str(e)}


def handle_payroll_module_registration(context, user, registration_data):
    """
    Handle Payroll module registration by creating PayrollOrg and related entities.
    
    This function is called during business registration when Payroll module is selected.
    
    Args:
        context: Context object created during business registration
        user: User object created during business registration
        registration_data: Original registration request data
    
    Returns:
        dict: Success response with PayrollOrg details
    
    Raises:
        Exception: If PayrollOrg creation fails
    """
    try:
        # First check if PayrollOrg already exists
        check_result = check_payroll_org_exists(context.business.id)
        if check_result.get('exists', False):
            logger.warning(f"PayrollOrg already exists for business_id: {context.business.id}")
            return {
                'payroll_org_created': False,
                'message': 'PayrollOrg already exists for this business',
                'existing_payroll_org': check_result.get('payroll_org')
            }
        
        # Create PayrollOrg
        payroll_response = create_payroll_org_for_business_registration(
            context, user, registration_data
        )
        
        return {
            'payroll_org_created': True,
            'message': 'PayrollOrg created successfully for business registration',
            'payroll_org': payroll_response
        }
        
    except Exception as e:
        error_msg = f"Failed to handle Payroll module registration: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)
