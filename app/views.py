from django.shortcuts import render
from django.http import HttpResponse
from django.shortcuts import render,redirect
from django.contrib.auth.forms import UserCreationForm
from app.models import CreateUserForm 
from django.contrib.auth import login as auth_login,authenticate,logout
from django.contrib import messages
from django.contrib.auth import logout

def logout_view(request):
    logout(request)
    return redirect('login')
def home(request):
    if request.user.is_authenticated:
        user_not_login = "hidden"
        user_login = "show"
    else:
        user_not_login = "show"
        user_login = "hidden"
    context = {'user_not_login':user_not_login,'user_login':user_login}
    return render(request,'app/base.html',context)
def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == "POST":
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            auth_login(request, user)
            return redirect('home')
        else:
            messages.info(request, 'User or password not correct!')
    context = {}  # có thể thêm form hoặc message sau
    return render(request, 'app/login.html', context)
def register(request):
    form = CreateUserForm()
    if request.method == "POST":
        form = CreateUserForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username')
            messages.success(request, f'Tạo tài khoản cho {username} thành công!')
            return redirect('login')
        else:
            messages.error(request, 'Đăng ký thất bại. Vui lòng kiểm tra lại thông tin.')
    context = {'form':form}
    return render(request,'app/register.html',context)
def logoutPage(request):
    logout(request)
    return redirect('login')
def game(request):
     return render(request, 'app/game.html')