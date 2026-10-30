from __future__ import annotations

from it2pr_worker.agent.limits import LimitKind, LimitTracker


class FakeClock:
    """Deterministic monotonic clock; `advance` moves time forward."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def test_ok_when_under_all_limits() -> None:
    clock = FakeClock()
    tracker = LimitTracker(max_turns=30, wall_clock_seconds=1800, max_cost_usd=20.0, clock=clock)
    tracker.start()
    tracker.record_turn()
    tracker.add_cost(1.0)
    assert tracker.check().kind is LimitKind.OK


def test_max_turns_exceeded() -> None:
    clock = FakeClock()
    tracker = LimitTracker(max_turns=2, clock=clock)
    tracker.start()
    tracker.record_turn()
    assert tracker.check().kind is LimitKind.OK
    tracker.record_turn()
    status = tracker.check()
    assert status.kind is LimitKind.TURNS
    assert status.exceeded is True


def test_wall_clock_exceeded() -> None:
    clock = FakeClock()
    tracker = LimitTracker(wall_clock_seconds=100.0, clock=clock)
    tracker.start()
    tracker.record_turn()
    assert tracker.check().kind is LimitKind.OK
    clock.advance(100.0)
    assert tracker.check().kind is LimitKind.TIME


def test_max_cost_exceeded() -> None:
    clock = FakeClock()
    tracker = LimitTracker(max_cost_usd=5.0, clock=clock)
    tracker.start()
    tracker.add_cost(3.0)
    tracker.record_turn()
    assert tracker.check().kind is LimitKind.OK
    tracker.add_cost(2.5)
    assert tracker.check().kind is LimitKind.COST
    assert tracker.cost_usd == 5.5


def test_cost_none_handled_without_crash_and_marks_unknown() -> None:
    clock = FakeClock()
    tracker = LimitTracker(max_cost_usd=5.0, clock=clock)
    tracker.start()
    tracker.add_cost(None)
    tracker.record_turn()
    # Unknown cost must never trip the cost limit or crash.
    assert tracker.check().kind is LimitKind.OK
    assert tracker.cost_usd is None


def test_cost_none_after_known_still_reports_none() -> None:
    tracker = LimitTracker(max_cost_usd=100.0, clock=FakeClock())
    tracker.start()
    tracker.add_cost(1.0)
    tracker.add_cost(None)
    assert tracker.cost_usd is None


def test_turns_limit_takes_precedence_ordering() -> None:
    # Turns checked before time/cost; verify turns wins when all would trip.
    clock = FakeClock()
    tracker = LimitTracker(
        max_turns=1, wall_clock_seconds=1.0, max_cost_usd=1.0, clock=clock
    )
    tracker.start()
    tracker.record_turn()
    tracker.add_cost(5.0)
    clock.advance(10.0)
    assert tracker.check().kind is LimitKind.TURNS
