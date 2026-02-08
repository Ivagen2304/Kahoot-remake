from django.shortcuts import render
import random
import string
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from .models import Quiz, Question, AnswerOption, GameSession, Player
from .forms import QuizForm, QuestionForm, AnswerOptionForm, AnswerOptionFormSet, JoinGameForm, RegisterForm, AuthenticationForm


def generate_code(length=6):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def home(request):
    error = None
    if request.method == 'POST':
        code = request.POST.get('code')
        if code:
            try:
                session = GameSession.objects.get(code=code.upper(), is_active=True)
                return redirect("enter_nickname", code=code.upper())
            except GameSession.DoesNotExist:
                error = f"Вікторину з кодом {code.upper()} не знайдено"
    return render(request, "home.html", {"error": error})


def register(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("create_quiz")
        else:
            print(form.errors)
    else:
        form = RegisterForm()

    return render(request, "register.html", {"form": form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("quiz_list")  # вже залогінений

    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect("quiz_list")
    else:
        form = AuthenticationForm()

    return render(request, "login.html", {"form": form})


def logout_view(request):
    logout(request)
    return redirect("home")


def quiz_list(request):
    quizzes = Quiz.objects.filter(owner=request.user)
    return render(request, "quiz_list.html", {"quizzes": quizzes})


@login_required
def create_quiz(request):
    if request.method == "POST":
        form = QuizForm(request.POST)
        if form.is_valid():
            quiz = form.save(commit=False)
            quiz.owner = request.user
            quiz.save()
            return redirect("quiz_detail", quiz.id)
    else:
        form = QuizForm()

    return render(request, "create_quiz.html", {"form": form})


@login_required
def quiz_detail(request, quiz_id):
    quiz = get_object_or_404(Quiz, id=quiz_id)
    questions = quiz.questions.all()
    return render(request, "quiz_detail.html", {"quiz": quiz, "questions": questions})


@login_required
def add_question(request, quiz_id):
    quiz = get_object_or_404(Quiz, id=quiz_id)

    if request.method == 'POST':
        qform = QuestionForm(request.POST)
        formset = AnswerOptionFormSet(request.POST, prefix='answeroption_set')
        if qform.is_valid() and formset.is_valid():
            question = qform.save(commit=False)
            question.quiz = quiz
            question.save()
            formset.instance = question
            formset.save()
            return redirect('quiz_detail', quiz_id=quiz.id)  # можна додавати ще
    else:
        qform = QuestionForm()
        formset = AnswerOptionFormSet(prefix='answeroption_set')
    return render(request, 'add_question.html', {'qform': qform, 'formset': formset, 'quiz': quiz})


@login_required
def create_session(request, quiz_id):
    quiz = get_object_or_404(Quiz, id=quiz_id)

    code = generate_code()
    session = GameSession.objects.create(
        quiz=quiz,
        host=request.user,
        code=code
    )

    return redirect("host_room", session.code)


@login_required
def host_room(request, code):
    session = get_object_or_404(GameSession, code=code)
    return render(request, "host_room.html", {"session": session})


def player_room(request, code):
    session = get_object_or_404(GameSession, code=code)
    player_name = ""
    player_id = None
    if "player_id" in request.session:
        player = Player.objects.filter(id=request.session["player_id"], session=session).first()
        if player:
            player_name = player.name
            player_id = player.id
    return render(request, "player_room.html", {"session": session, "player_name": player_name, "player_id": player_id})

def enter_nickname(request, code):
    session = get_object_or_404(GameSession, code=code, is_active=True)
    if request.method == 'POST':
        name = request.POST.get('name')
        if name:
            player, created = Player.objects.get_or_create(session=session, name=name)
            request.session["player_id"] = player.id
            return redirect("player_room", code)
    return render(request, "join_nickname.html", {"code": code})

def test_play(request, code):
    session = get_object_or_404(GameSession, code=code)
    return render(request, "test_play.html", {"code": code, "session": session})


@login_required
def delete_question(request, quiz_id, question_id):
    quiz = get_object_or_404(Quiz, id=quiz_id, owner=request.user)
    question = get_object_or_404(Question, id=question_id, quiz=quiz)
    question.delete()
    return redirect("quiz_detail", quiz_id=quiz.id)
