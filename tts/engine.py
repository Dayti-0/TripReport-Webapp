"""TTS engine using edge-tts for natural-sounding neural voices."""

import asyncio
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


def _hash_text(text: str) -> str:
    """Create a short hash of the text for cache filenames."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def _generate_audio(text: str, voice_id: str, output_path: str) -> None:
    """Generate MP3 audio from text using edge-tts."""
    communicate = edge_tts.Communicate(text, voice_id)
    await communicate.save(output_path)


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

    # Return cached version if available
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        return cache_path

    # Generate new audio
    try:
        asyncio.run(_generate_audio(text, voice_id, cache_path))
        return cache_path
    except Exception as e:
        print(f"[tts] Error generating audio: {e}")
        # Clean up partial file
        if os.path.exists(cache_path):
            os.remove(cache_path)
        return None


def get_voices() -> list[dict]:
    """Return list of available voices for the frontend."""
    return [
        {"key": key, "id": info["id"], "label": info["label"]}
        for key, info in VOICES.items()
    ]
