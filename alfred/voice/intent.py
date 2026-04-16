"""Intent classifier — maps voice text to robot actions.

IMPORTANT: Order matters! Intents with overlapping keywords must be
listed with the MORE SPECIFIC one first. "follow the marker" must
match go_to_aruco before "follow" matches follow_track.
"""


class IntentClassifier:
    """Classifies voice commands into robot intents.

    Checks all keywords across all intents, picks the LONGEST match.
    This prevents "follow" from stealing "follow the marker".
    """

    # All keyword-to-intent mappings
    KEYWORDS = {
        # ArUco / marker — must beat "follow" for "follow the marker"
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

        # Line following
        "follow the track": "follow_track",
        "follow track": "follow_track",
        "follow the line": "follow_track",
        "follow line": "follow_track",
        "follow the path": "follow_track",
        "follow path": "follow_track",
        "track": "follow_track",  # "track" alone = follow track
        "line": "follow_track",   # "line" alone = follow line

        # Stop
        "stop": "stop",
        "halt": "stop",
        "freeze": "stop",

        # Dance
        "dance": "dance",
        "groove": "dance",

        # Photo
        "take a photo": "take_photo",
        "take photo": "take_photo",
        "take a picture": "take_photo",
        "take picture": "take_photo",
        "photo": "take_photo",
        "picture": "take_photo",
        "selfie": "take_photo",

        # Come here
        "come here": "come_here",
        "come to me": "come_here",
        "come over": "come_here",
        "come": "come_here",

        # Patrol
        "patrol": "patrol",
        "wander": "patrol",
        "roam": "patrol",
        "explore": "patrol",

        # Sleep
        "go to sleep": "sleep",
        "sleep": "sleep",
        "rest": "sleep",

        # Search
        "search": "search",
        "look around": "search",
        "scan": "search",

        # Chat
        "chat": "chat",
        "talk to me": "chat",
        "tell me": "chat",

        # Confirm / Cancel
        "yes": "confirm",
        "yeah": "confirm",
        "okay": "confirm",
        "ok": "confirm",
        "no": "cancel",
        "nope": "cancel",
        "cancel": "cancel",
    }

    # Pre-sorted: longest keywords first (checked in this order)
    _SORTED = None

    def __init__(self):
        if IntentClassifier._SORTED is None:
            IntentClassifier._SORTED = sorted(
                self.KEYWORDS.items(), key=lambda x: len(x[0]), reverse=True
            )

    def classify(self, text):
        """Classify text. Longest keyword match wins.

        Returns:
            Tuple (intent_name, confidence). 1.0 = match, 0.0 = unknown.
        """
        lower = text.lower().strip()
        if not lower:
            return ("unknown", 0.0)

        # Longest keyword first — "follow the marker" beats "follow"
        for keyword, intent in IntentClassifier._SORTED:
            if keyword in lower:
                return (intent, 1.0)

        return ("unknown", 0.0)

    @staticmethod
    def extract_marker_id(text):
        """Extract a marker ID number from voice text.

        Examples:
            "go to marker 42" → 42
            "marker eight" → 8
            "find marker 18" → 18
            "go to qr code" → None (no specific ID)

        Returns:
            int marker ID, or None if no specific ID mentioned.
        """
        import re
        lower = text.lower().strip()

        # Try numeric: "marker 42", "code 8", "marker number 18"
        match = re.search(r'(?:marker|code|aruco)\s*(?:number\s*)?(\d+)', lower)
        if match:
            return int(match.group(1))

        # Try word numbers
        word_to_num = {
            "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
            "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
            "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
            "eighteen": 18, "nineteen": 19, "twenty": 20,
            "forty two": 42, "forty-two": 42, "twenty seven": 27,
            "forty three": 43, "forty-three": 43,
        }
        for word, num in sorted(word_to_num.items(), key=lambda x: len(x[0]), reverse=True):
            if word in lower:
                return num

        return None
