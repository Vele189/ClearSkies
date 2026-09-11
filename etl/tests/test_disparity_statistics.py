"""The arithmetic under the headline finding (CS-213, methodology section 13.6).

Following the convention of `test_interpolate.py`: each test states the number it
expects and where that number comes from, so a subtly wrong formula fails here
rather than agreeing with itself.

The sums are worked by hand in the comments. Where the final step is a square
root it is written as the expression rather than a decimal, because rounding a
correlation to six places in a test is how a test stops checking the formula and
starts checking the rounding.
"""

import math

import pytest

from pipeline.analysis import statistics as st

# ---- weighted means ----------------------------------------------------


def test_weighted_mean_counts_a_heavy_observation_more_than_once() -> None:
    # (1*1 + 2*1 + 3*2) / 4 = 9/4
    assert st.weighted_mean([1.0, 2.0, 3.0], [1.0, 1.0, 2.0]) == pytest.approx(2.25)


def test_weighted_mean_of_nothing_is_not_zero() -> None:
    with pytest.raises(st.NotComputable):
        st.weighted_mean([1.0, 2.0], [0.0, 0.0])


# ---- weighted Pearson --------------------------------------------------


def correlate(xs: list[float], ys: list[float], ws: list[float]) -> float:
    """One cluster holding everything, which is the unclustered case."""
    m = st.moments_about(
        xs,
        ys,
        ws,
        centre_x=st.weighted_mean(xs, ws),
        centre_y=st.weighted_mean(ys, ws),
    )
    return st.correlation(m)


def test_a_straight_line_correlates_perfectly() -> None:
    assert correlate([1.0, 2.0, 3.0], [2.0, 4.0, 6.0], [1.0, 1.0, 1.0]) == pytest.approx(1.0)


def test_a_descending_line_correlates_perfectly_negatively() -> None:
    assert correlate([1.0, 2.0, 3.0], [6.0, 4.0, 2.0], [1.0, 1.0, 1.0]) == pytest.approx(-1.0)


def test_the_coefficient_matches_the_sums_worked_by_hand() -> None:
    # x = [1,2,3,4], mean 2.5; y = [2,4,5,4], mean 3.75.
    # dx = [-1.5,-0.5, 0.5, 1.5]; dy = [-1.75, 0.25, 1.25, 0.25]
    # cov = 2.625 - 0.125 + 0.625 + 0.375 = 3.5
    # var x = 2.25 + 0.25 + 0.25 + 2.25 = 5
    # var y = 3.0625 + 0.0625 + 1.5625 + 0.0625 = 4.75
    expected = 3.5 / math.sqrt(5.0 * 4.75)

    got = correlate([1.0, 2.0, 3.0, 4.0], [2.0, 4.0, 5.0, 4.0], [1.0, 1.0, 1.0, 1.0])

    assert got == pytest.approx(expected)


def test_a_weight_of_two_is_the_same_as_listing_the_point_twice() -> None:
    """The property that makes population weighting mean what section 13.6 says.

    A hex of twelve thousand people should count as twelve thousand people, not
    as one cell, and that is only true if weights behave like repetition.
    """
    weighted = correlate([1.0, 2.0, 3.0], [1.0, 5.0, 2.0], [1.0, 2.0, 1.0])
    repeated = correlate([1.0, 2.0, 2.0, 3.0], [1.0, 5.0, 5.0, 2.0], [1.0, 1.0, 1.0, 1.0])

    assert weighted == pytest.approx(repeated)


def test_weighting_can_reverse_the_sign_of_the_answer() -> None:
    """Not a curiosity: it is why the unweighted number must never be published.

    Four populous cells trend one way and two nearly empty ones trend the other
    hard enough to carry an unweighted coefficient with them. The per-cell answer
    and the per-person answer have opposite signs, and only the second is the
    claim the project makes.
    """
    xs = [1.0, 2.0, 3.0, 4.0, 1.0, 4.0]
    ys = [1.0, 2.0, 3.0, 4.0, 10.0, 1.0]

    per_cell = correlate(xs, ys, [1.0] * 6)
    per_person = correlate(xs, ys, [50.0, 50.0, 50.0, 50.0, 1.0, 1.0])

    assert per_cell < 0
    assert per_person > 0


def test_a_constant_column_has_no_correlation_rather_than_a_zero_one() -> None:
    with pytest.raises(st.NotComputable):
        correlate([1.0, 2.0, 3.0], [7.0, 7.0, 7.0], [1.0, 1.0, 1.0])


def test_moments_add_across_any_split_of_the_sample() -> None:
    """What lets the bootstrap resample parishes instead of a hundred thousand hexes."""
    xs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    ys = [2.0, 1.0, 5.0, 4.0, 9.0, 7.0]
    ws = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0]
    cx, cy = st.weighted_mean(xs, ws), st.weighted_mean(ys, ws)

    whole = st.moments_about(xs, ys, ws, centre_x=cx, centre_y=cy)
    split = st.combine(
        [
            st.moments_about(xs[:2], ys[:2], ws[:2], centre_x=cx, centre_y=cy),
            st.moments_about(xs[2:5], ys[2:5], ws[2:5], centre_x=cx, centre_y=cy),
            st.moments_about(xs[5:], ys[5:], ws[5:], centre_x=cx, centre_y=cy),
        ]
    )

    assert st.correlation(split) == pytest.approx(st.correlation(whole))
    assert split.n == whole.n
    assert split.w == pytest.approx(whole.w)


def test_a_negative_weight_is_rejected_rather_than_absorbed() -> None:
    with pytest.raises(ValueError):
        st.moments_about([1.0], [1.0], [-1.0], centre_x=0.0, centre_y=0.0)


# ---- weighted ranks ----------------------------------------------------


def test_unit_weights_without_ties_reproduce_the_hazen_positions() -> None:
    """Migration 0009 ranks indicator percentiles at k - 0.5. So does this."""
    assert st.weighted_ranks([10.0, 30.0, 20.0], [1.0, 1.0, 1.0]) == [0.5, 2.5, 1.5]


def test_ties_sit_at_the_midpoint_of_the_weight_they_share() -> None:
    # The two 5s span weight 0 to 2, midpoint 1. The 9 spans 2 to 4, midpoint 3.
    assert st.weighted_ranks([5.0, 5.0, 9.0], [1.0, 1.0, 2.0]) == [1.0, 1.0, 3.0]


def test_a_heavy_observation_pushes_everything_above_it_up() -> None:
    # Weights 5 then 1: the first spans 0 to 5 (midpoint 2.5), the second 5 to 6
    # (midpoint 5.5).
    assert st.weighted_ranks([1.0, 2.0], [5.0, 1.0]) == [2.5, 5.5]


def test_spearman_sees_a_curved_relationship_that_pearson_discounts() -> None:
    """Why both are reported. The shares are heavily right-skewed."""
    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [1.0, 10.0, 100.0, 1000.0]
    ws = [1.0, 1.0, 1.0, 1.0]

    pearson = correlate(xs, ys, ws)
    spearman = correlate(st.weighted_ranks(xs, ws), st.weighted_ranks(ys, ws), ws)

    assert spearman == pytest.approx(1.0)
    assert pearson < 0.95


# ---- effective sample size and the analytic interval -------------------


def test_equal_weights_make_the_effective_sample_the_real_one() -> None:
    # (4^2) / 4 = 4
    m = st.moments_about(
        [1.0, 2.0, 3.0, 4.0],
        [1.0, 2.0, 3.0, 5.0],
        [1.0, 1.0, 1.0, 1.0],
        centre_x=0.0,
        centre_y=0.0,
    )
    assert st.effective_sample_size(m) == pytest.approx(4.0)


def test_one_dominant_weight_collapses_the_effective_sample() -> None:
    # (3 + 1)^2 / (9 + 1) = 16/10. Two hexes are worth 1.6 observations.
    m = st.moments_about([1.0, 2.0], [1.0, 2.0], [3.0, 1.0], centre_x=0.0, centre_y=0.0)
    assert st.effective_sample_size(m) == pytest.approx(1.6)


def test_the_fisher_interval_around_zero_is_symmetric_and_known() -> None:
    # z = atanh(0) = 0; spread = 1.959964 / sqrt(103 - 3) = 0.1959964.
    low, high = st.fisher_interval(0.0, 103.0)

    assert low == pytest.approx(-math.tanh(1.959963985 / 10.0), rel=1e-6)
    assert high == pytest.approx(math.tanh(1.959963985 / 10.0), rel=1e-6)


def test_a_tiny_effective_sample_has_no_fisher_interval() -> None:
    with pytest.raises(st.NotComputable):
        st.fisher_interval(0.5, 3.0)


def test_the_normal_quantile_hits_the_textbook_values() -> None:
    assert st._normal_quantile(0.5) == pytest.approx(0.0, abs=1e-9)
    assert st._normal_quantile(0.975) == pytest.approx(1.959963985, abs=1e-6)
    assert st._normal_quantile(0.025) == pytest.approx(-1.959963985, abs=1e-6)
    # The far-tail branch, which is a different rational approximation.
    assert st._normal_quantile(0.001) == pytest.approx(-3.090232306, abs=1e-6)


# ---- quantiles and the bootstrap ---------------------------------------


def test_the_median_of_an_even_sample_interpolates() -> None:
    assert st.quantile([1.0, 2.0, 3.0, 4.0], 0.5) == pytest.approx(2.5)


def test_the_endpoints_are_the_endpoints() -> None:
    assert st.quantile([1.0, 2.0, 3.0], 0.0) == 1.0
    assert st.quantile([1.0, 2.0, 3.0], 1.0) == 3.0


Cluster = tuple[list[float], list[float], list[float]]


def clustered(points: list[Cluster]) -> list[st.Moments]:
    xs = [x for cluster in points for x in cluster[0]]
    ys = [y for cluster in points for y in cluster[1]]
    ws = [w for cluster in points for w in cluster[2]]
    cx, cy = st.weighted_mean(xs, ws), st.weighted_mean(ys, ws)
    return [
        st.moments_about(c_xs, c_ys, c_ws, centre_x=cx, centre_y=cy) for c_xs, c_ys, c_ws in points
    ]


def parish_like_clusters() -> list[st.Moments]:
    """Clusters that behave the way parishes do.

    Each has a strong internal trend and its own level, so hexes inside one
    parish look far more alike than hexes drawn from the state at large. That is
    the spatial dependence the cluster bootstrap exists to price in, and it is
    what makes the two intervals below differ.
    """
    offsets = [0.0, 6.0, -6.0, 9.0, -9.0, 3.0]
    points: list[Cluster] = []
    for offset in offsets:
        xs = [float(j) for j in range(30)]
        ys = [0.5 * j + offset + ((j * 7) % 11 - 5) * 0.3 for j in range(30)]
        points.append((xs, ys, [1.0] * 30))
    return clustered(points)


def test_the_bootstrap_is_reproducible_from_its_seed() -> None:
    """CS-204 asks the scoring run to be reproducible. So is the interval on it."""
    clusters = parish_like_clusters()

    first = st.bootstrap_interval(clusters, resamples=200, seed=7)
    second = st.bootstrap_interval(clusters, resamples=200, seed=7)
    different = st.bootstrap_interval(clusters, resamples=200, seed=8)

    assert first == second
    assert first != different


def test_the_bootstrap_interval_brackets_the_point_estimate() -> None:
    clusters = parish_like_clusters()
    point = st.correlation(st.combine(clusters))

    low, high = st.bootstrap_interval(clusters, resamples=400, seed=3)

    assert low <= point <= high


def test_the_cluster_bootstrap_is_wider_than_the_independence_interval() -> None:
    """The whole reason both are reported.

    Hexes in one parish share tracts, facilities and an ACS estimate. Treating
    them as independent draws buys precision the data does not have, and the two
    intervals side by side are what stop that going unnoticed.
    """
    clusters = parish_like_clusters()
    total = st.combine(clusters)
    point = st.correlation(total)

    boot_low, boot_high = st.bootstrap_interval(clusters, resamples=800, seed=11)
    fisher_low, fisher_high = st.fisher_interval(point, st.effective_sample_size(total))

    assert (boot_high - boot_low) > (fisher_high - fisher_low)


def test_one_cluster_cannot_be_bootstrapped() -> None:
    clusters = clustered([([1.0, 2.0, 3.0], [2.0, 1.0, 3.0], [1.0, 1.0, 1.0])])

    with pytest.raises(st.NotComputable):
        st.bootstrap_interval(clusters, resamples=100, seed=1)


# ---- the top-decile contrast -------------------------------------------


def test_group_means_are_population_weighted_on_each_side() -> None:
    # inside: (40*100 + 60*300) / 400 = 22000/400 = 55
    # outside: (10*100 + 20*100) / 200 = 3000/200 = 15
    sums = st.group_sums(
        [40.0, 60.0, 10.0, 20.0],
        [100.0, 300.0, 100.0, 100.0],
        [True, True, False, False],
    )

    inside, outside = st.group_means(sums)

    assert inside == pytest.approx(55.0)
    assert outside == pytest.approx(15.0)


def test_a_contrast_with_an_empty_side_is_not_computable() -> None:
    sums = st.group_sums([40.0, 60.0], [100.0, 300.0], [True, True])

    with pytest.raises(st.NotComputable):
        st.group_means(sums)


def test_group_sums_add_across_clusters() -> None:
    whole = st.group_sums(
        [40.0, 60.0, 10.0, 20.0], [100.0, 300.0, 100.0, 100.0], [True, True, False, False]
    )
    split = st.group_sums([40.0, 60.0], [100.0, 300.0], [True, True]) + st.group_sums(
        [10.0, 20.0], [100.0, 100.0], [False, False]
    )

    assert st.group_means(whole) == pytest.approx(st.group_means(split))


def test_the_contrast_bootstrap_brackets_its_point_estimates() -> None:
    clusters = [
        st.group_sums([50.0, 12.0], [400.0, 900.0], [True, False]),
        st.group_sums([46.0, 15.0], [500.0, 800.0], [True, False]),
        st.group_sums([58.0, 9.0], [300.0, 950.0], [True, False]),
        st.group_sums([41.0, 18.0], [600.0, 700.0], [True, False]),
        st.group_sums([62.0, 11.0], [350.0, 880.0], [True, False]),
    ]
    total = st.GroupSums()
    for cluster in clusters:
        total = total + cluster
    inside, outside = st.group_means(total)

    (d_low, d_high), (r_low, r_high) = st.bootstrap_contrast(clusters, resamples=400, seed=5)

    assert d_low <= inside - outside <= d_high
    assert r_low <= inside / outside <= r_high
