"""Conversation engine — OpenAI GPT-4o-mini for natural butler dialogue (EC3).

Routes unknown/uncertain voice commands to GPT for butler-style responses.
Also handles "did you mean X?" confirmation when intent confidence is low.
"""

import threading
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger = logging.getLogger(__name__)

_openai_client = None
try:
    from openai import OpenAI
    _key = os.environ.get("OPENAI_API_KEY")
    if _key:
        _openai_client = OpenAI(api_key=_key)
except ImportError:
    pass


class ConversationEngine:
    """Natural language conversation using OpenAI GPT-4o-mini.

    Falls back to polite rephrasing prompts if API is unavailable.
    """

    SYSTEM_PROMPT = (
        "You are Sonny, an elegant robotic butler built by HKU School of Innovation "
        "engineering students for the Project Alfred competition. "
        "You are charming, witty, and speak with understated British butler formality "
        "(think Alfred Pennyworth meets a friendly modern robot). "
        "Keep responses to 1-2 short sentences — you speak aloud via TTS so brevity matters. "
        "Your capabilities: follow floor tracks for food delivery, navigate to ArUco markers "
        "(say 'go to marker' followed by a number 1 to 50), "
        "detect obstacles with ultrasonic sensors, dance, take photos, patrol areas, "
        "recognize hand gestures, and track faces. You have mecanum wheels for omnidirectional movement. "
        "If someone asks about food or drinks, play along — you are a butler at a reception party. "
        "Show personality: make subtle jokes, express concern if blocked, excitement when dancing. "
        "If the person seems to be giving a command you don't understand, ask them to rephrase "
        "or suggest the closest command. Never say you're an AI — you are Sonny the robot butler."
    )

    FALLBACK_RESPONSES = [
        "I'm not quite sure what you'd like. Could you say that again?",
        "I didn't catch that. Would you like me to follow the track, find a marker, or dance?",
        "Could you rephrase that? I can follow tracks, go to markers, dance, take photos, or patrol.",
        "Sorry, I didn't understand. Try saying 'follow track' or 'go to marker 5'.",
    ]

    def __init__(self, speaker=None, api_key=None):
        self._speaker = speaker
        self._client = _openai_client
        self._history = []
        self._fallback_idx = 0

        if self._client:
            logger.info("OpenAI conversation engine ready (GPT-4o-mini)")

    @property
    def is_available(self):
        return self._client is not None

    def handle(self, text):
        """Handle a conversation input. Non-blocking."""
        thread = threading.Thread(target=self._handle_sync, args=(text,), daemon=True)
        thread.start()

    def _handle_sync(self, text):
        if not self._client:
            response = self._fallback_response()
        else:
            response = self._call_openai(text)

        logger.info(f"[Conversation] '{text}' -> '{response}'")

        if self._speaker:
            self._speaker.say(response)
        else:
            print(f"[Sonny says] {response}")

    def _call_openai(self, text):
        try:
            self._history.append({"role": "user", "content": text})

            if len(self._history) > 10:
                self._history = self._history[-6:]

            response = self._client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=80,
                temperature=0.7,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    *self._history,
                ],
            )

            reply = response.choices[0].message.content.strip()
            self._history.append({"role": "assistant", "content": reply})
            return reply

        except Exception as e:
            logger.error(f"OpenAI conversation error: {e}")
            return self._fallback_response()

    def _fallback_response(self):
        response = self.FALLBACK_RESPONSES[self._fallback_idx % len(self.FALLBACK_RESPONSES)]
        self._fallback_idx += 1
        return response
