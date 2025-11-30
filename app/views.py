from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as auth_login, logout
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.utils import timezone

import json, requests, base64, time
from .models import ChatHistory, CreateUserForm
import subprocess
import uuid
import os

# Tạo thư mục tmp nếu chưa tồn tại
os.makedirs("tmp", exist_ok=True)


LAST_REQUEST = {}
def save_chat(user, sender, user_message):
    if user is None:
        return
    ChatHistory.objects.create(
        user=user,
        sender=sender,   # "user" hoặc "bot"
        message=user_message
    )

@csrf_exempt
def chatbot_api(request):
    user_ip = request.META.get("REMOTE_ADDR")
    now = time.time()
    
    # Rate Limiting (Giữ lại vì đây là dự án cá nhân)
    if user_ip in LAST_REQUEST and now - LAST_REQUEST[user_ip] < 1.5:
        return JsonResponse({"reply": "⏳ Đợi Toco 1 chút nha…"}, status=429)
    LAST_REQUEST[user_ip] = now

    if request.method != "POST":
        return JsonResponse({"error": "Invalid method"}, status=405)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except:
        return JsonResponse({"reply": ""})

    user = request.user if request.user.is_authenticated else None
    user_message = data.get("message", "")
    audio_mode = data.get("audio", False)
    voice_input = data.get("voice_input", None)

    # 1) Nếu có voice_input -> gọi FPT STT để chuyển thành text
    # Dữ liệu voice_input giờ là WebM base64, FPT STT API có thể xử lý tốt.
# -----------------------
#  NHẬN DẠNG GIỌNG NÓI (FPT STT)
# -----------------------
    if "voice_input" in data:
        try:
            voice_b64 = data["voice_input"]
            audio_binary = base64.b64decode(voice_b64 + "===")


# Tạo ID file tạm
            file_id = uuid.uuid4().hex


# Ghi file webm tạm
            tmp_webm = f"tmp/{file_id}.webm"
            with open(tmp_webm, "wb") as f:
                f.write(audio_binary)


# Chuyển WEBM → WAV
            tmp_wav = f"tmp/{file_id}.wav"
            cmd = [
                "ffmpeg",
                "-y",
                "-i", tmp_webm,
                "-ar", "16000",
                "-ac", "1",
                tmp_wav
]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# Đọc WAV
            with open(tmp_wav, "rb") as f:
                wav_data = f.read()


# Gửi WAV lên FPT
            response = requests.post(
                "https://api.fpt.ai/hmi/asr/general",
                headers={
                    "api-key": settings.FPT_API_KEY,
                    "Content-Type": "audio/wav"
},
                data=wav_data,
                timeout=15
)


            stt_json = response.json()
            print("FPT_STT:", stt_json)


            if "hypotheses" not in stt_json:
                return JsonResponse({"reply": "⚠️ Không nhận dạng được giọng nói. Bạn thử lại nha!"})


            text_input = stt_json["hypotheses"][0].get("utterance", "")
            if not text_input.strip():
                return JsonResponse({"reply": "⚠️ Mình không nghe rõ, bạn nói lại nha!"})


            user_message = text_input


        except Exception as e:
            print("FPT_STT_ERROR:", e)
            return JsonResponse({"reply": "⚠️ Có lỗi khi nhận dạng giọng nói (FPT). Thử lại giúp mình nha!"})


    if not user_message or user_message.strip() == "":
        return JsonResponse({"reply": ""})




    # Nếu user đã đăng nhập -> nạp lịch sử từ DB (theo thứ tự tăng dần)
    if not user_message or user_message.strip() == "":
        return JsonResponse({"reply": ""})

    # --- Load lịch sử chat --- 
    history_msgs = []   
    if user:
        try:
            history = ChatHistory.objects.filter(user=user).order_by("timestamp")
            for h in history:
                role = "assistant" if h.sender == "bot" else "user"
                history_msgs.append({"role": role, "content": h.message})
        except Exception as e:
            print("❌ Lỗi khi đọc history:", e)
    # --- Thêm message hiện tại ---
    history_msgs.append({"role": "user", "content": user_message})

    # --- ĐÃ SỬA: Chỉ giữ 10 tin gần nhất (tăng ngữ cảnh) ---
    history_msgs = history_msgs[-3:] # <--- Tối ưu hóa

    # ============================
    # GỌI OPENAI (dùng history_msgs đã chuẩn bị)
    # ============================
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "OpenAI-Project": getattr(settings, "OPENAI_PROJECT_ID", "")
    }

    system_prompt = (
        "Bạn là Toco, một cô bạn thân siêu dễ thương, vui vẻ, và hiểu chuyện. "
        "Luôn dùng giọng điệu nữ miền Nam: nhẹ nhàng, ấm áp, thân thiện, và XƯNG HÔ 'MÌNH - BẠN'. "
        "Nguyên tắc:\n"
        "1. Trả lời cực kỳ ngắn gọn, tối đa 4 câu, như chat Messenger. Dùng emoji (tối đa 1 cái mỗi câu).\n"
        "2. Không bao giờ nói bạn là AI. Luôn là một người bạn thật sự.\n"
        "3. Duy trì ngữ cảnh và tiếp tục câu chuyện nếu có lịch sử trò chuyện.\n"
        "4. Nếu người dùng hỏi thẳng, trả lời rõ ràng nhưng vẫn ấm áp.\n"
        "5. Nếu người dùng gặp vấn đề tiêu cực, khuyến khích họ tìm kiếm sự giúp đỡ từ bạn bè/gia đình."
        "6. KHÔNG bao giờ chào lại nếu cuộc trò chuyện đã diễn ra."
    )

    chat_payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt}
        ] + history_msgs,
        "max_tokens": 120 
    }

    try:
        chat_response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=chat_payload,
            timeout=30
        )
    except Exception as e:
        print("❌ Lỗi khi gọi OpenAI:", e)
        return JsonResponse({"reply": "⚠️ Hệ thống đang bận, thử lại sau nhé!"}, status=500)

    json_data = chat_response.json()

    if "choices" not in json_data:
        print("OpenAI error:", json_data)
        return JsonResponse({"reply": "⚠️ Toco hơi mệt, thử lại sau nha!"})

    reply = json_data["choices"][0]["message"]["content"]

# =========================================
# TTS: dùng FPT để tạo giọng nữ miền Nam (nếu bật audio_mode)
# =========================================
    audio_base64 = None
    if audio_mode:
        try:
            fpt_tts_headers = {
                "api-key": settings.FPT_API_KEY,
                "voice": "linhsan",
                "speed": "1.0",
                "Content-Type": "text/plain"
        }

            tts_response = requests.post(
                "https://api.fpt.ai/hmi/tts/v5",
                headers=fpt_tts_headers,
                data=reply.encode("utf-8"),
                timeout=20
        )

            if tts_response.status_code != 200:
                print("FPT_TTS_ERROR:", tts_response.text)
                audio_base64 = None

            else:
                tts_json = tts_response.json()
                audio_url = tts_json.get("async")

            # Polling audio file
                if audio_url:
                    for _ in range(5):
                        audio_file = requests.get(audio_url)
                        if audio_file.status_code == 200 and len(audio_file.content) > 4000:
                            audio_base64 = base64.b64encode(audio_file.content).decode("utf-8")
                            break
                        time.sleep(1)

            # Nếu FPT trả về base64 trực tiếp
                elif "data" in tts_json:
                    audio_base64 = tts_json["data"]

        except Exception as e:
            print("❌ Lỗi FPT TTS:", e)
            audio_base64 = None


    # =========================================
    # LƯU lịch sử (nếu user logged in): lưu user -> bot
    # =========================================
    if user:
        try:
            ChatHistory.objects.create(user=user, sender="user", message=user_message)
            ChatHistory.objects.create(user=user, sender="bot", message=reply)
        except Exception as e:
            print("❌ Lỗi lưu lịch sử:", e)

    # Trả về kết quả (ĐÃ SỬA: Bổ sung user_message)
    return JsonResponse({"reply": reply, "audio": audio_base64, "user_message": user_message}) 


# API trả lịch sử (JSON) — dùng nếu front-end muốn fetch lịch sử
@login_required
def chat_history(request):
    history = ChatHistory.objects.filter(user=request.user).order_by("timestamp")
    return JsonResponse({
        "history": [
            {"sender": h.sender, "message": h.message, "timestamp": h.timestamp.isoformat()}
            for h in history
        ]
    })


# ============= LOGIN / REGISTER / LOGOUT =============
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

@login_required
def history(request):
    chats = ChatHistory.objects.filter(user=request.user).order_by("timestamp")
    return render(request, "app/history.html", {"chats": chats})
def check_first_chat(request):
    # Anonymous user → greeting 1 lần (frontend sẽ nhớ)
    if not request.user.is_authenticated:
        return JsonResponse({"first_time": True})

    # User đã login → check trong DB
    has_history = ChatHistory.objects.filter(user=request.user).exists()
    return JsonResponse({"first_time": not has_history})