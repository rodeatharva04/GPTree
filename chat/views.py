from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Conversation, Message, MessageFile, EmailVerification, UserProfile
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.conf import settings
import json
import os
import requests
from PIL import Image
import google.generativeai as genai

# Initialize Gemini
api_key = getattr(settings, 'GOOGLE_API_KEY', None) or os.environ.get("GOOGLE_API_KEY")

if api_key and genai:
    genai.configure(api_key=api_key)

def send_brevo_email(subject, content, to_email):
    """Fallback to HTTP API since SMTP is failing with 535"""
    api_key = getattr(settings, 'EMAIL_HOST_PASSWORD', '')
    url = "https://api.brevo.com/v3/smtp/email"
    payload = {
        "sender": {"name": "GPTree", "email": settings.DEFAULT_FROM_EMAIL},
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": content
    }
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": api_key
    }
    try:
        response = requests.post(url, json=payload, headers=headers)
        return response.status_code in [201, 202, 200]
    except Exception as e:
        print(f"Brevo API Error: {e}")
        return False

@login_required
def index(request):
    return render(request, 'chat/index.html')

@csrf_exempt
def register_view(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')

        existing_user = User.objects.filter(username=username).first()
        if existing_user:
            if existing_user.is_active:
                return JsonResponse({'error': 'Username already exists'}, status=400)
            else:
                # Re-use inactive user: update details and send new OTP
                existing_user.email = email
                existing_user.set_password(password)
                existing_user.save()
                user = existing_user
                
                # Update or create verification record
                verification, _ = EmailVerification.objects.get_or_create(user=user)
        else:
            user = User.objects.create_user(username=username, email=email, password=password)
            user.is_active = False
            user.save()
            UserProfile.objects.create(user=user)
            verification = EmailVerification.objects.create(user=user)

        otp = verification.generate_otp()

        # Send Email
        success = send_brevo_email(
            'GPTree - Verify your Email',
            f'Your OTP for email verification is: {otp}',
            email
        )
        if not success:
            print(f"Email delivery failed for {email}")

        return JsonResponse({'status': 'ok', 'user_id': user.id})
    return render(request, 'chat/register.html')

@csrf_exempt
def verify_otp(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        user_id = data.get('user_id')
        otp = data.get('otp')

        verification = get_object_or_404(EmailVerification, user_id=user_id)
        if verification.otp == otp:
            verification.is_verified = True
            verification.save()
            
            user = verification.user
            user.is_active = True
            user.save()
            
            login(request, user)
            return JsonResponse({'status': 'ok'})
        else:
            return JsonResponse({'error': 'Invalid OTP'}, status=400)
    return JsonResponse({'error': 'Method not allowed'}, status=405)

@csrf_exempt
def login_view(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        username = data.get('username')
        password = data.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            if user.is_active:
                login(request, user)
                return JsonResponse({'status': 'ok'})
            else:
                return JsonResponse({'error': 'Account not verified', 'user_id': user.id}, status=403)
        else:
            return JsonResponse({'error': 'Invalid credentials'}, status=401)
    return render(request, 'chat/login.html')

@csrf_exempt
def forgot_password(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        email = data.get('email')
        user = User.objects.filter(email=email).first()
        
        if user:
            verification, _ = EmailVerification.objects.get_or_create(user=user)
            otp = verification.generate_otp()
            success = send_brevo_email(
                'GPTree - Password Reset OTP',
                f'Your OTP for password reset is: {otp}',
                email
            )
            if success:
                return JsonResponse({'status': 'ok', 'user_id': user.id})
            else:
                return JsonResponse({'error': 'Failed to send reset email'}, status=500)
        return JsonResponse({'error': 'Email not found'}, status=404)
    return JsonResponse({'error': 'Method not allowed'}, status=405)

@csrf_exempt
def reset_password(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        user_id = data.get('user_id')
        otp = data.get('otp')
        new_password = data.get('password')

        verification = get_object_or_404(EmailVerification, user_id=user_id)
        if verification.otp == otp:
            user = verification.user
            user.set_password(new_password)
            user.is_active = True # In case they were resetting while inactive
            user.save()
            return JsonResponse({'status': 'ok'})
        else:
            return JsonResponse({'error': 'Invalid OTP'}, status=400)
    return JsonResponse({'error': 'Method not allowed'}, status=405)

@login_required
@csrf_exempt
def get_user_settings(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return JsonResponse({
        'username': request.user.username,
        'full_name': profile.full_name,
        'profile_pic': profile.profile_pic.url if profile.profile_pic else None,
        'personal_prompt': profile.personal_prompt,
        'subscription_tier': profile.subscription_tier
    })

@login_required
@csrf_exempt
def update_user_settings(request):
    if request.method == 'POST':
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        
        full_name = request.POST.get('full_name')
        personal_prompt = request.POST.get('personal_prompt')
        profile_pic = request.FILES.get('profile_pic')

        if full_name is not None:
            profile.full_name = full_name
        if personal_prompt is not None:
            profile.personal_prompt = personal_prompt
        if profile_pic:
            profile.profile_pic = profile_pic
        
        profile.save()
        return JsonResponse({'status': 'ok'})
@csrf_exempt
def bmac_webhook(request):
    """
    Buy Me A Coffee Webhook Handler
    Updates user tier based on email matching.
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            # BMC often nests data under 'response'
            res = data.get('response', data)
            email = res.get('payer_email') or res.get('email')
            
            if not email:
                # Debug logging if needed
                print(f"BMAC Webhook received but no email found in: {data}")
                return JsonResponse({'error': 'No email found'}, status=400)

            user = User.objects.filter(email=email).first()
            if user:
                profile = user.profile
                # For now, any successful payment upgrades to 'plus'
                # You can extend this to check 'plan_id' or 'amount' for 'pro'
                profile.subscription_tier = 'plus'
                profile.subscription_status = 'active'
                profile.save()
                return JsonResponse({'status': 'upgraded'})
            
            return JsonResponse({'status': 'user_not_found'})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'POST required'}, status=405)

@csrf_exempt
def logout_view(request):
    logout(request)
    return JsonResponse({'status': 'ok'})

def get_tree(request):
    nodes = Conversation.objects.all().values('id', 'title', 'parent_id', 'created_at').order_by('created_at')
    return JsonResponse(list(nodes), safe=False)

@csrf_exempt
def create_conversation(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        parent_id = data.get('parent_id')
        title = data.get('title', 'New Chat')
        parent = None
        if parent_id:
            parent = Conversation.objects.get(id=parent_id)
        conv = Conversation.objects.create(title=title, parent=parent)
        return JsonResponse({'id': conv.id, 'title': conv.title, 'parent_id': conv.parent_id})
    return JsonResponse({'error': 'Invalid method'}, status=405)

@csrf_exempt
def update_conversation(request, conversation_id):
    conv = get_object_or_404(Conversation, id=conversation_id)
    if request.method == 'PUT':
        data = json.loads(request.body)
        conv.title = data.get('title', conv.title)
        conv.save()
        return JsonResponse({'status': 'ok'})
    elif request.method == 'DELETE':
        conv.delete()
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'error': 'Invalid method'}, status=405)

from .models import Conversation, Message, MessageFile

def get_messages(request, conversation_id):
    messages = []
    current = get_object_or_404(Conversation, id=conversation_id)
    
    path = []
    while current:
        path.append(current)
        current = current.parent
    path.reverse()
    
    for node in path:
        msgs = node.messages.all().prefetch_related('files')
        for m in msgs:
            msg_dict = {
                'id': m.id,
                'role': m.role,
                'content': m.content,
                'node_id': node.id,
                'node_title': node.title,
                'created_at': m.created_at.strftime("%I:%M %p") # 12-hour format
            }
            file_urls = [f.file.url for f in m.files.all()]
            msg_dict['file_urls'] = file_urls
            messages.append(msg_dict)
            
    return JsonResponse(messages, safe=False)

@csrf_exempt
def add_message(request, conversation_id):
    if request.method == 'POST':
        conv = get_object_or_404(Conversation, id=conversation_id)
        
        if request.content_type.startswith('multipart/form-data'):
            role = request.POST.get('role', 'user')
            content = request.POST.get('content', '')
            files = request.FILES.getlist('files') # Support multiple
            
            msg = Message.objects.create(
                conversation=conv,
                role=role,
                content=content
            )
            for f in files:
                MessageFile.objects.create(message=msg, file=f)
            return JsonResponse({'status': 'ok'})
        else:
            data = json.loads(request.body)
            msg = Message.objects.create(
                conversation=conv, 
                role=data.get('role'), 
                content=data.get('content')
            )
            return JsonResponse({'status': 'ok'})
            
    return JsonResponse({'error': 'Invalid method'}, status=405)

@csrf_exempt
def generate_reply(request, conversation_id):
    """
    Generates AI reply using Gemini, with context aware of the tree path.
    Supports multiple files and uses gemini-2.5-flash as the primary model.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)

    if not api_key:
         conv = get_object_or_404(Conversation, id=conversation_id)
         Message.objects.create(
             conversation=conv,
             role='ai',
             content="I am ready to help! Please set your GOOGLE_API_KEY in the environment."
         )
         return JsonResponse({'status': 'ok'})

    try:
        conv = get_object_or_404(Conversation, id=conversation_id)
        
        path = []
        current = conv
        while current:
            path.append(current)
            current = current.parent
        path.reverse()
        
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        system_instr = "You are a helpful AI assistant in GPTree."
        if profile.personal_prompt:
            system_instr += f"\n\nUSER PERSONAL INSTRUCTIONS:\n{profile.personal_prompt}"

        contents = []
        contents.append({"role": "user", "parts": [f"[System Note: {system_instr}]"]})
        
        for node in path:
            # Inject Branch Title context
            contents.append({"role": "user", "parts": [f"[Context: Entering conversation branch named '{node.title}']"]})
            
            node_messages = node.messages.all().order_by('created_at').prefetch_related('files')
            for m in node_messages:
                role = "user" if m.role == 'user' else "model"
                parts = []
                
                # Add all files (Images for now)
                for f in m.files.all():
                    try:
                        # Gemini SDK handles PIL Images for vision
                        img = Image.open(f.file.path)
                        parts.append(img)
                    except Exception as img_err:
                        print(f"Error loading file at {f.file.path}: {img_err}")
                
                if m.content:
                    parts.append(m.content)
                
                if parts:
                    contents.append({"role": role, "parts": parts})

        models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]
        ai_text = None
        error_msg = ""

        for model_name in models_to_try:
            try:
                print(f"Attempting to call model: {model_name}")
                model = genai.GenerativeModel(model_name)
                generation_config = {"temperature": 0.7, "max_output_tokens": 4096}
                response = model.generate_content(contents, generation_config=generation_config)
                if response and response.text:
                    ai_text = response.text
                    break
                else:
                    error_msg = f"Empty response from {model_name}"
            except Exception as e:
                print(f"Model {model_name} failed: {e}")
                error_msg = str(e)
                continue
        
        if not ai_text:
            return JsonResponse({'error': f"AI Error: {error_msg}"}, status=500)

        Message.objects.create(conversation=conv, role='ai', content=ai_text)
        return JsonResponse({'status': 'ok'})

    except Exception as e:
        print(f"Gemini General Error: {e}")
        return JsonResponse({'error': str(e)}, status=500)
