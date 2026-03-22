import os
import django  # 👈 ДОБАВЬ ЭТО

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "main_project.settings")
django.setup()  # 👈 И ЭТО

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from app.routing import websocket_urlpatterns

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(
            websocket_urlpatterns
        )
    ),
})