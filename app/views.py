from django.shortcuts import render
from django.http import HttpResponse
from django.shortcuts import render,redirect
from django.contrib.auth.forms import UserCreationForm
from app.models import CreateUserForm 
from django.contrib.auth import login as auth_login,authenticate,logout
from django.contrib import messages
from django.contrib.auth import logout
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json

# Từ điển từ thô tục → thay thế
BAD_WORDS = {
    "dm": "trời đất ơi",
    "đm": "trời đất ơi",
    "dmm": "ôi trời",
    "vãi": "thật là",
    "vl": "rất",
    "dit": "trêu",
    "địt": "không hay",
    "cc": "không hay",
    "loz": "khó chịu",
    "lon": "khó chịu"
}

def rewrite_sentence(text):
    words = text.split()
    new_words = []
    changed = False

    for w in words:
        lw = w.lower()
        if lw in BAD_WORDS:
            new_words.append(BAD_WORDS[lw])
            changed = True
        else:
            new_words.append(w)

    rewritten = " ".join(new_words)
    return rewritten, changed


# -------------------------------
#   HỆ THỐNG TRẢ LỜI THÔNG MINH
# -------------------------------
def smart_reply(text):
    low = text.lower()

    # 1. Hỏi về website
    if "xem bài viết" in low or "bài viết" in low:
        return "Bạn có thể bấm vào mục **Bài viết** trên thanh menu để xem danh sách đầy đủ nha!"

    if "dự án" in low or "project" in low:
        return "Để xem các dự án KHKT, bạn mở mục **Dự án KHKT** trên menu nhé!"

    if "đăng ký" in low:
        return "Để đăng ký tài khoản, bạn nhấn vào nút **Đăng ký** ở góc phải màn hình nha!"

    if "đăng nhập" in low:
        return "Bạn có thể đăng nhập bằng cách chọn nút **Đăng nhập** ở góc phải trên cùng."

    # 2. Hỏi về chatbot
    if "chatbot" in low:
        return "Mình là chatbot KHKT, luôn sẵn sàng hỗ trợ bạn trong quá trình xem bài viết và dự án!"

    # 3. Hỏi chung chung
    if "hello" in low or "hi" in low or "xin chào" in low:
        return "Xin chào! Mình có thể giúp gì cho bạn trong dự án KHKT không?"

    if "cảm ơn" in low:
        return "Không có gì, mình luôn sẵn sàng hỗ trợ bạn!"

    # 4. Nếu không hiểu
    return "Mình chưa rõ ý bạn lắm, nhưng bạn có thể hỏi về bài viết, dự án hoặc cách dùng website nhé!"
    


@csrf_exempt
def chatbot_api(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    data = json.loads(request.body)
    user_text = data.get("text", "")

    # Lọc + rewrite
    rewritten, changed = rewrite_sentence(user_text)

    # Tạo câu trả lời
    smart = smart_reply(rewritten)

    # Nếu câu ban đầu bị thô tục → trước tiên nhắc nhở
    if changed:
        warning = f"Tớ có chỉnh câu lại cho phù hợp nè: \"{rewritten}\"."
    else:
        warning = ""

    final_reply = f"{warning} {smart}".strip()

    return JsonResponse({
        "original": user_text,
        "rewritten": rewritten,
        "changed": changed,
        "reply": final_reply
    })
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