"""Intent classifier — maps voice text to robot actions.

Two-tier classification:
1. GPT-4o-mini (smart, understands natural language, extracts marker IDs 1-50)
2. Keyword matching (fast offline fallback)
"""

import os
import json
import logging
import re
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

INTENT_SYSTEM_PROMPT = """You are the intent classifier for Sonny, a robotic butler. Classify the user's spoken command into exactly one intent.

Available intents:
- follow_track: Follow the line/track/path on the ground for food delivery
- go_to_aruco: Go to / find / follow a QR code or ArUco marker (may include a marker ID 1-50)
- stop: Stop all movement immediately
- dance: Perform a dance routine
- take_photo: Take a photo / picture / selfie
- come_here: Come to me / follow me / come here
- patrol: Patrol / wander / roam / explore the area
- sleep: Go to sleep / rest / standby
- search: Search / look around / scan for markers
- chat: General conversation (not a robot command)
- confirm: Yes / agree / okay
- cancel: No / disagree / cancel
- unknown: Cannot determine intent

Respond with ONLY a JSON object (no markdown, no explanation):
{"intent": "intent_name", "confidence": 0.0-1.0, "marker_id": null or 1-50}

Examples:
"follow the track" → {"intent": "follow_track", "confidence": 0.95, "marker_id": null}
"go to marker 5" → {"intent": "go_to_aruco", "confidence": 0.98, "marker_id": 5}
"find QR code forty two" → {"intent": "go_to_aruco", "confidence": 0.95, "marker_id": 42}
"take me to the nearest marker" → {"intent": "go_to_aruco", "confidence": 0.90, "marker_id": null}
"what's the weather like" → {"intent": "chat", "confidence": 0.85, "marker_id": null}
"stop right now" → {"intent": "stop", "confidence": 0.99, "marker_id": null}
"can you go to code number 12" → {"intent": "go_to_aruco", "confidence": 0.95, "marker_id": 12}"""


class IntentClassifier:
    """Classifies voice commands into robot intents.

    Uses GPT-4o-mini for smart classification with keyword fallback.
    """

    KEYWORDS = {
        "follow the marker": "go_to_aruco",
        "follow the code": "go_to_aruco",
        "follow marker": "go_to_aruco",
        "follow code": "go_to_aruco",
        "go to qr code": "go_to_aruco",
        "go to the qr code": "go_to_aruco",
        "go to code": "go_to_aruco",
        "go to the code": "go_to_aruco",
        "go to marker": "go_to_aruco",
        "go to the marker": "go_to_aruco",
        "find the marker": "go_to_aruco",
        "find marker": "go_to_aruco",
        "qr code": "go_to_aruco",
        "marker": "go_to_aruco",
        "follow the track": "follow_track",
        "follow track": "follow_track",
        "follow the line": "follow_track",
        "follow line": "follow_track",
        "follow the path": "follow_track",
        "follow path": "follow_track",
        "track": "follow_track",
        "line": "follow_track",
        "stop": "stop",
        "halt": "stop",
        "freeze": "stop",
        "dance": "dance",
        "groove": "dance",
        "take a photo": "take_photo",
        "take photo": "take_photo",
        "take a picture": "take_photo",
        "take picture": "take_photo",
        "photo": "take_photo",
        "picture": "take_photo",
        "selfie": "take_photo",
        "come here": "come_here",
        "come to me": "come_here",
        "come over": "come_here",
        "come": "come_here",
        "follow me": "come_here",
        "patrol": "patrol",
        "wander": "patrol",
        "roam": "patrol",
        "explore": "patrol",
        "go to sleep": "sleep",
        "sleep": "sleep",
        "rest": "sleep",
        "search": "search",
        "look around": "search",
        "scan": "search",
        "chat": "chat",
        "talk to me": "chat",
        "tell me": "chat",
        "yes": "confirm",
        "yeah": "confirm",
        "okay": "confirm",
        "ok": "confirm",
        "no": "cancel",
        "nope": "cancel",
        "cancel": "cancel",
    }

    _SORTED = None

    def __init__(self):
        if IntentClassifier._SORTED is None:
            IntentClassifier._SORTED = sorted(
                self.KEYWORDS.items(), key=lambda x: len(x[0]), reverse=True
            )

    def classify(self, text):
        """Classify text into an intent. Tries GPT-4o-mini first, then keywords.

        Returns:
            Tuple (intent_name, confidence). Also sets self.last_marker_id.
        """
        self.last_marker_id = None

        if _openai_client:
            result = self._classify_smart(text)
            if result:
                return result

        return self._classify_keywords(text)

    def _classify_smart(self, text):
        """Use GPT-4o-mini for natural language intent classification."""
        try:
            response = _openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                max_tokens=80,
                temperature=0.1,
            )
            raw = response.choices[0].message.content.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)
            data = json.loads(raw)
            intent = data.get("intent", "unknown")
            confidence = float(data.get("confidence", 0.5))
            marker_id = data.get("marker_id")
            if marker_id is not None:
                marker_id = int(marker_id)
                if not (0 <= marker_id <= 50):
                    marker_id = None
            self.last_marker_id = marker_id
            logger.info(f"Smart intent: '{text}' -> {intent} ({confidence:.0%}) marker={marker_id}")
            return (intent, confidence)
        except Exception as e:
            logger.warning(f"Smart intent failed: {e}")
            return None

    def _classify_keywords(self, text):
        """Fallback keyword-based classification. Longest match wins."""
        lower = text.lower().strip()
        if not lower:
            return ("unknown", 0.0)

        for keyword, intent in IntentClassifier._SORTED:
            if keyword in lower:
                self.last_marker_id = self.extract_marker_id(text)
                return (intent, 1.0)

        return ("unknown", 0.0)

    @staticmethod
    def extract_marker_id(text):
        """Extract a marker ID number (1-50) from voice text."""
        lower = text.lower().strip()

        match = re.search(r'(?:marker|code|aruco)\s*(?:number\s*)?(\d+)', lower)
        if match:
            num = int(match.group(1))
            if 0 <= num <= 50:
                return num

        word_to_num = {
            "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
            "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
            "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
            "eighteen": 18, "nineteen": 19, "twenty": 20,
            "twenty one": 21, "twenty two": 22, "twenty three": 23,
            "twenty four": 24, "twenty five": 25, "twenty six": 26,
            "twenty seven": 27, "twenty eight": 28, "twenty nine": 29,
            "thirty": 30, "thirty one": 31, "thirty two": 32,
            "thirty three": 33, "thirty four": 34, "thirty five": 35,
            "thirty six": 36, "thirty seven": 37, "thirty eight": 38,
            "thirty nine": 39, "forty": 40, "forty one": 41,
            "forty two": 42, "forty three": 43, "forty four": 44,
            "forty five": 45, "forty six": 46, "forty seven": 47,
            "forty eight": 48, "forty nine": 49, "fifty": 50,
        }
        for word, num in sorted(word_to_num.items(), key=lambda x: len(x[0]), reverse=True):
            if word in lower:
                return num

        return None
