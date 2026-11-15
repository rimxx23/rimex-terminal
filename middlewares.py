from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from ratelimit import SlidingWindowLimiter


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, limiter: SlidingWindowLimiter) -> None:
        self.limiter = limiter

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        retry_after = self.limiter.hit(user.id)
        if retry_after:
            await self._reject(event, retry_after)
            return None
        return await handler(event, data)

    async def _reject(self, event: TelegramObject, retry_after: int) -> None:
        text = f"⏳ Too many requests. Try again in {retry_after}s."
        if isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)
        elif isinstance(event, Message):
            await event.answer(text)
