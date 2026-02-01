import json
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from urllib.parse import parse_qs
from .models import GameSession, Player, AnswerOption, PlayerAnswer

class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.code = self.scope["url_route"]["kwargs"]["code"]
        self.room_group_name = f"game_{self.code}"

        # Перевіряємо сесію
        self.session = await sync_to_async(
            GameSession.objects.filter(code=self.code, is_active=True).first
        )()
        if not self.session:
            await self.close()
            return

        # 👉 ПРОВЕРЯЕМ, ХОст ЛИ ЭТО
        user = self.scope.get("user")
        host_id = await sync_to_async(lambda: self.session.host.id)()
        self.is_host = user and user.is_authenticated and user.id == host_id

        # 👉 Дістаємо імʼя гравця з WebSocket URL
        query_string = parse_qs(self.scope["query_string"].decode())
        player_name = query_string.get("name", [None])[0]

        # Если хост — не создаём Player, но сохраняем имя для отображения
        if self.is_host:
            self.player = None
            self.host_name = player_name or user.username if user else "Host"
        else:
            if not player_name:
                await self.close()
                return

            # 👉 Створюємо або беремо гравця
            self.player, _ = await sync_to_async(Player.objects.get_or_create)(
                session=self.session,
                name=player_name,
                # 👇 ЕСЛИ УЖЕ СУЩЕСТВУЕТ — НЕ СОЗДАЁМ ДУБЛЬ
                defaults={"correct_answers": 0}
            )

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

        await self.send(text_data=json.dumps({
            "type": "connected",
            "message": f"Connected as {self.player.name if self.player else 'host'}"
        }))

        await self.broadcast_players()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        await self.broadcast_players()

    async def receive(self, text_data):
        data = json.loads(text_data)

        if data["type"] == "join":
            await self.add_player(data["name"])
        elif data["type"] == "start_game":
            await self.start_game()
        elif data["type"] == "answer":
            await self.record_answer(data)
        elif data["type"] == "get_current_question":  # 👈 ДОБАВЬ ЭТО
            session = await sync_to_async(GameSession.objects.get)(code=self.code)
            await self.send_first_question(session)
    # =====================
    # Методи гри
    # =====================

    async def start_game(self):
        """Старт гри: редірект гравців і перше питання"""
        session = await sync_to_async(GameSession.objects.get)(code=self.code)

        # Редірект усіх гравців на сторінку проходження
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "redirect_players",
                "url": f"/play/{self.code}/"
            }
        )

        # Надсилаємо перше питання
        await self.send_first_question(session)

    async def send_first_question(self, session):
        """Відправляє перше питання всім гравцям"""
        question = await sync_to_async(lambda: session.quiz.questions.first())()
        options = await sync_to_async(lambda: list(question.options.all()))() if question else []

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "show_question",
                "question": question.text if question else "Немає питань",
                "options": [{"id": o.id, "text": o.text} for o in options]
            }
        )

    async def record_answer(self, data):
        """Записывает ответ игрока"""
        # 👇 ХОСТ НЕ МОЖЕТ ОТВЕЧАТЬ
        if not self.player:
            return
    
        option_id = data["option_id"]

        option = await sync_to_async(AnswerOption.objects.get)(
            id=option_id
        )

        is_correct = option.is_correct

        # 👇 ЗАПИСЫВАЕМ ОТВЕТ ОДИН РАЗ
        await sync_to_async(PlayerAnswer.objects.create)(
            player=self.player,
            question=await sync_to_async(lambda: option.question)(),
            selected_option=option,
            is_correct=is_correct
        )

        # 👇 ОБНОВЛЯЕМ СЧЁТЧИК ЕСЛИ ПРАВИЛЬНО
        if is_correct:
            self.player.correct_answers += 1
            await sync_to_async(self.player.save)()

        # 👇 ОТПРАВЛЯЕМ "waiting" ВСЕМ ДРУГИМ ИГРОКАМ
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "player_answered",
                "player_name": self.player.name,
                "is_correct": is_correct
            }
        )

    async def broadcast_players(self):
        """Надсилає актуальний список гравців (БЕЗ ХОСТА)"""
        players = await sync_to_async(list)(
            Player.objects.filter(session__code=self.code).values_list("name", flat=True)
        )
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "players_update",
                "players": list(players)
            }
        )

    async def add_player(self, name):
        """Додає гравця в сесію"""
        session = await sync_to_async(GameSession.objects.get)(code=self.code)
        await sync_to_async(Player.objects.create)(session=session, name=name)
        await self.broadcast_players()

    # =====================
    # Методи group_send
    # =====================

    # 👇 ДОБАВЛЯЕМ НОВЫЙ МЕТОД ДЛЯ ВЫВОДА WAITING
    async def player_answered(self, event):
        """Отправляет уведомление что игрок ответил"""
        await self.send(text_data=json.dumps({
            "type": "waiting",
            "player_name": event["player_name"],
            "is_correct": event["is_correct"]
        }))

    async def show_question(self, event):
        await self.send(text_data=json.dumps({
            "type": "question",
            "text": event["question"],
            "options": event["options"]
        }))

    async def redirect_players(self, event):
        await self.send(text_data=json.dumps({
            "type": "redirect",
            "url": event["url"]
        }))

    async def players_update(self, event):
        await self.send(text_data=json.dumps({
            "type": "players",
            "players": event["players"]
        }))
