from django import forms
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.models import User

class CustomPasswordResetForm(PasswordResetForm):
    username = forms.CharField(
        label="Tên đăng nhập", 
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nhập tên đăng nhập...'})
    )
    email = forms.EmailField(
        label="Email",
        required=True,  # Bắt buộc phải nhập email mới cho gửi form
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Nhập email đã đăng ký...'})
    )

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get("email")
        username = cleaned_data.get("username")

        if email and username:
            # Kiểm tra xem có User nào khớp cả 2 thông tin không
            user_exists = User.objects.filter(email__iexact=email, username__iexact=username).exists()
            if not user_exists:
                # Thông báo lỗi tiếng Việt trực tiếp trên form thay vì chuyển hướng
                raise forms.ValidationError(
                    "Thông tin không chính xác. Tên đăng nhập hoặc Email không khớp với dữ liệu của chúng tôi."
                )
        return cleaned_data

    def get_users(self, email):
        """
        Ghi đè logic mặc định để chỉ lấy đúng 1 người dùng khớp cả email và username.
        Điều này giúp khắc phục lỗi gửi 2 email cùng lúc mà bạn đang gặp phải.
        """
        username = self.cleaned_data.get("username")
        active_users = User.objects.filter(
            email__iexact=email,
            username__iexact=username,
            is_active=True
        )
        # Trả về duy nhất 1 đối tượng đầu tiên tìm thấy
        if active_users.exists():
            return [active_users.first()]
        return []