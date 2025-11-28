from django.db import models
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm 
from django.contrib.auth.models import User
class ChatHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    sender = models.CharField(max_length=10)   # user / bot
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.sender}: {self.message[:30]}"

# Change forms register django
class CreateUserForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['username','email','first_name','last_name','password1','password2']