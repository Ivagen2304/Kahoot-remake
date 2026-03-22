from django.db import models
from django.contrib.auth.models import User
import uuid

class Quiz(models.Model):
    """Основна вікторина"""
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Question(models.Model):
    """Питання у вікторині"""
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    text = models.CharField(max_length=500)
    time_limit = models.IntegerField(default=20)  # сек на питання

    def __str__(self):
        return self.text


class AnswerOption(models.Model):
    """Варіанти відповідей"""
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    text = models.CharField(max_length=300)
    is_correct = models.BooleanField(default=False)

    def __str__(self):
        return self.text


class GameSession(models.Model):
    """Сесія"""
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE)
    host = models.ForeignKey(User, on_delete=models.CASCADE)
    code = models.CharField(max_length=6, unique=True)  # 6-значний код для входу
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    current_question_index = models.IntegerField(default=0)

    def __str__(self):
        return f"Session {self.code}"


class Player(models.Model):
    """Гравець, що приєднався через код"""
    session = models.ForeignKey(GameSession, on_delete=models.CASCADE, related_name="players")
    name = models.CharField(max_length=100)
    current_answer = models.CharField(max_length=300, null=True, blank=True)
    correct_answers = models.IntegerField(default=0)
    channel_name = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        unique_together = ('session', 'name')

    def __str__(self):
        return self.name


class PlayerAnswer(models.Model):
    """Відповідь гравця на одне питання"""
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    selected_option = models.ForeignKey(AnswerOption, on_delete=models.CASCADE, null=True)
    is_correct = models.BooleanField(default=False)
    answered_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.player} - {self.question}"
