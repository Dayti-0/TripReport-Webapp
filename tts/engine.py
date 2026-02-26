"""TTS engine using edge-tts for natural-sounding neural voices."""

import asyncio
import json
import os
import hashlib

import edge_tts

# Available French neural voices (natural sounding)
VOICES = {
    "denise": {"id": "fr-FR-DeniseNeural", "label": "Denise (femme)"},
    "henri": {"id": "fr-FR-HenriNeural", "label": "Henri (homme)"},
    "eloise": {"id": "fr-FR-EloiseNeural", "label": "Eloïse (enfant)"},
    "vivienne": {"id": "fr-FR-VivienneMultilingualNeural", "label": "Vivienne (multilingue)"},
    "remy": {"id": "fr-FR-RemyMultilingualNeural", "label": "Rémy (multilingue)"},
}

DEFAULT_VOICE = "denise"

# Cache directory for generated audio
AUDIO_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "audio")


def _get_cache_path(text_hash: str, voice_key: str) -> str:
    """Return the file path for a cached audio file."""
    os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)
    return os.path.join(AUDIO_CACHE_DIR, f"{text_hash}_{voice_key}.mp3")


def _get_timings_cache_path(text_hash: str, voice_key: str) -> str:
    """Return the file path for cached word timings."""
    os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)
    return os.path.join(AUDIO_CACHE_DIR, f"{text_hash}_{voice_key}_timings.json")


def _hash_text(text: str) -> str:
    """Create a short hash of the text for cache filenames."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def _generate_audio(text: str, voice_id: str, output_path: str,
                          timings_path: str | None = None) -> None:
    """Generate MP3 audio from text using edge-tts.

    When timings_path is provided, also saves word boundary timings as JSON
    for karaoke-style highlighting.
    """
    communicate = edge_tts.Communicate(text, voice_id)
    timings: list[dict] = []

    with open(output_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                timings.append({
                    "t": round(chunk["offset"] / 10_000_000, 3),
                    "d": round(chunk["duration"] / 10_000_000, 3),
                    "w": chunk["text"],
                })

    if timings_path and timings:
        with open(timings_path, "w", encoding="utf-8") as f:
            json.dump(timings, f, ensure_ascii=False)


def generate_tts(text: str, voice_key: str = DEFAULT_VOICE) -> str | None:
    """Generate TTS audio and return the path to the MP3 file.

    Uses cache: if the audio was already generated for this text+voice,
    returns the cached file immediately.

    Args:
        text: The text to convert to speech.
        voice_key: Key from VOICES dict (e.g. "denise", "henri").

    Returns:
        Path to the generated MP3 file, or None on error.
    """
    if not text or not text.strip():
        return None

    voice_info = VOICES.get(voice_key, VOICES[DEFAULT_VOICE])
    voice_id = voice_info["id"]

    text_hash = _hash_text(text)
    cache_path = _get_cache_path(text_hash, voice_key)
    timings_path = _get_timings_cache_path(text_hash, voice_key)

    # Return cached version if both audio and timings exist
    if (os.path.exists(cache_path) and os.path.getsize(cache_path) > 0
            and os.path.exists(timings_path)):
        return cache_path

    # Generate audio + word timings
    try:
        asyncio.run(_generate_audio(text, voice_id, cache_path, timings_path))
        return cache_path
    except Exception as e:
        print(f"[tts] Error generating audio: {e}")
        # Clean up partial files
        for p in (cache_path, timings_path):
            if os.path.exists(p):
                os.remove(p)
        return None


def get_timings(text: str, voice_key: str = DEFAULT_VOICE) -> list[dict] | None:
    """Return word boundary timings for karaoke highlighting.

    If timings are not cached yet, triggers audio generation first.

    Returns:
        List of {t: seconds, d: duration, w: word} dicts, or None on error.
    """
    if not text or not text.strip():
        return None

    voice_info = VOICES.get(voice_key, VOICES[DEFAULT_VOICE])
    text_hash = _hash_text(text)
    timings_path = _get_timings_cache_path(text_hash, voice_key)

    # Return cached timings
    if os.path.exists(timings_path):
        with open(timings_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # Generate audio + timings
    generate_tts(text, voice_key)

    if os.path.exists(timings_path):
        with open(timings_path, "r", encoding="utf-8") as f:
            return json.load(f)

    return None


def get_voices() -> list[dict]:
    """Return list of available voices for the frontend."""
    return [
        {"key": key, "id": info["id"], "label": info["label"]}
        for key, info in VOICES.items()
    ]
