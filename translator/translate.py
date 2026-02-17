"""Translation module using deep-translator (Google Translate, free)."""

import re
import time
from typing import Optional

from deep_translator import GoogleTranslator

MAX_CHUNK_SIZE = 4500  # Google Translate limit
CHUNK_DELAY = 0.5  # seconds between chunks
MAX_RETRIES = 3
RETRY_DELAY = 2.0  # seconds between retries

# Patterns to preserve (timestamps, substance names patterns)
TIMESTAMP_PATTERN = re.compile(r"(T\+\d+:\d+(?::\d+)?)")
TIME_PATTERN = re.compile(r"(\d{1,2}:\d{2}\s*(?:am|pm|AM|PM)?)")


def _split_into_chunks(text: str, max_size: int = MAX_CHUNK_SIZE) -> list[str]:
    """Split text into chunks respecting paragraph boundaries.

    Tries to split on double newlines (paragraph breaks) first,
    then single newlines, then at max_size boundaries.
    """
    if len(text) <= max_size:
        return [text]

    chunks = []
    paragraphs = text.split("\n\n")
    current_chunk = ""

    for paragraph in paragraphs:
        # If a single paragraph is too long, split it further
        if len(paragraph) > max_size:
            # Flush current chunk first
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""

            # Split long paragraph on single newlines
            lines = paragraph.split("\n")
            for line in lines:
                if len(current_chunk) + len(line) + 1 > max_size:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = line
                else:
                    current_chunk = current_chunk + "\n" + line if current_chunk else line

        elif len(current_chunk) + len(paragraph) + 2 > max_size:
            # Adding this paragraph would exceed the limit
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = paragraph
        else:
            current_chunk = current_chunk + "\n\n" + paragraph if current_chunk else paragraph

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def _protect_timestamps(text: str) -> tuple[str, dict[str, str]]:
    """Replace timestamps with placeholders to prevent translation.

    Returns the modified text and a mapping of placeholder -> original.
    """
    placeholders = {}
    counter = 0

    def replace_timestamp(match: re.Match) -> str:
        nonlocal counter
        placeholder = f"__TS{counter}__"
        placeholders[placeholder] = match.group(0)
        counter += 1
        return placeholder

    text = TIMESTAMP_PATTERN.sub(replace_timestamp, text)
    text = TIME_PATTERN.sub(replace_timestamp, text)
    return text, placeholders


def _restore_timestamps(text: str, placeholders: dict[str, str]) -> str:
    """Restore original timestamps from placeholders."""
    for placeholder, original in placeholders.items():
        text = text.replace(placeholder, original)
    return text


def translate_text(text: str, source: str = "en", target: str = "fr") -> Optional[str]:
    """Translate text from source to target language.

    Handles chunking for long texts and preserves timestamps.

    Args:
        text: The text to translate.
        source: Source language code.
        target: Target language code.

    Returns:
        Translated text, or None on failure.
    """
    if not text or not text.strip():
        return ""

    # Don't translate if already in target language
    if source == target:
        return text

    # Protect timestamps
    text, placeholders = _protect_timestamps(text)

    # Split into chunks
    chunks = _split_into_chunks(text)
    translated_chunks = []

    translator = GoogleTranslator(source=source, target=target)

    for i, chunk in enumerate(chunks):
        if not chunk.strip():
            translated_chunks.append(chunk)
            continue

        success = False
        for attempt in range(MAX_RETRIES):
            try:
                translated = translator.translate(chunk)
                if translated:
                    translated_chunks.append(translated)
                    success = True
                    break
            except Exception as e:
                print(f"[translator] Attempt {attempt+1}/{MAX_RETRIES} failed for chunk {i+1}: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))

        if not success:
            print(f"[translator] Failed to translate chunk {i+1}/{len(chunks)}, keeping original")
            translated_chunks.append(chunk)

        # Delay between chunks to avoid rate limiting
        if i < len(chunks) - 1:
            time.sleep(CHUNK_DELAY)

    result = "\n\n".join(translated_chunks)

    # Restore timestamps
    result = _restore_timestamps(result, placeholders)

    return result


def translate_report(report: dict) -> dict:
    """Translate a report's body text if needed.

    Modifies the report dict in place and returns it.
    Only translates if language is not 'fr'.
    """
    if report.get("language") == "fr":
        report["body_translated"] = report.get("body_original", "")
        return report

    body = report.get("body_original", "")
    if not body:
        report["body_translated"] = ""
        return report

    print(f"[translator] Translating report '{report.get('title', '?')}' ({len(body)} chars)...")
    translated = translate_text(body, source="en", target="fr")

    if translated:
        report["body_translated"] = translated
        print(f"[translator] Translation complete ({len(translated)} chars)")
    else:
        report["body_translated"] = ""
        print("[translator] Translation failed")

    return report
