"""Tests for alfred.comms.protocol command formatting functions."""
from alfred.comms.protocol import (
    cmd_vector, cmd_stop, cmd_forward, cmd_reverse,
    cmd_strafe_left, cmd_strafe_right, cmd_turn_left, cmd_turn_right,
    cmd_curve, cmd_side_pivot,
)


def test_cmd_vector():
    assert cmd_vector(30, 0, 15) == "mv_vector:30,0,15\n"


def test_cmd_stop():
    assert cmd_stop() == "stop:0\n"


def test_cmd_forward():
    assert cmd_forward(50) == "mv_fwd:50\n"


def test_cmd_reverse():
    assert cmd_reverse(30) == "mv_rev:30\n"


def test_cmd_strafe_left():
    assert cmd_strafe_left(40) == "mv_left:40\n"


def test_cmd_strafe_right():
    assert cmd_strafe_right(40) == "mv_right:40\n"


def test_cmd_turn_left():
    assert cmd_turn_left(60) == "mv_turnleft:60\n"


def test_cmd_turn_right():
    assert cmd_turn_right(60) == "mv_turnright:60\n"


def test_cmd_curve():
    assert cmd_curve(30, 50) == "mv_curve:30,50\n"


def test_cmd_side_pivot():
    assert cmd_side_pivot(80, 15, 1) == "mv_sidepivot:80,15,1\n"
