from django.contrib import admin
from .models import Quiz, Question, GameSession, Player

admin.site.register(Quiz)
admin.site.register(Question)
admin.site.register(GameSession)
admin.site.register(Player)