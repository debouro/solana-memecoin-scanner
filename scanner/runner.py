import threading

import uvicorn

from .api import create_app
from .collector import Collector
from .config import Settings, get_settings
from .db import make_session_factory


def build_components(settings: Settings | None = None):
    settings = settings or get_settings()
    session_factory, engine = make_session_factory(settings)
    collector = Collector(settings, session_factory)
    return settings, session_factory, engine, collector


def run_scan_once(settings: Settings | None = None) -> dict:
    settings, session_factory, _, collector = build_components(settings)
    return collector.collect_once()


def serve(settings: Settings | None = None):
    settings, session_factory, _, collector = build_components(settings)
    if not settings.api_only:
        thread = threading.Thread(target=collector.run_forever, daemon=True)
        thread.start()
    app = create_app(session_factory, settings, collector)
    uvicorn.run(app, host=settings.api_host, port=settings.api_port, log_level="info")
