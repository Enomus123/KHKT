from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as auth_login, logout
from django.contrib import messages
from app.models import CreateUserForm
import json
import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import base64
import time


# ============================================
# 🔥 API CHATBOT (OpenAI + FPT AI STT/TTS)
# ============================================

@csrf_exempt
def chatbot_api(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid method"}, status=405)

    data = json.loads(request.body.decode("utf-8"))
    user_message = data.get("message", "")
    audio_mode = data.get("audio", False)
    voice_input = data.get("voice_input", None)

    # ============================
    # 1️⃣ NHẬN GIỌNG NÓI BẰNG FPT AI
    # ============================
    if voice_input:
        try:
            fpt_stt_headers = {
                "api-key": settings.FPT_API_KEY,
            }
            stt_response = requests.post(
                "https://api.fpt.ai/hmi/asr/general",
                headers=fpt_stt_headers,
                data=base64.b64decode(voice_input)
            )

            stt_json = stt_response.json()
            user_message = stt_json.get("hypotheses", [{}])[0].get("utterance", user_message)

        except Exception as e:
            print("❌ Lỗi FPT STT:", e)

    # ============================================
    # 2️⃣ GỬI TIN NHẮN CHO OPENAI TRẢ LỜI
    # ============================================

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "OpenAI-Project": settings.OPENAI_PROJECT_ID
    }

    chat_payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Bạn là Toco – một người bạn thân dễ thương, vui vẻ, hiểu chuyện. "
                    "Luôn trả lời ngắn gọn tối đa 4 câu."
                    "một người bạn thân, dễ thương, nói chuyện kiểu thân mật, "
                    "đặc biệt là ngữ điệu nữ miền Nam nhẹ nhàng."
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
                    "Hãy trả lời tự nhiên, giống người thật, không nói kiểu máy móc, không nhắc rằng bạn là AI."
                    "Ưu tiên trả lời ngắn gọn như một người bạn, đừng trả lời quá dài dòng, lan man"
                    "Đừng đặt quá nhiều câu hỏi mà ưu tiên việc trò chuyện như một người bạn"
                    "Chủ động kể chuyện, bắt chuyện với người dùng"
                )
            },
            {"role": "user", "content": user_message}
        ]
    }

    chat_response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=headers,
        json=chat_payload
    )

    if chat_response.status_code != 200:
        return JsonResponse({
            "reply": "⚠️ Hệ thống đang bận, thử lại sau nhé!"
        }, status=500)

    reply = chat_response.json()["choices"][0]["message"]["content"]

    # ============================================
    # 3️⃣ TTS — CHUYỂN TEXT → GIỌNG NỮ MIỀN NAM (FPT AI)
    # ============================================

    audio_base64 = None

    if audio_mode:
        try:
            fpt_tts_headers = {
                "api-key": settings.FPT_API_KEY,
                "voice": "linhsan",     # giọng nữ miền Nam
                "speed": "1.0"
            }

            tts_response = requests.post(
                "https://api.fpt.ai/hmi/tts/v5",
                headers=fpt_tts_headers,
                data=reply.encode("utf-8")
            )

            tts_json = tts_response.json()
            audio_url = tts_json.get("async")

            if audio_url:
                # chờ đến khi file âm thanh sẵn sàng
                for _ in range(7):
                    audio_file = requests.get(audio_url)
                    if audio_file.status_code == 200 and len(audio_file.content) > 4000:
                        audio_base64 = base64.b64encode(audio_file.content).decode("utf-8")
                        break
                    time.sleep(1)

        except Exception as e:
            print("❌ Lỗi FPT TTS:", e)

    return JsonResponse({
        "reply": reply,
        "audio": audio_base64
    })



# ============================================
# 🔐 LOGIN / REGISTER / LOGOUT
# ============================================

def logoutPage(request):
    logout(request)
    return redirect('login')

def home(request):
    if request.user.is_authenticated:
        user_not_login = "hidden"
        user_login = "show"
    else:
        user_not_login = "show"
        user_login = "hidden"

    return render(request, 'app/base.html', {
        'user_not_login': user_not_login,
        'user_login': user_login
    })

def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == "POST":
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)

        if user:
            auth_login(request, user)
            return redirect('home')
        else:
            messages.error(request, "Sai tài khoản hoặc mật khẩu!")

    return render(request, "app/login.html")

def register(request):
    form = CreateUserForm()

    if request.method == "POST":
        form = CreateUserForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Tạo tài khoản thành công!")
            return redirect('login')

    return render(request, "app/register.html", {"form": form})
