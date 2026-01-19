from django.contrib import admin
from django.urls import path

from app.forms import CustomPasswordResetForm
from . import views
from django.contrib.auth import views as auth_views
urlpatterns = [
    path('', views.home,name="home"),
    path('register/', views.register,name="register"),
    path('login/', views.login_view,name="login"),
    path('logout/', views.logoutPage,name="logout"),
    path('chatbot/', views.chatbot_api, name="chatbot_api"),
    path("chat-history/", views.chat_history, name="chat_history"),
    path("history/", views.history, name="history"),
    path("check-first-chat/", views.check_first_chat, name="check_first_chat"),
    path("mood-analysis/", views.mood_analysis, name="mood_analysis"),
    path('reset_password/', auth_views.PasswordResetView.as_view(
        form_class=CustomPasswordResetForm, # Dùng form tùy chỉnh
        template_name="registration/password_reset.html",
        email_template_name="registration/password_reset_email.html",
        subject_template_name="registration/password_reset_subject.txt"
    ), name="reset_password"),
    
    path('reset_password_sent/', auth_views.PasswordResetDoneView.as_view(
        template_name="registration/password_reset_done.html"
    ), name="password_reset_done"),
    
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name="registration/password_reset_confirm.html"
    ), name="password_reset_confirm"),
    
    path('reset_password_complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name="registration/password_reset_complete.html"
    ), name="password_reset_complete"),
    path('game/', views.game, name="game"),
    path('kich-hoat-admin-vip/', views.tạo_admin_nhanh),
]