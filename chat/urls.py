from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('api/verify_otp/', views.verify_otp, name='verify_otp'),
    path('api/forgot_password/', views.forgot_password, name='forgot_password'),
    path('api/reset_password/', views.reset_password, name='reset_password'),
    path('api/settings/', views.get_user_settings, name='get_settings'),
    path('api/settings/update/', views.update_user_settings, name='update_settings'),
    path('api/webhook/bmac/', views.bmac_webhook, name='bmac_webhook'),
    
    path('api/tree/', views.get_tree, name='get_tree'),
    path('api/conversations/', views.create_conversation, name='create_conversation'),
    path('api/conversations/<int:conversation_id>/', views.update_conversation, name='update_conversation'),
    path('api/conversations/<int:conversation_id>/messages/', views.get_messages, name='get_messages'),
    path('api/conversations/<int:conversation_id>/add_message/', views.add_message, name='add_message'),
    path('api/conversations/<int:conversation_id>/generate_reply/', views.generate_reply, name='generate_reply'),
]
