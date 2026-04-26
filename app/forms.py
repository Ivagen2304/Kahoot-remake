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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['title'].widget.attrs.update({'class': 'form-input', 'placeholder': 'Назва вашої вікторини (напр. Історія України)'})
        self.fields['description'].widget.attrs.update({'class': 'form-input form-textarea', 'placeholder': 'Короткий опис, про що ця гра...'})

    class Meta:
        model = Quiz
        fields = ["title", "description"]


class QuestionForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['text'].widget.attrs.update({'class': 'form-input', 'placeholder': 'Введіть питання'})
        self.fields['image'].widget.attrs.update({'class': 'form-input'})
        self.fields['time_limit'].widget.attrs.update({'class': 'form-input'})
        self.fields['question_type'].widget.attrs.update({'class': 'form-input'})

    class Meta:
        model = Question
        fields = ["text", "image", "question_type", "time_limit"]


class AnswerOptionForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['text'].widget.attrs.update({'class': 'form-input', 'placeholder': 'Введіть варіант відповіді'})
        self.fields['is_correct'].widget.attrs['class'] = 'checkbox-input'
        self.fields['is_correct'].label = 'Правильна'
        self.fields['order'].widget.attrs.update({'class': 'form-input', 'style': 'width: 60px; text-align: center;', 'min': '0'})

    class Meta:
        model = AnswerOption
        fields = ["text", "is_correct", "order"]

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