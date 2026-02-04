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
import threading
from datetime import datetime
try:
    from google import genai
    from google.genai import types
    # Initialize Gemini
    api_key = getattr(settings, 'GOOGLE_API_KEY', None) or os.environ.get("GOOGLE_API_KEY")
    client = None
    if api_key:
        client = genai.Client(api_key=api_key)
except ImportError:
    print("Google GenAI SDK not found or failed to import.")
    client = None

def get_email_html(title, content, warning=None):
    warning_html = ""
    if warning:
        warning_html = f"""
        <div style="background-color: #2a1515; border-left: 4px solid #ff4a4a; padding: 10px; margin: 20px 0; color: #ff8a8a;">
            <strong style="color: #ff4a4a;">SECURITY ALERT:</strong><br>
            {warning}
        </div>
        """
    
    return f"""
    <!DOCTYPE html>
    <html>
    <body style="margin: 0; padding: 0; background-color: #121212; color: #e0e0e0; font-family: 'Courier New', Courier, monospace;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px; background-color: #121212;">
            <table cellpadding="0" cellspacing="0" border="0" width="100%" style="border-bottom: 1px solid #333; margin-bottom: 20px;">
                <tr>
                    <td width="40" style="padding-bottom: 10px;">
                        <div style="width: 30px; height: 30px; background-color: #20b8cd; border-radius: 50%; display: block; text-align: center; line-height: 30px; color: black; font-weight: bold;">G</div>
                    </td>
                    <td style="padding-bottom: 10px;">
                         <h2 style="color: #e0e0e0; margin: 0; font-size: 18px;">GPTree System</h2>
                    </td>
                </tr>
            </table>
            
            <div style="font-size: 14px; line-height: 1.6;">
                <p style="color: #20b8cd; font-weight: bold; font-size: 16px;">{title}</p>
                <div style="background-color: #1a1a1a; padding: 15px; border-radius: 4px; border: 1px solid #333;">
                    {content}
                </div>
                {warning_html}
            </div>
            
            <div style="font-size: 11px; color: #666; border-top: 1px solid #333; padding-top: 15px; margin-top: 30px;">
                This represents an automated security notification from GPTree.<br>
                Device: Unknown via Web Client<br>
                Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            </div>
        </div>
    </body>
    </html>
    """

def send_brevo_email(subject, html_content, to_email):
    """Fallback to HTTP API since SMTP is failing with 535"""
    api_key = getattr(settings, 'EMAIL_HOST_PASSWORD', '')
    url = "https://api.brevo.com/v3/smtp/email"
    payload = {
        "sender": {"name": "GPTree Security", "email": settings.DEFAULT_FROM_EMAIL},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content
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
        email = data.get('email')
        password = data.get('password')

        if len(password) < 7:
            return JsonResponse({'error': 'Password must be at least 7 characters long'}, status=400)

        # Check for existing user by email
        existing_user = User.objects.filter(email=email).first()
        if existing_user:
            if existing_user.is_active:
                return JsonResponse({'error': 'An account with this email already exists'}, status=400)
            else:
                # Re-use inactive user: update details and send new OTP
                existing_user.set_password(password)
                existing_user.save()
                user = existing_user
                
                # Update or create verification record
                verification, _ = EmailVerification.objects.get_or_create(user=user)
        else:
            # Use email as the username for Django internals
            user = User.objects.create_user(username=email, email=email, password=password)
            user.is_active = False
            user.save()
            UserProfile.objects.create(user=user)
            verification = EmailVerification.objects.create(user=user)

        otp = verification.generate_otp()
        
        # Send Email in background thread
        def send_async():
            html_body = get_email_html(
                "Verify Your Identity",
                f"A request was made to register a new account.<br><br>Your verification OTP is: <strong style='font-size: 1.2em; color: #fff;'>{otp}</strong>",
                "If you did not initiate this request, someone may be trying to use your email address. No action is required."
            )
            if not send_brevo_email(
                'Security Alert: Verify your Email',
                html_body,
                email
            ):
                print(f"Email delivery failed for {email}")

        threading.Thread(target=send_async).start()

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
        email = data.get('email')
        password = data.get('password')
        
        # Django's authentication expects 'username'. We use email as username.
        user = authenticate(request, username=email, password=password)
        
        if user is not None:
            if user.is_active:
                login(request, user)
                return JsonResponse({'status': 'ok'})
            else:
                return JsonResponse({'error': 'Account not verified', 'user_id': user.id}, status=403)
        else:
            return JsonResponse({'error': 'Invalid email or password'}, status=401)
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
            
            def send_async():
                html_body = get_email_html(
                    "Password Reset Required",
                    f"A password reset was requested for your account.<br><br>Your OTP is: <strong style='font-size: 1.2em; color: #fff;'>{otp}</strong>",
                    "If you did not request a password reset, your account credentials may be compromised. Please secure your account immediately."
                )
                send_brevo_email(
                    'Security Alert: Password Reset Request',
                    html_body,
                    email
                )
            
            threading.Thread(target=send_async).start()
            return JsonResponse({'status': 'ok', 'user_id': user.id})
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
        'email': request.user.email,
        'full_name': profile.full_name,
        'profile_pic': profile.profile_pic.url if profile.profile_pic else None,
        'personal_prompt': profile.personal_prompt
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
        elif request.POST.get('remove_profile_pic') == 'true':
            profile.profile_pic = None
        
        profile.save()
        return JsonResponse({'status': 'ok'})

@csrf_exempt
@login_required
def delete_account_view(request):
    if request.method == 'DELETE':
        user = request.user
        logout(request) # Logout before deleting to clear session
        user.delete()
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'error': 'Method not allowed'}, status=405)

@csrf_exempt
def logout_view(request):
    logout(request)
    return JsonResponse({'status': 'ok'})

@login_required
def get_tree(request):
    nodes = Conversation.objects.filter(user=request.user).values('id', 'title', 'parent_id', 'created_at').order_by('created_at')
    return JsonResponse(list(nodes), safe=False)

@csrf_exempt
@login_required
def create_conversation(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        parent_id = data.get('parent_id')
        title = data.get('title', 'New Chat')
        parent = None
        if parent_id:
            # Ensure parent belongs to user
            parent = get_object_or_404(Conversation, id=parent_id, user=request.user)
        conv = Conversation.objects.create(title=title, parent=parent, user=request.user)
        return JsonResponse({'id': conv.id, 'title': conv.title, 'parent_id': conv.parent_id})
    return JsonResponse({'error': 'Invalid method'}, status=405)

@csrf_exempt
@login_required
def update_conversation(request, conversation_id):
    conv = get_object_or_404(Conversation, id=conversation_id, user=request.user)
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

@login_required
def get_messages(request, conversation_id):
    messages = []
    current = get_object_or_404(Conversation, id=conversation_id, user=request.user)
    
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
@login_required
def add_message(request, conversation_id):
    if request.method == 'POST':
        conv = get_object_or_404(Conversation, id=conversation_id, user=request.user)
        
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
@login_required
def generate_reply(request, conversation_id):
    """
    Generates AI reply using Gemini, with context aware of the tree path.
    Supports multiple files and uses gemini-2.5-flash as the primary model.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=405)

    if not api_key or not client:
         conv = get_object_or_404(Conversation, id=conversation_id, user=request.user)
         Message.objects.create(
             conversation=conv,
             role='ai',
             content="I am ready to help! Please set your GOOGLE_API_KEY in the environment or ensure the SDK is installed."
         )
         return JsonResponse({'status': 'ok'})

    try:
        conv = get_object_or_404(Conversation, id=conversation_id, user=request.user)
        
        path = []
        current = conv
        while current:
            path.append(current)
            current = current.parent
        path.reverse()
        
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        system_instr = "You are a helpful AI assistant in GPTree. IMPORTANT: Do not use emojis in your responses. Keep a professional and clean tone."
        if profile.personal_prompt:
            system_instr += f"\n\nUSER PERSONAL INSTRUCTIONS:\n{profile.personal_prompt}"

        contents = []
        # Add system instruction as a user message since new SDK handles system_instructions parameter separately, 
        # but for simplicity in this tree-context, we'll keep the system note style.
        
        for node in path:
            # Inject Branch Title context
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=f"[Context: Entering conversation branch named '{node.title}']")]))
            
            node_messages = node.messages.all().order_by('created_at').prefetch_related('files')
            for m in node_messages:
                role = "user" if m.role == 'user' else "model"
                parts = []
                
                # Add all files (Images)
                for f in m.files.all():
                    try:
                        # With the new SDK, we provide the file path or bytes
                        with open(f.file.path, 'rb') as file_data:
                            parts.append(types.Part.from_bytes(data=file_data.read(), mime_type="image/jpeg"))
                    except Exception as img_err:
                        print(f"Error loading file at {f.file.path}: {img_err}")
                
                if m.content:
                    parts.append(types.Part.from_text(text=m.content))
                
                if parts:
                    contents.append(types.Content(role=role, parts=parts))

        models_to_try = ["gemini-2.5-flash", "gemini-2.5-pro"]
        ai_text = None
        error_msg = ""

        for model_name in models_to_try:
            try:
                print(f"Attempting to call model: {model_name}")
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instr,
                        temperature=0.7,
                        max_output_tokens=4096,
                    )
                )
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
