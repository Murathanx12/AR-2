"""Intent classifier — fuzzy keyword-based speech intent recognition.

Maps recognised voice text to robot actions. Uses both exact substring
matching and fuzzy matching (difflib) to handle VOSK recognition errors
and accent variations.
"""

from difflib import SequenceMatcher


class IntentClassifier:
    """Classifies voice commands into robot intents using keyword + fuzzy matching."""

    INTENTS = {
        "follow_track": ["follow track", "follow the track", "follow line", "follow"],
        "go_to_aruco": [
            "go to qr code", "go to code", "go to marker",
            "qr code", "qr", "find marker", "find the marker",
            "go to the marker", "go to the code",
        ],
        "dance": ["dance", "groove", "boogie", "let's dance"],
        "take_photo": ["photo", "picture", "selfie", "take a photo", "take photo"],
        "come_here": ["come here", "come", "approach", "come to me"],
        "stop": ["stop", "halt", "freeze", "wait"],
        "sleep": ["sleep", "rest", "standby", "go to sleep"],
        "patrol": ["patrol", "wander", "roam", "explore"],
        "search": ["search", "look around", "scan"],
        "confirm": ["confirm", "ok", "okay", "yes", "sure", "yeah"],
        "cancel": ["cancel", "no", "never mind", "nevermind"],
        "chat": ["chat", "talk", "tell me", "let's talk", "conversation"],
        "switch_language": [
            "switch language", "change language",
            "speak turkish", "turkish", "turkce",
            "speak english", "english", "ingilizce",
        ],
    }

    # Minimum fuzzy match ratio to accept (0.0-1.0)
    # Set high to avoid false positives on unrelated sentences
    FUZZY_THRESHOLD = 0.80

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
        """Classify text into an intent with confidence scoring.

        Tries exact substring match first, then fuzzy matching.

        Args:
            text: Recognised speech text.

        Returns:
            Tuple (intent_name, confidence).
            confidence is 1.0 for exact match, 0.7-0.99 for fuzzy, 0.0 for unknown.
        """
        lower = text.lower().strip()

        # Phase 1: Exact substring matching (fast path)
        for keyword, intent in IntentClassifier._SORTED_INTENTS:
            if keyword in lower:
                return (intent, 1.0)

        # Phase 2: Fuzzy matching for speech recognition errors
        best_intent = "unknown"
        best_score = 0.0

        words = lower.split()
        for keyword, intent in IntentClassifier._SORTED_INTENTS:
            # Compare against full text
            ratio = SequenceMatcher(None, lower, keyword).ratio()
            if ratio > best_score:
                best_score = ratio
                best_intent = intent

            # Compare against sliding window of words matching keyword length
            kw_words = keyword.split()
            kw_len = len(kw_words)
            for i in range(max(1, len(words) - kw_len + 1)):
                window = " ".join(words[i:i + kw_len])
                ratio = SequenceMatcher(None, window, keyword).ratio()
                if ratio > best_score:
                    best_score = ratio
                    best_intent = intent

        if best_score >= self.FUZZY_THRESHOLD:
            return (best_intent, best_score)

        return ("unknown", 0.0)

    def extract_language(self, text):
        """Extract target language from a switch_language intent.

        Args:
            text: Recognised speech text.

        Returns:
            "tr" for Turkish, "en" for English, or None if unclear.
        """
        lower = text.lower()
        if any(w in lower for w in ("turkish", "turkce", "türkçe")):
            return "tr"
        if any(w in lower for w in ("english", "ingilizce")):
            return "en"
        # Toggle: if current language not specified, return None
        return None
