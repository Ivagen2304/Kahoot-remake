import json
import asyncio
from asyncio import sleep
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from urllib.parse import parse_qs
from django.db import connection
from .models import GameSession, Player, AnswerOption, PlayerAnswer

class GameConsumer(AsyncWebsocketConsumer):
    # Class variable to store active timers per room
    active_timers = {}

    async def connect(self):
        self.code = self.scope["url_route"]["kwargs"]["code"]
        self.room_group_name = f"game_{self.code}"

        # Перевіряємо сесію
        self.session = await sync_to_async(lambda: GameSession.objects.filter(code=self.code, is_active=True).first())()
        if not self.session:
            await self.close()
            return

        # 👉 ПРОВЕРЯЕМ, ХОст ЛИ ЭТО
        user = self.scope.get("user")
        host_id = await sync_to_async(lambda: self.session.host_id)()
        self.is_host = user and user.is_authenticated and user.id == host_id

        # 👉 Дістаємо імʼя гравця з WebSocket URL
        query_string = parse_qs(self.scope["query_string"].decode())
        player_name = query_string.get("name", [None])[0]

        # Если хост — не создаём Player, но сохраняем имя для отображения
        if self.is_host:
            self.player = None
            self.host_name = player_name or user.username if user else "Host"
        else:
            # 👉 Спробуємо знайти гравця за player_id з сесії
            session_dict = self.scope.get("session", {})
            player_id = session_dict.get("player_id")
            if player_id:
                self.player = await sync_to_async(lambda: Player.objects.filter(id=player_id, session=self.session).first())()
                if self.player:
                    self.player.channel_name = self.channel_name
                    await sync_to_async(self.player.save)()
                else:
                    # Якщо не знайдено, закриваємо з'єднання
                    await self.close()
                    return
            else:
                # Якщо немає player_id, закриваємо
                await self.close()
                return

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
        elif data["type"] == "kick_player":
            await self.kick_player(data)
        elif data["type"] == "get_current_question":  # 👈 ДОБАВЬ ЭТО
            session = await sync_to_async(GameSession.objects.get)(code=self.code)
            await sync_to_async(session.refresh_from_db)()
            await self.send_current_question(session)
        elif data["type"] == "time_up":
            await self.handle_time_up()
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
        session.current_question_index = 0
        await sync_to_async(session.save)()
        await self.send_current_question(session)

    async def send_current_question(self, session):
        """Відправляє поточне питання всім гравцям"""
        questions = await sync_to_async(lambda: list(session.quiz.questions.order_by('id')))()
        current_index = session.current_question_index

        if current_index < len(questions):
            question = questions[current_index]
            options = await sync_to_async(lambda: list(question.options.all()))()

            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "show_question",
                    "question": question.text,
                    "options": [{"id": o.id, "text": o.text} for o in options],
                    "time_limit": question.time_limit
                }
            )

            # Start server-side timer for the room
            await self.start_question_timer(question.time_limit, False)
        else:
            await self.show_final_results(session)

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
        question = await sync_to_async(lambda: option.question)()

        # 👇 ПРОВЕРЯЕМ, НЕ ОТВЕЧАЛ ЛИ УЖЕ ИГРОК НА ЭТОТ ВОПРОС
        if await sync_to_async(PlayerAnswer.objects.filter(player=self.player, question=question).exists)():
            return

        # 👇 ЗАПИСЫВАЕМ ОТВЕТ ОДИН РАЗ
        await sync_to_async(PlayerAnswer.objects.create)(
            player=self.player,
            question=question,
            selected_option=option,
            is_correct=is_correct
        )

        # 👇 ОБНОВЛЯЕМ СЧЁТЧИК ЕСЛИ ПРАВИЛЬНО
        if is_correct:
            self.player.correct_answers += 1
            await sync_to_async(self.player.save)()

        # 👇 ПРОВЕРЯЕМ, ВСЕ ЛИ ИГРОКИ ОТВЕТИЛИ
        await self.check_all_answered(question, self.player.name, is_correct)

    async def check_all_answered(self, question, player_name, is_correct):
        """Проверяет, все ли игроки ответили на вопрос"""
        session = await sync_to_async(GameSession.objects.get)(code=self.code)
        total_players = await sync_to_async(lambda: session.players.count())()
        answered_players = await sync_to_async(lambda: PlayerAnswer.objects.filter(question=question).count())()

        # Отправляем обновление счетчика ответов всем игрокам
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "answers_update",
                "answered": answered_players,
                "total": total_players
            }
        )

        if answered_players >= total_players:
            # Cancel the timer if it's still running
            if self.code in self.active_timers:
                self.active_timers[self.code].cancel()
                del self.active_timers[self.code]
            await self.show_answer_and_next_question(session, question)

    async def show_answer_and_next_question(self, session, question):
        """Показывает правильный ответ и переходит к следующему вопросу"""
        # Cancel the timer if it exists
        if self.code in self.active_timers:
            self.active_timers[self.code].cancel()
            del self.active_timers[self.code]

        # Получаем список вопросов
        questions = await sync_to_async(lambda: list(session.quiz.questions.order_by('id')))()
        current_index = session.current_question_index
        next_index = current_index + 1

        # Показываем правильный ответ
        correct_option = await sync_to_async(lambda: question.options.filter(is_correct=True).first())()
        total_players = await sync_to_async(lambda: session.players.count())()
        wait_time = 0.1 if total_players == 1 else 3  # Для одного игрока небольшая задержка для порядка сообщений

        if next_index < len(questions):
            # Инкрементируем индекс
            session.current_question_index = next_index
            await sync_to_async(session.save)()

            # Показываем правильный ответ
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "show_answer",
                    "correct_option": correct_option.text if correct_option else "No correct answer",
                    "wait_time": wait_time
                }
            )

            # Ждем немного для порядка сообщений
            await sleep(wait_time)

            # Отправляем следующий вопрос
            next_question = questions[next_index]
            options = await sync_to_async(lambda: list(next_question.options.all()))()
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "show_question",
                    "question": next_question.text,
                    "options": [{"id": o.id, "text": o.text} for o in options],
                    "time_limit": next_question.time_limit
                }
            )

            # Start timer for the next question
            await self.start_question_timer(next_question.time_limit, force_restart=True)
        else:
            # Вопросы закончились, показываем результаты
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "show_answer",
                    "correct_option": correct_option.text if correct_option else "No correct answer",
                    "wait_time": wait_time
                }
            )

            await sleep(wait_time)
            await self.show_final_results(session)

    async def broadcast_players(self):
        """Надсилає актуальний список гравців (БЕЗ ХОСТА)"""
        players = await sync_to_async(lambda: list(Player.objects.filter(session__code=self.code).values_list("name", flat=True)))()
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

    async def kick_player(self, data):
        """Виганяє гравця з лоббі"""
        player_name = data["player_name"]
        player = await sync_to_async(lambda: Player.objects.filter(session=self.session, name=player_name).first())()
        if player:
            await sync_to_async(player.delete)()
            # Надсилаємо повідомлення вигнаному гравцю
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "kicked",
                    "kicked_player_name": player_name,
                    "message": "Ви були вигнані з лоббі хостом"
                }
            )
            # Оновлюємо список гравців
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
            "question": event["question"],
            "options": event["options"],
            "time_limit": event["time_limit"]
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

    async def show_answer(self, event):
        await self.send(text_data=json.dumps({
            "type": "answer",
            "correct_option": event["correct_option"],
            "wait_time": event.get("wait_time", 3)
        }))

    async def show_final_results(self, session):
        """Показывает финальные результаты игры"""
        players = await sync_to_async(lambda: list(session.players.all().order_by('-correct_answers')))()
        total_questions = await sync_to_async(lambda: session.quiz.questions.count())()
        results = []
        for player in players:
            results.append({
                "name": player.name,
                "correct": player.correct_answers,
                "total": total_questions
            })

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "final_results",
                "results": results
            }
        )

    async def final_results(self, event):
        await self.send(text_data=json.dumps({
            "type": "results",
            "results": event["results"]
        }))

    async def kicked(self, event):
        await self.send(text_data=json.dumps({
            "type": "kicked",
            "message": event["message"]
        }))

    async def answers_update(self, event):
        await self.send(text_data=json.dumps({
            "type": "answers_count",
            "answered": event["answered"],
            "total": event["total"]
        }))

    async def time_up(self, event):
        await self.send(text_data=json.dumps({
            "type": "time_up"
        }))

    async def start_question_timer(self, time_limit, force_restart=False):
        """Запускает серверный таймер для вопроса"""
        if self.code in self.active_timers and not force_restart:
            return  # Timer already running, don't restart

        async def timer_task():
            await asyncio.sleep(time_limit)
            await self.handle_time_up()

        # Cancel any existing timer for this room
        if self.code in self.active_timers:
            self.active_timers[self.code].cancel()
            del self.active_timers[self.code]

        # Start new timer
        self.active_timers[self.code] = asyncio.create_task(timer_task())

    async def handle_time_up(self):
        """Обработка истечения времени на вопрос"""
        # Send time up signal to all clients
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "time_up"
            }
        )

        # Do not show answer yet, wait for all players to answer
