from django import forms
from .models import Quiz, Question, AnswerOption, GameSession, Player
from django.forms import inlineformset_factory
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm


class RegisterForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "password1", "password2")

        labels = {
            "username": "Ім'я користувача",
            "password1": "Пароль",
            "password2": "Підтвердження пароля",
        }



class QuizForm(forms.ModelForm):
    class Meta:
        model = Quiz
        fields = ["title", "description"]


class QuestionForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = ["text", "time_limit"]


class AnswerOptionForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['is_correct'].widget.attrs['class'] = 'checkbox-input'
        self.fields['is_correct'].label = 'Правильна відповідь'

    class Meta:
        model = AnswerOption
        fields = ["text", "is_correct"]

AnswerOptionFormSet = inlineformset_factory(
    Question, AnswerOption, form=AnswerOptionForm, extra=2
)


class CreateSessionForm(forms.ModelForm):
    class Meta:
        model = GameSession
        fields = []  # тільки створення сесії (код згенеруємо автоматично)


class JoinGameForm(forms.Form):
    name = forms.CharField(max_length=100, label="Ваше імʼя")
    code = forms.CharField(max_length=6, label="Код гри")