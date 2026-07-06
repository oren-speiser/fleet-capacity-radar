#!/usr/bin/env python3
# Fleet Capacity Radar - daily updater
# 1) Fetches fresh public TLEs (CelesTrak GP).
# 2) Refreshes the live board in index.html (epoch, tracked count, per-object states).
# 3) Maintains a rolling altitude history and applies the validated two-tier
#    detector (red / amber) once enough self-logged history exists.
# 4) Verifies reentries of open predictions.
# Stdlib only. Safe-exit on any fetch failure so the workflow never breaks.

import csv, math, sys, os, re, json, datetime, urllib.request

TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=tle"
HIST = "history.csv"
PRED = "predictions.csv"
BOARD = "index.html"
STORM = "storm_log.csv"
KP_API = "https://kp.gfz-potsdam.de/app/json/?start={s}T00:00:00Z&end={e}T23:59:59Z&index=Kp"
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



# ---------- STORM WATCH (module inside the radar; safe-fail, never breaks the board) ----------

def gscale(k):
    if k >= 9: return "G5"
    if k >= 8: return "G4"
    if k >= 7: return "G3"
    if k >= 6: return "G2"
    if k >= 5: return "G1"
    return "quiet"

def fetch_kp():
    # Official planetary Kp from GFZ Potsdam, last 12 days. Returns {date: max_kp} or None.
    try:
        d0 = datetime.date.today()
        url = KP_API.format(s=(d0 - datetime.timedelta(days=12)).isoformat(), e=d0.isoformat())
        req = urllib.request.Request(url, headers={"User-Agent": "fleet-capacity-radar-stormwatch"})
        data = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
        daily = {}
        for t, k in zip(data.get("datetime", []), data.get("Kp", [])):
            if k is None: continue
            day = t[:10]
            if k > daily.get(day, -1): daily[day] = k
        return daily or None
    except Exception as e:
        print("storm: kp fetch failed, section skipped:", e)
        return None

def storm_metrics(hist, day_iso):
    # Day-over-day altitude loss across the self-logged cohort for `day_iso`.
    prev = (datetime.date.fromisoformat(day_iso) - datetime.timedelta(days=1)).isoformat()
    losses = []
    for h_sat in hist.values():
        if day_iso in h_sat and prev in h_sat:
            losses.append(h_sat[prev] - h_sat[day_iso])
    if len(losses) < 300: return None
    losses.sort()
    med = losses[len(losses)//2]
    heavy = sum(1 for x in losses if x >= 2.0)
    return {"pairs": len(losses), "median": round(med, 2), "heavy": heavy}

def update_storm(hist):
    kp_daily = fetch_kp()
    if not kp_daily: return None
    d0 = datetime.date.today().isoformat()
    d1 = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    m0 = storm_metrics(hist, d0)
    # refresh today's row in storm_log.csv (idempotent per date)
    rows = {}
    if os.path.exists(STORM):
        for r in csv.DictReader(open(STORM)):
            rows[r["date"]] = r
    kp0 = kp_daily.get(d0)
    rows[d0] = {"date": d0,
                "max_kp": "" if kp0 is None else round(kp0, 2),
                "gscale": "" if kp0 is None else gscale(kp0),
                "pairs": m0["pairs"] if m0 else "",
                "heavy_gt2kmday": m0["heavy"] if m0 else "",
                "median_loss_kmday": m0["median"] if m0 else ""}
    cols = ["date", "max_kp", "gscale", "pairs", "heavy_gt2kmday", "median_loss_kmday"]
    with open(STORM, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for day in sorted(rows): w.writerow({c: rows[day].get(c, "") for c in cols})
    # yesterday's heavy count for the day-over-day comparison in the section
    prev_heavy = rows.get(d1, {}).get("heavy_gt2kmday", "")
    return {"today": d0, "kp0": kp0, "kp1": kp_daily.get(d1),
            "m0": m0, "prev_heavy": prev_heavy}

def update_storm_section(s):
    if not s: return
    html = open(BOARD, encoding="utf-8").read()
    kp0 = "n/a" if s["kp0"] is None else f"{s['kp0']:.1f} ({gscale(s['kp0'])})"
    kp1 = "n/a" if s["kp1"] is None else f"{s['kp1']:.1f} ({gscale(s['kp1'])})"
    if s["m0"]:
        prev = f" vs {s['prev_heavy']} the day before" if s["prev_heavy"] != "" else ""
        resp = (f"HEAVY DECAY (&gt;2 km/day) <b style=\"color:#FFB454\">{s['m0']['heavy']}</b>{prev}"
                f" \u00b7 MEDIAN DAILY LOSS <b>{s['m0']['median']:+.2f} km</b>"
                f" \u00b7 cohort {s['m0']['pairs']:,} day-pairs")
    else:
        resp = "fleet response: accruing (needs two logged days)"
    block = ("<!--STORMWATCH-->\n"
             "<h2>Storm watch</h2>\n"
             "<div class=\"cap\" style=\"max-width:900px\">Geomagnetic storms inflate the upper atmosphere and raise drag on the whole fleet at once: an external injection spike hitting every satellite simultaneously. This section reads the official planetary Kp index (GFZ Potsdam) next to the fleet's own day-over-day decay response from the self-logged history. Storm-to-drag physics is textbook. Full record: storm_log.csv in this repository, updated daily.</div>\n"
             f"<div class=\"meta\">KP TODAY <b>{kp0}</b> \u00b7 KP YESTERDAY <b>{kp1}</b> \u00b7 {resp}</div>\n"
             "<div class=\"meta\">ARCHIVE BACKTEST (Jul 2026): 22 storms, Dec 2025 to Jul 2026, controls-only threshold, same two decay metrics as the live module. Every storm of class G2 or stronger flagged: <b style=\"color:#7FE08A\">10/10</b> \u00b7 weakest class G1: 5/12 \u00b7 quiet-day controls flagged: <b>0/6</b>. Fixed 500-satellite sample of the current tracking cohort; survivor-bias and methodology notes in storm_backtest_results.csv in this repository.</div>\n"
             "<!--/STORMWATCH-->")
    if "<!--STORMWATCH-->" in html:
        html2, n = re.subn(r"<!--STORMWATCH-->.*?<!--/STORMWATCH-->", lambda m: block, html, count=1, flags=re.S)
    else:
        anchor = "<h2>Prediction journal</h2>"
        html2, n = (html.replace(anchor, block + "\n" + anchor, 1), 1) if anchor in html else (html, 0)
    if n == 1:
        open(BOARD, "w", encoding="utf-8").write(html2)
        print(f"storm: section updated, kp today {kp0}, kp yesterday {kp1}")
    else:
        print("storm: anchor not found, section skipped")

STATE_NAMES = ["OPERATIONAL", "TRANSIT", "ELEVATED", "DECAYING", "TERMINAL"]

def board_state(alt, da):
    # Snapshot-state rule, reverse-engineered from the 2026-07-02 board and
    # verified to reproduce it exactly (0 mismatches on 10,713 objects).
    if alt < 250 or da >= 10: return 4                          # TERMINAL
    if alt >= 470: return 2 if da >= 0.5 else 0                 # ELEVATED / OPERATIONAL
    if da >= 1.5 or (alt < 300 and abs(da) >= 1.5): return 3    # DECAYING
    return 1                                                    # TRANSIT

def update_board(sats):
    # Rewrites the embedded snapshot (epoch, tracked count, states, rows)
    # inside index.html. Skips safely if the anchors are not found.
    html = open(BOARD, encoding="utf-8").read()
    states = {s: 0 for s in STATE_NAMES}
    rows = []
    for norad in sorted(sats):
        name, alt, da = sats[norad]
        code = board_state(alt, da)
        states[STATE_NAMES[code]] += 1
        rows.append([name, alt, da, code])
    d = {"epoch": TODAY, "states": states, "rows": rows}
    blob = "const D=" + json.dumps(d, separators=(",", ":")) + ";"
    html, n1 = re.subn(r"const D=\{.*?\};", lambda m: blob, html, count=1, flags=re.S)
    meta = f"EPOCH <b>{TODAY}</b> \u00b7 TRACKED <b>{len(sats):,}</b>"
    html, n2 = re.subn(r"EPOCH <b>[^<]*</b> \u00b7 TRACKED <b>[^<]*</b>", lambda m: meta, html, count=1)
    if n1 == 1 and n2 == 1:
        open(BOARD, "w", encoding="utf-8").write(html)
        print(f"board: epoch {TODAY}, tracked {len(sats)}, " +
              ", ".join(f"{k} {v}" for k, v in states.items()))
    else:
        print(f"board: patch skipped (anchors found: data={n1}, meta={n2})")

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
    update_board(sats)
    try:
        update_storm_section(update_storm(hist))
    except Exception as e:
        print("storm: module error, board unaffected:", e)
    op = sum(1 for r in pred if r["status"] == "open")
    ver = sum(1 for r in pred if r["status"] == "reentered")
    print(f"journal: {op} open, {ver} verified reentries")

if __name__ == "__main__":
    main()
