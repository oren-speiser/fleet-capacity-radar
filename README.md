# Fleet Capacity Radar: Starlink

An independent, public-data monitor of orbit-maintenance capacity across the Starlink fleet, with a validated early-warning layer. Live page: open `index.html`, or the GitHub Pages deployment of this repository.

Not affiliated with SpaceX. Built from public data only.

## What it shows

Every satellite holds altitude only while its orbit-maintenance capacity exceeds atmospheric drag injection. This is the same stability ratio, Theta = injection over capacity, that this portfolio's other instruments apply to hydraulic rigs, Li-ion cells, bearings and gear run-to-fail data. The board reads that state for 10,713 tracked Starlink objects from a public CelesTrak GP snapshot: operational, transit, elevated stress, decaying, terminal.

## Validated early warning

A latched exhaustion detector was calibrated on 10 healthy Starlink satellites only (13 months of archived orbital histories), then applied unchanged to 21 real deorbits spanning December 2025 to June 2026, three per month, 28,825 archived element sets in total.

Results:

- Detected: 21 of 21 deorbits
- False alarms: 0 of 10 healthy satellites over 13 months, including one real 1.9 km/day maneuver episode absorbed without alarm
- Warning before atmospheric burn-up: median 49 days, minimum 6, maximum 243
- The alarm preceded the terminal plunge onset in all 21 cases

Alarm rule: sustained altitude loss above 2.9 km/day for 5 consecutive days, latched. The threshold was derived from the healthy cohort alone and never tuned on the deorbits it was scored against. Per-satellite results: `starlink_earlywarning_results.csv`. Validation figure: `starlink_earlywarning_validation.png`.

## Honest scope and limitations

Most Starlink reentries are controlled descents initiated by the operator, not surprise failures. The validated claim is therefore: robust, false-alarm-free detection of sustained loss of altitude-hold across the whole fleet, with a measured runway to burn-up, using one uncalibrated-per-satellite rule. It is not a claim of predicting unexpected failures. A documented weakness: on old satellites descending slowly below the conservative threshold, the alarm arrives late relative to the start of their descent (6 to 10 days before reentry in the worst cases); a two-tier threshold is the planned v2 refinement, to be recalibrated on controls only.

## Data and reproduction

Fleet snapshot: CelesTrak GP data (public). Historical element sets: Space-Track gp_history for 21 decayed satellites (selected from the public decay catalog, three per month) and 10 operational controls, epoch window June 2025 to July 2026. Raw element sets are not redistributed here, in line with the Space-Track user agreement; the derived per-satellite results are published in full. Detector internals are not exposed.


## Author

Oren A. L. Speiser · ORCID 0009-0001-1205-4079 · Portfolio hub: https://oren-speiser.github.io/stability-diagnostics/

License: MIT (code and page). Derived result files may be reused with attribution.

