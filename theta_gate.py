#!/usr/bin/env python3
"""
theta_gate.py

Theta GATE, run 01. Starlink Fleet Radar.

The radar answers one question: when will a satellite come down.
This script answers a second one: is the warning early enough to act on.

A warning has no value on its own. It has a value per owner, because the
owner is what sets the response window W, the total time needed to decide
and then to act. The usable part of a warning is what is left after W.

    L_act = L_det - W          usable lead time
    Gamma = L_act / L_det      fraction of the warning that is usable

W is not known for any real fleet operator and is not invented here. It is
swept across its full range and the result is reported as a curve.

Input:  starlink_amber_v2_results.csv, in this repository.
        21 archived Starlink deorbits, detections calibrated on controls only.
        lead_v1 = single threshold, lead_v2 = dual amber/red threshold.

Output: theta_gate_run01.csv, the survival curve, written next to this file.

No dependencies beyond the standard library.

Oren A. L. Speiser, Theta WATCH. CC BY 4.0.
Paper series: https://orcid.org/0009-0001-1205-4079
"""

import csv
import os
import sys

CSV_NAME = "starlink_amber_v2_results.csv"
OUT_NAME = "theta_gate_run01.csv"

# Response windows to report, in days.
WINDOWS = [0, 7, 14, 21, 30, 45, 60, 66, 90, 105, 120, 150, 167, 180, 210, 240, 250]

# Sample floor from the pre-registered kill criteria. Below this, no Gamma
# is reported for an instrument. See K5 in the definition document.
MIN_EVENTS = 10


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def load_leads(path):
    """Return (lead_v1, lead_v2) as lists of ints, one entry per event."""
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SystemExit("no rows in %s" % path)
    for col in ("lead_v1", "lead_v2"):
        if col not in rows[0]:
            raise SystemExit("column %s missing from %s" % (col, path))
    return ([int(r["lead_v1"]) for r in rows],
            [int(r["lead_v2"]) for r in rows])


def survivors(leads, w):
    """How many events keep a strictly positive usable lead at window w."""
    return sum(1 for L in leads if L - w > 0)


def gamma_median(leads, w):
    """Median usable fraction of the warning at window w, clipped at zero."""
    return median([max(0.0, (L - w)) / L for L in leads])


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, CSV_NAME)
    if not os.path.exists(path):
        raise SystemExit("cannot find %s next to this script" % CSV_NAME)

    v1, v2 = load_leads(path)
    n = len(v2)

    print("Theta GATE, run 01, Starlink Fleet Radar")
    print("source: %s" % CSV_NAME)
    print("events: %d" % n)
    if n < MIN_EVENTS:
        print("below the sample floor of %d. No Gamma reported." % MIN_EVENTS)
        return
    print()
    print("lead time, days      median   min   max")
    print("  single threshold  %7s %5d %5d" % (median(v1), min(v1), max(v1)))
    print("  dual threshold    %7s %5d %5d" % (median(v2), min(v2), max(v2)))
    print()

    header = ["window_days", "survivors_v2", "pct_v2", "gamma_v2",
              "survivors_v1", "pct_v1", "gamma_v1"]
    rows = []
    for w in WINDOWS:
        s2, s1 = survivors(v2, w), survivors(v1, w)
        rows.append([w,
                     s2, round(100.0 * s2 / n, 1), round(gamma_median(v2, w), 3),
                     s1, round(100.0 * s1 / n, 1), round(gamma_median(v1, w), 3)])

    print("response window W is swept, not assumed.")
    print("survivors = events whose warning still has usable time left at W.")
    print()
    print("   W    dual        Gamma    single      Gamma")
    for w, s2, p2, g2, s1, p1, g1 in rows:
        print("%4d  %3d/%d %5.1f%%  %5.2f   %3d/%d %5.1f%%  %5.2f"
              % (w, s2, n, p2, g2, s1, n, p1, g1))

    out = os.path.join(here, OUT_NAME)
    with open(out, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    print()
    print("written: %s" % OUT_NAME)

    # The one anchor that is not swept. SpaceX states in its public
    # sustainability document that a controlled deorbit is a staged lowering
    # taking about six months. That is the fleet operator's action time.
    w = 180
    s2 = survivors(v2, w)
    print()
    print("anchored case, fleet operator.")
    print("  SpaceX states a controlled deorbit runs about six months.")
    print("  At W = %d days, and assuming zero decision time, %d of %d clear."
          % (w, s2, n))
    print("  The median warning is shorter than the action it would trigger.")
    print()
    print("  A third party doing conjunction planning acts in days, not months.")
    print("  At W = 14 days, %d of %d clear." % (survivors(v2, 14), n))
    print()
    print("  Same warnings. The value is set by who holds the decision.")


if __name__ == "__main__":
    sys.exit(main())
