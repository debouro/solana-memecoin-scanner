from sqlalchemy.orm import Session

from .models import Notification, utcnow


class Notifier:
    def __init__(self, session: Session):
        self.session = session

    def emit(self, type: str, message: str, mint: str | None = None) -> Notification:
        note = Notification(ts=utcnow(), type=type, mint=mint, message=message[:2000], read=False)
        self.session.add(note)
        return note
