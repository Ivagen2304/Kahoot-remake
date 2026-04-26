import json
import asyncio
from asyncio import sleep
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from urllib.parse import parse_qs
from django.db import connection
from .models import GameSession, Player, Question, AnswerOption, PlayerAnswer

class GameConsumer(AsyncWebsocketConsumer):
    # Class variable to store active timers and start times per room
    active_timers = {}
    room_start_times = {}

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

        # 👉 Дістаємо параметри з WebSocket URL
        query_string = parse_qs(self.scope["query_string"].decode())
        player_name = query_string.get("name", [None])[0]
        role = query_string.get("role", ["player"])[0]

        # Перевіряємо, чи є користувач хостом сесії І чи він підключився як хост
        self.is_host = user and user.is_authenticated and user.id == host_id and role == "host"

        # Если хост — не создаём Player, но сохраняем имя для отображения
        if self.is_host:
            self.player = None
            self.host_name = player_name or user.username if user else "Host"
        else:
            # 👉 Спробуємо знайти гравця за ім'ям, щоб уникнути конфліктів при тестуванні в одному браузері
            if player_name:
                self.player = await sync_to_async(lambda: Player.objects.filter(name=player_name, session=self.session).first())()
                if self.player:
                    self.player.channel_name = self.channel_name
                    await sync_to_async(self.player.save)()
                else:
                    # Якщо не знайдено, закриваємо з'єднання
                    await self.close()
                    return
            else:
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
        if hasattr(self, 'player') and self.player:
            # Очищаємо channel_name, якщо гравець відключився (і якщо він ще існує в БД)
            try:
                current_channel = await sync_to_async(lambda: Player.objects.get(id=self.player.id).channel_name)()
                if current_channel == self.channel_name:
                    self.player.channel_name = None
                    await sync_to_async(self.player.save)()
            except Player.DoesNotExist:
                pass

        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        await self.broadcast_players()

    async def receive(self, text_data):
        data = json.loads(text_data)

        if data["type"] == "join":
            await self.add_player(data["name"])
        if data["type"] == "start_game":
            if self.is_host:
                await self.start_game(data)
        elif data["type"] == "answer":
            if not self.is_host:
                await self.record_answer(data)
        elif data["type"] == "kick_player":
            if self.is_host:
                await self.kick_player(data)
        elif data["type"] == "next_phase":
            if self.is_host:
                await self.handle_next_phase(data)
        elif data["type"] == "skip_question":
            if self.is_host:
                await self.handle_skip_question()
        elif data["type"] == "disband_lobby":
            if self.is_host:
                await self.disband_lobby()
        elif data["type"] == "get_current_question":  # 👈 ДОБАВЬ ЭТО
            session = await sync_to_async(GameSession.objects.get)(code=self.code)
            await sync_to_async(session.refresh_from_db)()
            await self.send_current_question(session)
        elif data["type"] == "time_up":
            await self.handle_time_up()

    # =====================
    # Методи гри
    # =====================

    async def start_game(self, data):
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

    async def send_current_question(self, session, to_all=True):
        """Відправляє поточне питання всім гравцям або індивідуально"""
        questions = await sync_to_async(lambda: list(session.quiz.questions.order_by('id')))()
        current_index = session.current_question_index

        if current_index < len(questions):
            question = questions[current_index]
            options = await sync_to_async(lambda: list(question.options.all()))()
            
            import random
            shuffled_options = list(options)
            random.shuffle(shuffled_options)

            # 👉 Перевіряємо, чи цей конкретний гравець вже відповів
            already_answered = False
            if self.player:
                already_answered = await sync_to_async(lambda: PlayerAnswer.objects.filter(player=self.player, question=question).exists())()

            event_data = {
                "type": "show_question",
                "question": question.text,
                "image_url": question.image.url if question.image else None,
                "question_type": question.question_type,
                "options": [{"id": o.id, "text": o.text} for o in shuffled_options],
                "time_limit": question.time_limit,
                "already_answered": already_answered
            }

            if to_all:
                await self.channel_layer.group_send(self.room_group_name, event_data)

                # Record start time for scoring (delayed by 2.5s to match client animation)
                import time
                self.room_start_times[self.code] = time.time() + 2.5

                # Start server-side timer for the room (with 2.5s animation delay)
                await self.start_question_timer(question.time_limit + 2.5, False)
            else:
                # Direct call to the handler for this specific connection
                await self.show_question(event_data)
        else:
            if to_all:
                await self.broadcast_final_results(session)

    async def record_answer(self, data):
        """Записывает ответ игрока"""
        if not self.player:
            return

        # Get session and current question safely
        session = await sync_to_async(GameSession.objects.get)(code=self.code)
        # 👇 УНІФІКУЄМО СОРТУВАННЯ
        questions = await sync_to_async(lambda: list(session.quiz.questions.order_by('id')))()
        question = questions[session.current_question_index] if session.current_question_index < len(questions) else None
        
        if not question: return

        # 👇 ПРОВЕРЯЕМ, НЕ ОТВЕЧАЛ ЛИ УЖЕ ИГРОК НА ЭТОТ ВОПРОС
        if await sync_to_async(PlayerAnswer.objects.filter(player=self.player, question=question).exists)():
            return

        is_correct = False
        selected_option = None

        if question.question_type in ['multiple_choice', 'true_false']:
            option_id = data.get("option_id")
            if not option_id: return
            selected_option = await sync_to_async(AnswerOption.objects.get)(id=option_id)
            is_correct = selected_option.is_correct
        
        elif question.question_type == 'text_input':
            answer_text = str(data.get("answer_text", "")).strip().lower()
            # Find any option marked as correct (the host types the correct text into the option)
            correct_options = await sync_to_async(lambda: list(question.options.filter(is_correct=True)))()
            for opt in correct_options:
                if opt.text.strip().lower() == answer_text:
                    is_correct = True
                    selected_option = opt
                    break
        
        elif question.question_type == 'puzzle':
            option_ids = data.get("option_ids", [])
            # Отримуємо правильний порядок з бази
            correct_options = await sync_to_async(lambda: list(question.options.all().order_by('order')))()
            correct_ids = [str(o.id) for o in correct_options]
            provided_ids = [str(oid) for oid in option_ids]
            
            if len(correct_ids) > 0:
                # Рахуємо скільки елементів на своїх місцях
                matches = 0
                for i in range(min(len(correct_ids), len(provided_ids))):
                    if correct_ids[i] == provided_ids[i]:
                        matches += 1
                
                accuracy = matches / len(correct_ids)
                if accuracy == 1.0:
                    is_correct = True
                
                # Ми будемо використовувати accuracy для розрахунку балів пізніше
                self.puzzle_accuracy = accuracy # Тимчасово зберігаємо в об'єкті
            
            if correct_options:
                selected_option = correct_options[0]

        # 👇 ПЕРЕВІРКА ЧАСУ (БЛОКУВАННЯ ВІДПОВІДЕЙ)
        import time
        start_time = self.room_start_times.get(self.code, time.time())
        time_spent = time.time() - start_time
        time_limit = question.time_limit

        if time_spent > time_limit + 0.5: # Даємо 0.5с на затримку мережі
            return # Час вийшов, ігноруємо відповідь

        # 👇 ОБНОВЛЯЕМ СЧЁТЧИК И БАЛЛЫ
        time_spent_clamped = max(0, time_spent)


        score_earned = 0
        if is_correct or (question.question_type == 'puzzle' and getattr(self, 'puzzle_accuracy', 0) > 0):
            time_ratio = max(0, (time_limit - time_spent_clamped) / time_limit)
            base_score = int(500 + (500 * time_ratio))
            
            if question.question_type == 'puzzle':
                accuracy = getattr(self, 'puzzle_accuracy', 1.0)
                score_earned = int(base_score * accuracy)
            else:
                score_earned = base_score
            
            if is_correct:
                self.player.streak += 1
                streak_bonus = min(self.player.streak * 100, 500)
                score_earned += streak_bonus
                self.player.correct_answers += 1
            else:
                self.player.streak = 0
            
            self.player.score += score_earned
        else:
            self.player.streak = 0
        
        await sync_to_async(self.player.save)()

        # 👇 ЗАПИСЫВАЕМ ОТВЕТ ОДИН РАЗ (з балами)
        player_answer = await sync_to_async(PlayerAnswer.objects.create)(
            player=self.player,
            question=question,
            selected_option=selected_option,
            is_correct=is_correct,
            score_earned=score_earned,
            accuracy=getattr(self, 'puzzle_accuracy', 1.0 if is_correct else 0.0),
            answer_text=data.get("answer_text") or (",".join(map(str, data.get("option_ids", []))) if question.question_type == 'puzzle' else None)
        )

        # 👇 ПРОВЕРЯЕМ, ВСЕ ЛИ ИГРОКИ ОТВЕТИЛИ
        await self.check_all_answered(question, self.player.name, is_correct, score_earned, self.player.streak)

    async def check_all_answered(self, question, player_name, is_correct, score_earned=0, streak=0):
        """Проверяет, все ли игроки ответили на вопрос"""
        session = await sync_to_async(GameSession.objects.get)(code=self.code)
        # Враховуємо тільки тих гравців, які зараз онлайн
        total_players = await sync_to_async(lambda: session.players.exclude(channel_name__isnull=True).exclude(channel_name="").count())()
        answered_players = await sync_to_async(lambda: PlayerAnswer.objects.filter(question=question, player__session=session).count())()

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
            # Автоматично завершуємо питання, коли всі відповіли
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "cancel_timer_and_proceed",
                    "question_id": question.id
                }
            )

    async def cancel_timer_and_proceed(self, event):
        if self.is_host:
            session = await sync_to_async(GameSession.objects.get)(code=self.code)
            question = await sync_to_async(Question.objects.get)(id=event["question_id"])
            await self.display_answer_chart(session, question)

    async def handle_skip_question(self):
        if self.code in self.active_timers:
            self.active_timers[self.code].cancel()
            del self.active_timers[self.code]

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "skip_question_message"
            }
        )

    async def skip_question_message(self, event):
        await self.send(text_data=json.dumps({
            "type": "host_skipped_question"
        }))

    async def display_answer_chart(self, session, question):
        """Показывает график ответов и правильный ответ (без перехода к следующему)"""
        if self.code in self.active_timers:
            self.active_timers[self.code].cancel()
            del self.active_timers[self.code]

        options = await sync_to_async(lambda: list(question.options.all()))()
        chart_data = []
        puzzle_stats = None

        if question.question_type == 'puzzle':
            answers = await sync_to_async(lambda: list(PlayerAnswer.objects.filter(question=question, player__session=session)))()
            num_options = await sync_to_async(lambda: question.options.count())()
            
            # Розрахунок можливих відсотків (напр., 0, 25, 50, 75, 100 для 4 опцій)
            possible_percentages = [round((i / max(num_options, 1)) * 100) for i in range(num_options + 1)]
            
            chart_data = []
            for p in possible_percentages:
                count = len([a for a in answers if round(a.accuracy * 100) == p])
                chart_data.append({
                    "id": p,  # Використовуємо відсоток як ID
                    "text": f"{p}%",
                    "is_correct": (p == 100),
                    "votes": count
                })
        else:
            for opt in options:
                votes = await sync_to_async(lambda o=opt: PlayerAnswer.objects.filter(question=question, selected_option=o, player__session=session).count())()
                chart_data.append({
                    "id": opt.id,
                    "text": opt.text,
                    "is_correct": opt.is_correct,
                    "votes": votes
                })

        # Формуємо текст правильної відповіді залежно від типу
        if question.question_type == 'puzzle':
            correct_options = await sync_to_async(lambda: list(question.options.all().order_by('order')))()
            correct_text = " → ".join([o.text for o in correct_options])
        elif question.question_type == 'text_input':
            correct_option = await sync_to_async(lambda: question.options.filter(is_correct=True).first())()
            correct_text = correct_option.text if correct_option else "Текст не задано"
        else:
            correct_option = await sync_to_async(lambda: question.options.filter(is_correct=True).first())()
            correct_text = correct_option.text if correct_option else "Немає правильної відповіді"

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "show_answer_chart",
                "chart_data": chart_data,
                "puzzle_stats": puzzle_stats,
                "correct_option": correct_text,
                "question_type": question.question_type,
                "question_id": question.id
            }
        )

    async def handle_next_phase(self, data):
        """Хост нажимает 'Далее', переходим на следующий этап"""
        session = await sync_to_async(GameSession.objects.get)(code=self.code)
        current_phase = data.get("current_phase")
        
        if current_phase == "chart":
            results = await self.get_leaderboard(session)
            questions_count = await sync_to_async(lambda: session.quiz.questions.count())()
            is_last = (session.current_question_index + 1) >= questions_count
            
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "show_leaderboard",
                    "leaderboard": results,
                    "is_last_question": is_last
                }
            )
        elif current_phase == "leaderboard":
            questions = await sync_to_async(lambda: list(session.quiz.questions.order_by('id')))()
            next_index = session.current_question_index + 1
            
            if next_index < len(questions):
                session.current_question_index = next_index
                await sync_to_async(session.save)()
                
                # Використовуємо єдиний централізований метод, який правильно формує і відправляє всі дані (включаючи image_url) та запускає таймери.
                await self.send_current_question(session)
            else:
                await self.broadcast_final_results(session)

    async def get_leaderboard(self, session):
        players = await sync_to_async(lambda: list(Player.objects.filter(session=session).order_by('-score')[:5]))()
        results = []
        for p in players:
            results.append({
                "name": p.name, 
                "score": p.score, 
                "streak": p.streak,
                "correct": p.correct_answers, 
                "total": session.current_question_index + 1,
                "avatar": p.avatar
            })
        return results

    async def broadcast_players(self):
        """Надсилає актуальний список гравців (БЕЗ ХОСТА)"""
        # Отримуємо тільки тих гравців, у яких є активний channel_name
        players = await sync_to_async(lambda: list(
            Player.objects.filter(session__code=self.code)
            .exclude(channel_name__isnull=True)
            .exclude(channel_name="")
            .values('name', 'avatar')
        ))()
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

    async def disband_lobby(self):
        """Хост розпускає лоббі до початку гри"""
        session = await sync_to_async(GameSession.objects.get)(code=self.code)
        session.is_active = False
        await sync_to_async(session.save)()

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "lobby_disbanded",
                "message": "Хост розпустив лоббі. Гру скасовано."
            }
        )

    async def lobby_disbanded(self, event):
        await self.send(text_data=json.dumps({
            "type": "lobby_disbanded",
            "message": event["message"]
        }))

    # =====================
    # Методи group_send
    # =====================

    # 👇 ДОБАВЛЯЕМ НОВЫЙ МЕТОД ДЛЯ ВЫВОДА WAITING
    async def player_answered(self, event):
        """Отправляет уведомление что игрок ответил"""
        await self.send(text_data=json.dumps({
            "type": "waiting",
            "player_name": event["player_name"],
            "is_correct": event["is_correct"],
            "score_earned": event.get("score_earned", 0),
            "streak": event.get("streak", 0)
        }))

    async def show_question(self, event):
        await self.send(text_data=json.dumps({
            "type": "question",
            "question": event["question"],
            "image_url": event.get("image_url"),
            "question_type": event.get("question_type", "multiple_choice"),
            "options": event["options"],
            "time_limit": event["time_limit"],
            "already_answered": event.get("already_answered", False) # Приймаємо статус
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

    async def show_answer_chart(self, event):
        player_accuracy = None
        if self.player and event.get("question_type") == "puzzle" and "question_id" in event:
            try:
                ans = await sync_to_async(PlayerAnswer.objects.get)(player=self.player, question_id=event["question_id"])
                player_accuracy = round(ans.accuracy * 100)
            except PlayerAnswer.DoesNotExist:
                pass

        await self.send(text_data=json.dumps({
            "type": "show_answer_chart",
            "chart_data": event["chart_data"],
            "puzzle_stats": event.get("puzzle_stats"),
            "correct_option": event["correct_option"],
            "question_type": event.get("question_type", "multiple_choice"),
            "player_accuracy": player_accuracy
        }))

    async def show_leaderboard(self, event):
        await self.send(text_data=json.dumps({
            "type": "show_leaderboard",
            "leaderboard": event["leaderboard"],
            "is_last_question": event.get("is_last_question", False)
        }))

    async def show_answer(self, event):
        await self.send(text_data=json.dumps({
            "type": "answer",
            "correct_option": event["correct_option"],
            "wait_time": event.get("wait_time", 3)
        }))

    async def broadcast_final_results(self, session):
        """Показывает финальные результаты игры"""
        players = await sync_to_async(lambda: list(session.players.all().order_by('-correct_answers')))()
        total_questions = await sync_to_async(lambda: session.quiz.questions.count())()
        results = []
        for player in players:
            results.append({
                "name": player.name,
                "correct": player.correct_answers,
                "total": total_questions,
                "score": player.score,
                "avatar": player.avatar
            })

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "show_final_results",
                "results": results
            }
        )

    async def show_final_results(self, event):
        await self.send(text_data=json.dumps({
            "type": "show_final_results",
            "results": event["results"]
        }))

    async def kicked(self, event):
        if self.player and self.player.name == event.get("kicked_player_name"):
            await self.send(text_data=json.dumps({
                "type": "kicked",
                "message": event["message"]
            }))
            await self.close()

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
            try:
                await asyncio.sleep(time_limit)
                await self.handle_time_up()
            except asyncio.CancelledError:
                pass

        # Cancel any existing timer for this room
        if self.code in self.active_timers:
            self.active_timers[self.code].cancel()
            del self.active_timers[self.code]

        # Start new timer
        self.active_timers[self.code] = asyncio.create_task(timer_task())

    async def handle_time_up(self):
        """Обработка истечения времени на вопрос"""
        # Remove timer from active_timers so check_all_answered doesn't trigger twice
        if self.code in self.active_timers:
            del self.active_timers[self.code]

        # Send time up signal to all clients
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "time_up"
            }
        )

        # Прибираємо затримку, щоб графік показувався миттєво
        # await asyncio.sleep(2) 


        session = await sync_to_async(GameSession.objects.get)(code=self.code)
        questions = await sync_to_async(lambda: list(session.quiz.questions.order_by('id')))()
        current_index = session.current_question_index
        
        if current_index < len(questions):
            question = questions[current_index]
            await self.display_answer_chart(session, question)
