"""Intent classifier — maps voice text to robot actions.

Simple keyword matching designed for VOSK open recognition output.
Handles common VOSK misrecognitions (e.g. "cue are" for "QR").
"""


class IntentClassifier:
    """Classifies voice commands into robot intents."""

    # Each intent has keywords sorted longest-first.
    # First match wins, so longer/more specific phrases take priority.
    INTENTS = [
        # Line following (R2)
        ("follow_track", [
            "follow the track", "follow track", "follow the line",
            "follow line", "follow the path", "follow path",
            "follow",
        ]),
        # ArUco marker (R3)
        ("go_to_aruco", [
            "go to qr code", "go to the qr code", "go to q r code",
            "go to code", "go to the code", "go to marker",
            "go to the marker", "find the marker", "find marker",
            "follow the qr code", "follow qr code", "follow the code",
            "qr code", "q r code", "qr", "marker",
        ]),
        # Stop — highest priority single word
        ("stop", ["stop", "halt", "freeze"]),
        # Dance
        ("dance", ["dance", "groove", "boogie"]),
        # Photo
        ("take_photo", [
            "take a photo", "take photo", "take a picture",
            "take picture", "photo", "picture", "selfie",
        ]),
        # Come here
        ("come_here", ["come here", "come to me", "come over", "come"]),
        # Patrol
        ("patrol", ["patrol", "wander", "roam", "explore"]),
        # Sleep (puts listener back to sleep too)
        ("sleep", ["go to sleep", "sleep", "rest", "standby"]),
        # Search
        ("search", ["search", "look around", "scan"]),
        # Conversation (EC3)
        ("chat", ["chat", "talk to me", "let's talk", "talk", "tell me"]),
        # Confirmation
        ("confirm", ["confirm", "okay", "ok", "yes", "sure", "yeah"]),
        ("cancel", ["cancel", "never mind", "no"]),
    ]

    def classify(self, text):
        """Classify text into an intent.

        Args:
            text: Recognised speech text.

        Returns:
            Tuple (intent_name, confidence).
            1.0 = exact keyword match, 0.0 = unknown.
        """
        lower = text.lower().strip()
        if not lower:
            return ("unknown", 0.0)

        # Exact substring match — first hit wins (longest keywords first per intent)
        for intent, keywords in self.INTENTS:
            for kw in keywords:
                if kw in lower:
                    return (intent, 1.0)

        return ("unknown", 0.0)
