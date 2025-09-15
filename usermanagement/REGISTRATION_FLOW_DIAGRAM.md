# 🎯 PRECISE REGISTRATION FLOW DIAGRAM

## 📋 **VISUAL FLOW BREAKDOWN**

### **🔍 MAIN REGISTRATION FLOW**
```
┌─────────────────────────────────────────────────────────────────┐
│                    ZOHO-STYLE REGISTRATION FLOW                 │
└─────────────────────────────────────────────────────────────────┘

1. REQUEST ARRIVAL
   ┌─────────────────┐
   │ User Action     │
   │ /register/business │
   └─────────────────┘
           │
           ▼
   ┌─────────────────┐
   │ System Action   │
   │ zoho_style_register() │
   └─────────────────┘
           │
           ▼

2. TYPE DETECTION
   ┌─────────────────┐
   │ detect_registration_type_from_url() │
   │                                     │
   │ Input: "/register/business"         │
   │ Process:                           │
   │ - Extract url_path                 │
   │ - Check patterns                   │
   │ - Match: r'^/register/business'    │
   │                                     │
   │ Output:                            │
   │ {                                  │
   │   'registration_type': 'business', │
   │   'registration_flow': 'module',   │
   │   'account_type': 'business',      │
   │   'required_fields': [...]         │
   │ }                                  │
   └─────────────────┘
           │
           ▼

3. ROUTING DECISION
   ┌─────────────────┐
   │ if registration_type == 'business': │
   │   return handle_business_registration() │
   │ elif registration_type == 'service':    │
   │   return handle_service_registration()  │
   │ elif registration_type == 'personal':   │
   │   return handle_standard_registration() │
   └─────────────────┘
           │
           ▼

4. SPECIFIC HANDLER
   ┌─────────────────┐
   │ handle_business_registration() │
   │                                 │
   │ Input: request + config         │
   │ Process:                        │
   │ - Extract data                  │
   │ - Validate fields               │
   │ - Validate OTP                  │
   │ - Validate user existence       │
   │ - Validate module               │
   │ - Create user + context         │
   │ - Assign role                   │
   │ - Create subscription           │
   │ - Generate tokens               │
   │                                 │
   │ Output: Success response        │
   └─────────────────┘
```

---

## 🎯 **BUSINESS REGISTRATION FLOW (DETAILED)**

```
┌─────────────────────────────────────────────────────────────────┐
│                    BUSINESS REGISTRATION FLOW                   │
└─────────────────────────────────────────────────────────────────┘

1. DATA EXTRACTION
   ┌─────────────────┐
   │ Input Data:     │
   │ {               │
   │   "email": "business@example.com", │
   │   "password": "password123",       │
   │   "business_name": "My Business",  │
   │   "module_id": "1",               │
   │   "otp": "123456"                 │
   │ }               │
   └─────────────────┘
           │
           ▼

2. FIELD VALIDATION
   ┌─────────────────┐
   │ Required Fields: │
   │ ['email', 'password', 'business_name', 'module_id', 'otp'] │
   │                 │
   │ Check Each:     │
   │ ✅ email: "business@example.com" │
   │ ✅ password: "password123"       │
   │ ✅ business_name: "My Business"  │
   │ ✅ module_id: "1"               │
   │ ✅ otp: "123456"                │
   │                 │
   │ Result: All fields present ✅   │
   └─────────────────┘
           │
           ▼

3. OTP VALIDATION
   ┌─────────────────┐
   │ Process:        │
   │ 1. Get OTP from DB │
   │ 2. Check expiration │
   │ 3. Verify code  │
   │                 │
   │ Result: OTP valid ✅ │
   └─────────────────┘
           │
           ▼

4. USER EXISTENCE CHECK
   ┌─────────────────┐
   │ Process:        │
   │ User.objects.filter(email="business@example.com").exists() │
   │                 │
   │ Result: User doesn't exist ✅ │
   └─────────────────┘
           │
           ▼

5. MODULE VALIDATION
   ┌─────────────────┐
   │ Process:        │
   │ 1. Get Module by ID │
   │ 2. Get Trial Plan │
   │                 │
   │ Result: Module + Trial Plan exist ✅ │
   └─────────────────┘
           │
           ▼

6. DATABASE TRANSACTION (ATOMIC)
   ┌─────────────────┐
   │ with transaction.atomic(): │
   │                 │
   │ 6.1 Create User │
   │     - email: "business@example.com" │
   │     - password: "password123"       │
   │     - registration_flow: 'module'   │
   │     - is_active: True               │
   │                 │
   │ 6.2 Create Context │
   │     - name: "My Business"           │
   │     - context_type: 'business'      │
   │     - owner_user: user              │
   │     - status: 'active'              │
   │                 │
   │ 6.3 Set Active Context │
   │     user.active_context = context   │
   │                 │
   │ 6.4 Get System Role │
   │     Role.objects.filter(name='System Admin') │
   │                 │
   │ 6.5 Assign Role │
   │     UserContextRole.objects.create() │
   │                 │
   │ 6.6 Create Module Subscription │
   │     ModuleSubscription.objects.create() │
   │                 │
   │ 6.7 Delete OTP  │
   │     otp_obj.delete() │
   │                 │
   │ 6.8 Generate Tokens │
   │     get_login_response(user) │
   │                 │
   │ Result: All operations successful ✅ │
   └─────────────────┘
           │
           ▼

7. RESPONSE GENERATION
   ┌─────────────────┐
   │ Response:       │
   │ {               │
   │   "success": true, │
   │   "message": "Business registration successful", │
   │   "registration_type": "business", │
   │   "user": {...}, │
   │   "tokens": {...}, │
   │   "context": {...}, │
   │   "module": {...} │
   │ }               │
   │                 │
   │ Status: 201 CREATED │
   └─────────────────┘
```

---

## 🎯 **SERVICE REGISTRATION FLOW (DETAILED)**

```
┌─────────────────────────────────────────────────────────────────┐
│                    SERVICE REGISTRATION FLOW                    │
└─────────────────────────────────────────────────────────────────┘

1. DATA EXTRACTION
   ┌─────────────────┐
   │ Input Data:     │
   │ {               │
   │   "email": "user@example.com", │
   │   "password": "password123",   │
   │   "name": "John Doe",          │
   │   "service_id": "2",           │
   │   "otp": "123456"              │
   │ }               │
   └─────────────────┘
           │
           ▼

2. FIELD VALIDATION
   ┌─────────────────┐
   │ Required Fields: │
   │ ['email', 'password', 'name', 'service_id', 'otp'] │
   │                 │
   │ Check Each:     │
   │ ✅ email: "user@example.com" │
   │ ✅ password: "password123"   │
   │ ✅ name: "John Doe"          │
   │ ✅ service_id: "2"           │
   │ ✅ otp: "123456"             │
   │                 │
   │ Result: All fields present ✅ │
   └─────────────────┘
           │
           ▼

3. OTP VALIDATION
   ┌─────────────────┐
   │ Process:        │
   │ 1. Get OTP from DB │
   │ 2. Check expiration │
   │ 3. Verify code  │
   │                 │
   │ Result: OTP valid ✅ │
   └─────────────────┘
           │
           ▼

4. USER EXISTENCE CHECK
   ┌─────────────────┐
   │ Process:        │
   │ User.objects.filter(email="user@example.com").exists() │
   │                 │
   │ Result: User doesn't exist ✅ │
   └─────────────────┘
           │
           ▼

5. SERVICE VALIDATION
   ┌─────────────────┐
   │ Process:        │
   │ Service.objects.get(id=2) │
   │                 │
   │ Result: Service exists ✅ │
   └─────────────────┘
           │
           ▼

6. DATABASE TRANSACTION (ATOMIC)
   ┌─────────────────┐
   │ with transaction.atomic(): │
   │                 │
   │ 6.1 Create User │
   │     - email: "user@example.com" │
   │     - password: "password123"   │
   │     - registration_flow: 'service' │
   │     - is_active: True               │
   │                 │
   │ 6.2 Create Context │
   │     - name: "John Doe"              │
   │     - context_type: 'business'      │
   │     - owner_user: user              │
   │     - status: 'active'              │
   │                 │
   │ 6.3 Set Active Context │
   │     user.active_context = context   │
   │                 │
   │ 6.4 Get System Role │
   │     Role.objects.filter(name='System Admin') │
   │                 │
   │ 6.5 Assign Role │
   │     UserContextRole.objects.create() │
   │                 │
   │ 6.6 Create Service Request │
   │     ServiceRequest.objects.create() │
   │                 │
   │ 6.7 Delete OTP  │
   │     otp_obj.delete() │
   │                 │
   │ 6.8 Generate Tokens │
   │     get_login_response(user) │
   │                 │
   │ Result: All operations successful ✅ │
   └─────────────────┘
           │
           ▼

7. RESPONSE GENERATION
   ┌─────────────────┐
   │ Response:       │
   │ {               │
   │   "success": true, │
   │   "message": "Service registration successful", │
   │   "registration_type": "service", │
   │   "user": {...}, │
   │   "tokens": {...}, │
   │   "context": {...}, │
   │   "service": {...} │
   │ }               │
   │                 │
   │ Status: 201 CREATED │
   └─────────────────┘
```

---

## 🎯 **PERSONAL REGISTRATION FLOW (DETAILED)**

```
┌─────────────────────────────────────────────────────────────────┐
│                    PERSONAL REGISTRATION FLOW                   │
└─────────────────────────────────────────────────────────────────┘

1. DATA EXTRACTION
   ┌─────────────────┐
   │ Input Data:     │
   │ {               │
   │   "email": "personal@example.com", │
   │   "password": "password123",       │
   │   "otp": "123456"                  │
   │ }               │
   └─────────────────┘
           │
           ▼

2. FIELD VALIDATION
   ┌─────────────────┐
   │ Required Fields: │
   │ ['email', 'password', 'otp'] │
   │                 │
   │ Check Each:     │
   │ ✅ email: "personal@example.com" │
   │ ✅ password: "password123"       │
   │ ✅ otp: "123456"                 │
   │                 │
   │ Result: All fields present ✅   │
   └─────────────────┘
           │
           ▼

3. OTP VALIDATION
   ┌─────────────────┐
   │ Process:        │
   │ 1. Get OTP from DB │
   │ 2. Check expiration │
   │ 3. Verify code  │
   │                 │
   │ Result: OTP valid ✅ │
   └─────────────────┘
           │
           ▼

4. USER EXISTENCE CHECK
   ┌─────────────────┐
   │ Process:        │
   │ User.objects.filter(email="personal@example.com").exists() │
   │                 │
   │ Result: User doesn't exist ✅ │
   └─────────────────┘
           │
           ▼

5. DATABASE TRANSACTION (ATOMIC)
   ┌─────────────────┐
   │ with transaction.atomic(): │
   │                 │
   │ 5.1 Create User │
   │     - email: "personal@example.com" │
   │     - password: "password123"       │
   │     - registration_flow: 'standard' │
   │     - is_active: True               │
   │     - set_password()                │
   │                 │
   │ 5.2 Delete OTP  │
   │     otp_obj.delete() │
   │                 │
   │ 5.3 Generate Tokens │
   │     get_login_response(user) │
   │                 │
   │ Result: All operations successful ✅ │
   └─────────────────┘
           │
           ▼

6. RESPONSE GENERATION
   ┌─────────────────┐
   │ Response:       │
   │ {               │
   │   "success": true, │
   │   "message": "Standard registration successful", │
   │   "registration_type": "standard", │
   │   "user": {...}, │
   │   "tokens": {...} │
   │ }               │
   │                 │
   │ Status: 201 CREATED │
   └─────────────────┘
```

---

## 🎯 **ERROR HANDLING FLOW**

```
┌─────────────────────────────────────────────────────────────────┐
│                        ERROR HANDLING FLOW                      │
└─────────────────────────────────────────────────────────────────┘

1. FIELD VALIDATION ERROR
   ┌─────────────────┐
   │ Input: Missing 'business_name' │
   │                 │
   │ Process:        │
   │ missing_fields = ['business_name'] │
   │                 │
   │ Response:       │
   │ {               │
   │   "error": "Missing required fields: business_name" │
   │ }               │
   │                 │
   │ Status: 400 BAD REQUEST │
   └─────────────────┘

2. OTP VALIDATION ERROR
   ┌─────────────────┐
   │ Input: Invalid OTP "999999" │
   │                 │
   │ Process:        │
   │ otp_obj.otp_code != "999999" → True │
   │                 │
   │ Response:       │
   │ {               │
   │   "error": "Invalid OTP" │
   │ }               │
   │                 │
   │ Status: 400 BAD REQUEST │
   └─────────────────┘

3. USER EXISTS ERROR
   ┌─────────────────┐
   │ Input: Email already exists │
   │                 │
   │ Process:        │
   │ User.objects.filter(email="existing@example.com").exists() → True │
   │                 │
   │ Response:       │
   │ {               │
   │   "error": "User already exists with this email" │
   │ }               │
   │                 │
   │ Status: 400 BAD REQUEST │
   └─────────────────┘

4. MODULE NOT FOUND ERROR
   ┌─────────────────┐
   │ Input: module_id = 999 (doesn't exist) │
   │                 │
   │ Process:        │
   │ Module.objects.get(id=999) → DoesNotExist │
   │                 │
   │ Response:       │
   │ {               │
   │   "error": "Module with ID 999 does not exist" │
   │ }               │
   │                 │
   │ Status: 404 NOT FOUND │
   └─────────────────┘

5. DATABASE TRANSACTION ERROR
   ┌─────────────────┐
   │ Input: Database constraint violation │
   │                 │
   │ Process:        │
   │ with transaction.atomic(): │
   │   # Any error here rolls back entire transaction │
   │   raise IntegrityError("Constraint violation") │
   │                 │
   │ Response:       │
   │ {               │
   │   "error": "Business registration failed: Constraint violation" │
   │ }               │
   │                 │
   │ Status: 500 INTERNAL SERVER ERROR │
   └─────────────────┘
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

**This is the exact, precise flow for each registration type with every step detailed!** 🎯

