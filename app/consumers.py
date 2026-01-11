import json
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from asgiref.sync import sync_to_async
from .models import GameSession, Player

class GameConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.code = self.scope["url_route"]["kwargs"]["code"]
        self.room_group_name = f"game_{self.code}"

        # Перевіряємо, чи існує активна сесія
        exists = await sync_to_async(GameSession.objects.filter(code=self.code, is_active=True).exists)()
        if not exists:
            await self.close()
            return

        # Додаємо сокет у групу
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        # Підтвердження підключення
        await self.send_json({
            "type": "connected",
            "message": f"Connected to game {self.code}"
        })

        # Надсилаємо поточний список гравців
        await self.broadcast_players()

    async def disconnect(self, close_code):
        # Видаляємо з групи
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        await self.broadcast_players()

    async def receive_json(self, content):
        """Цей метод викликається при отриманні JSON"""
        if content["type"] == "join":
            await self.add_player(content["name"])
        elif content["type"] == "start_game":
            await self.start_game()

    async def add_player(self, name):
        """Додаємо гравця у сесію, якщо його ще немає"""
        session = await sync_to_async(GameSession.objects.get)(code=self.code)

        # Перевірка, чи вже є такий гравець
        exists = await sync_to_async(Player.objects.filter(session=session, name=name).exists)()
        if not exists:
            await sync_to_async(Player.objects.create)(session=session, name=name)

        await self.broadcast_players()

    async def broadcast_players(self):
        """Надсилаємо всім гравцям список учасників"""
        session = await sync_to_async(GameSession.objects.get)(code=self.code)
        players = await sync_to_async(list)(Player.objects.filter(session=session))
        names = [p.name for p in players]

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "players_update",
                "players": names
            }
        )

    async def players_update(self, event):
        """Обробка події для оновлення списку гравців"""
        await self.send_json({
            "type": "players",
            "players": event["players"]
        })

    async def start_game(self):
        """Стартує гру та надсилає перше питання"""
        session = await sync_to_async(GameSession.objects.get)(code=self.code)
        question = await sync_to_async(lambda: session.quiz.questions.first())()

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "show_question",
                "question": question.text if question else "Немає питань"
            }
        )

    async def show_question(self, event):
        """Надсилає питання всім гравцям"""
        await self.send_json({
            "type": "question",
            "text": event["question"]
        })
