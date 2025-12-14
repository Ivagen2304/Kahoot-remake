from django import forms
from .models import Quiz, Question, AnswerOption, GameSession, Player


class QuizForm(forms.ModelForm):
    class Meta:
        model = Quiz
        fields = ["title", "description"]


class QuestionForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = ["text", "time_limit"]


class AnswerOptionForm(forms.ModelForm):
    class Meta:
        model = AnswerOption
        fields = ["text", "is_correct"]


class CreateSessionForm(forms.ModelForm):
    class Meta:
        model = GameSession
        fields = []  # тільки створення сесії (код згенеруємо автоматично)


class JoinGameForm(forms.Form):
    name = forms.CharField(max_length=100, label="Ваше імʼя")
    code = forms.CharField(max_length=6, label="Код гри")