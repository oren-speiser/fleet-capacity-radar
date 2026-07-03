#!/usr/bin/env python3
# Fleet Capacity Radar - daily journal updater
# Fetches fresh public TLEs, maintains a rolling altitude history,
# applies the validated two-tier detector (red / amber) once enough
# self-logged history exists, and verifies reentries of open predictions.
# Stdlib only. Safe-exit on any fetch failure so the workflow never breaks.

import csv, math, sys, os, datetime, urllib.request

TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=tle"
HIST = "history.csv"
PRED = "predictions.csv"
TODAY = datetime.date.today().isoformat()
KEEP_DAYS = 45
RED_RATE, RED_RUN = 2.904, 5      # km/day sustained, consecutive days (frozen v1)
AMB_RATE, AMB_RUN = 0.05, 24      # km/day sustained, consecutive days (validated v2)

def fetch():
    try:
        req = urllib.request.Request(TLE_URL, headers={"User-Agent": "fleet-capacity-radar-journal"})
        raw = urllib.request.urlopen(req, timeout=90).read().decode()
    except Exception as e:
        print("fetch failed, skipping today:", e); sys.exit(0)
    lines = raw.splitlines(); out = {}
    for i in range(0, len(lines) - 2, 3):
        name, l1, l2 = lines[i].strip(), lines[i+1], lines[i+2]
        if not l1.startswith("1 "): continue
        try:
            norad = int(l1[2:7]); ndot = float(l1[33:43]); mm = float(l2[52:63])
            n = mm * 2 * math.pi / 86400; a = (398600.4418 / n**2) ** (1/3)
            alt = a - 6371.0
            da = (2.0/3.0) * (a/mm) * (ndot*2)   # km/day loss estimate
            out[norad] = (name.replace("STARLINK-", "SL-"), round(alt,1), round(da,2))
        except Exception:
            continue
    if len(out) < 1000:
        print("suspiciously small catalog, skipping"); sys.exit(0)
    return out

def load_hist():
    h = {}
    if os.path.exists(HIST):
        for r in csv.DictReader(open(HIST)):
            h.setdefault(int(r["norad"]), {})[r["date"]] = float(r["alt"])
    return h

def save_hist(h):
    cutoff = (datetime.date.today() - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    with open(HIST, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "norad", "alt"])
        for norad in sorted(h):
            for d in sorted(h[norad]):
                if d >= cutoff:
                    w.writerow([d, norad, h[norad][d]])

def load_pred():
    rows = list(csv.DictReader(open(PRED))) if os.path.exists(PRED) else []
    return rows

def save_pred(rows):
    cols = ["flag_date","norad","name","alt_at_flag","decay_kmday_at_flag","tier","status","reentry_date","lead_days"]
    with open(PRED, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow({c: r.get(c, "") for c in cols})

def sustained(h_sat, rate, run):
    # True if 7-day net drift < -rate on `run` consecutive calendar days ending today
    d0 = datetime.date.today()
    for k in range(run):
        d = (d0 - datetime.timedelta(days=k)).isoformat()
        d7 = (d0 - datetime.timedelta(days=k+7)).isoformat()
        if d not in h_sat or d7 not in h_sat: return False
        if (h_sat[d] - h_sat[d7]) / 7.0 > -rate: return False
    return True

def main():
    sats = fetch()
    hist = load_hist()
    # append today for tracked set + anything already in history or journal
    pred = load_pred()
    watched = {int(r["norad"]) for r in pred if r["status"] == "open"}
    for norad, (name, alt, da) in sats.items():
        if alt < 460 or da > 0.5 or norad in hist or norad in watched:
            hist.setdefault(norad, {})[TODAY] = alt
    # detector flags on self-logged history
    known = {int(r["norad"]) for r in pred}
    for norad, h_sat in hist.items():
        if norad in known or norad not in sats: continue
        name, alt, da = sats[norad]
        tier = None
        if sustained(h_sat, RED_RATE, RED_RUN): tier = "red"
        elif sustained(h_sat, AMB_RATE, AMB_RUN): tier = "amber"
        if tier:
            pred.append(dict(flag_date=TODAY, norad=norad, name=name, alt_at_flag=alt,
                             decay_kmday_at_flag=da, tier=tier, status="open",
                             reentry_date="", lead_days=""))
    # verify reentries: open prediction, absent from today's catalog, last seen low
    for r in pred:
        if r["status"] != "open": continue
        norad = int(r["norad"])
        if norad not in sats:
            h_sat = hist.get(norad, {})
            if h_sat:
                last_alt = h_sat[max(h_sat)]
                if last_alt < 300:
                    r["status"] = "reentered"; r["reentry_date"] = TODAY
                    r["lead_days"] = (datetime.date.fromisoformat(TODAY) -
                                      datetime.date.fromisoformat(r["flag_date"])).days
    save_hist(hist); save_pred(pred)
    op = sum(1 for r in pred if r["status"] == "open")
    ver = sum(1 for r in pred if r["status"] == "reentered")
    print(f"journal: {op} open, {ver} verified reentries")

if __name__ == "__main__":
    main()
