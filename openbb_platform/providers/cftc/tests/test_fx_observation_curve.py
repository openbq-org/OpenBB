from statistics import median

import numpy as np

from openbb_cftc.utils.fx_vol import (
    ObservationCurve,
    observation_curve,
)

YEARS = (0.0, 0.002, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 3.0)
DAYS = (1, 2, 3, 5, 9, 10, 20, 45, 90, 200)


def _obs(days, rate, identifier):
    return {"days": days, "rate": rate, "dissemination_identifier": identifier}


def _reference(observations):
    observations = [o for o in observations if o["days"] > 2]

    if not observations:
        return None, None, 0

    by_day = {}

    for o in observations:
        by_day.setdefault(o["days"], []).append(o["rate"])

    nodes = sorted((days, median(rates)) for days, rates in by_day.items())
    days = [node[0] for node in nodes]
    near = [rate for day, rates in by_day.items() if day <= 9 for rate in rates]
    spot = median(near) if near else nodes[0][1]

    def forward(years):
        from bisect import bisect_right

        target = years * 365.0

        if target <= days[0]:
            return nodes[0][1]

        if target >= days[-1]:
            return nodes[-1][1]

        upper = bisect_right(days, target)
        day_low, rate_low = nodes[upper - 1]
        day_high, rate_high = nodes[upper]

        return rate_low + (target - day_low) / (day_high - day_low) * (
            rate_high - rate_low
        )

    return spot, forward, len(nodes)


def _random_observations(rng):
    return [
        _obs(
            int(rng.choice(DAYS)),
            round(float(rng.uniform(1400.0, 1500.0)), int(rng.choice((0, 1, 3)))),
            "" if rng.random() < 0.1 else f"id{index}",
        )
        for index in range(int(rng.integers(1, 41)))
    ]


def _same(actual, expected):
    spot, forward, count = actual
    ref_spot, ref_forward, ref_count = expected

    assert spot == ref_spot
    assert count == ref_count

    if ref_forward is None:
        assert forward is None
        return

    for years in YEARS:
        assert forward(years) == ref_forward(years)


def test_observation_curve_matches_the_reference_on_random_observations():
    rng = np.random.default_rng(20261110)

    for _ in range(400):
        observations = _random_observations(rng)
        spot, forward = observation_curve(observations)
        ref_spot, ref_forward, _ = _reference(observations)

        assert spot == ref_spot

        if ref_forward is None:
            assert forward is None
        else:
            assert all(forward(y) == ref_forward(y) for y in YEARS)


def test_leaving_a_print_out_equals_rebuilding_without_it():
    rng = np.random.default_rng(7)
    checked = 0

    for _ in range(600):
        observations = _random_observations(rng)
        curve = ObservationCurve(observations)

        for target in observations:
            identifier = target["dissemination_identifier"]
            rest = [o for o in observations if o is not target]

            if identifier:
                assert identifier in curve
                expected = _reference(rest)
                checked += 1
            else:
                assert identifier not in curve
                expected = _reference(observations)

            _same(curve.curve(identifier), expected)
            assert curve.near_rates(identifier) == sorted(
                o["rate"]
                for o in (rest if identifier else observations)
                if o["days"] <= 9
            )

    assert checked > 5_000


def test_an_unknown_or_blank_identifier_leaves_the_curve_whole():
    observations = [_obs(5, 1.0, "a"), _obs(30, 2.0, ""), _obs(60, 3.0, "")]
    curve = ObservationCurve(observations)

    assert curve.curve("missing") is curve.curve()
    assert curve.curve("") is curve.curve()
    assert curve.near_rates("missing") == [1.0]
    assert curve.near_rates("") == [1.0]
    assert "" not in curve


def test_a_spot_dated_print_does_not_move_the_curve():
    curve = ObservationCurve([_obs(1, 9.0, "x"), _obs(5, 1.0, "a"), _obs(30, 2.0, "b")])

    assert curve.curve("x") is curve.curve()
    assert curve.near_rates() == [1.0, 9.0]
    assert curve.near_rates("x") == [1.0]


def test_the_spot_is_the_median_of_the_near_nodes_without_the_print():
    curve = ObservationCurve(
        [_obs(4, 1.0, "a"), _obs(6, 2.0, "b"), _obs(8, 9.0, "c"), _obs(30, 5.0, "d")]
    )

    assert curve.curve()[0] == 2.0
    assert curve.curve("c")[0] == 1.5
    assert curve.curve("a")[0] == 5.5


def test_the_spot_falls_back_to_the_shortest_node_without_near_prints():
    curve = ObservationCurve([_obs(30, 1.0, "a"), _obs(60, 2.0, "b")])

    assert curve.curve()[0] == 1.0
    assert curve.curve("a")[0] == 2.0
    assert curve.curve("b")[0] == 1.0


def test_a_far_print_keeps_the_spot_of_the_near_nodes():
    curve = ObservationCurve(
        [_obs(5, 1.0, "a"), _obs(30, 2.0, "b"), _obs(60, 3.0, "c")]
    )
    spot, _, count = curve.curve("c")

    assert spot == curve.curve()[0] == 1.0
    assert count == 2


def test_the_last_print_leaves_no_curve():
    curve = ObservationCurve([_obs(1, 1.0, "x"), _obs(30, 2.0, "a")])

    assert curve.curve("a") == (None, None, 0)
    assert curve.curve("x") is curve.curve()


def test_an_empty_curve():
    curve = ObservationCurve([])

    assert curve.curve() == (None, None, 0)
    assert curve.near_rates() == []
    assert observation_curve([]) == (None, None)


def test_a_repeated_identifier_is_never_left_out():
    observations = [
        _obs(30, 1.0, "d"),
        _obs(60, 2.0, "d"),
        _obs(90, 3.0, "b"),
        _obs(5, 4.0, "d"),
    ]
    curve = ObservationCurve(observations)

    assert "d" not in curve
    assert "b" in curve
    assert curve.curve("d") is curve.curve()
    assert curve.near_rates("d") == [4.0]
    _same(curve.curve("b"), _reference(observations[:2] + observations[3:]))


def test_repeated_identifiers_match_the_whole_curve_on_random_observations():
    rng = np.random.default_rng(11)

    for _ in range(300):
        observations = _random_observations(rng)

        for index, observation in enumerate(observations):
            observation["dissemination_identifier"] = f"id{int(rng.integers(0, 6))}"

        curve = ObservationCurve(observations)

        for identifier in {o["dissemination_identifier"] for o in observations}:
            count = sum(
                o["dissemination_identifier"] == identifier for o in observations
            )

            if count > 1:
                assert identifier not in curve
                _same(curve.curve(identifier), _reference(observations))
                assert curve.near_rates(identifier) == sorted(
                    o["rate"] for o in observations if o["days"] <= 9
                )
