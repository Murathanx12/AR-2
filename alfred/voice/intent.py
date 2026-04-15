"""Intent classifier — maps voice text to robot actions.

Two-pass matching:
1. Exact keyword match (high confidence)
2. Partial/fuzzy match (asks for confirmation)
"""


class IntentClassifier:
    """Classifies voice commands into robot intents."""

    # (intent, exact_keywords, partial_keywords)
    # exact = if found in text, it's definitely this intent
    # partial = might be this intent, needs confirmation
    INTENTS = [
        ("follow_track", [
            "follow the track", "follow track", "follow the line",
            "follow line", "follow the path", "follow path",
        ], ["follow", "track", "line", "path"]),

        ("go_to_aruco", [
            "go to qr code", "go to the qr code", "go to q r code",
            "go to code", "go to the code", "go to marker",
            "go to the marker", "find the marker", "find marker",
            "follow the qr code", "follow qr code", "follow the code",
            "qr code", "q r code",
        ], ["qr", "marker", "code", "aruco"]),

        ("stop", [
            "stop", "halt", "freeze",
        ], []),  # stop has no partial — it's always exact

        ("dance", [
            "dance", "groove", "boogie", "let's dance",
        ], []),

        ("take_photo", [
            "take a photo", "take photo", "take a picture",
            "take picture", "photo", "picture", "selfie",
        ], []),

        ("come_here", [
            "come here", "come to me", "come over",
        ], ["come"]),

        ("patrol", [
            "patrol", "wander", "roam", "explore",
        ], []),

        ("sleep", [
            "go to sleep", "sleep", "rest", "standby",
        ], []),

        ("search", [
            "search", "look around", "scan",
        ], []),

        ("chat", [
            "chat", "talk to me", "let's talk", "tell me",
        ], ["talk"]),

        ("confirm", [
            "confirm", "okay", "ok", "yes", "sure", "yeah", "yep",
        ], []),

        ("cancel", [
            "cancel", "never mind", "no", "nope",
        ], []),
    ]

    def classify(self, text):
        """Classify text into an intent.

        Returns:
            Tuple (intent_name, confidence).
            1.0 = exact match
            0.5 = partial match (should ask for confirmation)
            0.0 = unknown
        """
        lower = text.lower().strip()
        if not lower:
            return ("unknown", 0.0)

        # Pass 1: Exact keyword match (longest first per intent)
        for intent, exact_kws, _ in self.INTENTS:
            for kw in sorted(exact_kws, key=len, reverse=True):
                if kw in lower:
                    return (intent, 1.0)

        # Pass 2: Partial match — single keyword that hints at an intent
        words = set(lower.split())
        for intent, _, partial_kws in self.INTENTS:
            if not partial_kws:
                continue
            for kw in partial_kws:
                if kw in words:
                    return (intent, 0.5)

        return ("unknown", 0.0)

    def get_confirmation_question(self, intent):
        """Get a yes/no question to confirm a partially matched intent.

        Args:
            intent: The partially matched intent name.

        Returns:
            Question string, or None if no confirmation needed.
        """
        questions = {
            "follow_track": "Did you say follow the track?",
            "go_to_aruco": "Did you say go to the QR code?",
            "come_here": "Did you say come here?",
            "chat": "Would you like to chat?",
        }
        return questions.get(intent)
