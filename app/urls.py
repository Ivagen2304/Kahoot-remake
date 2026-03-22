from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("register/", views.register, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("quiz/list/", views.quiz_list, name="quiz_list"),
    path("quiz/create/", views.create_quiz, name="create_quiz"),
    path("quiz/<int:quiz_id>/", views.quiz_detail, name="quiz_detail"),
    path("quiz/<int:quiz_id>/add-question/", views.add_question, name="add_question"),
    path("quiz/<int:quiz_id>/delete-question/<int:question_id>/", views.delete_question, name="delete_question"),

    path("quiz/<int:quiz_id>/start/", views.create_session, name="create_session"),

    path("enter/<str:code>/", views.enter_nickname, name="enter_nickname"),
    path("host/<str:code>/", views.host_room, name="host_room"),
    path("lobby/<str:code>/", views.player_room, name="player_room"),
    path("play/<str:code>/", views.test_play, name="test_play"),
]