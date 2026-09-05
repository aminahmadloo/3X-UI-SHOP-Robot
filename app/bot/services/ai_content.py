from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AIContentSettings, ChannelContent

logger = logging.getLogger(__name__)


class AIContentError(RuntimeError):
    pass


class AIContentService:
    def __init__(self, api_key: str | None, default_model: str = "gpt-5.6-luna") -> None:
        self.api_key = api_key
        self.default_model = default_model

    async def generate(self, topic: str | None = None, model: str | None = None) -> dict:
        if not self.api_key:
            raise AIContentError("OPENAI_API_KEY تنظیم نشده است.")
        requested_topic = topic or "یک موضوع جذاب و کاربردی برای اعضای کانال ToonelVPN انتخاب کن."
        prompt = f"""
تو مدیر محتوای حرفه‌ای کانال تلگرام ToonelVPN هستی.
هدف: تولید محتوای فارسی جذاب، کوتاه و طبیعی که ابتدا برای عضو ارزش ایجاد کند و سپس در صورت مناسب بودن او را به ربات هدایت کند.
از کلیشه، اغراق، وعده غیرواقعی و تبلیغ مستقیم افراطی پرهیز کن.
یک hook قوی در ابتدای متن، بدنه خوانا با فاصله‌گذاری مناسب و CTA متناسب با هدف بساز.
دکمه‌ها باید فقط وقتی لازم هستند پیشنهاد شوند و هر URL باید واقعی و قابل استفاده باشد.
برای محتوای آموزشی CTA آموزشی/تعامل، برای فروش CTA خرید، و برای جذب عضو CTA ورود به ربات/اکانت هدیه پیشنهاد کن.

موضوع درخواستی: {requested_topic}

فقط JSON معتبر با این ساختار برگردان:
{{
  "title": "عنوان داخلی",
  "body": "متن نهایی پست با HTML ساده Telegram",
  "content_type": "text",
  "goal": "education|engagement|sales|acquisition|announcement",
  "cta_reason": "دلیل کوتاه انتخاب CTA",
  "buttons": [{{"label":"متن دکمه","url":"https://example.com"}}],
  "image_prompt": "اگر تصویر مناسب است، prompt انگلیسی تولید تصویر؛ در غیر این صورت خالی",
  "video_prompt": "اگر ویدئو مناسب است، prompt انگلیسی؛ در غیر این صورت خالی"
}}
"""
        payload = {
            "model": model or self.default_model,
            "input": prompt,
        }

        def request() -> dict:
            req = urllib.request.Request(
                "https://api.openai.com/v1/responses",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=90) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:1000]
                raise AIContentError(f"OpenAI API خطا داد: HTTP {exc.code} — {detail}") from exc
            except urllib.error.URLError as exc:
                raise AIContentError(f"اتصال به OpenAI برقرار نشد: {exc.reason}") from exc

        response = await asyncio.to_thread(request)
        output_text = str(response.get("output_text") or "").strip()
        if not output_text:
            for item in response.get("output", []):
                for part in item.get("content", []) if isinstance(item, dict) else []:
                    if part.get("type") == "output_text":
                        output_text += str(part.get("text") or "")
        try:
            result = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise AIContentError("پاسخ AI JSON معتبر نبود.") from exc
        if not isinstance(result, dict) or not str(result.get("body") or "").strip():
            raise AIContentError("AI محتوای قابل انتشار تولید نکرد.")
        result["buttons"] = [
            item for item in (result.get("buttons") or [])
            if isinstance(item, dict) and str(item.get("label") or "").strip() and str(item.get("url") or "").startswith(("https://", "http://"))
        ][:8]
        result["content_type"] = "text"
        return result

    async def get_settings(self, session: AsyncSession) -> AIContentSettings:
        settings = (await session.execute(select(AIContentSettings).order_by(AIContentSettings.id).limit(1))).scalar_one_or_none()
        if settings:
            return settings
        settings = AIContentSettings()
        session.add(settings)
        await session.flush()
        return settings

    @staticmethod
    def decide_status(mode: str, goal: str) -> str:
        if mode == "auto":
            return "scheduled"
        if mode == "approval":
            return "draft"
        # Smart mode: routine value content can be automated; sales/announcements stay for review.
        return "scheduled" if goal in {"education", "engagement"} else "draft"

    async def create_content(self, session: AsyncSession, channel_id: int, settings: AIContentSettings, topic: str | None = None) -> ChannelContent:
        result = await self.generate(topic=topic, model=settings.model)
        status = self.decide_status(settings.mode, str(result.get("goal") or "education"))
        content = ChannelContent(
            channel_id=channel_id,
            title=str(result.get("title") or "محتوای AI"),
            content_type="text",
            body=str(result["body"]),
            status=status,
            scheduled_at=datetime.utcnow() if status == "scheduled" else None,
        )
        content.buttons = result.get("buttons") or []
        session.add(content)
        await session.flush()
        settings.last_run_at = datetime.utcnow()
        return content

    @staticmethod
    def schedule_next(settings: AIContentSettings) -> None:
        posts = max(1, min(settings.posts_per_day, 24))
        settings.next_run_at = datetime.utcnow() + timedelta(hours=24 / posts)
