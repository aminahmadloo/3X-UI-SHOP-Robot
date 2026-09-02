#!/usr/bin/env python3

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
MAPPING_FILE = APP / "bot" / "utils" / "custom_emoji_mapping.json"
FALLBACK_FILE = APP / "bot" / "utils" / "custom_emoji.py"

VS = {"\ufe0e", "\ufe0f"}
ZWJ = "\u200d"


def strip_vs(value: str) -> str:
    return value.replace("\ufe0e", "").replace("\ufe0f", "")


def is_emoji_base(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x1F000 <= cp <= 0x1FAFF
        or 0x2600 <= cp <= 0x27BF
        or 0x2300 <= cp <= 0x23FF
        or 0x2B00 <= cp <= 0x2BFF
    )


def consume_sequence(text: str, start: int) -> tuple[str, int]:
    if start >= len(text) or not is_emoji_base(text[start]):
        return "", start

    i = start + 1

    # Variation selector
    if i < len(text) and text[i] in VS:
        i += 1

    # Regional-indicator flag pair
    cp = ord(text[start])
    if 0x1F1E6 <= cp <= 0x1F1FF:
        if i < len(text) and 0x1F1E6 <= ord(text[i]) <= 0x1F1FF:
            i += 1
            if i < len(text) and text[i] in VS:
                i += 1
        return text[start:i], i

    # ZWJ sequences, e.g. 👨‍💻
    while i + 1 < len(text):
        if text[i] != ZWJ:
            break

        if not is_emoji_base(text[i + 1]):
            break

        i += 2

        if i < len(text) and text[i] in VS:
            i += 1

    return text[start:i], i


def extract_sequences(text: str) -> set[str]:
    found = set()
    i = 0

    while i < len(text):
        if is_emoji_base(text[i]):
            seq, end = consume_sequence(text, i)

            if seq:
                found.add(seq)
                i = end
                continue

        i += 1

    return found


def load_mapping():
    data = json.loads(
        MAPPING_FILE.read_text(encoding="utf-8")
    )

    exact = set()
    normalized = set()

    for entries in data.get("packs", {}).values():
        for entry in entries:
            emoji = entry.get("emoji")

            if not emoji:
                continue

            exact.add(emoji)
            normalized.add(strip_vs(emoji))

    return exact, normalized


def load_fallbacks():
    """
    Parse _FALLBACK_EMOJI using Python AST so ZWJ sequences,
    variation selectors and quoted strings are handled exactly.
    """
    tree = ast.parse(
        FALLBACK_FILE.read_text(encoding="utf-8"),
        filename=str(FALLBACK_FILE),
    )

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue

        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue

            if target.id != "_FALLBACK_EMOJI":
                continue

            if not isinstance(node.value, ast.Dict):
                continue

            result = set()

            for key in node.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    result.add(key.value)

            return result

    return set()


def main():
    exact, normalized = load_mapping()
    fallbacks = load_fallbacks()

    # Fallback source emoji are intentionally not required to exist
    # in the Telegram packs because they are replaced by another
    # emoji that DOES exist in the packs.
    fallback_exact = set(fallbacks)
    fallback_normalized = {
        strip_vs(x)
        for x in fallbacks
    }

    excluded = {
        MAPPING_FILE.resolve(),
        FALLBACK_FILE.resolve(),
    }

    sequences = {}

    allowed_suffixes = {
        ".py",
        ".json",
        ".po",
        ".pot",
        ".html",
        ".txt",
        ".md",
    }

    for path in APP.rglob("*"):
        if not path.is_file():
            continue

        if path.resolve() in excluded:
            continue

        if "__pycache__" in path.parts:
            continue

        if path.suffix.lower() not in allowed_suffixes:
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        for seq in extract_sequences(text):
            sequences.setdefault(seq, set()).add(
                str(path.relative_to(ROOT))
            )

    # Extract the actual sequences represented by fallback keys.
    fallback_sequences = set()

    for fallback in fallbacks:
        for seq in extract_sequences(fallback):
            fallback_sequences.add(seq)

    fallback_sequences_normalized = {
        strip_vs(x)
        for x in fallback_sequences
    }

    unmapped = {}

    for seq, files in sorted(sequences.items()):
        normalized_seq = strip_vs(seq)

        # Exact Telegram pack emoji
        if seq in exact:
            continue

        # Telegram pack emoji with/without variation selector
        if normalized_seq in normalized:
            continue

        # Explicit fallback source
        if seq in fallback_exact:
            continue

        if normalized_seq in fallback_normalized:
            continue

        # Fallback source that is a composed sequence such as 👨‍💻
        if seq in fallback_sequences:
            continue

        if normalized_seq in fallback_sequences_normalized:
            continue

        unmapped[seq] = files

    print(f"Known custom emoji: {len(exact)}")
    print(f"Unique emoji sequences found in app/: {len(sequences)}")
    print(f"Fallback source sequences: {len(fallbacks)}")
    print(f"Unmapped emoji sequences: {len(unmapped)}")
    print()

    if unmapped:
        for seq, files in sorted(unmapped.items()):
            print(
                f"{seq} -> "
                + ", ".join(sorted(files))
            )

        raise SystemExit(1)

    print("COVERAGE OK: all emoji sequences are covered.")


if __name__ == "__main__":
    main()
