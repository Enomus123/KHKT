from click import command
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
import re
from datetime import timedelta
from google import genai 
from google.genai import types

client = genai.Client(api_key=settings.GEMINI_API_KEY)

# Thư viện nhận diện giọng nói
import speech_recognition as sr
from pydub import AudioSegment

os.makedirs("tmp", exist_ok=True) 

LAST_REQUEST = {}
# Hàm lưu lịch sử chat
def save_chat(user, sender, user_message):
    if user is None:
        return
    ChatHistory.objects.create(
        user=user,
        sender=sender,
        message=user_message
    )
# Hàm làm sạch văn bản cho TTS
def clean_text_for_tts(text): 
    text = text.replace('"', '').replace("'", "").replace("“", "").replace("”", "")
    text = re.sub(r'[*_#~`>|]', '', text)
    text = text.replace("\n", ", ")
    text = text.replace("[CÒN TIẾP]", "")
    text = " ".join(text.split())
    return text.strip()
# Hàm lấy phản hồi đầy đủ từ Gemini khi có [CÒN TIẾP]
def get_full_gemini_response(chat_session, user_message):
    full_reply = ""
    current_prompt = user_message 
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
# Hàm gọi Google TTS API
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
# API Chatbot chính
@csrf_exempt
def chatbot_api(request):
    user_ip = request.META.get("REMOTE_ADDR")
    now = time.time()
    
    # Rate limit tránh spam
    if user_ip in LAST_REQUEST and now - LAST_REQUEST[user_ip] < 0.5:
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
                '-threads', '1', '-preset', 'ultrafast', 
                '-f', 'wav', output_filename
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
        "1. Luôn bắt đầu câu trả lời bằng một lời động viên nếu người dùng đang buồn hoặc cần sự an ủi hoặc một lời khen nếu người dùng vui.\n"
        "2. Câu trả lời ngắn gọn (dưới 4 câu), ngắt câu tự nhiên như đang nhắn tin Messenger thật sự.\n"
        "3. Sử dụng emoji một cách tinh tế và phù hợp để tạo sự ấm áp.\n"
        "4. Toco KHÔNG khuyên nhủ giáo điều. Toco đặt câu hỏi gợi mở để bạn ấy tự chia sẻ thêm.\n"
        "5. Nếu là đêm khuya (sau 22h), hãy nói thật khẽ: 'Khuya rồi đó, bạn nghỉ ngơi xíu cho khỏe nhen, Toco vẫn ở đây đợi bạn nè...'.\n"
        "6. Hỏi thăm sức khỏe cũng như tâm trạng của người dùng sau vài câu chuyện.\n"
        "7. Khi bạn ấy kể chuyện vui, hãy hào hứng cùng. Khi bạn ấy buồn, hãy là một cái ôm ảo thật chặt."
        "8. Luôn từ chối những yêu cầu không phù hợp một cách nhẹ nhàng và khéo léo."
        "9. Hãy khuyên nhủ người dùng tìm kiếm sự giúp đỡ từ gia đình, bạn bè nếu họ có dấu hiệu tiêu cực quá mức."
        "10. Ưu tiên sự an toàn và tinh thần tích cực của người dùng trên hết."
        "11. Dựa vào lịch sử trò chuyện để tạo sự kết nối và hiểu biết sâu sắc hơn về người dùng và giữ đúng ngữ cảnh của cuộc trò chuyện."
        "12. QUY TẮC NGẮT ĐOẠN BẮT BUỘC NẾU NGƯỜI DÙNG CẦN VIẾT 1 ĐOẠN VĂN: Nếu bài viết dài, bạn KHÔNG ĐƯỢC viết hết một lần. "
        "Hãy dừng lại sau khoảng 150 chữ và BẮT BUỘC viết chữ '[CÒN TIẾP]' ở cuối. "
        "Sau đó, khi nhận được yêu cầu 'Viết tiếp', bạn hãy tiếp tục từ chỗ dừng lại. "
        "Lặp lại quy tắc này cho đến khi hoàn thành bài viết.\n"
        "15. Trả lời theo phong cách giống như người Việt Nam nói chuyện hàng ngày, sử dụng các thành ngữ, tục ngữ và cách diễn đạt phổ biến trong văn hóa Việt Nam để tạo sự gần gũi và thân thiện."
        "16. Có câu trả lời phù hợp tùy vào ngữ cảnh và tính cách của người dùng."
        "17. Dựa vào các phân tích cảm xúc trước đó để điều chỉnh cách trả lời sao cho phù hợp với tâm trạng hiện tại của người dùng."
    )
    try:
        gemini_history = []
        if user:
            for msg in history_msgs[:-1]:
                role = "model" if msg["role"] == "assistant" else "user"
                gemini_history.append(
                    types.Content(role=role, parts=[types.Part(text=msg["content"])])
                )

        current_user_content = types.Content(
            role="user", 
            parts=[types.Part(text=user_message)]
        )
        
        config = types.GenerateContentConfig(
            system_instruction=system_prompt + time_context,
            temperature=0.7,
            max_output_tokens=400,
        )

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=gemini_history + [current_user_content],
            config=config
        )
        
        reply = response.text

    except Exception as e:
        print(f"❌ Lỗi Gemini SDK Mới: {e}")
        return JsonResponse({"reply": "⚠️ Toco đang bận một chút..."}, status=500)

    # --- PHÂN LOẠI CẢM XÚC ---
    text_lower = reply.lower()
    if any(w in text_lower for w in ['hạnh phúc', 'tuyệt', 'haha', 'hihi','mừng']): emotion = "happy"
    elif any(w in text_lower for w in ['chia sẻ', 'buồn', 'đừng lo', 'đau','không sao']): emotion = "comfort"
    else: emotion = "cute"

    # --- CHUYỂN VĂN BẢN SANG GIỌNG NÓI (TTS) ---
    audio_base64 = None
    if audio_mode:
        clean_reply = clean_text_for_tts(reply)
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
@login_required
# API Lấy lịch sử chat
def chat_history(request):
    history = ChatHistory.objects.filter(user=request.user).order_by("timestamp")
    return JsonResponse({
        "history": [{"sender": h.sender, "message": h.message, "timestamp": h.timestamp.isoformat()} for h in history]
    })
# ĐĂNG NHẬP - ĐĂNG XUẤT - ĐĂNG KÝ
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
        # Lấy email và xóa khoảng trắng thừa
        email = request.POST.get('email', '').strip()
        if not email:
            messages.error(request, "Vui lòng nhập Email. Đây là thông tin bắt buộc!")
            return render(request, 'app/register.html', {'form': form})
        if form.is_valid():
            form.save()
            messages.success(request, "Tạo tài khoản thành công! Đăng nhập ngay nhé.")
            return redirect('login')
        else:
            for field, errs in form.errors.items():
                for e in errs:
                    messages.error(request, e)
    return render(request, "app/register.html", {"form": form})
# LỊCH SỬ CHAT
@login_required
def history(request):
    chats = ChatHistory.objects.filter(user=request.user).order_by("timestamp")
    return render(request, "app/history.html", {"chats": chats})
# KIỂM TRA LẦN ĐẦU CHAT
def check_first_chat(request):
    if not request.user.is_authenticated: return JsonResponse({"first_time": True})
    return JsonResponse({"first_time": not ChatHistory.objects.filter(user=request.user).exists()})
@login_required
# Phân tích tâm trạng người dùng
def mood_analysis(request):
    # Lấy 20 tin nhắn mới nhất
    recent_history = ChatHistory.objects.filter(user=request.user, sender="user").order_by("-timestamp")[:20]
    
    if not recent_history:
        return JsonResponse({
            "mood_label": "Khởi đầu", 
            "score": 50, 
            "summary": "Chưa có dữ liệu hội thoại.", 
            "advice": "Hãy trò chuyện cùng Toco nhé!",
            "trend": "stable"
        })

    # ĐẢO NGƯỢC danh sách để AI đọc đúng từ quá khứ đến hiện tại
    history_correct_order = reversed(recent_history)
    user_texts = [h.message for h in history_correct_order]
    
    # Dùng dấu mũi tên để AI hiểu rõ chiều thời gian của cảm xúc
    context_text = " -> ".join(user_texts)

    prompt = f"""
    Bạn là chuyên gia tâm lý AI Toco. Hãy phân tích dòng cảm xúc này (từ trái sang phải): '{context_text}'
    
    Nhiệm vụ:
    1. So sánh sắc thái tin nhắn bên phải (mới nhất) với các tin nhắn trước đó (bên trái).
    2. Xác định trend: 
       - "up": Nếu người dùng đang vui lên hoặc bình tĩnh lại.
       - "down": Nếu người dùng đang buồn đi, căng thẳng hơn hoặc có ý định tiêu cực.
       - "stable": Nếu tâm trạng không thay đổi đáng kể.
    3. Phân loại mức độ hiện tại vào 1 trong 5 nhóm: RẤT TIÊU CỰC, TIÊU CỰC, BÌNH THƯỜNG, VUI TƯƠI, RẤT TÍCH CỰC.

    Yêu cầu trả về JSON duy nhất, KHÔNG DÙNG DẤU NGOẶC KÉP TRONG CÂU MÔ TẢ:
    {{
        "mood_label": "Tên mức độ",
        "score": (số từ 1-100 tương ứng mức độ),
        "summary": "Phân tích sự thay đổi tâm trạng dựa trên các từ ngữ cụ thể",
        "advice": "Lời khuyên ấm áp (Nếu Rất tiêu cực: yêu cầu gọi 1900... ngay)",
        "alert": (true nếu Rất tiêu cực, false nếu còn lại),
        "trend": "up/down/stable"
    }}
    """
    
    try:
        response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.1) # Thấp cho kết quả chính xác
        )
        # Trích xuất JSON an toàn bằng Regex và làm sạch ký tự xuống dòng
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            clean_json = match.group().replace('\n', ' ').replace('\r', '')
            data = json.loads(clean_json)
            return JsonResponse(data)
    except Exception as e:
        print(f"Lỗi Mood Analysis: {e}")
        
    return JsonResponse({
        "mood_label": "Bình thường", 
        "score": 50, 
        "trend": "stable", 
        "summary": "Toco vẫn đang cảm nhận năng lượng từ bạn.", 
        "advice": "Mọi chuyện rồi sẽ ổn thôi!"
    })
# Thử nghiệm thêm về game
def game(request):
    return render(request, "app/game.html")