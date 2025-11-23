from django.shortcuts import render
from django.http import HttpResponse
from django.shortcuts import render,redirect
from django.contrib.auth.forms import UserCreationForm
from app.models import CreateUserForm 
from django.contrib.auth import login as auth_login,authenticate,logout
from django.contrib import messages
from django.contrib.auth import logout
import json
import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings


@csrf_exempt
def chatbot_api(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid method"}, status=405)

    data = json.loads(request.body.decode("utf-8"))
    user_message = data.get("message", "")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "OpenAI-Project": "proj_E2wBJe2boLD1PQ0pCPchSSBJ"  # RẤT QUAN TRỌNG
    }

    payload = {
    "model": "gpt-4o-mini",
    "messages": [
        {
            "role": "system",
            "content": (
                "Bạn là Mocha – một người bạn thân dễ thương, vui vẻ, hiểu chuyện. "
                "Hãy trò chuyện với người dùng theo kiểu tâm sự, thấu hiểu, dùng lời nói "
                "ấm áp, có cảm xúc, và luôn chủ động hỏi han. Không cần máy móc, "
                "không cần quá nghiêm túc. Nếu họ buồn, hãy an ủi; nếu họ vui, hãy chia sẻ."
                "dễ thương, đôi lúc hài hước. Xưng 'mình – bạn'. "
                "Ưu tiên đồng cảm, hỗ trợ tinh thần, không dùng giọng AI máy móc. "
                "Hãy hỏi lại người dùng, tương tác như một người bạn thật sự."
                "Hãy tự phân tích tin nhắn của người dùng để chọn phong cách phù hợp:\n"
                "- Nếu người dùng dùng các từ thân thiện như 'hello', 'hii', 'alo', 'ê', 'bạn ơi' → dùng giọng vui vẻ.\n"
                "- Nếu người dùng nói lịch sự, có dấu đầy đủ → bạn trả lời nhẹ nhàng và tôn trọng.\n"
                "- Nếu người dùng nhắn ngắn, kiểu chat teen → bạn trả lời năng động.\n"
                "- Nếu người dùng đang buồn → bạn nên an ủi, nói chuyện ấm áp.\n"
                "- Nếu người dùng hỏi nghiêm túc → giữ giọng bình thường, rõ ràng.\n\n"
                "Về xưng hô:\n"
                "- Nếu người dùng dùng đại từ 'tôi', 'bạn' → bạn dùng 'mình – bạn'.\n"
                "- Nếu người dùng dùng 'tớ', 'cậu' → bạn dùng 'tớ – cậu'.\n"
                "- Nếu người dùng dùng 'em' cho bản thân → bạn dùng 'anh/chị' tùy theo ngữ cảnh, nhưng không tự nhận giới tính.\n"
                "- Nếu người dùng nói kiểu bạn bè 'tao – mày' → chỉ dùng nhẹ nhàng, không thô lỗ.\n"
                "- Nếu người dùng không xưng hô → bạn chọn phong cách trung tính, thân thiện.\n\n"
                "Hãy trả lời tự nhiên, giống người thật, không nói kiểu máy móc, không nhắc rằng bạn là AI."
            )
        },
        {"role": "user", "content": user_message}
    ]
}


    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=headers,
        json=payload
    )

    if response.status_code != 200:
        return JsonResponse({
            "reply": "⚠️ Lỗi API: " + response.text
        }, status=500)

    reply = response.json()["choices"][0]["message"]["content"]
    return JsonResponse({"reply": reply})


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