"""
Telegram custom emoji presentation layer.

IMPORTANT:
This module is presentation-only.

It does not modify:
- handlers
- callbacks
- commands
- FSM
- database
- services
- business logic

It intercepts outgoing Telegram text/captions and replaces ordinary
Unicode emoji with Telegram custom emoji HTML entities.

Source packs:
- TgAndroidIcons
- tgiosicons
"""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.methods.base import TelegramMethod

logger = logging.getLogger(__name__)

_MAPPING_PATH = Path(__file__).with_name("custom_emoji_mapping.json")

_mapping: dict[str, Any] | None = None
_exact_map: dict[str, str] | None = None
_normalized_map: dict[str, str] | None = None

# Presentation-only semantic fallbacks.
#
# These are used ONLY when an exact/variation-selector tolerant
# mapping is unavailable in the two Telegram custom-emoji packs.
#
# Important:
# We intentionally do NOT map colored status dots to black/white
# dots when a semantic status symbol is available.
_FALLBACK_EMOJI = {
    '⚫': '⚪️',
    '🔵': 'ℹ️',
    '🟠': '⚠️',
    '🟡': '⚠️',
    '🟢': '✅',
    '🟣': 'ℹ️',

    '⏱️': '⏲️',
    '⏱': '⏲️',
    '⏳': '⌛️',
    '⛔': '🚫',
    '❕': '❗️',
    '🆔': '🪪',
        '🆘': "⚠️",
    '🌍': '🌐',
    '🎟': '🎁',
    '🎟️': '🎁',
    '🎫': '🎁',
    '🎬': '▶️',
    '🏆': '⭐️',
    '🏦': '💵',
    '🐧': '💻',
    '👀': '🤔',
    '👇': '⬇️',
    '💩': '🤖',
    '💸': '💰',
    '📆': '📅',
    '📋': '📄',
    '📚': '📖',
    '📜': '📄',
    '📡': '📶',
    '📨': '✉️',
    '📩': '⬇️',
    '🔌': '💡',
    '🔍': '🔎',
    '🔐': '🔒',
    '🔘': '🔳',
    '🔙': '↩️',
    '🔢': '🔣',
    '🔩': '⚙️',
    '🔹': '🔼',
    '🕐': '⏰',
    '🗓': '🗒',
    '🙏': '🙋',
    '🚀': '⚡️',
    '🚧': '⚠️',
    '🛒': '🎁',
    '🤝': '👋',
    '🧮': '📊',
    '🧾': '📄',
    '☑️': '✅',
    '♻️': '🔄',
    '✍️': '✋',
    '🛍️': '🎁',
    '👨\u200d💻': '💻',
    '🇮🇷': '🌐',
    '🇬🇧': '🌐',
    '🇷🇺': '🌐',
}


def _load_mapping() -> dict[str, Any]:
    global _mapping

    if _mapping is None:
        with _MAPPING_PATH.open("r", encoding="utf-8") as f:
            _mapping = json.load(f)

    return _mapping


def _strip_variation_selectors(value: str) -> str:
    return value.replace("\ufe0f", "").replace("\ufe0e", "")


def _build_maps() -> tuple[dict[str, str], dict[str, str]]:
    global _exact_map, _normalized_map

    if _exact_map is not None and _normalized_map is not None:
        return _exact_map, _normalized_map

    data = _load_mapping()

    exact: dict[str, str] = {}
    normalized: dict[str, str] = {}

    # Android is the primary visual style.
    # iOS is the fallback.
    preferred_packs = ("TgAndroidIcons", "tgiosicons")

    by_emoji = data.get("by_emoji", {})

    for emoji, entries in by_emoji.items():
        if not entries:
            continue

        selected = None

        for pack in preferred_packs:
            for entry in entries:
                if entry.get("pack") == pack:
                    selected = entry
                    break
            if selected:
                break

        if not selected:
            selected = entries[0]

        emoji_id = str(selected["custom_emoji_id"])

        # Exact representation is always preferred.
        exact.setdefault(emoji, emoji_id)

        # Also provide variation-selector tolerant fallback.
        normalized.setdefault(
            _strip_variation_selectors(emoji),
            emoji_id,
        )

    _exact_map = exact
    _normalized_map = normalized

    logger.info(
        "Telegram custom emoji layer loaded: "
        "%d exact mappings, %d normalized mappings",
        len(exact),
        len(normalized),
    )

    return exact, normalized


def _emoji_tokens() -> list[str]:
    exact, _ = _build_maps()

    # Longest first so multi-codepoint emoji are matched before
    # their individual components.
    return sorted(exact.keys(), key=len, reverse=True)


def _make_custom_emoji(emoji_id: str, visible_emoji: str) -> str:
    """Build a Telegram custom emoji HTML entity."""
    return (
        f'<tg-emoji emoji-id="{html.escape(emoji_id, quote=True)}">'
        f"{visible_emoji}"
        f"</tg-emoji>"
    )


def _resolve_fallback(
    emoji: str,
    exact: dict[str, str],
    normalized: dict[str, str],
) -> tuple[str, str, int] | None:
    """
    Resolve an unmapped emoji through the presentation-only fallback table.

    Returns:
        (custom_emoji_id, replacement_visible_emoji, consumed_length)
    """
    # Longest fallback key first.
    for source in sorted(_FALLBACK_EMOJI, key=len, reverse=True):
        if not emoji.startswith(source):
            continue

        replacement = _FALLBACK_EMOJI[source]

        emoji_id = exact.get(replacement)

        if not emoji_id:
            emoji_id = normalized.get(
                _strip_variation_selectors(replacement)
            )

        if emoji_id:
            return emoji_id, replacement, len(source)

    return None


def _replace_text_segment(text: str) -> str:
    exact, normalized = _build_maps()

    if not text:
        return text

    tokens = _emoji_tokens()

    # Fast path.
    if not any(token in text for token in tokens) and not any(
        token in text for token in _FALLBACK_EMOJI
    ):
        return text

    result: list[str] = []
    i = 0

    while i < len(text):
        matched = False

        # ------------------------------------------------------------
        # 1. Exact mapping.
        # ------------------------------------------------------------
        for emoji in tokens:
            if text.startswith(emoji, i):
                emoji_id = exact[emoji]
                result.append(
                    _make_custom_emoji(emoji_id, emoji)
                )
                i += len(emoji)
                matched = True
                break

        if matched:
            continue

        # ------------------------------------------------------------
        # 2. Variation-selector tolerant mapping.
        # ------------------------------------------------------------
        for emoji in tokens:
            normalized_emoji = _strip_variation_selectors(emoji)

            if not normalized_emoji:
                continue

            if text.startswith(normalized_emoji, i):
                emoji_id = normalized.get(normalized_emoji)

                if emoji_id:
                    result.append(
                        _make_custom_emoji(
                            emoji_id,
                            emoji,
                        )
                    )
                    i += len(normalized_emoji)
                    matched = True
                    break

        if matched:
            continue

        # ------------------------------------------------------------
        # 3. Semantic fallback.
        #
        # Example:
        #   🟢 -> custom ✅
        #   🟡 -> custom ⚠️
        #   🔵 -> custom ℹ️
        # ------------------------------------------------------------
        fallback = _resolve_fallback(
            text[i:],
            exact,
            normalized,
        )

        if fallback:
            emoji_id, replacement, consumed_length = fallback

            result.append(
                _make_custom_emoji(
                    emoji_id,
                    replacement,
                )
            )

            i += consumed_length
            continue

        # ------------------------------------------------------------
        # 4. Conservative single-code-point normalized lookup.
        # ------------------------------------------------------------
        ch = text[i]
        normalized_ch = _strip_variation_selectors(ch)
        emoji_id = normalized.get(normalized_ch)

        if emoji_id:
            result.append(
                _make_custom_emoji(
                    emoji_id,
                    ch,
                )
            )
            i += len(ch)
            continue

        # ------------------------------------------------------------
        # 5. Unmapped character: leave untouched.
        # ------------------------------------------------------------
        result.append(ch)
        i += len(ch)

    return "".join(result)


def transform_html(text: str | None) -> str | None:
    """
    Replace emoji in HTML-aware text without touching HTML tags.

    Existing:
        <b>سلام 🔥</b>

    Becomes:
        <b>سلام <tg-emoji emoji-id="...">🔥</tg-emoji></b>

    Emoji inside <code>/<pre> are intentionally left untouched.
    """

    if not text:
        return text

    exact, _ = _build_maps()

    if not exact:
        return text

    result: list[str] = []
    buffer: list[str] = []

    i = 0
    protected_depth = 0

    while i < len(text):
        ch = text[i]

        if ch == "<":
            # Flush normal text before HTML tag.
            if buffer:
                segment = "".join(buffer)
                if protected_depth:
                    result.append(segment)
                else:
                    result.append(_replace_text_segment(segment))
                buffer.clear()

            end = text.find(">", i)

            if end == -1:
                buffer.append(text[i:])
                break

            tag = text[i : end + 1]
            result.append(tag)

            lowered = tag.lower()

            if lowered.startswith("<code") or lowered.startswith("<pre"):
                protected_depth += 1
            elif lowered.startswith("</code") or lowered.startswith("</pre"):
                protected_depth = max(0, protected_depth - 1)

            i = end + 1
            continue

        buffer.append(ch)
        i += 1

    if buffer:
        segment = "".join(buffer)
        if protected_depth:
            result.append(segment)
        else:
            result.append(_replace_text_segment(segment))

    return "".join(result)


_TEXT_FIELDS = (
    "text",
    "caption",
    "message_text",
    "description",
    "title",
)


def _transform_value(value: Any) -> Any:
    if isinstance(value, str):
        return transform_html(value)

    if isinstance(value, list):
        return [_transform_value(item) for item in value]

    if isinstance(value, dict):
        return {
            key: _transform_value(item)
            for key, item in value.items()
        }

    return value


def transform_telegram_method(
    method: TelegramMethod[Any],
) -> TelegramMethod[Any]:
    """
    Presentation-only transformation of outgoing Telegram methods.

    Only string fields that represent visible message/caption text
    are transformed. Callback data, URLs, IDs, commands and other
    logic-bearing fields remain untouched.
    """

    changes: dict[str, Any] = {}

    fields = getattr(method, "model_fields", {})

    for field_name in _TEXT_FIELDS:
        if field_name not in fields:
            continue

        value = getattr(method, field_name, None)

        if isinstance(value, str):
            transformed = transform_html(value)

            if transformed != value:
                changes[field_name] = transformed

    # SendMediaGroup/EditMessageMedia/etc. contain InputMedia objects.
    media = getattr(method, "media", None)

    if isinstance(media, list):
        changed_media = []

        for item in media:
            if hasattr(item, "caption") and isinstance(item.caption, str):
                transformed_caption = transform_html(item.caption)

                if transformed_caption != item.caption:
                    item = item.model_copy(
                        update={"caption": transformed_caption}
                    )

            changed_media.append(item)

        if changed_media != media:
            changes["media"] = changed_media

    if changes:
        # TelegramMethod objects are mutable input models in aiogram 3.
        return method.model_copy(update=changes)

    return method


class ToonelCustomEmojiBot(Bot):
    """
    Bot subclass that applies the presentation layer immediately
    before any Telegram Bot API request is serialized.

    No business logic is changed.
    """

    async def __call__(
        self,
        method: TelegramMethod[Any],
        request_timeout: int | None = None,
    ) -> Any:
        try:
            method = transform_telegram_method(method)
        except Exception:
            # Never allow presentation enhancement to break the bot.
            logger.exception("Custom emoji transformation failed")

        return await super().__call__(
            method,
            request_timeout=request_timeout,
        )
