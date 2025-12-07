from channels.generic.websocket import AsyncJsonWebsocketConsumer

class GameConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        # можна читати кімнату з URL: self.scope["url_route"]["kwargs"]["room_code"]
        await self.accept()
        await self.send_json({"type": "connected", "message": "hello"})

    async def receive_json(self, content):
        # content — словник, наприклад {"action": "answer", "payload": {...}}
        await self.send_json({"type": "echo", "you_sent": content})

    async def disconnect(self, code):
        pass
