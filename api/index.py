import os
import sys
from pathlib import Path

from django.core.asgi import get_asgi_application


BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR / "youtube_streamer"

if str(PROJECT_DIR) not in sys.path:
    sys.path.append(str(PROJECT_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "youtube_streamer.settings")

app = get_asgi_application()
