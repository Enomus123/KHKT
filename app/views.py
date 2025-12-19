from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as auth_login, logout
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.utils import timezone
import static_ffmpeg
static_ffmpeg.add_paths() # Tự động tìm và kích hoạt ffmpeg cho Render
import json, requests, base64, time
from .models import ChatHistory, CreateUserForm
import subprocess
import uuid
import os
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# Cấu hình Gemini
genai.configure(api_key=settings.GEMINI_API_KEY)

# Thư viện nhận diện giọng nói
import speech_recognition as sr
from pydub import AudioSegment

os.makedirs("tmp", exist_ok=True) 

LAST_REQUEST = {}

def save_chat(user, sender, user_message):
    if user is None:
        return
    ChatHistory.objects.create(
        user=user,
        sender=sender,
        message=user_message
    )

def get_google_tts(text, api_key):
    """
    Gọi trực tiếp Google TTS REST API (Không cần thư viện google-cloud-text-to-speech)
    Cách này tối ưu cho Python 3.14+ và chạy ổn định trên mobile.
    """
    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={api_key}"
    payload = {
        "input": {"text": text},
        "voice": {
            "languageCode": "vi-VN",
            "name": "vi-VN-Neural2-A", 
            "ssmlGender": "FEMALE"
        },
        "audioConfig": {
            "audioEncoding": "MP3",
            "pitch": 2.5,
            "speakingRate": 1.0,
            "volumeGainDb": 6.0
        }
    }
    try:
        response = requests.post(url, json=payload, timeout=15)
        if response.status_code == 200:
            return response.json().get("audioContent") # Trả về chuỗi base64
        else:
            print(f"❌ Lỗi Google TTS API: {response.text}")
    except Exception as e:
        print(f"❌ Exception Google TTS: {e}")
    return None

@csrf_exempt
def chatbot_api(request):
    user_ip = request.META.get("REMOTE_ADDR")
    now = time.time()
    
    # Rate limit tránh spam
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

    # --- NHẬN DẠNG GIỌNG NÓI (STT) ---
    if voice_input:
        file_id = uuid.uuid4().hex
        input_filename = f"tmp/{file_id}_input.audio"  
        output_filename = f"tmp/{file_id}_output.wav"  
        
        try:
            audio_binary = base64.b64decode(voice_input)
            with open(input_filename, "wb") as f:
                f.write(audio_binary)
            
            # Chuẩn hóa audio sang WAV 16kHz cho Google STT
            command = [
                'ffmpeg', '-y', '-i', input_filename, 
                '-ar', '16000', '-ac', '1', 
                '-c:a', 'pcm_s16le', '-f', 'wav', output_filename
            ]
            subprocess.run(command, check=True, capture_output=True, timeout=10)
            
            r = sr.Recognizer()
            with sr.AudioFile(output_filename) as source:
                audio_data = r.record(source)  

            stt_result = r.recognize_google(audio_data, language="vi-VN")
            if stt_result:
                user_message = stt_result
        except Exception as e:
            print(f"❌ Lỗi STT: {e}")
            user_message = None
        finally:
            if os.path.exists(input_filename): os.remove(input_filename)
            if os.path.exists(output_filename): os.remove(output_filename)

    if not user_message or user_message.strip() == "":
        return JsonResponse({"reply": ""})

    # --- XỬ LÝ LỊCH SỬ CHAT ---
    history_msgs = []   
    if user:
        history = ChatHistory.objects.filter(user=user).order_by("timestamp")
        for h in history:
            role = "assistant" if h.sender == "bot" else "user"
            history_msgs.append({"role": role, "content": h.message})
    
    history_msgs.append({"role": "user", "content": user_message})
    history_msgs = history_msgs[-5:] # Lấy 5 tin gần nhất để Toco thông minh hơn

    # --- GỌI GEMINI ---
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
    )
    try:
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",       
            system_instruction=system_prompt,
            generation_config={"max_output_tokens": 150, "temperature": 0.7}
        )

        gemini_history = []
        for msg in history_msgs[:-1]:
            role = "model" if msg["role"] == "assistant" else "user"
            gemini_history.append({"role": role, "parts": [msg["content"]]})

        chat_session = model.start_chat(history=gemini_history)
        response = chat_session.send_message(user_message)
        reply = response.text
    except Exception as e:
        print(f"❌ Lỗi Gemini: {e}")
        return JsonResponse({"reply": "⚠️ Toco đang bận một chút..."}, status=500)

    # --- PHÂN LOẠI CẢM XÚC ---
    text_lower = reply.lower()
    if any(w in text_lower for w in ['vui', 'tuyệt', 'haha', 'hihi']): emotion = "happy"
    elif any(w in text_lower for w in ['chia sẻ', 'buồn', 'đừng lo']): emotion = "comfort"
    else: emotion = "cute"

    # --- CHUYỂN VĂN BẢN SANG GIỌNG NÓI (TTS) ---
    audio_base64 = None
    if audio_mode:
        # Sử dụng API Key từ settings (nên dùng chung key Gemini nếu đã bật TTS API)
        audio_base64 = get_google_tts(reply, settings.GEMINI_API_KEY)

    # --- LƯU DB ---
    if user:
        ChatHistory.objects.create(user=user, sender="user", message=user_message)
        ChatHistory.objects.create(user=user, sender="bot", message=reply)

    return JsonResponse({
        "reply": reply, 
        "audio": audio_base64, 
        "user_message": user_message, 
        "emotion": emotion
    })

# --- CÁC HÀM CÒN LẠI (GIỮ NGUYÊN) ---
@login_required
def chat_history(request):
    history = ChatHistory.objects.filter(user=request.user).order_by("timestamp")
    return JsonResponse({
        "history": [{"sender": h.sender, "message": h.message, "timestamp": h.timestamp.isoformat()} for h in history]
    })

def logoutPage(request):
    logout(request)
    return redirect('login')

def home(request):
    status = "show" if request.user.is_authenticated else "hidden"
    return render(request, 'app/base.html', {'user_login': status, 'user_not_login': "hidden" if status=="show" else "show"})

def login_view(request):
    if request.user.is_authenticated: return redirect('home')
    if request.method == "POST":
        u, p = request.POST.get('username'), request.POST.get('password')
        user = authenticate(request, username=u, password=p)
        if user:
            auth_login(request, user)
            return redirect('home')
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
        else:
            errors = {
                "A user with that username already exists.": "Tên đăng nhập này đã tồn tại.",
                "The two password fields didn’t match.": "Mật khẩu không khớp."
            }
            for field, errs in form.errors.items():
                for e in errs:
                    messages.error(request, f"Lỗi: {errors.get(str(e), str(e))}")
    return render(request, "app/register.html", {"form": form})

@login_required
def history(request):
    chats = ChatHistory.objects.filter(user=request.user).order_by("timestamp")
    return render(request, "app/history.html", {"chats": chats})

def check_first_chat(request):
    if not request.user.is_authenticated: return JsonResponse({"first_time": True})
    return JsonResponse({"first_time": not ChatHistory.objects.filter(user=request.user).exists()})