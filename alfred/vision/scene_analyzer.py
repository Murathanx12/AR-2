"""Scene analyzer — GPT-4o-mini vision for intelligent scene understanding.

Periodically sends camera frames to OpenAI Vision API for:
- Obstacle identification and description
- Person count and position
- Scene context (room layout, objects)
- Safety assessment for navigation

Rate-limited to save API budget (~$0.01 per analysis).
"""

import base64
import time
import logging
import threading
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

SCENE_SYSTEM_PROMPT = """You are the vision system for Sonny, a robotic butler on mecanum wheels navigating indoors.
Analyze the camera frame and report in JSON (no markdown fences):
{
  "obstacles": [{"description": "chair", "position": "center-left", "distance": "close"}],
  "people": [{"position": "center", "gesture": "waving/standing/sitting/pointing/none", "facing_robot": true}],
  "path_clear": true,
  "scene": "classroom with tables",
  "navigation_advice": "path clear ahead, person on the right"
}
Keep descriptions short. Focus on navigation-relevant information."""


class SceneAnalyzer:
    """Analyzes camera frames using GPT-4o-mini vision.

    Rate-limited: minimum 5 seconds between analyses to save budget.
    Results cached and accessible via properties.
    """

    def __init__(self, min_interval=5.0):
        self._min_interval = min_interval
        self._last_analysis_time = 0
        self._last_result = None
        self._lock = threading.Lock()
        self._analyzing = False

    @property
    def is_available(self):
        return _openai_client is not None

    @property
    def last_result(self):
        with self._lock:
            return self._last_result

    @property
    def path_clear(self):
        with self._lock:
            if self._last_result:
                return self._last_result.get("path_clear", True)
            return True

    @property
    def people_count(self):
        with self._lock:
            if self._last_result:
                return len(self._last_result.get("people", []))
            return 0

    @property
    def navigation_advice(self):
        with self._lock:
            if self._last_result:
                return self._last_result.get("navigation_advice", "")
            return ""

    def analyze_async(self, frame):
        """Submit a frame for analysis (non-blocking). Respects rate limit."""
        if not _openai_client or self._analyzing:
            return
        now = time.monotonic()
        if now - self._last_analysis_time < self._min_interval:
            return
        self._analyzing = True
        thread = threading.Thread(target=self._analyze, args=(frame.copy(),), daemon=True)
        thread.start()

    def analyze_sync(self, frame):
        """Analyze a frame synchronously. Returns result dict or None."""
        if not _openai_client:
            return None
        return self._analyze(frame)

    def _analyze(self, frame):
        try:
            import cv2
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 40])
            b64 = base64.b64encode(buffer).decode('utf-8')

            response = _openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SCENE_SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "text", "text": "Analyze this camera frame for navigation."},
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                            "detail": "low",
                        }},
                    ]},
                ],
                max_tokens=200,
                temperature=0.2,
            )

            raw = response.choices[0].message.content.strip()
            import re, json
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)
            result = json.loads(raw)

            with self._lock:
                self._last_result = result
                self._last_analysis_time = time.monotonic()

            logger.info(f"Scene: {result.get('scene', '?')} | clear={result.get('path_clear')} | people={len(result.get('people', []))}")
            return result

        except Exception as e:
            logger.warning(f"Scene analysis failed: {e}")
            return None
        finally:
            self._analyzing = False

    def describe_scene(self, frame):
        """Get a natural language description of the scene for butler conversation."""
        if not _openai_client:
            return "I can't see clearly right now."
        try:
            import cv2
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 40])
            b64 = base64.b64encode(buffer).decode('utf-8')

            response = _openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are Sonny, a butler robot. Describe what you see in 1-2 sentences, as a butler would."},
                    {"role": "user", "content": [
                        {"type": "text", "text": "What do you see?"},
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                            "detail": "low",
                        }},
                    ]},
                ],
                max_tokens=80,
                temperature=0.7,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"Scene describe failed: {e}")
            return "I'm having trouble with my vision right now."
