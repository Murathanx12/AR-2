"""Tests for alfred.voice.intent IntentClassifier — keyword fallback path."""
from alfred.voice.intent import IntentClassifier


def test_follow():
    clf = IntentClassifier()
    intent, conf = clf._classify_keywords("please follow the track")
    assert intent == "follow_track"
    assert conf == 1.0


def test_dance():
    clf = IntentClassifier()
    intent, conf = clf._classify_keywords("let's dance")
    assert intent == "dance"
    assert conf == 1.0


def test_stop():
    clf = IntentClassifier()
    intent, conf = clf._classify_keywords("halt right now")
    assert intent == "stop"
    assert conf == 1.0


def test_unknown():
    clf = IntentClassifier()
    intent, conf = clf._classify_keywords("what is quantum physics")
    assert intent == "unknown"
    assert conf == 0.0


def test_photo():
    clf = IntentClassifier()
    intent, conf = clf._classify_keywords("take a picture")
    assert intent == "take_photo"
    assert conf == 1.0


def test_marker_id_numeric():
    assert IntentClassifier.extract_marker_id("go to marker 42") == 42


def test_marker_id_word():
    assert IntentClassifier.extract_marker_id("find marker eight") == 8


def test_marker_id_word_compound():
    assert IntentClassifier.extract_marker_id("go to marker forty two") == 42


def test_marker_id_none():
    assert IntentClassifier.extract_marker_id("go to qr code") is None


def test_marker_id_range():
    assert IntentClassifier.extract_marker_id("marker 51") is None
    assert IntentClassifier.extract_marker_id("marker 50") == 50
    assert IntentClassifier.extract_marker_id("marker 0") == 0


def test_follow_me():
    clf = IntentClassifier()
    intent, conf = clf._classify_keywords("follow me")
    assert intent == "come_here"
    assert conf == 1.0


def test_aruco_longest_match():
    clf = IntentClassifier()
    intent, _ = clf._classify_keywords("follow the marker")
    assert intent == "go_to_aruco"
