from django.shortcuts import render
import random
import string
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Quiz, Question, AnswerOption, GameSession, Player
from .forms import QuizForm, QuestionForm, AnswerOptionForm, JoinGameForm


def generate_code(length=6):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


@login_required
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

    if request.method == "POST":
        form = QuestionForm(request.POST)
        if form.is_valid():
            question = form.save(commit=False)
            question.quiz = quiz
            question.save()
            return redirect("quiz_detail", quiz.id)
    else:
        form = QuestionForm()

    return render(request, "add_question.html", {"form": form, "quiz": quiz})


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


def join_game(request):
    if request.method == "POST":
        form = JoinGameForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data["name"]
            code = form.cleaned_data["code"]

            session = get_object_or_404(GameSession, code=code, is_active=True)
            player = Player.objects.create(
                session=session,
                name=name
            )

            request.session["player_id"] = player.id
            return redirect("player_room", session.code)
    else:
        form = JoinGameForm()

    return render(request, "join_game.html", {"form": form})


@login_required
def host_room(request, code):
    session = get_object_or_404(GameSession, code=code)
    return render(request, "host_room.html", {"session": session})


def player_room(request, code):
    session = get_object_or_404(GameSession, code=code)
    return render(request, "player_room.html", {"session": session})