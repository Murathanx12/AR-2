"""Intent classifier — maps voice text to robot actions.

Simple exact keyword matching only. No fuzzy, no partial, no confirmation.
If it matches, it matches. If not, say "I don't understand."
"""


class IntentClassifier:
    """Classifies voice commands into robot intents.

    Exact substring match only — longest keyword wins.
    """

    # (intent, keywords) — keywords sorted longest-first per intent
    INTENTS = [
        ("follow_track", [
            "follow the track", "follow track", "follow the line",
            "follow line", "follow the path", "follow path",
            "start follow", "follow",
        ]),
        ("go_to_aruco", [
            "go to qr code", "go to the qr code",
            "go to code", "go to the code",
            "go to marker", "go to the marker",
            "find the marker", "find marker",
            "follow the code", "follow code",
            "qr code", "marker",
        ]),
        ("stop", ["stop", "halt", "freeze"]),
        ("dance", ["dance", "groove"]),
        ("take_photo", [
            "take photo", "take a photo", "take picture",
            "take a picture", "photo", "picture", "selfie",
        ]),
        ("come_here", ["come here", "come to me", "come over", "come"]),
        ("patrol", ["patrol", "wander", "roam", "explore"]),
        ("sleep", ["go to sleep", "sleep", "rest", "standby"]),
        ("search", ["search", "look around", "scan"]),
        ("chat", ["chat", "talk to me", "tell me", "talk"]),
        ("confirm", ["yes", "yeah", "yep", "okay", "ok"]),
        ("cancel", ["no", "nope", "cancel"]),
    ]

    def classify(self, text):
        """Classify text into an intent.

        Returns:
            Tuple (intent_name, confidence). 1.0 = match, 0.0 = unknown.
        """
        lower = text.lower().strip()
        if not lower:
            return ("unknown", 0.0)

        for intent, keywords in self.INTENTS:
            for kw in keywords:
                if kw in lower:
                    return (intent, 1.0)

        return ("unknown", 0.0)
