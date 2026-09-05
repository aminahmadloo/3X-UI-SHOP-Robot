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


SMART_CATEGORIES: dict[str, tuple[str, str]] = {
    "education": ("📚 آموزشی", "auto"),
    "tips": ("💡 نکته و ترفند", "auto"),
    "technology": ("🌐 فناوری و اینترنت", "auto"),
    "news": ("📰 اخبار و ترند", "auto"),
    "interaction": ("❓ پرسش و تعامل", "auto"),
    "poll": ("📊 نظرسنجی", "auto"),
    "viral": ("😂 سرگرمی / محتوای وایرال", "auto"),
    "community": ("💬 ارتباط با اعضا", "auto"),
    "feature": ("🔐 معرفی قابلیت ToonelVPN", "auto"),
    "announcement": ("📢 اطلاعیه معمولی", "auto"),
    "sales": ("💰 معرفی سرویس / فروش معمولی", "approval"),
    "special_sale": ("🔥 فروش ویژه", "approval"),
    "discount": ("🎁 تخفیف", "approval"),
    "heavy_discount": ("🚨 تخفیف سنگین", "mandatory"),
    "campaign": ("📣 کمپین تبلیغاتی", "approval"),
    "important_campaign": ("🏆 کمپین مهم", "mandatory"),
    "ai_video": ("🎬 ویدئوی تولیدشده توسط AI", "approval"),
    "ai_image": ("🖼 تصویر تولیدشده توسط AI", "auto"),
    "sensitive": ("⚠️ موضوع حساس / بحث‌برانگیز", "mandatory"),
    "pricing": ("💳 قیمت، شرایط پرداخت یا تغییر تعرفه", "mandatory"),
    "legal": ("📜 متن حقوقی/قوانین/شرایط", "mandatory"),
    "outage": ("🛠 اطلاعیه قطعی/اختلال سرویس", "approval"),
    "experimental": ("🧪 محتوای آزمایشی", "approval"),
    "statistics": ("📈 محتوای مبتنی بر آمار", "approval"),
    "sensitive_cta": ("🔗 CTA حساس یا لینک کمپین مهم", "approval"),
}

DEFAULT_SMART_RULES = {key: decision for key, (_, decision) in SMART_CATEGORIES.items()}
RISK_LEVELS = {"conservative", "balanced", "free"}
HARD_APPROVAL_CATEGORIES = {
    "heavy_discount",
    "important_campaign",
    "sensitive",
    "pricing",
    "legal",
}

# AI is never allowed to invent destination URLs. It may only request one of
# these semantic actions; the publisher is responsible for resolving them.
CTA_ACTIONS = {
    "BUY",
    "MY_SERVICES",
    "RENEW",
    "WALLET",
    "ACCOUNT",
    "LEVEL",
    "REFERRAL",
    "SUPPORT",
    "GIFT",
    "DOWNLOAD",
}


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
برای هر محتوا یک content_category دقیق از فهرست زیر انتخاب کن:
{", ".join(SMART_CATEGORIES.keys())}
اگر محتوا درباره قیمت/پرداخت/تعرفه، قانون، موضوع حساس، تخفیف سنگین، کمپین مهم یا ادعای عددی است، همان دسته را انتخاب کن.
اگر CTA یا لینک یک کمپین مهم/حساس است، cta_risk را high قرار بده.

موضوع درخواستی: {requested_topic}

CTA را هرگز به‌صورت URL خام تولید نکن. فقط از actionهای معنایی مجاز زیر استفاده کن:
{", ".join(sorted(CTA_ACTIONS))}
برای لینک کمپین فقط از فرمت CAMPAIGN:<slug> استفاده کن؛ slug را از موضوع حدس نزن و فقط وقتی استفاده کن که در ورودی صراحتاً ارائه شده باشد.
اگر CTA مشخصی لازم نیست، آرایه buttons را خالی برگردان.

فقط JSON معتبر با این ساختار برگردان:
{{
  "title": "عنوان داخلی",
  "body": "متن نهایی پست با HTML ساده Telegram",
  "content_type": "text",
  "content_category": "education|tips|technology|news|interaction|poll|viral|community|feature|announcement|sales|special_sale|discount|heavy_discount|campaign|important_campaign|ai_video|ai_image|sensitive|pricing|legal|outage|experimental|statistics|sensitive_cta",
  "goal": "education|engagement|sales|acquisition|announcement",
  "sensitivity": "low|medium|high",
  "numeric_claim": false,
  "cta_risk": "low|medium|high",
  "cta_reason": "دلیل کوتاه انتخاب CTA",
  "buttons": [{{"label":"متن دکمه","action":"BUY"}}],
  "image_prompt": "اگر تصویر مناسب است، prompt انگلیسی تولید تصویر؛ در غیر این صورت خالی",
  "video_prompt": "اگر ویدئو مناسب است، prompt انگلیسی؛ در غیر این صورت خالی"
}}
"""
        payload = {"model": model or self.default_model, "input": prompt}

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

        category = str(result.get("content_category") or "education").strip().lower()
        if category not in SMART_CATEGORIES:
            category = "sensitive"
        result["content_category"] = category
        result["sensitivity"] = str(result.get("sensitivity") or "low").lower()
        result["numeric_claim"] = bool(result.get("numeric_claim"))
        result["cta_risk"] = str(result.get("cta_risk") or "low").lower()

        # Keep only semantic CTA intents. Arbitrary URLs from the model are
        # deliberately discarded and can never reach Telegram publishing.
        safe_buttons: list[dict[str, str]] = []
        for item in result.get("buttons") or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()[:64]
            action = str(item.get("action") or "").strip().upper()
            if not label:
                continue
            if action in CTA_ACTIONS or (action.startswith("CAMPAIGN:") and action[10:].strip()):
                safe_buttons.append({"label": label, "action": action})
        result["buttons"] = safe_buttons[:8]
        result["content_type"] = "text"
        return result

    async def get_settings(self, session: AsyncSession) -> AIContentSettings:
        settings = (await session.execute(select(AIContentSettings).order_by(AIContentSettings.id).limit(1))).scalar_one_or_none()
        if settings:
            return settings
        settings = AIContentSettings(smart_rules=json.dumps(DEFAULT_SMART_RULES, ensure_ascii=False))
        session.add(settings)
        await session.flush()
        return settings

    @staticmethod
    def smart_rules(settings: AIContentSettings) -> dict[str, str]:
        try:
            rules = json.loads(settings.smart_rules or "{}")
        except (TypeError, json.JSONDecodeError):
            rules = {}
        normalized = dict(DEFAULT_SMART_RULES)
        for key, value in rules.items():
            if key in SMART_CATEGORIES and value in {"auto", "approval", "mandatory"}:
                normalized[key] = value
        return normalized

    @staticmethod
    def decide_status(mode: str, category: str, settings: AIContentSettings | None = None, *, sensitivity: str = "low", numeric_claim: bool = False, cta_risk: str = "low") -> str:
        category = category if category in SMART_CATEGORIES else "sensitive"

        # Safety gates always win over the selected publication mode. This
        # prevents a global "auto" mode from bypassing hard-risk categories.
        if category in HARD_APPROVAL_CATEGORIES:
            return "draft"
        if sensitivity == "high" or cta_risk == "high":
            return "draft"
        if numeric_claim and category == "statistics":
            return "draft"

        if mode == "approval":
            return "draft"
        if mode == "auto":
            return "scheduled"

        rules = AIContentService.smart_rules(settings) if settings else DEFAULT_SMART_RULES
        decision = rules.get(category, "mandatory")
        if decision in {"mandatory", "approval"}:
            return "draft"
        return "scheduled"

    @staticmethod
    def risk_adjusted_rules(settings: AIContentSettings) -> dict[str, str]:
        rules = AIContentService.smart_rules(settings)
        risk = settings.smart_risk_level if settings.smart_risk_level in RISK_LEVELS else "balanced"
        if risk == "conservative":
            for key, (_, default) in SMART_CATEGORIES.items():
                if default != "auto":
                    rules[key] = "approval"
            for key in ("news", "ai_image", "announcement"):
                rules[key] = "approval"
        elif risk == "free":
            for key, decision in rules.items():
                if decision != "mandatory" and key not in HARD_APPROVAL_CATEGORIES:
                    rules[key] = "auto"
        for key in HARD_APPROVAL_CATEGORIES:
            rules[key] = "mandatory"
        return rules

    async def create_content(self, session: AsyncSession, channel_id: int, settings: AIContentSettings, topic: str | None = None) -> ChannelContent:
        result = await self.generate(topic=topic, model=settings.model)
        if settings.mode == "smart":
            effective_rules = self.risk_adjusted_rules(settings)
            original_rules = settings.smart_rules
            settings.smart_rules = json.dumps(effective_rules, ensure_ascii=False)
            status = self.decide_status(
                settings.mode,
                str(result.get("content_category") or "education"),
                settings,
                sensitivity=str(result.get("sensitivity") or "low"),
                numeric_claim=bool(result.get("numeric_claim")),
                cta_risk=str(result.get("cta_risk") or "low"),
            )
            settings.smart_rules = original_rules
        else:
            status = self.decide_status(
                settings.mode,
                str(result.get("content_category") or "education"),
                settings,
                sensitivity=str(result.get("sensitivity") or "low"),
                numeric_claim=bool(result.get("numeric_claim")),
                cta_risk=str(result.get("cta_risk") or "low"),
            )

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
