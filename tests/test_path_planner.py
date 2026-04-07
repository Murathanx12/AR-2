"""PathPlanner tests."""
from alfred.navigation.path_planner import PathPlanner


def test_planner_init():
    planner = PathPlanner()
    assert planner is not None


def test_plan_velocities_no_spline():
    planner = PathPlanner()
    result = planner.plan_velocities(None, None)
    assert result == (0, 0, 0)


def test_plan_velocities_with_spline():
    import numpy as np
    planner = PathPlanner(base_speed=30)
    spline = np.array([[0, 0], [1, 0], [2, 0], [3, 0], [4, 0]])
    pos = (0, 0.5, 0)  # slightly off to the right
    vx, vy, omega = planner.plan_velocities(spline, pos, lookahead=0.3)
    assert isinstance(vx, int)
    assert isinstance(omega, int)


def test_fuse_with_ir():
    planner = PathPlanner()
    planned = (30, 0, 10)
    ir_correction = (25, 0, -5)
    result = planner.fuse_with_ir(planned, ir_correction)
    assert len(result) == 3
    assert all(isinstance(v, int) for v in result)
