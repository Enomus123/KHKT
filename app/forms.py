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
                # Thông báo lỗi tiếng Việt trực tiếp trên form
                raise forms.ValidationError(
                    "Thông tin không chính xác. Tên đăng nhập hoặc Email không khớp với dữ liệu của chúng tôi."
                )
        return cleaned_data