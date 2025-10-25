from django.contrib import admin
from django.urls import path
from . import views
urlpatterns = [
    path('', views.home,name="home"),
    path('register/', views.register,name="register"),
    path('login/', views.login_view,name="login"),
    path('logout/', views.logoutPage,name="logout"),
    path('game/',views.game,name="game")
]