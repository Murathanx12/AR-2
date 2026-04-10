"""Intent classifier — keyword-based speech intent recognition.

Maps recognised voice text to robot actions. Designed for VOSK grammar-constrained
recognition where we get exact keyword matches.
"""


class IntentClassifier:
    """Classifies voice commands into robot intents using keyword matching."""

    INTENTS = {
        "follow_track": ["follow track", "follow the track", "follow"],
        "go_to_aruco": ["go to qr code", "go to code", "go to marker", "qr code", "qr"],
        "dance": ["dance", "groove", "boogie"],
        "take_photo": ["photo", "picture", "selfie"],
        "come_here": ["come here", "come", "approach"],
        "stop": ["stop", "halt", "freeze"],
        "sleep": ["sleep", "rest", "standby"],
        "patrol": ["patrol", "wander", "roam"],
        "search": ["search"],
        "confirm": ["confirm", "ok", "okay", "yes"],
        "cancel": ["cancel", "no"],
        "chat": ["chat", "talk", "tell me"],
    }

    # Priority order: longer phrases match first to avoid partial matches
    _SORTED_INTENTS = None

    def __init__(self):
        if IntentClassifier._SORTED_INTENTS is None:
            # Sort keywords longest-first for greedy matching
            pairs = []
            for intent, keywords in self.INTENTS.items():
                for kw in keywords:
                    pairs.append((kw, intent))
            pairs.sort(key=lambda x: len(x[0]), reverse=True)
            IntentClassifier._SORTED_INTENTS = pairs

    def classify(self, text):
        """Classify text into an intent.

        Args:
            text: Recognised speech text.

        Returns:
            Tuple (intent_name, confidence). confidence is 1.0 for match, 0.0 for unknown.
        """
        lower = text.lower().strip()
        for keyword, intent in IntentClassifier._SORTED_INTENTS:
            if keyword in lower:
                return (intent, 1.0)
        return ("unknown", 0.0)
