"""Alfred V4 FSM state definitions — 17 states for the full robotic butler."""

from enum import IntEnum


class State(IntEnum):
    """All possible states for the Alfred V4 finite state machine."""
    IDLE = 0
    LISTENING = 1
    FOLLOWING = 2
    ENDPOINT = 3
    PARKING = 4
    ARUCO_SEARCH = 5
    ARUCO_APPROACH = 6
    BLOCKED = 7
    REROUTING = 8
    PATROL = 9
    PERSON_APPROACH = 10
    DANCING = 11
    PHOTO = 12
    LOST_REVERSE = 13
    LOST_PIVOT = 14
    STOPPING = 15
    SLEEPING = 16


STATE_NAMES = {
    State.IDLE:             "IDLE",
    State.LISTENING:        "LISTEN",
    State.FOLLOWING:        "FOLLOW",
    State.ENDPOINT:         "ENDPOINT",
    State.PARKING:          "PARKING",
    State.ARUCO_SEARCH:     "ARUCO_SRCH",
    State.ARUCO_APPROACH:   "ARUCO_APPR",
    State.BLOCKED:          "BLOCKED",
    State.REROUTING:        "REROUTE",
    State.PATROL:           "PATROL",
    State.PERSON_APPROACH:  "PERSON",
    State.DANCING:          "DANCE",
    State.PHOTO:            "PHOTO",
    State.LOST_REVERSE:     "LOST_REV",
    State.LOST_PIVOT:       "LOST_PIVOT",
    State.STOPPING:         "STOPPING",
    State.SLEEPING:         "SLEEP",
}
