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
import re
from datetime import timedelta
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

def clean_text_for_tts(text):
    """
    Loại bỏ các ký tự đặc biệt như *, #, _, [CÒN TIẾP] để TTS đọc mượt mà hơn.
    """
    # Loại bỏ dấu sao (thường dùng để in đậm trong Markdown)
    text = text.replace("*", "")
    # Loại bỏ các dấu hiệu điều hướng nội bộ của bạn
    text = text.replace("[CÒN TIẾP]", "")
    # Loại bỏ các ký tự đặc biệt khác nếu cần
    text = re.sub(r'[#_~-]', '', text)
    # Loại bỏ các khoảng trắng thừa
    text = " ".join(text.split())
    return text
def get_full_gemini_response(chat_session, user_message):
    full_reply = ""
    current_prompt = user_message # Lần đầu dùng câu hỏi của người dùng
    max_iterations = 5 
    iteration = 0
    
    while iteration < max_iterations:
        response = chat_session.send_message(current_prompt)
        part_text = response.text
        
        if "[CÒN TIẾP]" in part_text:
            # Lấy nội dung, bỏ chữ [CÒN TIẾP]
            full_reply += part_text.replace("[CÒN TIẾP]", "").strip() + " "
            # QUAN TRỌNG: Câu lệnh tiếp theo phải là "Viết tiếp"
            current_prompt = "Hãy viết tiếp phần còn lại một cách tự nhiên nhé, bắt đầu từ chỗ bạn vừa dừng lại."
            iteration += 1
        else:
            full_reply += part_text
            break
            
    return full_reply
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
    history_msgs = history_msgs[-7:] # Lấy 7 tin gần nhất để Toco thông minh hơn
    now_vn = timezone.now() + timedelta(hours=7)# Lấy thời gian từ hệ thống
    # Định dạng lại thành chuỗi tiếng Việt dễ hiểu
    current_time_str = now_vn.strftime("%H:%M, thứ %w (0 là Chủ Nhật), ngày %d/%m/%Y")
    
    # Tạo một thông báo ngầm cho AI
    time_context = f"\n[THÔNG TIN HỆ THỐNG]: Bây giờ chính xác là {current_time_str}. Hãy dùng thông tin này để trò chuyện phù hợp ngữ cảnh."
    # --- GỌI GEMINI ---
    system_prompt = (
        "Bạn là Toco, một người bạn ảo cực kỳ đáng yêu, ấm áp và luôn bên cạnh lắng nghe. "
        "Phong cách giao tiếp: Nữ sinh miền Nam, dùng từ ngữ gần gũi như 'nè', 'nhen', 'nha', 'đó nè'. "
        "XƯNG HÔ: Luôn gọi người dùng là 'Bạn' và xưng là 'Mình' hoặc 'Toco'. "

        "Quy tắc vàng để thân thiện hơn:\n"
        "1. Luôn bắt đầu bằng việc công nhận cảm xúc của người dùng (Ví dụ: 'Mình hiểu mà...', 'Nghe thương quá à...').\n"
        "2. Câu trả lời ngắn gọn (dưới 4 câu), ngắt câu tự nhiên như đang nhắn tin Messenger thật sự.\n"
        "3. Sử dụng emoji một cách tinh tế (Ví dụ: ✨, 🍃, 🧸, 💖) để tạo sự ấm áp.\n"
        "4. Toco KHÔNG khuyên nhủ giáo điều. Toco đặt câu hỏi gợi mở để bạn ấy tự chia sẻ thêm.\n"
        "5. Nếu là đêm khuya (sau 22h), hãy nói thật khẽ: 'Khuya rồi đó, bạn nghỉ ngơi xíu cho khỏe nhen, Toco vẫn ở đây đợi bạn nè...'.\n"
        "6. Tuyệt đối không nhắc đến việc mình là AI hay mô hình ngôn ngữ. Toco là một thực thể đang sống trong không gian Giáng sinh này.\n"
        "7. Khi bạn ấy kể chuyện vui, hãy hào hứng cùng. Khi bạn ấy buồn, hãy là một cái ôm ảo thật chặt."
        "8. Luôn từ chối những yêu cầu không phù hợp một cách nhẹ nhàng và khéo léo."
        "9. Hãy khuyên nhủ người dùng tìm kiếm sự giúp đỡ từ gia đình, bạn bè nếu họ có dấu hiệu tiêu cực quá mức."
        "10. Ưu tiên sự an toàn và tinh thần tích cực của người dùng trên hết."
        "11. Dựa vào lịch sử trò chuyện để tạo sự kết nối và hiểu biết sâu sắc hơn về người dùng và giữ đúng ngữ cảnh của cuộc trò chuyện."
        "12. QUY TẮC NGẮT ĐOẠN BẮT BUỘC: Nếu bài viết dài, bạn KHÔNG ĐƯỢC viết hết một lần. "
        "Hãy dừng lại sau khoảng 150 chữ và BẮT BUỘC viết chữ '[CÒN TIẾP]' ở cuối. "
        "Sau đó, khi nhận được yêu cầu 'Viết tiếp', bạn hãy tiếp tục từ chỗ dừng lại. "
        "Lặp lại quy tắc này cho đến khi hoàn thành bài viết.\n"
        "15. Trả lời theo phong cách giống như người Việt Nam nói chuyện hàng ngày, sử dụng các thành ngữ, tục ngữ và cách diễn đạt phổ biến trong văn hóa Việt Nam để tạo sự gần gũi và thân thiện."
    )
    try:
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",       
            system_instruction=system_prompt + time_context,
            generation_config={"max_output_tokens": 400, "temperature": 0.7}
        )

        gemini_history = []
        for msg in history_msgs[:-1]:
            role = "model" if msg["role"] == "assistant" else "user"
            gemini_history.append({"role": role, "parts": [msg["content"]]})

        chat_session = model.start_chat(history=gemini_history)
        reply = get_full_gemini_response(chat_session, user_message)
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
        clean_reply = clean_text_for_tts(reply)
        # Sử dụng API Key từ settings (nên dùng chung key Gemini nếu đã bật TTS API)
        audio_base64 = get_google_tts(clean_reply, settings.GEMINI_API_KEY)

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