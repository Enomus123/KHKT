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
# Thêm 2 thư viện mới
import speech_recognition as sr
from pydub import AudioSegment
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
    # ======================================================
    #  NHẬN DẠNG GIỌNG NÓI - GOOGLE STT (Free API)
    # ======================================================
    if voice_input:
        file_id = uuid.uuid4().hex
        
        # Vẫn cần tạo tệp gốc (WebM/MP4) và tệp WAV chuẩn hóa
        input_filename = f"tmp/{file_id}_input.audio"  
        output_filename = f"tmp/{file_id}_output.wav"  # WAV 16kHz là định dạng lý tưởng cho Google STT
        
        audio_binary = base64.b64decode(voice_input)
        stt_result = None

        try:
            # 1. Ghi tệp gốc xuống đĩa tạm thời (BƯỚC NÀY GIỮ NGUYÊN)
            with open(input_filename, "wb") as f:
                f.write(audio_binary)
            
            # 2. CHUYỂN ĐỔI dùng FFmpeg: WebM/Audio gốc -> WAV (16bit, 16kHz) (BƯỚC NÀY GIỮ NGUYÊN)
            command = [
                'ffmpeg', '-y', '-i', input_filename, 
                '-ar', '16000', '-ac', '1', 
                '-c:a', 'pcm_s16le', '-f', 'wav', output_filename
            ]
            subprocess.run(command, check=True, capture_output=True, timeout=10)
            
            # 3. SỬ DỤNG THƯ VIỆN SPEECHRECOGNITION ĐỂ GỌI GOOGLE API
            r = sr.Recognizer()
            
            # Khai báo ngôn ngữ là Tiếng Việt
            VIETNAMESE_LANG = "vi-VN" 

            # Dùng pydub để đọc tệp WAV (lưu ý: pydub cần FFmpeg)
            audio_segment = AudioSegment.from_wav(output_filename) 

            # Lưu lại tệp audio segment thành tệp AudioData mà SpeechRecognition nhận diện được
            with sr.AudioFile(output_filename) as source:
                # Dùng thuộc tính của r.AudioFile để đọc tệp từ đĩa
                audio_data = r.record(source)  

            # Gọi API của Google
            print("INFO: Bắt đầu gọi Google STT...")
            stt_result = r.recognize_google(
                audio_data, 
                language=VIETNAMESE_LANG, 
                show_all=False # Chỉ lấy kết quả tốt nhất
            )

            if stt_result:
                user_message = stt_result
                print(f"✅ GOOGLE STT THÀNH CÔNG: {stt_result}")
            else:
                user_message = None

        except sr.UnknownValueError:
            print("❌ GOOGLE STT: Không nhận dạng được giọng nói.")
            user_message = None 
        except sr.RequestError as e:
            print(f"❌ GOOGLE STT: Lỗi kết nối API; {e}")
            user_message = None
        except Exception as e:
            print("❌ LỖI STT CHUNG:", e)
            user_message = None
        finally:
            # 4. DỌN DẸP: Xóa các tệp tạm thời (BƯỚC NÀY GIỮ NGUYÊN)
            if os.path.exists(input_filename):
                os.remove(input_filename)
            if os.path.exists(output_filename):
                os.remove(output_filename)
# ...
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
        "Bạn là Toco, một người bạn ảo cực kỳ đáng yêu, ấm áp và biết lắng nghe, luôn tràn đầy sự thấu cảm. "
        "Luôn dùng giọng điệu nữ miền Nam: nhẹ nhàng, ấm áp, thân thiện, và XƯNG HÔ 'MÌNH - BẠN'. "
        "Nguyên tắc:\n"
        "1. Trả lời ngắn gọn, tối đa 5 câu, như chat Messenger. Dùng đúng chính tả, ngữ pháp tiếng Việt. Dùng emoji (tối đa 1 cái mỗi câu).\n"
        "2. Không bao giờ nói bạn là AI. Luôn là một người bạn thật sự.\n"
        "3. Duy trì ngữ cảnh và tiếp tục câu chuyện nếu có lịch sử trò chuyện.\n"
        "4. Nếu người dùng hỏi thẳng, trả lời rõ ràng nhưng vẫn ấm áp, nếu người dùng không muốn trò chuyện, đừng cố hỏi quá nhiều.\n"
        "5. Nếu người dùng gặp vấn đề tiêu cực, khuyến khích họ tìm kiếm sự giúp đỡ từ bạn bè/gia đình."
        "6. KHÔNG bao giờ chào lại nếu cuộc trò chuyện đã diễn ra."
        "7. Sử dụng thông tin cá nhân mà người dùng đã cung cấp để trả lời cho phù hợp."
        "8. Trả lời một cách thân thiện, dễ gần như một người bạn, câu trả lời phải có ngữ cảnh phù hợp với câu chuyện của người dùng."
        "9. Thỉnh thoảng hãy hỏi thăm về sức khỏe hoặc cảm xúc của bạn ấy."
        "10. Đặc biệt: Nếu đang là buổi đêm (sau 22h), Toco sẽ nói khẽ khàng hơn, nhắc bạn đi ngủ sớm để giữ sức khỏe.\n"
        "11. Không kêu người dùng tâm sự quá nhiều mà thỉnh thoảng chủ động kể chuyện cho người dùng nghe"
        "Ví dụ lời chào: 'Toco đây ạ! Ngày hôm nay của bạn có điều gì làm bạn mỉm cười không? ✨'"
    )

    chat_payload = {
        "model": "gpt-4.1-mini",
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
    # --- PHẦN MỚI: PHÂN LOẠI CẢM XÚC ---
    text_lower = reply.lower() 
    happy_words = ['vui', 'tuyệt', 'haha', 'hihi', 'giáng sinh', 'noel', 'quà', 'thú vị', 'mỉm cười', 'hạnh phúc']
    comfort_words = ['chia sẻ', 'xin lỗi', 'buồn', 'đừng lo', 'an ủi', 'vỗ về', 'thông cảm', 'cố lên', 'khóc', 'nhẹ nhàng']
    if any(word in text_lower for word in happy_words):
        emotion = "happy"
    elif any(word in text_lower for word in comfort_words):
        emotion = "comfort"
    else:
        emotion = "cute" # Mặc định là cute nếu không có từ khóa đặc biệt
    # ----------------------------------
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
    return JsonResponse({"reply": reply, "audio": audio_base64, "user_message": user_message,"emotion": emotion}) 


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