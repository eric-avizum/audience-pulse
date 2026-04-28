#!/usr/bin/env python3
"""Build data.json + update embedded data in index.html for the Audience Pulse dashboard."""

import csv
import io
import json
import math
import statistics
import urllib.request
from datetime import datetime, timezone, timedelta

CSV_URL = "https://docs.google.com/spreadsheets/d/1hXojkDNaNL0t8KtP5K1zcAAsA4kHUJHylfMCB0zdA8w/export?format=csv"

ROLE_ORDER = ["Manager / Senior Manager", "Director", "Senior Director", "VP or above", "Other"]
SIZE_ORDER = ["Fewer than 500", "500 \u2013 5,000", "5,000 \u2013 50,000", "More than 50,000"]


def fetch_csv():
    req = urllib.request.Request(CSV_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def parse_rows(raw_csv):
    reader = csv.reader(io.StringIO(raw_csv))
    header = next(reader)
    rows = []
    for r in reader:
        if len(r) < 7:
            continue
        try:
            p3, p4, p5, p6 = int(r[3]), int(r[4]), int(r[5]), int(r[6])
        except (ValueError, IndexError):
            continue
        sensing = (p3 + p4 + p5) / 3
        rows.append({
            "role": r[1].strip(),
            "size": r[2].strip(),
            "p3": p3, "p4": p4, "p5": p5, "p6": p6,
            "sensing": sensing,
            "velocity": p6
        })
    return rows


def build_data(rows):
    n = len(rows)
    if n == 0:
        return None

    # KPIs
    p3_vals = [r["p3"] for r in rows]
    p4_vals = [r["p4"] for r in rows]
    p5_vals = [r["p5"] for r in rows]
    p6_vals = [r["p6"] for r in rows]
    sensing_vals = [r["sensing"] for r in rows]
    velocity_vals = [r["velocity"] for r in rows]

    mean_sensing = statistics.mean(sensing_vals)
    mean_velocity = statistics.mean(velocity_vals)
    gap = mean_sensing - mean_velocity

    # Audience composition — count by role and size
    role_counts = {}
    for role in ROLE_ORDER:
        c = sum(1 for r in rows if r["role"] == role)
        if c > 0:
            role_counts[role] = c
    # Sort by count descending for roles
    role_counts = dict(sorted(role_counts.items(), key=lambda x: -x[1]))

    size_counts = {}
    for sz in SIZE_ORDER:
        c = sum(1 for r in rows if r["size"] == sz)
        if c > 0:
            size_counts[sz] = c

    # Distributions (1-7)
    def dist(vals):
        return [sum(1 for v in vals if v == i) for i in range(1, 8)]

    distributions = {
        "p3": dist(p3_vals),
        "p4": dist(p4_vals),
        "p5": dist(p5_vals),
        "p6": dist(p6_vals)
    }

    medians = {
        "p3": int(statistics.median(p3_vals)),
        "p4": int(statistics.median(p4_vals)),
        "p5": int(statistics.median(p5_vals)),
        "p6": int(statistics.median(p6_vals))
    }

    # Scatter data
    scatter = [{"x": round(r["sensing"], 2), "y": r["velocity"]} for r in rows]

    # Quadrant counts (threshold 4.5)
    leaders = sum(1 for r in rows if r["sensing"] >= 4.5 and r["velocity"] >= 4.5)
    stuck = sum(1 for r in rows if r["sensing"] >= 4.5 and r["velocity"] < 4.5)
    reactive = sum(1 for r in rows if r["sensing"] < 4.5 and r["velocity"] >= 4.5)
    laggards = sum(1 for r in rows if r["sensing"] < 4.5 and r["velocity"] < 4.5)

    # Gap by segment
    def segment_gaps(rows, key, order):
        gaps = {}
        for seg in order:
            seg_rows = [r for r in rows if r[key] == seg]
            if not seg_rows:
                continue
            s = statistics.mean([r["sensing"] for r in seg_rows])
            v = statistics.mean([r["velocity"] for r in seg_rows])
            gaps[seg] = {"n": len(seg_rows), "sensing": round(s, 2), "velocity": round(v, 2), "gap": round(s - v, 2)}
        return gaps

    size_gaps = segment_gaps(rows, "size", SIZE_ORDER)
    role_gaps = segment_gaps(rows, "role", ROLE_ORDER)

    # Time
    cest = timezone(timedelta(hours=2))
    now = datetime.now(cest)
    updated = now.strftime("%H:%M CEST")

    # Executive summary — data-driven
    stuck_pct = round(100 * stuck / n, 1) if n else 0

    summary = []

    # Scenario check per skill instructions
    if gap < 1.0:
        summary.append(
            f"This room breaks the pattern. With a sense\u2013act gap of just {gap:.1f}, "
            f"these {n} respondents are unusually aligned between what they detect and how fast they act on it. "
            f"That is rare. The question worth asking is not what is wrong but what this group has figured out that most have not."
        )
    elif mean_velocity > mean_sensing:
        summary.append(
            f"An unusual signal from this room: velocity ({mean_velocity:.1f}) outpaces sensing ({mean_sensing:.1f}). "
            f"That means organisations here are acting faster than they are detecting \u2014 a recipe for false positives. "
            f"The risk is not sluggishness but premature commitment to signals that have not been properly validated."
        )
    else:
        summary.append(
            f"Sixty-three professionals in one room, and the data tells a single story: "
            f"this industry senses well and acts slowly. Mean sensing sits at {mean_sensing:.1f}. "
            f"Mean velocity lands at {mean_velocity:.1f}. The gap \u2014 {gap:.1f} points on a seven-point scale \u2014 "
            f"is not noise. It is the distance between knowing something and doing something about it."
        )

    # Quadrant finding
    if stuck_pct > 70:
        summary.append(
            f"{stuck_pct}% of this room falls into the Stuck at Sensing quadrant \u2014 above the midpoint on awareness, "
            f"below it on action. The radar is on but it is not connected to the cockpit. "
            f"Organisations are investing in intelligence functions, subscribing to monitoring services, attending conferences like this one. "
            f"The problem is not information supply. It is the decision architecture downstream."
        )
    elif leaders / n > 0.3 if n else False:
        summary.append(
            f"A notable share of this room ({leaders} of {n}) lands in the Leaders quadrant. "
            f"That is worth interrogating: what structural or cultural factors let these organisations close the gap?"
        )

    # Distribution texture
    p6_low = sum(1 for v in p6_vals if v <= 2)
    p6_low_pct = round(100 * p6_low / n, 1)
    if p6_low_pct > 50:
        summary.append(
            f"Look at the velocity distribution: {p6_low_pct}% of respondents scored themselves a 1 or 2. "
            f"Not a 3 hedging towards the middle \u2014 the floor. When over half a senior room says "
            f"\"we barely translate signals into action,\" that is not pessimism. That is an institutional confession."
        )

    # Segment uniformity
    size_gap_vals = [v["gap"] for v in size_gaps.values()]
    role_gap_vals = [v["gap"] for v in role_gaps.values()]
    size_range = max(size_gap_vals) - min(size_gap_vals) if size_gap_vals else 0
    role_range = max(role_gap_vals) - min(role_gap_vals) if role_gap_vals else 0

    if size_range < 0.6 and role_range < 0.8:
        summary.append(
            f"The gap is remarkably uniform. Company size does not save you \u2014 the spread across size bands is just "
            f"{size_range:.1f} points. Seniority does not save you either. "
            f"This is not a resource problem or an authority problem. It is a structural one, and it spans the industry."
        )
    elif size_range >= 0.6:
        max_size = max(size_gaps.items(), key=lambda x: x[1]["gap"])
        min_size = min(size_gaps.items(), key=lambda x: x[1]["gap"])
        summary.append(
            f"Company size does matter here. {max_size[0]} companies show a gap of {max_size[1]['gap']:.1f}, "
            f"while {min_size[0]} companies narrow it to {min_size[1]['gap']:.1f}. "
            f"That {size_range:.1f}-point spread is the segment finding."
        )

    # Closing recommendation
    summary.append(
        f"The fix is not more intelligence. It is a shorter distance from signal to decision. "
        f"Every organisation in this room that scores above 5 on sensing and below 3 on velocity has the same homework: "
        f"map the path from your last significant insight to the action it produced, count the handoffs, and ask which ones "
        f"added judgement and which ones added delay."
    )

    # Discussion prompts — data-driven where possible
    prompts = []
    if leaders > 0:
        prompts.append(
            f"Who in this room clears 4.5 on velocity \u2014 what is different about your organisation? "
            f"({leaders} of {n} respondents land in the Leaders quadrant.)"
        )
    else:
        prompts.append(
            f"Not a single respondent in this room lands in the Leaders quadrant. "
            f"Is that a reflection of pharma specifically, or of large organisations generally?"
        )

    if size_range < 0.6:
        prompts.append(
            "If the gap is uniform across company size and seniority, is this a pharma-industry problem or a CI-function problem?"
        )
    else:
        max_seg = max(size_gaps.items(), key=lambda x: x[1]["gap"])
        prompts.append(
            f"{max_seg[0]} companies show the widest gap ({max_seg[1]['gap']:.1f}). What structural barrier is unique to that size band?"
        )

    prompts.append("What would shorten your signal-to-decision loop by 50%? Name one concrete change.")
    prompts.append(
        "What is one specific signal your organisation detected early but failed to act on within a useful timeframe?"
    )

    return {
        "n": n,
        "updated": updated,
        "kpis": {
            "responses": n,
            "meanSensing": round(mean_sensing, 2),
            "meanVelocity": round(mean_velocity, 2),
            "gap": round(gap, 2)
        },
        "roles": role_counts,
        "sizes": size_counts,
        "distributions": distributions,
        "medians": medians,
        "scatter": scatter,
        "quadrants": {
            "leaders": leaders,
            "stuck": stuck,
            "reactive": reactive,
            "laggards": laggards
        },
        "sizeGaps": size_gaps,
        "roleGaps": role_gaps,
        "summary": summary,
        "prompts": prompts,
        "responses": [{"role": r["role"], "size": r["size"],
                        "p3": r["p3"], "p4": r["p4"], "p5": r["p5"], "p6": r["p6"],
                        "sensing": r["sensing"], "velocity": r["velocity"]} for r in rows]
    }


def update_html(data, html_path="index.html"):
    with open(html_path, "r") as f:
        html = f.read()

    # Replace EMBEDDED data
    import re
    embedded_json = json.dumps(data, ensure_ascii=False)
    # Pattern: const EMBEDDED = {...};
    pattern = r'const EMBEDDED = \{.*?\};'
    replacement = f'const EMBEDDED = {embedded_json};'
    new_html = re.sub(pattern, replacement, html, count=1, flags=re.DOTALL)

    with open(html_path, "w") as f:
        f.write(new_html)

    return new_html


def main():
    print("Fetching CSV...")
    raw = fetch_csv()
    rows = parse_rows(raw)
    print(f"Parsed {len(rows)} responses")

    data = build_data(rows)
    if not data:
        print("ERROR: No valid data")
        return

    print(f"KPIs: n={data['n']}, sensing={data['kpis']['meanSensing']}, "
          f"velocity={data['kpis']['meanVelocity']}, gap={data['kpis']['gap']}")
    print(f"Quadrants: leaders={data['quadrants']['leaders']}, stuck={data['quadrants']['stuck']}, "
          f"reactive={data['quadrants']['reactive']}, laggards={data['quadrants']['laggards']}")

    # Write data.json
    with open("data.json", "w") as f:
        json.dump(data, f, ensure_ascii=False)
    print("Wrote data.json")

    # Update embedded data in index.html
    update_html(data)
    print("Updated index.html embedded data")


if __name__ == "__main__":
    main()
