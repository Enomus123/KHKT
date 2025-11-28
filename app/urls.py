from django.contrib import admin
from django.urls import path
from . import views
urlpatterns = [
    path('', views.home,name="home"),
    path('register/', views.register,name="register"),
    path('login/', views.login_view,name="login"),
    path('logout/', views.logoutPage,name="logout"),
    path('chatbot/', views.chatbot_api, name="chatbot_api"),
    path("chat-history/", views.chat_history, name="chat_history"),
    path("history/", views.history, name="history"),
    path("check-first-chat/", views.check_first_chat, name="check_first_chat"),
]