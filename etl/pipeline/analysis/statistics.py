"""Population-weighted correlation, and honest intervals around it.

Split out from `disparity` for the reason `pipeline.dasymetric.weights` is split
out from `pipeline.dasymetric.postgis`: every number the headline finding rests
on should be reachable by a unit test that hand-computes it, without a database
anywhere near the assertion.

**Weighting.** Every statistic here is weighted by hex population. Hexes are
equal-area, so an unweighted correlation would answer "does a randomly chosen
square kilometre of Louisiana with a high score tend to be Black?", and the claim
the project actually makes is about people. Unweighted, a cell holding thirty
people and a cell holding twelve thousand count the same.

**Sufficient statistics, not resampled rows.** A weighted Pearson coefficient is
recoverable from six sums, and each of those sums is additive over any partition
of the sample. So the cluster bootstrap below resamples parish-level `Moments`
rather than hexes: two thousand resamples cost two thousand passes over sixty-odd
parishes instead of two thousand passes over a hundred and eighty thousand hexes.
The result is identical, which the tests check directly against a resampling of
the underlying rows.

**Centred before accumulating.** `moments_about` subtracts the full-sample
weighted means before squaring, so the accumulated sums stay small relative to
the weights. Accumulating raw products and subtracting the mean at the end is
the textbook way to lose most of the significant digits of a correlation taken
over a hundred thousand rows.
"""

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

#: The level everything here defaults to.
DEFAULT_LEVEL = 0.95

#: Enough resamples that the interval endpoints are stable to about three
#: decimal places, which is more precision than the finding is reported to.
DEFAULT_RESAMPLES = 2000

#: Fixed so two runs over the same rows produce the same interval. CS-204 asks
#: the scoring run to be reproducible; an interval that moved every night would
#: undo that for the one number the project leads with.
DEFAULT_SEED = 20260911


class NotComputable(Exception):
    """A statistic that has no value on the sample it was handed.

    Raised rather than returned as a sentinel because every caller in this
    package turns it into a reported reason, and a `None` that means four
    different things is how a report ends up saying nothing.
    """


@dataclass(frozen=True)
class Moments:
    """Weighted sums over one cluster, sufficient for a Pearson coefficient.

    `x` and `y` are already centred on the full-sample weighted means, so `sx`
    and `sy` are deviations rather than totals and are near zero for a typical
    cluster. `ww` is carried for Kish's effective sample size, which needs the
    sum of squared weights and cannot be recovered from the rest.
    """

    n: int = 0
    w: float = 0.0
    ww: float = 0.0
    sx: float = 0.0
    sy: float = 0.0
    sxx: float = 0.0
    syy: float = 0.0
    sxy: float = 0.0

    def __add__(self, other: "Moments") -> "Moments":
        return Moments(
            n=self.n + other.n,
            w=self.w + other.w,
            ww=self.ww + other.ww,
            sx=self.sx + other.sx,
            sy=self.sy + other.sy,
            sxx=self.sxx + other.sxx,
            syy=self.syy + other.syy,
            sxy=self.sxy + other.sxy,
        )


def combine(parts: Sequence[Moments]) -> Moments:
    total = Moments()
    for part in parts:
        total = total + part
    return total


def weighted_mean(values: Sequence[float], weights: Sequence[float]) -> float:
    if len(values) != len(weights):
        raise ValueError("values and weights must be the same length")
    total = math.fsum(weights)
    if total <= 0:
        raise NotComputable("total weight is zero")
    return math.fsum(v * w for v, w in zip(values, weights, strict=True)) / total


def moments_about(
    xs: Sequence[float],
    ys: Sequence[float],
    weights: Sequence[float],
    *,
    centre_x: float,
    centre_y: float,
) -> Moments:
    """Accumulate one cluster's contribution, centred on the full-sample means."""
    if not (len(xs) == len(ys) == len(weights)):
        raise ValueError("xs, ys and weights must be the same length")
    n = 0
    w = ww = sx = sy = sxx = syy = sxy = 0.0
    for x_raw, y_raw, weight in zip(xs, ys, weights, strict=True):
        if weight < 0:
            raise ValueError("weights must not be negative")
        x = x_raw - centre_x
        y = y_raw - centre_y
        n += 1
        w += weight
        ww += weight * weight
        sx += weight * x
        sy += weight * y
        sxx += weight * x * x
        syy += weight * y * y
        sxy += weight * x * y
    return Moments(n=n, w=w, ww=ww, sx=sx, sy=sy, sxx=sxx, syy=syy, sxy=sxy)


def correlation(m: Moments) -> float:
    """Weighted Pearson coefficient from accumulated moments.

    The variance terms correct for the sample's own weighted mean, which is why
    the moments carry `sx` and `sy` even though those are zero over the full
    sample by construction: a bootstrap resample of clusters has its own mean and
    it is not the full-sample one.
    """
    if m.w <= 0:
        raise NotComputable("total weight is zero")
    var_x = m.sxx - (m.sx * m.sx) / m.w
    var_y = m.syy - (m.sy * m.sy) / m.w
    if var_x <= 0 or var_y <= 0:
        raise NotComputable("one variable has no weighted variance on this sample")
    covariance = m.sxy - (m.sx * m.sy) / m.w
    r = covariance / math.sqrt(var_x * var_y)
    # Floating point can carry a perfectly correlated sample a few ulps outside
    # the range, and atanh of 1.0000000000000002 is a domain error.
    return max(-1.0, min(1.0, r))


def weighted_ranks(values: Sequence[float], weights: Sequence[float]) -> list[float]:
    """Rank each value by the weighted empirical distribution, ties at the midpoint.

    For a value v the rank is the weight strictly below v plus half the weight
    tied at v. With unit weights and no ties this is exactly the Hazen position
    `k - 0.5` that migration 0009 uses for indicator percentiles, which is not a
    coincidence: the tie rule governing the ranking the disparity analysis does
    should be the tie rule that governed the ranking the score was built from.

    Weighted rather than ordinary ranks so that Spearman answers the same
    question as Pearson here. Ranking hexes without weights and then weighting
    the correlation would mix a per-cell ranking into a per-person statistic.
    """
    if len(values) != len(weights):
        raise ValueError("values and weights must be the same length")
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    cumulative = 0.0
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        tied = order[position : end + 1]
        tied_weight = math.fsum(weights[i] for i in tied)
        midpoint = cumulative + tied_weight / 2.0
        for i in tied:
            ranks[i] = midpoint
        cumulative += tied_weight
        position = end + 1
    return ranks


def effective_sample_size(m: Moments) -> float:
    """Kish's effective sample size, `(sum w)^2 / sum w^2`.

    The count of hexes overstates how much independent information a weighted
    sample carries, because a handful of dense urban cells hold most of the
    weight. This is the number the analytic interval is computed against, and it
    is reported next to the hex count so the gap between them stays visible.
    """
    if m.ww <= 0:
        raise NotComputable("total squared weight is zero")
    return (m.w * m.w) / m.ww


def fisher_interval(
    r: float, n_effective: float, *, level: float = DEFAULT_LEVEL
) -> tuple[float, float]:
    """Fisher z interval: the interval that assumes hexes are independent.

    Reported only as a comparison. Neighbouring hexes share tracts, share
    facilities and share an ACS estimate, so this interval is narrower than the
    truth by a margin the cluster bootstrap exists to expose. Publishing it alone
    would overstate the precision of the finding.
    """
    if n_effective <= 3:
        raise NotComputable("effective sample size is too small for a Fisher interval")
    if abs(r) >= 1.0:
        raise NotComputable("a perfect correlation has no Fisher interval")
    z = math.atanh(r)
    spread = _normal_quantile(0.5 + level / 2.0) / math.sqrt(n_effective - 3.0)
    return math.tanh(z - spread), math.tanh(z + spread)


def bootstrap_interval(
    clusters: Sequence[Moments],
    *,
    level: float = DEFAULT_LEVEL,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> tuple[float, float]:
    """Percentile interval from resampling whole clusters with replacement.

    Clusters are parishes. Hexes inside one are not independent draws: they share
    the tract-level ACS estimates that section 7 spread across them, and they
    share the facilities that drive the proximity indicators. Resampling hexes
    would treat that shared structure as independent evidence and return an
    interval far too narrow. Resampling parishes keeps the dependence inside the
    unit being resampled, which is the standard remedy and the honest one here.
    """
    if len(clusters) < 2:
        raise NotComputable("a cluster bootstrap needs at least two clusters")
    if resamples < 1:
        raise ValueError("resamples must be positive")
    rng = random.Random(seed)
    size = len(clusters)
    draws: list[float] = []
    for _ in range(resamples):
        picked = combine([clusters[rng.randrange(size)] for _ in range(size)])
        try:
            draws.append(correlation(picked))
        except NotComputable:
            # A resample that drew one parish repeatedly can have no variance in
            # a share. Dropping it is right: it carries no information about the
            # coefficient, and substituting a zero would drag the interval toward
            # the middle.
            continue
    if len(draws) < resamples // 2:
        raise NotComputable("too few usable bootstrap resamples")
    draws.sort()
    tail = (1.0 - level) / 2.0
    return quantile(draws, tail), quantile(draws, 1.0 - tail)


def quantile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolated quantile of an already sorted sequence."""
    if not sorted_values:
        raise NotComputable("no values to take a quantile of")
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must be between 0 and 1")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = q * (len(sorted_values) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return sorted_values[low]
    return sorted_values[low] + (position - low) * (sorted_values[high] - sorted_values[low])


@dataclass(frozen=True)
class GroupSums:
    """Weight and weighted share total for a cluster, split by group membership.

    The contrast the public site leads with is a difference of two
    population-weighted means, and like the correlation it is additive over
    clusters, so the same parish bootstrap applies to it unchanged.
    """

    weight_in: float = 0.0
    share_in: float = 0.0
    weight_out: float = 0.0
    share_out: float = 0.0

    def __add__(self, other: "GroupSums") -> "GroupSums":
        return GroupSums(
            weight_in=self.weight_in + other.weight_in,
            share_in=self.share_in + other.share_in,
            weight_out=self.weight_out + other.weight_out,
            share_out=self.share_out + other.share_out,
        )


def group_sums(
    shares: Sequence[float], weights: Sequence[float], inside: Sequence[bool]
) -> GroupSums:
    if not (len(shares) == len(weights) == len(inside)):
        raise ValueError("shares, weights and membership must be the same length")
    w_in = s_in = w_out = s_out = 0.0
    for share, weight, member in zip(shares, weights, inside, strict=True):
        if weight < 0:
            raise ValueError("weights must not be negative")
        if member:
            w_in += weight
            s_in += weight * share
        else:
            w_out += weight
            s_out += weight * share
    return GroupSums(weight_in=w_in, share_in=s_in, weight_out=w_out, share_out=s_out)


def group_means(sums: GroupSums) -> tuple[float, float]:
    """Population-weighted mean share inside the group, and outside it."""
    if sums.weight_in <= 0 or sums.weight_out <= 0:
        raise NotComputable("one side of the contrast holds no population")
    return sums.share_in / sums.weight_in, sums.share_out / sums.weight_out


def bootstrap_contrast(
    clusters: Sequence[GroupSums],
    *,
    level: float = DEFAULT_LEVEL,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Parish bootstrap interval for the difference and the ratio of the two means."""
    if len(clusters) < 2:
        raise NotComputable("a cluster bootstrap needs at least two clusters")
    if resamples < 1:
        raise ValueError("resamples must be positive")
    rng = random.Random(seed)
    size = len(clusters)
    differences: list[float] = []
    ratios: list[float] = []
    for _ in range(resamples):
        picked = GroupSums()
        for _ in range(size):
            picked = picked + clusters[rng.randrange(size)]
        try:
            inside, outside = group_means(picked)
        except NotComputable:
            continue
        differences.append(inside - outside)
        if outside > 0:
            ratios.append(inside / outside)
    if len(differences) < resamples // 2 or len(ratios) < resamples // 2:
        raise NotComputable("too few usable bootstrap resamples")
    differences.sort()
    ratios.sort()
    tail = (1.0 - level) / 2.0
    return (
        (quantile(differences, tail), quantile(differences, 1.0 - tail)),
        (quantile(ratios, tail), quantile(ratios, 1.0 - tail)),
    )


def _normal_quantile(p: float) -> float:
    """Inverse standard normal CDF, Acklam's rational approximation.

    Hand-rolled because the package depends on neither scipy nor numpy and
    should not acquire either for one number. Accurate to about 1e-9 across the
    range, far beyond what a interval endpoint is reported to.
    """
    if not 0.0 < p < 1.0:
        raise ValueError("p must be strictly between 0 and 1")
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )
    low, high = 0.02425, 1 - 0.02425
    if p < low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p > high:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )
