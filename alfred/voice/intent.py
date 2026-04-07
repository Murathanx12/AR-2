"""Intent classifier — keyword-based speech intent recognition."""


class IntentClassifier:
    INTENTS = {
        "follow_track": ["follow", "track", "line"],
        "go_to_aruco": ["go to", "aruco", "marker"],
        "dance": ["dance", "groove", "boogie"],
        "take_photo": ["photo", "picture", "selfie"],
        "come_here": ["come", "here", "approach"],
        "stop": ["stop", "halt", "freeze"],
        "sleep": ["sleep", "rest", "standby"],
        "patrol": ["patrol", "wander", "roam"],
    }

    def __init__(self):
        pass

    def classify(self, text):
        lower = text.lower()
        for intent, keywords in self.INTENTS.items():
            for kw in keywords:
                if kw in lower:
                    return (intent, 1.0)
        return ("unknown", 0.0)
