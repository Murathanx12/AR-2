"""Intent classifier — maps voice text to robot actions.

Grammar-constrained VOSK output means we get clean words.
Simple exact keyword matching is reliable here.
"""


class IntentClassifier:
    """Classifies voice commands into robot intents."""

    # (intent, exact_keywords, partial_keywords)
    # Exact keywords checked longest-first. First match wins.
    INTENTS = [
        ("follow_track", [
            "follow the track", "follow track", "follow the line",
            "follow line", "follow the path", "follow path",
            "start follow",
        ], ["follow"]),

        ("go_to_aruco", [
            "go to qr code", "go to the qr code",
            "go to code", "go to the code",
            "go to marker", "go to the marker",
            "find the marker", "find marker",
            "follow the code", "follow code",
            "qr code",
        ], ["qr", "marker", "code"]),

        ("stop", ["stop", "halt", "freeze"], []),

        ("dance", ["dance", "groove"], []),

        ("take_photo", [
            "take photo", "take a photo", "take picture",
            "take a picture", "photo", "picture", "selfie",
        ], []),

        ("come_here", [
            "come here", "come to me", "come over",
        ], ["come"]),

        ("patrol", ["patrol", "wander", "roam", "explore"], []),

        ("sleep", ["go to sleep", "sleep", "rest", "standby"], []),

        ("search", ["search", "look around", "scan"], []),

        ("chat", ["chat", "talk to me", "tell me"], ["talk"]),

        # yes/no — only exact words, not substrings
        ("confirm", ["yes", "yeah", "yep", "okay", "ok"], []),
        ("cancel", ["no", "nope", "cancel"], []),
    ]

    def classify(self, text):
        """Classify text into an intent.

        Returns:
            Tuple (intent_name, confidence).
            1.0 = exact match, 0.5 = partial, 0.0 = unknown.
        """
        lower = text.lower().strip()
        if not lower:
            return ("unknown", 0.0)

        # Pass 1: exact substring match (longest keywords first)
        for intent, exact_kws, _ in self.INTENTS:
            for kw in sorted(exact_kws, key=len, reverse=True):
                if kw in lower:
                    return (intent, 1.0)

        # Pass 2: single-word partial match
        words = set(lower.split())
        for intent, _, partial_kws in self.INTENTS:
            if not partial_kws:
                continue
            for kw in partial_kws:
                if kw in words:
                    return (intent, 0.5)

        return ("unknown", 0.0)

    def get_confirmation_question(self, intent):
        """Get yes/no question for a partial match."""
        questions = {
            "follow_track": "Did you say follow the track?",
            "go_to_aruco": "Did you say go to the QR code?",
            "come_here": "Did you say come here?",
            "chat": "Would you like to chat?",
        }
        return questions.get(intent)
