import json
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from config import settings

logger = logging.getLogger(__name__)

_ALLOWED_IDS: set[int] = set()
if settings:
    _ALLOWED_IDS = {settings.partner_1_id, settings.partner_2_id}


def _extract_user_id(body: dict) -> int | None:
    for key in ("message", "edited_message", "callback_query", "channel_post"):
        obj = body.get(key)
        if obj and isinstance(obj, dict):
            from_obj = obj.get("from")
            if from_obj and isinstance(from_obj, dict):
                uid = from_obj.get("id")
                if uid is not None:
                    return int(uid)
    return None


class TelegramAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method != "POST" or "/telegram/" not in request.url.path:
            return await call_next(request)

        body_bytes = await request.body()
        try:
            body = json.loads(body_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return await call_next(request)

        user_id = _extract_user_id(body)
        if user_id is not None and user_id not in _ALLOWED_IDS:
            logger.warning(f"Unauthorized Telegram access attempt by user ID: {user_id}")
            return Response(status_code=200)

        # Re-inject the buffered body for downstream handlers
        async def receive():
            return {"type": "http.request", "body": body_bytes}

        request._receive = receive
        return await call_next(request)
