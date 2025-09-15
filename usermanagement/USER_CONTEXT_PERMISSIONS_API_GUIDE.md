# User Context & Permissions API Guide

## Overview
This guide covers the new User Context and Permissions APIs that provide comprehensive access to user session management, context information, and module permissions.

## API Endpoints

### 1. Get Current User Session
**Endpoint:** `GET /user/current-session/`  
**Authentication:** Required (JWT Token)  
**Description:** Retrieves the current user's active session and context information.

#### Response Example:
```json
{
    "session_id": 1,
    "is_active": true,
    "default_session": true,
    "session_data": {
        "registration_type": "business"
    },
    "context": {
        "context_id": 1,
        "context_name": "My Business",
        "context_type": "business",
        "status": "active",
        "profile_status": "complete",
        "metadata": {
            "account_type": "business"
        },
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z"
    },
    "role": {
        "role_id": 1,
        "role_type": "owner",
        "role_name": "Business Owner",
        "permissions": ["view_business", "edit_business", "manage_users"]
    },
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
}
```

---

### 2. List All User Contexts
**Endpoint:** `GET /user/contexts/`  
**Authentication:** Required (JWT Token)  
**Description:** Lists all contexts that the user has access to with their roles and module subscriptions.

#### Response Example:
```json
{
    "total_contexts": 2,
    "contexts": [
        {
            "context_id": 1,
            "context_name": "My Business",
            "context_type": "business",
            "status": "active",
            "profile_status": "complete",
            "metadata": {
                "account_type": "business"
            },
            "is_default_session": true,
            "user_role": {
                "role_id": 1,
                "role_type": "owner",
                "role_name": "Business Owner",
                "permissions": ["view_business", "edit_business", "manage_users"]
            },
            "module_subscriptions": [
                {
                    "subscription_id": 1,
                    "module_id": 1,
                    "module_name": "Payroll",
                    "module_description": "Payroll management system",
                    "status": "active",
                    "start_date": "2024-01-01T00:00:00Z",
                    "end_date": "2024-12-31T23:59:59Z",
                    "auto_renew": true,
                    "plan_name": "Professional Plan",
                    "plan_type": "monthly"
                }
            ],
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z"
        }
    ]
}
```

---

### 3. Get Module Permissions
**Endpoint:** `GET /module/{module_id}/permissions/`  
**Authentication:** Required (JWT Token)  
**Description:** Retrieves all permissions available for a specific module.

#### Parameters:
- `module_id` (path): ID of the module

#### Response Example:
```json
{
    "module_id": 1,
    "module_name": "Payroll",
    "module_description": "Payroll management system",
    "module_type": "business",
    "is_active": true,
    "total_features": 3,
    "features": [
        {
            "feature_id": 1,
            "feature_name": "Employee Management",
            "feature_description": "Manage employee records",
            "feature_type": "core",
            "is_active": true,
            "permissions": ["view_employees", "add_employee", "edit_employee", "delete_employee"]
        },
        {
            "feature_id": 2,
            "feature_name": "Salary Processing",
            "feature_description": "Process employee salaries",
            "feature_type": "core",
            "is_active": true,
            "permissions": ["view_salaries", "process_salary", "approve_salary"]
        }
    ],
    "all_permissions": [
        "view_employees", "add_employee", "edit_employee", "delete_employee",
        "view_salaries", "process_salary", "approve_salary"
    ],
    "total_permissions": 7
}
```

---

### 4. Check Module Access
**Endpoint:** `GET /module/{module_id}/access/`  
**Authentication:** Required (JWT Token)  
**Description:** Checks if the user has access to a specific module in their current context.

#### Parameters:
- `module_id` (path): ID of the module to check access for

#### Response Examples:

**✅ User Has Access:**
```json
{
    "has_access": true,
    "reason": "Active subscription found",
    "module_id": 1,
    "module_name": "Payroll",
    "context_id": 1,
    "context_name": "My Business",
    "subscription_id": 1,
    "subscription_status": "active",
    "subscription_start_date": "2024-01-01T00:00:00Z",
    "subscription_end_date": "2024-12-31T23:59:59Z",
    "auto_renew": true,
    "user_role": {
        "role_id": 1,
        "role_type": "owner",
        "role_name": "Business Owner"
    }
}
```

**❌ User No Access:**
```json
{
    "has_access": false,
    "reason": "No active subscription for this module",
    "module_id": 2,
    "module_name": "Invoicing",
    "context_id": 1,
    "context_name": "My Business",
    "user_role": {
        "role_id": 1,
        "role_type": "owner",
        "role_name": "Business Owner"
    }
}
```

---

### 5. Get User Permissions Summary
**Endpoint:** `GET /user/permissions-summary/`  
**Authentication:** Required (JWT Token)  
**Description:** Provides a comprehensive summary of user's permissions across all contexts and modules.

#### Response Example:
```json
{
    "user_id": 1,
    "user_email": "user@example.com",
    "current_context": {
        "context_id": 1,
        "context_name": "My Business",
        "context_type": "business"
    },
    "summary": {
        "total_contexts": 2,
        "total_modules": 3,
        "total_permissions": 15,
        "all_permissions": [
            "view_business", "edit_business", "manage_users",
            "view_employees", "add_employee", "edit_employee",
            "view_salaries", "process_salary", "approve_salary"
        ]
    },
    "contexts": [
        {
            "context_id": 1,
            "context_name": "My Business",
            "context_type": "business",
            "is_current_context": true,
            "user_role": {
                "role_id": 1,
                "role_type": "owner",
                "role_name": "Business Owner",
                "permissions": ["view_business", "edit_business", "manage_users"]
            },
            "module_subscriptions": [
                {
                    "subscription_id": 1,
                    "module_id": 1,
                    "module_name": "Payroll",
                    "status": "active",
                    "start_date": "2024-01-01T00:00:00Z",
                    "end_date": "2024-12-31T23:59:59Z",
                    "auto_renew": true
                }
            ],
            "total_modules": 1
        }
    ]
}
```

## Usage Examples

### Frontend Integration

#### 1. Get Current Session (for navigation/header)
```javascript
const getCurrentSession = async () => {
    const response = await fetch('/user/current-session/', {
        headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
        }
    });
    const data = await response.json();
    return data;
};
```

#### 2. Check Module Access (before showing features)
```javascript
const checkModuleAccess = async (moduleId) => {
    const response = await fetch(`/module/${moduleId}/access/`, {
        headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
        }
    });
    const data = await response.json();
    return data.has_access;
};
```

#### 3. List All Contexts (for context switcher)
```javascript
const getUserContexts = async () => {
    const response = await fetch('/user/contexts/', {
        headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
        }
    });
    const data = await response.json();
    return data.contexts;
};
```

### Microservice Integration

#### 1. Validate User Access in Payroll Service
```python
import requests

def validate_user_access(user_token, module_id):
    headers = {
        'Authorization': f'Bearer {user_token}',
        'Content-Type': 'application/json'
    }
    
    response = requests.get(
        f'http://usermanagement-service/module/{module_id}/access/',
        headers=headers
    )
    
    if response.status_code == 200:
        data = response.json()
        return data.get('has_access', False)
    
    return False
```

## Error Handling

All APIs return appropriate HTTP status codes:

- **200 OK**: Success
- **401 Unauthorized**: Invalid or missing authentication token
- **404 Not Found**: Resource not found (e.g., module doesn't exist)
- **500 Internal Server Error**: Server error

Error responses follow this format:
```json
{
    "error": "Error message describing what went wrong"
}
```

## Security Notes

1. **Authentication Required**: All endpoints require valid JWT authentication
2. **Context Isolation**: Users can only access their own contexts and permissions
3. **Role-Based Access**: Permissions are checked based on user's role in the current context
4. **Subscription Validation**: Module access is validated against active subscriptions

## Performance Considerations

1. **Database Optimization**: APIs use `select_related()` for efficient queries
2. **Caching**: Consider implementing Redis caching for frequently accessed data
3. **Pagination**: For large datasets, consider adding pagination parameters
4. **Rate Limiting**: Implement rate limiting for production use

## Future Enhancements

1. **Real-time Updates**: WebSocket integration for live permission updates
2. **Bulk Operations**: APIs for checking multiple modules at once
3. **Audit Logging**: Track permission checks and access attempts
4. **Advanced Filtering**: Filter contexts by type, status, or other criteria
