#!/usr/bin/env python3
# Storm Watch archive backtest, one-time manual run.
# Pulls gp_history from Space-Track for a fixed 500-satellite sample
# around 22 geomagnetic storm events (Dec 2025 to Jul 2026) plus
# near-threshold control days, measures fleet decay response,
# and writes derived results only (storm_backtest_results.csv).
# No raw Space-Track data is stored or redistributed.

import os, json, csv, time, statistics
import urllib.request, urllib.parse
import http.cookiejar
from datetime import date, timedelta

BASE = "https://www.space-track.org"
USER = os.environ["SPACETRACK_USER"]
PASSWORD = os.environ["SPACETRACK_PASS"]
EARTH_R = 6378.137
HEAVY_KM_PER_DAY = 2.0
SAMPLE_N = 500
CHUNK = 200
SLEEP_S = 3

EVENTS = [
    ("2025-12-03", "2025-12-04", "G2"),
    ("2025-12-10", "2025-12-12", "G2"),
    ("2026-01-02", "2026-01-02", "G1"),
    ("2026-01-10", "2026-01-11", "G1"),
    ("2026-01-16", "2026-01-17", "G1"),
    ("2026-01-19", "2026-01-22", "G4"),
    ("2026-01-28", "2026-01-28", "G1"),
    ("2026-02-05", "2026-02-05", "G1"),
    ("2026-02-15", "2026-02-16", "G1"),
    ("2026-02-22", "2026-02-22", "G1"),
    ("2026-03-03", "2026-03-03", "G1"),
    ("2026-03-13", "2026-03-14", "G2"),
    ("2026-03-20", "2026-03-23", "G3"),
    ("2026-03-25", "2026-03-25", "G1"),
    ("2026-04-02", "2026-04-03", "G2"),
    ("2026-04-18", "2026-04-20", "G1"),
    ("2026-05-04", "2026-05-04", "G2"),
    ("2026-05-15", "2026-05-16", "G2"),
    ("2026-06-05", "2026-06-05", "G2"),
    ("2026-06-11", "2026-06-11", "G1"),
    ("2026-06-25", "2026-06-25", "G1"),
    ("2026-07-04", "2026-07-04", "G3"),
]

cj = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def http_get(url, data=None, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, data=data)
            with OPENER.open(req, timeout=180) as r:
                return r.read().decode()
        except Exception as e:
            print("  retry %d/%d after error: %s" % (attempt + 1, tries, e), flush=True)
            time.sleep(15 * (attempt + 1))
    raise RuntimeError("failed after retries: " + url[:120])


def st_login():
    data = urllib.parse.urlencode(
        {"identity": USER, "password": PASSWORD}).encode()
    body = http_get(BASE + "/ajaxauth/login", data=data)
    if "Failed" in body or "failed" in body:
        raise RuntimeError("Space-Track login failed, check repository secrets")
    print("Space-Track login OK", flush=True)


def load_cohort():
    with open("history.csv") as f:
        rows = list(csv.reader(f))
    header = [h.strip().lower() for h in rows[0]]
    idx = 0
    for i, h in enumerate(header):
        if "norad" in h:
            idx = i
            break
    ids = set()
    for row in rows[1:]:
        if idx >= len(row):
            continue
        try:
            ids.add(int(float(row[idx])))
        except ValueError:
            continue
    ids = sorted(ids)
    print("history.csv unique ids: %d (column %d: %s)" %
          (len(ids), idx, rows[0][idx]), flush=True)
    if not ids:
        raise RuntimeError("no NORAD ids found in history.csv")
    if len(ids) > SAMPLE_N:
        step = len(ids) / float(SAMPLE_N)
        ids = [ids[int(i * step)] for i in range(SAMPLE_N)]
    return ids


def kp_daily_max(start_s, end_s):
    url = ("https://kp.gfz-potsdam.de/app/json/?start=%sT00:00:00Z"
           "&end=%sT23:59:59Z&index=Kp" % (start_s, end_s))
    data = json.loads(http_get(url))
    out = {}
    for t, v in zip(data.get("datetime", []), data.get("Kp", [])):
        if v is None:
            continue
        d = t[:10]
        out[d] = max(out.get(d, 0.0), float(v))
    return out


def fetch_alts(ids, d0_s, d1_exclusive_s):
    acc = {}
    for i in range(0, len(ids), CHUNK):
        chunk = ids[i:i + CHUNK]
        idstr = ",".join(str(x) for x in chunk)
        url = (BASE + "/basicspacedata/query/class/gp_history"
               + "/NORAD_CAT_ID/" + idstr
               + "/EPOCH/" + d0_s + "--" + d1_exclusive_s
               + "/predicates/NORAD_CAT_ID,EPOCH,SEMIMAJOR_AXIS"
               + "/format/json")
        txt = http_get(url)
        try:
            recs = json.loads(txt)
        except ValueError:
            print("  bad JSON from Space-Track, skipping chunk", flush=True)
            recs = []
        for rec in recs:
            try:
                sma = float(rec["SEMIMAJOR_AXIS"])
                nid = int(rec["NORAD_CAT_ID"])
                day = rec["EPOCH"][:10]
            except (KeyError, TypeError, ValueError):
                continue
            key = (nid, day)
            s = acc.setdefault(key, [0.0, 0])
            s[0] += sma - EARTH_R
            s[1] += 1
        time.sleep(SLEEP_S)
    return dict((k, v[0] / v[1]) for k, v in acc.items())


def day_metrics(alts, ids, d):
    ds = d.isoformat()
    dn = (d + timedelta(days=1)).isoformat()
    losses = []
    for nid in ids:
        a0 = alts.get((nid, ds))
        a1 = alts.get((nid, dn))
        if a0 is None or a1 is None:
            continue
        losses.append(a0 - a1)
    if not losses:
        return None
    heavy = sum(1 for x in losses if x > HEAVY_KM_PER_DAY)
    return heavy, statistics.median(losses), len(losses)


def measure(ids, kp, start_s, end_s, kind, level):
    start = date.fromisoformat(start_s)
    end = date.fromisoformat(end_s)
    d0 = start - timedelta(days=4)
    d1x = end + timedelta(days=3)
    print("window %s %s..%s" % (kind, start_s, end_s), flush=True)
    alts = fetch_alts(ids, d0.isoformat(), d1x.isoformat())
    cohort_n = len(set(k[0] for k in alts))
    base_days = [start - timedelta(days=k) for k in (3, 2, 1)]
    resp_days = []
    d = start
    while d <= end + timedelta(days=1):
        resp_days.append(d)
        d += timedelta(days=1)
    base = [m for m in (day_metrics(alts, ids, x) for x in base_days) if m]
    resp = [m for m in (day_metrics(alts, ids, x) for x in resp_days) if m]
    if not base or not resp:
        print("  insufficient data, row marked no-data", flush=True)
        return [kind, start_s, end_s, level, cohort_n,
                "", "", "", "", "", "", "no-data"]
    base_heavy = sum(m[0] for m in base) / float(len(base))
    base_med = statistics.median([m[1] for m in base])
    peak_heavy = max(m[0] for m in resp)
    peak_med = max(m[1] for m in resp)
    ratio = peak_heavy / max(base_heavy, 1.0)
    base_kp = max(kp.get(x.isoformat(), 0.0) for x in base_days)
    ev_kp = max(kp.get(x.isoformat(), 0.0) for x in resp_days)
    return [kind, start_s, end_s, level, cohort_n,
            round(ev_kp, 2), round(base_kp, 2),
            round(base_heavy, 1), peak_heavy, round(ratio, 2),
            round(base_med, 3), round(peak_med, 3)]


def main():
    ids = load_cohort()
    print("cohort sample: %d satellites" % len(ids), flush=True)
    kp = kp_daily_max("2025-11-25", "2026-07-05")
    storm_days = set()
    for s, e, _ in EVENTS:
        d = date.fromisoformat(s)
        while d <= date.fromisoformat(e):
            storm_days.add(d)
            d += timedelta(days=1)
    controls = []
    for ds, v in sorted(kp.items()):
        if not (4.5 <= v < 5.0):
            continue
        d = date.fromisoformat(ds)
        near = any(abs((d - sd).days) <= 1 for sd in storm_days)
        if not near:
            controls.append(ds)
    controls = controls[:11]
    print("control days: %s" % ", ".join(controls), flush=True)
    st_login()
    header = ["type", "start", "end", "level", "cohort_n",
              "kp_max", "baseline_kp_max",
              "baseline_heavy_mean", "peak_heavy", "heavy_ratio",
              "baseline_median_loss_km", "peak_median_loss_km"]
    rows = []
    for s, e, lvl in EVENTS:
        rows.append(measure(ids, kp, s, e, "storm", lvl))
    for ds in controls:
        rows.append(measure(ids, kp, ds, ds, "control", "near"))
    with open("storm_backtest_results.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    ctrl_ratios = [r[9] for r in rows
                   if r[0] == "control" and isinstance(r[9], float)]
    storm_ratios = [(r[1], r[3], r[9]) for r in rows
                    if r[0] == "storm" and isinstance(r[9], float)]
    print("", flush=True)
    print("==== SUMMARY (controls-only threshold) ====", flush=True)
    if ctrl_ratios:
        thr = max(ctrl_ratios)
        hits = [x for x in storm_ratios if x[2] > thr]
        print("worst control heavy_ratio: %.2f" % thr, flush=True)
        print("storms above threshold: %d / %d measurable"
              % (len(hits), len(storm_ratios)), flush=True)
        for s, lvl, r in storm_ratios:
            mark = "HIT " if r > thr else "miss"
            print("  %s  %s  %s ratio %.2f" % (mark, s, lvl, r), flush=True)
    else:
        print("no measurable control days, report raw table only", flush=True)
    print("done, results in storm_backtest_results.csv", flush=True)


if __name__ == "__main__":
    main()
