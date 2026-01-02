import json
from django.contrib import admin
from django.contrib.auth.models import User
from .models import ChatHistory
from django.db.models import Count
from django.utils import timezone
from datetime import timedelta
from django.utils.html import format_html

# 1. Ẩn phần xem nội dung tin nhắn chi tiết
@admin.register(ChatHistory)
class ChatHistoryAdmin(admin.ModelAdmin):
    # Chỉ hiển thị các thông tin không nhạy cảm
    list_display = ('user', 'timestamp')
    list_filter = ('timestamp',)
    
    # Chặn quyền xem chi tiết nội dung tin nhắn
    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def changelist_view(self, request, extra_context=None):
        # --- LOGIC THỐNG KÊ ---
        today = timezone.now()
        last_7_days = [today - timedelta(days=i) for i in range(6, -1, -1)]
        labels = [d.strftime('%d/%m') for d in last_7_days]

        # Đếm số User mới mỗi ngày trong tuần qua
        user_counts = []
        for d in last_7_days:
            count = User.objects.filter(date_joined__date=d.date()).count()
            user_counts.append(count)

        # Đếm số tin nhắn (tương tác) mỗi ngày (không lấy nội dung)
        msg_counts = []
        for d in last_7_days:
            count = ChatHistory.objects.filter(timestamp__date=d.date()).count()
            msg_counts.append(count)

        # Thống kê trạng thái Online
        online_5m = User.objects.filter(last_login__gte=today - timedelta(minutes=5)).count()
        total_u = User.objects.count()

        # --- GIAO DIỆN BIỂU ĐỒ & BẢNG (NHÚNG TRỰC TIẾP) ---
        chart_html = format_html('''
            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
            <div style="display: flex; gap: 20px; margin-bottom: 25px; font-family: sans-serif;">
                <div style="flex: 1; background: #1a472a; color: white; padding: 20px; border-radius: 12px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                    <div style="font-size: 14px; opacity: 0.8;">ĐANG HOẠT ĐỘNG</div>
                    <div style="font-size: 32px; font-weight: bold; margin-top: 5px;">{0}</div>
                </div>
                <div style="flex: 1; background: #d42426; color: white; padding: 20px; border-radius: 12px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                    <div style="font-size: 14px; opacity: 0.8;">TỔNG NGƯỜI DÙNG</div>
                    <div style="font-size: 32px; font-weight: bold; margin-top: 5px;">{1}</div>
                </div>
            </div>

            <div style="background: white; padding: 20px; border-radius: 12px; border: 1px solid #eee; margin-bottom: 25px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
                <canvas id="tocoStatsChart" style="max-height: 300px;"></canvas>
            </div>

            <script>
                new Chart(document.getElementById('tocoStatsChart'), {{
                    type: 'line',
                    data: {{
                        labels: {2},
                        datasets: [
                            {{
                                label: 'Lượt tương tác (Tin nhắn)',
                                data: {3},
                                borderColor: '#d42426',
                                backgroundColor: 'rgba(212, 36, 38, 0.1)',
                                fill: true,
                                tension: 0.4
                            }},
                            {{
                                label: 'Người dùng mới',
                                data: {4},
                                borderColor: '#1a472a',
                                borderDash: [5, 5],
                                fill: false
                            }}
                        ]
                    }},
                    options: {{
                        responsive: true,
                        plugins: {{ title: {{ display: true, text: 'Tình hình sử dụng trong 7 ngày qua' }} }}
                    }}
                }});
            </script>
        ''', online_5m, total_u, json.dumps(labels), json.dumps(msg_counts), json.dumps(user_counts))

        self.message_user(request, chart_html)
        return super().changelist_view(request, extra_context=extra_context)

# 2. Quản lý thời gian sử dụng trong mục Users
admin.site.unregister(User)
@admin.register(User)
class CustomUserAdmin(admin.ModelAdmin):
    list_display = ('username', 'date_joined', 'last_login', 'is_active')
    list_filter = ('date_joined', 'last_login')
    # Sắp xếp ai vừa online lên đầu
    ordering = ('-last_login',)