# 🎯 PRECISE REGISTRATION FLOW - STEP BY STEP

## 📋 **EXACT REGISTRATION FLOW BREAKDOWN**

### **🔍 STEP 1: REQUEST ARRIVAL**
```
User Action: User goes to /register/business
System Action: Request hits zoho_style_register() endpoint
```

### **🔍 STEP 2: REGISTRATION TYPE DETECTION**
```python
# Function: detect_registration_type_from_url(request)
# Input: request with path="/register/business"
# Process:
1. Extract url_path = "/register/business"
2. Extract referer = "https://example.com/register/business"
3. Loop through registration_mappings:
   - Check 'business' patterns: [r'^/register/business', r'^/business/register']
   - Match found: r'^/register/business' matches "/register/business"
4. Return:
{
    'registration_type': 'business',
    'registration_flow': 'module',
    'account_type': 'business',
    'description': 'Business Registration with Module Subscription',
    'required_fields': ['email', 'password', 'business_name', 'module_id', 'otp'],
    'detected_from': 'url_path'
}
```

### **🔍 STEP 3: ROUTING DECISION**
```python
# Function: zoho_style_register(request)
# Process:
1. registration_config = detect_registration_type_from_url(request)
2. registration_type = registration_config['registration_type']  # 'business'
3. if registration_type == 'business':
       return handle_business_registration(request, registration_config)
```

---

## 🎯 **BUSINESS REGISTRATION FLOW (PRECISE)**

### **STEP 1: Data Extraction**
```python
# Function: handle_business_registration(request, config)
# Input: request.data = {
#     "email": "business@example.com",
#     "password": "password123",
#     "business_name": "My Business",
#     "module_id": "1",
#     "otp": "123456"
# }
# Process:
email = request.data.get('email')           # "business@example.com"
password = request.data.get('password')     # "password123"
business_name = request.data.get('business_name')  # "My Business"
module_id = request.data.get('module_id')   # "1"
submitted_otp = request.data.get('otp')     # "123456"
```

### **STEP 2: Field Validation**
```python
# Process:
required_fields = config['required_fields']  # ['email', 'password', 'business_name', 'module_id', 'otp']
missing_fields = [field for field in required_fields if not request.data.get(field)]

# Check each field:
- email: "business@example.com" ✅ (exists)
- password: "password123" ✅ (exists)
- business_name: "My Business" ✅ (exists)
- module_id: "1" ✅ (exists)
- otp: "123456" ✅ (exists)

# Result: missing_fields = [] (empty, all fields present)
```

### **STEP 3: OTP Validation**
```python
# Process:
1. otp_obj = PendingUserOTP.objects.get(email="business@example.com")
2. Check: otp_obj.is_expired() → False ✅
3. Check: otp_obj.otp_code == "123456" → True ✅
# Result: OTP is valid
```

### **STEP 4: User Existence Check**
```python
# Process:
if User.objects.filter(email="business@example.com").exists():
    return Response({"error": "User already exists"})
# Result: User doesn't exist ✅
```

### **STEP 5: Module Validation**
```python
# Process:
module = Module.objects.get(id=1)
# Result: Module exists ✅

trial_plan = SubscriptionPlan.objects.filter(
    module=module, 
    plan_type='trial', 
    is_active=True
).first()
# Result: Trial plan exists ✅
```

### **STEP 6: Database Transaction (ATOMIC)**
```python
# Process: with transaction.atomic():
# 6.1 Create User
user = User.objects.create_user(
    email="business@example.com",
    password="password123",
    is_active=True,
    registration_flow='module',  # From config
    registration_completed=False,
    status='active',
    is_super_admin=False,
)
# Result: User created with ID=123

# 6.2 Create Business Context
context = Context.objects.create(
    name="My Business",
    context_type='business',  # From config
    owner_user=user,  # ID=123
    status='active',
    profile_status='incomplete',
    metadata={'account_type': 'business'}
)
# Result: Context created with ID=456

# 6.3 Set Active Context
user.active_context = context  # ID=456
user.save()

# 6.4 Get System Role
system_role = Role.objects.filter(
    name='System Admin',
    context_type='business'
).first()
# Result: Role found with ID=789

# 6.5 Assign Role
UserContextRole.objects.create(
    user=user,  # ID=123
    context=context,  # ID=456
    role=system_role,  # ID=789
    status='active',
    added_by=user  # ID=123
)
# Result: UserContextRole created

# 6.6 Create Module Subscription
ModuleSubscription.objects.create(
    context=context,  # ID=456
    module=module,  # ID=1
    subscription_plan=trial_plan,
    status='active',
    start_date=timezone.now(),
    end_date=timezone.now() + timezone.timedelta(days=trial_plan.duration_days),
    is_trial=True
)
# Result: ModuleSubscription created

# 6.7 Delete OTP
otp_obj.delete()
# Result: OTP deleted

# 6.8 Get Login Response
login_response_data = get_login_response(user)
# Result: JWT tokens generated
```

### **STEP 7: Response Generation**
```python
# Process:
return Response({
    'success': True,
    'message': 'Business registration successful',
    'registration_type': 'business',
    'user': {
        'id': 123,
        'email': 'business@example.com',
        'is_active': True,
        'registration_flow': 'module'
    },
    'tokens': {
        'access': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...',
        'refresh': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...'
    },
    'context': {
        'id': 456,
        'name': 'My Business',
        'type': 'business'
    },
    'module': {
        'id': 1,
        'name': 'Payroll Management'
    }
}, status=status.HTTP_201_CREATED)
```

---

## 🎯 **SERVICE REGISTRATION FLOW (PRECISE)**

### **STEP 1: Data Extraction**
```python
# Input: request.data = {
#     "email": "user@example.com",
#     "password": "password123",
#     "name": "John Doe",
#     "service_id": "2",
#     "otp": "123456"
# }
# Process:
email = "user@example.com"
password = "password123"
name = "John Doe"
service_id = "2"
submitted_otp = "123456"
```

### **STEP 2: Field Validation**
```python
# Process:
required_fields = ['email', 'password', 'name', 'service_id', 'otp']
# All fields present ✅
```

### **STEP 3: OTP Validation**
```python
# Process:
otp_obj = PendingUserOTP.objects.get(email="user@example.com")
# OTP valid ✅
```

### **STEP 4: User Existence Check**
```python
# Process:
User.objects.filter(email="user@example.com").exists() → False ✅
```

### **STEP 5: Service Validation**
```python
# Process:
service = Service.objects.get(id=2)
# Result: Service exists ✅
```

### **STEP 6: Database Transaction (ATOMIC)**
```python
# Process: with transaction.atomic():
# 6.1 Create User
user = User.objects.create_user(
    email="user@example.com",
    password="password123",
    is_active=True,
    registration_flow='service',  # From config
    registration_completed=False,
    status='active',
    is_super_admin=False,
)

# 6.2 Create Context
context = Context.objects.create(
    name="John Doe",
    context_type='business',  # From config
    owner_user=user,
    status='active',
    profile_status='incomplete',
    metadata={'account_type': 'business'}
)

# 6.3 Set Active Context
user.active_context = context
user.save()

# 6.4 Get System Role
system_role = Role.objects.filter(
    name='System Admin',
    context_type='business'
).first()

# 6.5 Assign Role
UserContextRole.objects.create(
    user=user,
    context=context,
    role=system_role,
    status='active',
    added_by=user
)

# 6.6 Create Service Request
ServiceRequest.objects.create(
    user=user,
    context=context,
    service=service,
    status='initiated'
)

# 6.7 Delete OTP
otp_obj.delete()

# 6.8 Get Login Response
login_response_data = get_login_response(user)
```

### **STEP 7: Response Generation**
```python
# Process:
return Response({
    'success': True,
    'message': 'Service registration successful',
    'registration_type': 'service',
    'user': {...},
    'tokens': {...},
    'context': {
        'id': 457,
        'name': 'John Doe',
        'type': 'business'
    },
    'service': {
        'id': 2,
        'name': 'Invoice Management'
    }
}, status=status.HTTP_201_CREATED)
```

---

## 🎯 **PERSONAL REGISTRATION FLOW (PRECISE)**

### **STEP 1: Data Extraction**
```python
# Input: request.data = {
#     "email": "personal@example.com",
#     "password": "password123",
#     "otp": "123456"
# }
# Process:
email = "personal@example.com"
password = "password123"
submitted_otp = "123456"
```

### **STEP 2: Field Validation**
```python
# Process:
required_fields = ['email', 'password', 'otp']
# All fields present ✅
```

### **STEP 3: OTP Validation**
```python
# Process:
otp_obj = PendingUserOTP.objects.get(email="personal@example.com")
# OTP valid ✅
```

### **STEP 4: User Existence Check**
```python
# Process:
User.objects.filter(email="personal@example.com").exists() → False ✅
```

### **STEP 5: Database Transaction (ATOMIC)**
```python
# Process: with transaction.atomic():
# 5.1 Create User
user = User.objects.create(
    email="personal@example.com",
    status='active',
    registration_flow='standard',  # From config
    registration_completed=False,
    is_active=True,
    is_super_admin=False,
)
user.set_password("password123")
user.save()

# 5.2 Delete OTP
otp_obj.delete()

# 5.3 Get Login Response
login_response_data = get_login_response(user)
```

### **STEP 6: Response Generation**
```python
# Process:
return Response({
    'success': True,
    'message': 'Standard registration successful',
    'registration_type': 'standard',
    'user': {...},
    'tokens': {...}
}, status=status.HTTP_201_CREATED)
```

---

## 🎯 **ERROR HANDLING FLOW (PRECISE)**

### **Field Validation Error**
```python
# Input: Missing 'business_name' field
# Process:
missing_fields = ['business_name']
# Result:
return Response({
    'error': 'Missing required fields: business_name'
}, status=status.HTTP_400_BAD_REQUEST)
```

### **OTP Validation Error**
```python
# Input: Invalid OTP "999999"
# Process:
otp_obj.otp_code != "999999" → True
# Result:
return Response({'error': 'Invalid OTP'}, status=status.HTTP_400_BAD_REQUEST)
```

### **User Exists Error**
```python
# Input: Email already exists
# Process:
User.objects.filter(email="existing@example.com").exists() → True
# Result:
return Response({
    'error': 'User already exists with this email'
}, status=status.HTTP_400_BAD_REQUEST)
```

### **Module Not Found Error**
```python
# Input: module_id = 999 (doesn't exist)
# Process:
Module.objects.get(id=999) → DoesNotExist
# Result:
return Response({
    'error': 'Module with ID 999 does not exist'
}, status=status.HTTP_404_NOT_FOUND)
```

### **Database Transaction Error**
```python
# Input: Database constraint violation
# Process:
with transaction.atomic():
    # Any error here rolls back entire transaction
    raise IntegrityError("Constraint violation")
# Result:
return Response({
    'error': 'Business registration failed: Constraint violation'
}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
```

---

## 🎯 **SUMMARY: EXACT FLOW SEQUENCE**

### **For Business Registration:**
```
1. Request → /register/business
2. Detect → registration_type = 'business'
3. Route → handle_business_registration()
4. Extract → email, password, business_name, module_id, otp
5. Validate → All required fields present
6. Validate → OTP is valid and not expired
7. Validate → User doesn't exist
8. Validate → Module exists
9. Validate → Trial plan exists
10. Create → User + Context + Role + ModuleSubscription (ATOMIC)
11. Delete → OTP after successful creation
12. Generate → JWT tokens
13. Return → Success response with user, tokens, context, module
```

### **For Service Registration:**
```
1. Request → /register/service
2. Detect → registration_type = 'service'
3. Route → handle_service_registration()
4. Extract → email, password, name, service_id, otp
5. Validate → All required fields present
6. Validate → OTP is valid and not expired
7. Validate → User doesn't exist
8. Validate → Service exists
9. Create → User + Context + Role + ServiceRequest (ATOMIC)
10. Delete → OTP after successful creation
11. Generate → JWT tokens
12. Return → Success response with user, tokens, context, service
```

### **For Personal Registration:**
```
1. Request → /register/personal
2. Detect → registration_type = 'personal'
3. Route → handle_standard_registration()
4. Extract → email, password, otp
5. Validate → All required fields present
6. Validate → OTP is valid and not expired
7. Validate → User doesn't exist
8. Create → User only (ATOMIC)
9. Delete → OTP after successful creation
10. Generate → JWT tokens
11. Return → Success response with user, tokens
```

**This is the exact, precise flow for each registration type!** 🎯

