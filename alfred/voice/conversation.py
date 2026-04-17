"""Conversation engine — Claude API integration for natural butler dialogue (EC3).

Pipes VOSK-recognised text to Claude API for butler-style responses,
then speaks the response via TTS. Requires WiFi and ANTHROPIC_API_KEY.
"""

import threading
import logging
import os

logger = logging.getLogger(__name__)


class ConversationEngine:
    """Natural language conversation using Claude API.

    Falls back to canned responses if API is unavailable.
    """

    SYSTEM_PROMPT = (
        "You are Sonny, an elegant robotic butler built by HKU School of Innovation "
        "engineering students for the Project Alfred competition. "
        "You are charming, witty, and speak with understated British butler formality "
        "(think Alfred Pennyworth meets a friendly modern robot). "
        "Keep responses to 1-2 short sentences — you speak aloud via TTS so brevity matters. "
        "Your capabilities: follow floor tracks for food delivery, navigate to ArUco markers, "
        "detect obstacles with ultrasonic sensors, dance, take photos, patrol areas, "
        "recognize hand gestures, and track faces. You have mecanum wheels for omnidirectional movement. "
        "You understand English and Turkish. "
        "If someone asks about food or drinks, play along — you are a butler at a reception party. "
        "Show personality: make subtle jokes, express concern if blocked, excitement when dancing."
    )

    FALLBACK_RESPONSES = [
        "I'm afraid I can't chat right now, but I'm happy to help with a task.",
        "My conversation module is offline. Would you like me to follow the track or find a marker?",
        "I'd love to chat, but my WiFi seems to be down. Try a voice command instead.",
    ]

    def __init__(self, speaker=None, api_key=None):
        """
        Args:
            speaker: Speaker instance for TTS output.
            api_key: Anthropic API key. Reads from ANTHROPIC_API_KEY env var if None.
        """
        self._speaker = speaker
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client = None
        self._history = []
        self._fallback_idx = 0

        if self._api_key:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self._api_key)
                logger.info("Claude API conversation engine ready")
            except ImportError:
                logger.warning("anthropic package not installed — conversation falls back to canned responses")
            except Exception as e:
                logger.warning(f"Claude API init failed: {e}")

    @property
    def is_available(self):
        """Whether the Claude API is available."""
        return self._client is not None

    def handle(self, text):
        """Handle a conversation input. Non-blocking (runs in thread).

        Args:
            text: User's spoken text.
        """
        thread = threading.Thread(target=self._handle_sync, args=(text,), daemon=True)
        thread.start()

    def _handle_sync(self, text):
        """Process conversation synchronously."""
        if not self._client:
            response = self._fallback_response()
        else:
            response = self._call_claude(text)

        logger.info(f"[Conversation] '{text}' -> '{response}'")

        if self._speaker:
            self._speaker.say(response)
        else:
            print(f"[Sonny says] {response}")

    def _call_claude(self, text):
        """Call Claude API for a response."""
        try:
            self._history.append({"role": "user", "content": text})

            # Keep conversation history short
            if len(self._history) > 10:
                self._history = self._history[-6:]

            response = self._client.messages.create(
                model="claude-opus-4-6",
                max_tokens=100,
                system=self.SYSTEM_PROMPT,
                messages=self._history,
            )

            reply = response.content[0].text
            self._history.append({"role": "assistant", "content": reply})
            return reply

        except Exception as e:
            logger.error(f"Claude API error: {e}")
            return self._fallback_response()

    def _fallback_response(self):
        """Return a canned response when API is unavailable."""
        response = self.FALLBACK_RESPONSES[self._fallback_idx % len(self.FALLBACK_RESPONSES)]
        self._fallback_idx += 1
        return response
