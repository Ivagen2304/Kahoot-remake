import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "main_project.settings")
django.setup()

from app.models import Player
from django.db.models import Count

duplicates = Player.objects.values('session', 'name').annotate(count=Count('id')).filter(count__gt=1)
for dup in duplicates:
    players_to_delete = Player.objects.filter(session=dup['session'], name=dup['name'])[1:]
    for player in players_to_delete:
        player.delete()

print("Duplicates removed")
