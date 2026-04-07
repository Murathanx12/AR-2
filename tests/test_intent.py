"""Tests for alfred.voice.intent IntentClassifier."""
from alfred.voice.intent import IntentClassifier


def test_follow():
    clf = IntentClassifier()
    assert clf.classify("please follow the track") == ("follow_track", 1.0)


def test_dance():
    clf = IntentClassifier()
    assert clf.classify("let's dance") == ("dance", 1.0)


def test_stop():
    clf = IntentClassifier()
    assert clf.classify("halt right now") == ("stop", 1.0)


def test_unknown():
    clf = IntentClassifier()
    assert clf.classify("what is quantum physics") == ("unknown", 0.0)


def test_photo():
    clf = IntentClassifier()
    assert clf.classify("take a picture") == ("take_photo", 1.0)
