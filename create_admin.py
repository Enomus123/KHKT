import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'duankhkt.settings') # Thay duankhkt bằng tên thư mục settings của bạn
django.setup()

from django.contrib.auth.models import User

username = "#EnomusadminToco0913"
email = "ttungduong2000@gmail.com"
password = 'Tocomanifestgiaikhktcaptinh20252026'

if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username, email, password)
    print(f"Đã tạo tài khoản admin: {username}")
else:
    print("Tài khoản admin đã tồn tại.")