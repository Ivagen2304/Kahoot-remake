import os

# 1️⃣ налаштування Django ПЕРШИМ
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "main_project.settings")

# 2️⃣ імпортуємо get_asgi_application
from django.core.asgi import get_asgi_application

# 3️⃣ Створюємо базове ASGI application для HTTP
django_asgi_app = get_asgi_application()

# 4️⃣ Імпортуємо Channels і routing ЛИШЕ ПІСЛЯ цього
from channels.routing import ProtocolTypeRouter, URLRouter
import app.routing

# 5️⃣ Створюємо фінальний ASGI application
application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": URLRouter(
        app.routing.websocket_urlpatterns
    ),
})
