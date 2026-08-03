#!/usr/bin/env python3
"""Build the golf dashboard from rounds.json.

    python build.py            # regenerate dashboard.html
    python build.py --reset    # drop the sample rounds, keep courses/players
"""

import html
import json
import sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "rounds.json"
OUT = HERE / "dashboard.html"          # fragment, for the Claude artifact
SITE = HERE / "docs" / "index.html"    # standalone page, for GitHub Pages


# ---------------------------------------------------------------- data model

def load():
    with DATA.open(encoding="utf-8") as f:
        return json.load(f)


def totals(scores, par):
    """(gross, to_par, holes_played) over the holes that have a score."""
    gross = sum(s for s in scores if s is not None)
    played = [i for i, s in enumerate(scores) if s is not None]
    to_par = gross - sum(par[i] for i in played)
    return gross, to_par, len(played)


def side(scores, par, lo, hi):
    sub = scores[lo:hi]
    if any(s is None for s in sub):
        return None
    return sum(sub)


def fmt_par(n, plus=True):
    if n == 0:
        return "E"
    return f"+{n}" if (n > 0 and plus) else str(n)


def fmt_avg(n):
    if n is None:
        return "—"
    s = f"{n:+.1f}"
    return "E" if abs(n) < 0.05 else s


def nice_date(iso):
    d = datetime.strptime(iso, "%Y-%m-%d").date()
    return d.strftime("%b %-d") if sys.platform != "win32" else d.strftime("%b %#d")


def nice_date_full(iso):
    d = datetime.strptime(iso, "%Y-%m-%d").date()
    fmt = "%a %b %#d, %Y" if sys.platform == "win32" else "%a %b %-d, %Y"
    return d.strftime(fmt)


# ------------------------------------------------------------------ analysis

def analyse(data):
    players = {p["id"]: p for p in data["players"]}
    courses = {c["id"]: c for c in data["courses"]}
    rounds = sorted(data["rounds"], key=lambda r: r["date"])

    order = {p["id"]: i for i, p in enumerate(data["players"])}

    stats = {
        pid: {
            "id": pid,
            "name": p["name"],
            "short": p.get("short") or p["name"].split()[0],
            "idx": order[pid],
            "handicap": p.get("handicap"),
            "rounds": 0,
            "holes": 0,
            "gross": 0,
            "to_par": 0,
            "wins": 0.0,
            "eagles": 0, "birdies": 0, "pars": 0, "bogeys": 0, "doubles": 0,
            "best": None,           # (to_par, gross, round)
            "form": [],             # to_par per round, chronological
            "money": 0,
            "by_par": {3: [0, 0], 4: [0, 0], 5: [0, 0]},   # [strokes_over, holes]
        }
        for pid, p in players.items()
    }

    enriched = []
    any_money = False

    for rnd in rounds:
        course = courses[rnd["course"]]
        par = course["par"]
        rows = []
        for pid, scores in rnd["scores"].items():
            if pid not in stats:
                continue
            gross, to_par, holes = totals(scores, par)
            rows.append({
                "id": pid, "name": stats[pid]["short"], "idx": order[pid],
                "full": players[pid]["name"], "scores": scores,
                "gross": gross, "to_par": to_par, "holes": holes,
                "out": side(scores, par, 0, 9), "in": side(scores, par, 9, 18),
                "money": (rnd.get("money") or {}).get(pid),
            })
        if not rows:
            continue

        full = [r for r in rows if r["holes"] == len(par)]
        contenders = full or rows
        low = min(r["gross"] for r in contenders)
        winners = [r for r in contenders if r["gross"] == low]
        for r in rows:
            r["won"] = any(w["id"] == r["id"] for w in winners)

        rows.sort(key=lambda r: (r["gross"], r["name"]))

        for r in rows:
            s = stats[r["id"]]
            s["rounds"] += 1
            s["holes"] += r["holes"]
            s["gross"] += r["gross"]
            s["to_par"] += r["to_par"]
            s["form"].append(r["to_par"])
            if r["won"]:
                s["wins"] += 1.0 / len(winners)
            if s["best"] is None or r["to_par"] < s["best"][0]:
                s["best"] = (r["to_par"], r["gross"], rnd)
            if r["money"] is not None:
                s["money"] += r["money"]
                any_money = True
            for i, sc in enumerate(r["scores"]):
                if sc is None:
                    continue
                d = sc - par[i]
                if d <= -2:
                    s["eagles"] += 1
                elif d == -1:
                    s["birdies"] += 1
                elif d == 0:
                    s["pars"] += 1
                elif d == 1:
                    s["bogeys"] += 1
                else:
                    s["doubles"] += 1
                if par[i] in s["by_par"]:
                    s["by_par"][par[i]][0] += d
                    s["by_par"][par[i]][1] += 1

        enriched.append({"round": rnd, "course": course, "rows": rows})

    played = [s for s in stats.values() if s["rounds"]]
    for s in played:
        s["avg_to_par"] = s["to_par"] / s["rounds"]
        s["avg_gross"] = s["gross"] / s["rounds"]
        s["per_hole"] = s["to_par"] / s["holes"] if s["holes"] else 0
    played.sort(key=lambda s: (s["per_hole"], -s["rounds"]))

    # head to head: pair -> [a_wins, b_wins, ties]
    h2h = {}
    for e in enriched:
        rows = e["rows"]
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                key = tuple(sorted((a["id"], b["id"])))
                rec = h2h.setdefault(key, [0, 0, 0])
                first = key[0]
                if a["gross"] == b["gross"]:
                    rec[2] += 1
                else:
                    lower = a if a["gross"] < b["gross"] else b
                    rec[0 if lower["id"] == first else 1] += 1

    # hole difficulty, per course with >= 2 rounds
    hole_stats = []
    for cid, course in courses.items():
        cr = [e for e in enriched if e["course"]["id"] == cid]
        if len(cr) < 2:
            continue
        holes = []
        for i, p in enumerate(course["par"]):
            vals = [r["scores"][i] - p for e in cr for r in e["rows"]
                    if r["scores"][i] is not None]
            if vals:
                holes.append({"hole": i + 1, "par": p,
                              "avg": sum(vals) / len(vals), "n": len(vals)})
        if holes:
            hole_stats.append({"course": course, "holes": holes,
                               "rounds": len(cr)})

    return {
        "players": players, "courses": courses,
        "enriched": list(reversed(enriched)),   # newest first
        "standings": played, "h2h": h2h, "hole_stats": hole_stats,
        "any_money": any_money,
        "is_demo": bool(rounds) and all(r.get("demo") for r in rounds),
        "n_rounds": len(enriched),
        "span": (rounds[0]["date"], rounds[-1]["date"]) if rounds else None,
    }


# -------------------------------------------------------------------- render

def esc(s):
    return html.escape(str(s), quote=True)


def score_class(diff):
    if diff <= -2:
        return "eagle"
    if diff == -1:
        return "birdie"
    if diff == 0:
        return "par"
    if diff == 1:
        return "bogey"
    return "double"


def sparkline(values, width=76, height=22):
    """to-par per round, chronological. Lower is better, so the line is flipped."""
    if len(values) < 2:
        return '<span class="spark-empty">—</span>'
    vals = values[-8:]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    step = width / (len(vals) - 1)
    pts = [(i * step, height - 3 - ((hi - v) / span) * (height - 6))
           for i, v in enumerate(vals)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"0,{height} {line} {width},{height}"
    ex, ey = pts[-1]
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" '
        f'height="{height}" role="img" aria-hidden="true">'
        f'<polygon class="spark-fill" points="{area}"></polygon>'
        f'<polyline class="spark-line" points="{line}"></polyline>'
        f'<circle class="spark-dot" cx="{ex:.1f}" cy="{ey:.1f}" r="2.6"></circle>'
        f"</svg>"
    )


def standings_html(a):
    if not a["standings"]:
        return ""
    out = []
    for i, s in enumerate(a["standings"], 1):
        best = s["best"]
        best_txt = f'{best[1]} <span class="sub">({fmt_par(best[0])})</span>' if best else "—"
        wins = s["wins"]
        wins_txt = f"{wins:.0f}" if abs(wins - round(wins)) < 0.01 else f"{wins:.1f}"
        money = ""
        if a["any_money"]:
            m = s["money"]
            cls = "up" if m > 0 else ("down" if m < 0 else "flat")
            amt = f"+${m}" if m > 0 else (f"&minus;${abs(m)}" if m < 0 else "$0")
            money = (f'<div class="stat"><dt>Money</dt>'
                     f'<dd class="money {cls}">{amt}</dd></div>')
        form = (f'<div class="rank-form">{sparkline(s["form"])}'
                f'<span class="form-label">form</span></div>') if len(s["form"]) > 1 else ""
        out.append(f"""
      <li class="rank">
        <span class="rank-num">{i}</span>
        <div class="rank-main">
          <div class="rank-head">
            <h3><span class="n-full">{esc(s['name'])}</span><span class="n-short">{esc(s['short'])}</span></h3>
            <div class="rank-score">
              <span class="to-par {'under' if s['avg_to_par'] < 0 else 'over' if s['avg_to_par'] > 0 else ''}">{fmt_avg(s['avg_to_par'])}</span>
              <span class="sub">avg to par</span>
            </div>
          </div>
          <dl class="stats">
            <div class="stat"><dt>Rounds</dt><dd>{s['rounds']}</dd></div>
            <div class="stat"><dt>Avg</dt><dd>{s['avg_gross']:.1f}</dd></div>
            <div class="stat"><dt>Best</dt><dd>{best_txt}</dd></div>
            <div class="stat"><dt>Wins</dt><dd>{wins_txt}</dd></div>
            <div class="stat"><dt>Birdies+</dt><dd>{s['birdies'] + s['eagles']}</dd></div>
            {money}
          </dl>
        </div>
        {form}
      </li>""")
    return f'<ol class="ranks">{"".join(out)}</ol>'


def card_html(e, open_first):
    rnd, course, rows = e["round"], e["course"], e["rows"]
    par = course["par"]
    n = len(par)
    front_par, back_par = sum(par[:9]), sum(par[9:])

    nines = course.get("nines") or ["OUT", "IN"]
    out_label, in_label = esc(nines[0])[:11], esc(nines[1])[:11]

    head = "".join(f"<th>{i + 1}</th>" for i in range(9))
    head += f'<th class="side">{out_label}</th>'
    head += "".join(f"<th>{i + 1}</th>" for i in range(9, n))
    head += f'<th class="side">{in_label}</th><th class="side tot">TOT</th>'

    parrow = "".join(f"<td>{p}</td>" for p in par[:9])
    parrow += f'<td class="side">{front_par}</td>'
    parrow += "".join(f"<td>{p}</td>" for p in par[9:])
    parrow += f'<td class="side">{back_par}</td><td class="side tot">{sum(par)}</td>'

    body = []
    for r in rows:
        cells = []
        for i in range(n):
            sc = r["scores"][i]
            if sc is None:
                cells.append('<td class="cell empty">·</td>')
            else:
                cells.append(f'<td class="cell"><span class="mark {score_class(sc - par[i])}">{sc}</span></td>')
            if i == 8:
                cells.append(f'<td class="side">{r["out"] if r["out"] is not None else "—"}</td>')
        cells.append(f'<td class="side">{r["in"] if r["in"] is not None else "—"}</td>')
        cells.append(f'<td class="side tot">{r["gross"]}</td>')
        flag = '<span class="flag">&#9873;</span>' if r["won"] else ""
        body.append(
            f'<tr{" class=\"win\"" if r["won"] else ""}>'
            f'<th scope="row">{esc(r["name"])}{flag}</th>'
            f'{"".join(cells)}</tr>'
        )

    winners = [r["name"] for r in rows if r["won"]]
    low = min(r["gross"] for r in rows)
    money_line = ""
    if any(r["money"] is not None for r in rows):
        parts = []
        for r in sorted(rows, key=lambda x: -(x["money"] or 0)):
            m = r["money"]
            if m is None:
                continue
            cls = "up" if m > 0 else ("down" if m < 0 else "flat")
            amt = f'+${m}' if m > 0 else (f'&minus;${abs(m)}' if m < 0 else "$0")
            parts.append(f'<span class="chip {cls}">{esc(r["name"])} {amt}</span>')
        money_line = f'<div class="chips">{"".join(parts)}</div>'

    notes = f'<p class="notes">{esc(rnd["notes"])}</p>' if rnd.get("notes") else ""
    sub = f'<span class="course-sub">{esc(course["sub"])}</span>' if course.get("sub") else ""
    tees = f' &middot; {esc(rnd["tees"])} tees' if rnd.get("tees") else ""
    holes_played = max(r["holes"] for r in rows)
    hole_note = "" if holes_played == n else f' &middot; {holes_played} holes'

    return f"""
      <details class="round"{" open" if open_first else ""}>
        <summary>
          <div class="round-when">
            <span class="round-date">{nice_date(rnd['date'])}</span>
            <span class="round-year">{rnd['date'][:4]}</span>
          </div>
          <div class="round-what">
            <h3>{esc(course['name'])}</h3>
            <p>{esc(', '.join(winners))} took it at {low}{tees}{hole_note}</p>
          </div>
          <span class="chev" aria-hidden="true"></span>
        </summary>
        <div class="round-body">
          {sub}
          <div class="card-scroll">
            <table class="card">
              <thead><tr><th scope="col" class="corner">Hole</th>{head}</tr></thead>
              <tbody>
                <tr class="parrow"><th scope="row">Par</th>{parrow}</tr>
                {"".join(body)}
              </tbody>
            </table>
          </div>
          {money_line}
          {notes}
          {arc_html(e)}
        </div>
      </details>"""


def arc_html(e):
    """Prose recap plus a running to-par trace, so you can see the round develop."""
    rnd, course, rows = e["round"], e["course"], e["rows"]
    par = course["par"]
    n = len(par)

    traces = []
    for r in rows:
        cum, run = [], 0
        for i in range(n):
            if r["scores"][i] is None:
                cum.append(None)
                continue
            run += r["scores"][i] - par[i]
            cum.append(run)
        if any(v is not None for v in cum):
            traces.append((r, cum))
    if not traces:
        return ""

    flat = [v for _, c in traces for v in c if v is not None]
    lo, hi = min(0, min(flat)), max(flat)
    span = (hi - lo) or 1

    # right padding has to clear the longest end label, or long names clip
    longest = max(len(f'{r["name"]} {r["gross"]}') for r, _ in traces)
    W, H = 620, 210
    PAD_L, PAD_T, PAD_B = 30, 12, 26
    PAD_R = max(78, min(190, round(longest * 5.6) + 18))
    px = lambda i: PAD_L + (i / (n - 1)) * (W - PAD_L - PAD_R)
    py = lambda v: PAD_T + ((v - lo) / span) * (H - PAD_T - PAD_B)

    grid = []
    step = 5 if span > 12 else 2
    v = lo - (lo % step)
    while v <= hi:
        y = py(v)
        grid.append(f'<line class="ax" x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}"></line>'
                    f'<text class="ax-t" x="{PAD_L - 6}" y="{y + 3.5:.1f}" text-anchor="end">{fmt_par(v)}</text>')
        v += step

    turn = px(8.5)
    grid.append(f'<line class="turn" x1="{turn:.1f}" y1="{PAD_T}" x2="{turn:.1f}" y2="{H - PAD_B}"></line>')

    ticks = []
    for i in range(n):
        if i in (0, 4, 8, 9, 13, n - 1):
            ticks.append(f'<text class="ax-t" x="{px(i):.1f}" y="{H - PAD_B + 15}" text-anchor="middle">{i + 1}</text>')

    drawn = []
    for r, cum in traces:
        pts = [(px(i), py(v)) for i, v in enumerate(cum) if v is not None]
        drawn.append((r, pts, f"var(--p{r['idx'] % 6})"))

    # nudge end labels apart so names never overlap
    labels = sorted(range(len(drawn)), key=lambda k: drawn[k][1][-1][1])
    label_y, last = {}, None
    for k in labels:
        y = drawn[k][1][-1][1]
        if last is not None and y - last < 13:
            y = last + 13
        label_y[k], last = y, y

    lines = []
    for k, (r, pts, c) in enumerate(drawn):
        d = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        ex, ey = pts[-1]
        ly = label_y[k]
        tether = ("" if abs(ly - ey) < 1 else
                  f'<line class="tether" x1="{ex + 4:.1f}" y1="{ey:.1f}" '
                  f'x2="{ex + 8:.1f}" y2="{ly:.1f}" style="stroke:{c}"></line>')
        lines.append(
            f'<polyline class="trace" points="{d}" style="stroke:{c}"></polyline>'
            f'<circle class="trace-dot" cx="{ex:.1f}" cy="{ey:.1f}" r="3" style="fill:{c}"></circle>'
            f'{tether}'
            f'<text class="trace-t" x="{ex + 10:.1f}" y="{ly + 4:.1f}" style="fill:{c}">'
            f'{esc(r["name"])} {r["gross"]}</text>'
        )

    chart = f"""<div class="arc-chart">
            <svg viewBox="0 0 {W} {H}" role="img"
                 aria-label="Running strokes over par through {n} holes">
              {''.join(grid)}{''.join(ticks)}{''.join(lines)}
            </svg>
          </div>"""

    prose = rnd.get("arc")
    if isinstance(prose, str):
        prose = [prose]
    text = "".join(f"<p>{esc(p)}</p>" for p in (prose or []))

    return f"""
          <div class="arc">
            <h4>How it went</h4>
            {chart}
            <p class="arc-key">Strokes over par, hole by hole. Lower is better; the tick is the turn.</p>
            {f'<div class="arc-text">{text}</div>' if text else ''}
          </div>"""


def h2h_html(a):
    ids = [s["id"] for s in a["standings"]]
    if len(ids) < 2 or not a["h2h"]:
        return ""
    names = {s["id"]: s["short"] for s in a["standings"]}
    head = "".join(f'<th scope="col">{esc(names[i])}</th>' for i in ids)
    rows = []
    for x in ids:
        cells = []
        for y in ids:
            if x == y:
                cells.append('<td class="self">—</td>')
                continue
            key = tuple(sorted((x, y)))
            rec = a["h2h"].get(key)
            if not rec:
                cells.append('<td class="none">·</td>')
                continue
            w, l, t = (rec[0], rec[1], rec[2]) if key[0] == x else (rec[1], rec[0], rec[2])
            cls = "up" if w > l else ("down" if l > w else "flat")
            tie = f'<span class="sub">&ndash;{t}</span>' if t else ""
            cells.append(f'<td class="h2h {cls}">{w}&ndash;{l}{tie}</td>')
        rows.append(f'<tr><th scope="row">{esc(names[x])}</th>{"".join(cells)}</tr>')
    return f"""
    <section class="block">
      <h2>Head to head</h2>
      <p class="lede">Low gross in rounds you both played. Read across the row.</p>
      <div class="card-scroll">
        <table class="matrix">
          <thead><tr><td class="corner"></td>{head}</tr></thead>
          <tbody>{"".join(rows)}</tbody>
        </table>
      </div>
    </section>"""


def holes_html(a):
    if not a["hole_stats"]:
        return ""
    blocks = []
    for hs in a["hole_stats"]:
        holes = sorted(hs["holes"], key=lambda h: -h["avg"])
        worst, best = holes[:3], list(reversed(holes[-3:]))
        peak = max(abs(h["avg"]) for h in hs["holes"]) or 1

        def bars(items, cls):
            out = []
            for h in items:
                pct = min(100, abs(h["avg"]) / peak * 100)
                out.append(
                    f'<li><span class="hole-no">{h["hole"]}</span>'
                    f'<span class="hole-par">par {h["par"]}</span>'
                    f'<span class="bar"><span class="bar-fill {cls}" style="width:{pct:.0f}%"></span></span>'
                    f'<span class="hole-avg">{h["avg"]:+.1f}</span></li>'
                )
            return "".join(out)

        blocks.append(f"""
      <div class="holes-course">
        <h3>{esc(hs['course']['name'])} <span class="sub">{hs['rounds']} rounds</span></h3>
        <div class="holes-pair">
          <div><h4>Bites back</h4><ul class="holes">{bars(worst, 'bad')}</ul></div>
          <div><h4>Give-me-a-shot</h4><ul class="holes">{bars(best, 'good')}</ul></div>
        </div>
      </div>""")
    return f"""
    <section class="block">
      <h2>The holes</h2>
      <p class="lede">Average strokes over par, everyone pooled.</p>
      {"".join(blocks)}
    </section>"""


CSS = """
:root{
  --paper:#F2F4EE; --surface:#FCFCF9; --sunk:#E9ECE4;
  --ink:#15211C; --body:#2E3A34; --muted:#63706A; --faint:#8D9891;
  --line:#DBE0D7; --line-soft:#E7EBE3;
  --pencil:#B0821A; --pencil-bright:#D9A227;
  --under:#1E6B4E; --over:#B03A2E; --flat:#63706A;
  --shadow:0 1px 2px rgba(21,33,28,.05), 0 6px 18px -10px rgba(21,33,28,.22);
  --p0:#2F7D62; --p1:#B4553A; --p2:#3F6493; --p3:#7A5296; --p4:#8A6D1F; --p5:#3E7C86;
  --font-display:"Arial Narrow","Avenir Next Condensed","Liberation Sans Narrow","Helvetica Neue",system-ui,sans-serif;
  --font-body:Charter,"Bitstream Charter","Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
  --font-data:ui-monospace,"SF Mono","Cascadia Mono",Consolas,"Roboto Mono",monospace;
}
@media (prefers-color-scheme:dark){
  :root{
    --paper:#0F1714; --surface:#161F1B; --sunk:#121A17;
    --ink:#E9EEE8; --body:#CBD4CD; --muted:#8FA098; --faint:#6D7C75;
    --line:#25302B; --line-soft:#1E2723;
    --pencil:#E3B04B; --pencil-bright:#F0C468;
    --under:#57C593; --over:#E37766; --flat:#8FA098;
    --shadow:0 1px 2px rgba(0,0,0,.3), 0 8px 22px -12px rgba(0,0,0,.6);
    --p0:#5FC79C; --p1:#E5866A; --p2:#7FA6DE; --p3:#B58ACF; --p4:#D7B457; --p5:#6FC0CC;
  }
}
:root[data-theme="light"]{
  --paper:#F2F4EE; --surface:#FCFCF9; --sunk:#E9ECE4;
  --ink:#15211C; --body:#2E3A34; --muted:#63706A; --faint:#8D9891;
  --line:#DBE0D7; --line-soft:#E7EBE3;
  --pencil:#B0821A; --pencil-bright:#D9A227;
  --under:#1E6B4E; --over:#B03A2E; --flat:#63706A;
  --shadow:0 1px 2px rgba(21,33,28,.05), 0 6px 18px -10px rgba(21,33,28,.22);
  --p0:#2F7D62; --p1:#B4553A; --p2:#3F6493; --p3:#7A5296; --p4:#8A6D1F; --p5:#3E7C86;
}
:root[data-theme="dark"]{
  --paper:#0F1714; --surface:#161F1B; --sunk:#121A17;
  --ink:#E9EEE8; --body:#CBD4CD; --muted:#8FA098; --faint:#6D7C75;
  --line:#25302B; --line-soft:#1E2723;
  --pencil:#E3B04B; --pencil-bright:#F0C468;
  --under:#57C593; --over:#E37766; --flat:#8FA098;
  --shadow:0 1px 2px rgba(0,0,0,.3), 0 8px 22px -12px rgba(0,0,0,.6);
  --p0:#5FC79C; --p1:#E5866A; --p2:#7FA6DE; --p3:#B58ACF; --p4:#D7B457; --p5:#6FC0CC;
}

*{box-sizing:border-box}
body{
  margin:0; background:var(--paper); color:var(--body);
  font-family:var(--font-body); font-size:16px; line-height:1.55;
  -webkit-text-size-adjust:100%;
}
.wrap{max-width:860px; margin:0 auto; padding:28px 18px 72px; display:flex; flex-direction:column; gap:34px}
h1,h2,h3,h4{font-family:var(--font-display); color:var(--ink); margin:0; text-wrap:balance; font-weight:700}
.sub{color:var(--faint); font-size:.82em; font-family:var(--font-display); letter-spacing:.02em}
.lede{color:var(--muted); margin:.35rem 0 0; font-size:.94rem; max-width:60ch}

/* masthead */
.masthead{border-bottom:2px solid var(--ink); padding-bottom:14px}
.eyebrow{
  font-family:var(--font-display); font-size:.74rem; letter-spacing:.22em;
  text-transform:uppercase; color:var(--pencil); margin:0 0 6px;
}
.masthead h1{font-size:clamp(2.3rem,10vw,3.6rem); line-height:.94; letter-spacing:-.01em; text-transform:uppercase}
.masthead p{margin:10px 0 0; color:var(--muted); font-size:.95rem}
.meta{
  display:flex; flex-wrap:wrap; gap:6px 14px; margin-top:12px;
  font-family:var(--font-data); font-size:.74rem; color:var(--faint);
  text-transform:uppercase; letter-spacing:.06em;
}

.banner{
  border:1px dashed var(--pencil); border-radius:3px; padding:11px 14px;
  color:var(--muted); font-size:.9rem; background:var(--surface);
}
.banner b{color:var(--pencil); font-family:var(--font-display); letter-spacing:.02em}

.block{display:flex; flex-direction:column; gap:14px}
.block > h2{
  font-size:.82rem; letter-spacing:.2em; text-transform:uppercase; color:var(--muted);
  border-bottom:1px solid var(--line); padding-bottom:7px;
}
.block > h2 + .lede{margin-top:-8px}

/* standings */
.ranks{list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:9px}
.rank{
  display:grid; grid-template-columns:auto 1fr auto; gap:14px; align-items:start;
  background:var(--surface); border:1px solid var(--line); border-radius:3px;
  padding:14px 15px; box-shadow:var(--shadow);
}
.rank:first-child{border-left:3px solid var(--pencil)}
.rank-num{
  font-family:var(--font-display); font-size:1.5rem; color:var(--faint);
  line-height:1; padding-top:3px; font-variant-numeric:tabular-nums;
}
.rank:first-child .rank-num{color:var(--pencil)}
.rank-main{min-width:0; display:flex; flex-direction:column; gap:9px}
.rank-head{display:flex; align-items:baseline; justify-content:space-between; gap:12px}
.rank-head h3{font-size:1.35rem; letter-spacing:.01em}
.n-short{display:none}
.rank-score{text-align:right; display:flex; align-items:baseline; gap:6px; flex:0 0 auto}
.rank-score .sub{font-size:.68rem; text-transform:uppercase; letter-spacing:.08em; white-space:nowrap}
.to-par{font-family:var(--font-data); font-size:1.2rem; font-weight:600; color:var(--ink); font-variant-numeric:tabular-nums}
.to-par.under{color:var(--under)} .to-par.over{color:var(--over)}
.stats{display:flex; flex-wrap:wrap; gap:5px 20px; margin:0}
.stat dt{
  font-family:var(--font-display); font-size:.68rem; text-transform:uppercase;
  letter-spacing:.1em; color:var(--faint);
}
.stat dd{margin:0; font-family:var(--font-data); font-size:.94rem; color:var(--ink); font-variant-numeric:tabular-nums}
.stat dd .sub{font-family:var(--font-data)}
.money.up{color:var(--under)} .money.down{color:var(--over)} .money.flat{color:var(--muted)}
.rank-form{display:flex; flex-direction:column; align-items:center; gap:3px; padding-top:4px}
.form-label{font-family:var(--font-display); font-size:.6rem; letter-spacing:.14em; text-transform:uppercase; color:var(--faint)}
.spark{display:block; overflow:visible}
.spark-line{fill:none; stroke:var(--muted); stroke-width:1.5; stroke-linejoin:round; stroke-linecap:round}
.spark-fill{fill:var(--line-soft); opacity:.85}
.spark-dot{fill:var(--pencil-bright); stroke:var(--surface); stroke-width:1.4}
.spark-empty{font-family:var(--font-data); color:var(--faint); font-size:.85rem}

/* rounds */
.rounds{display:flex; flex-direction:column; gap:9px}
.round{background:var(--surface); border:1px solid var(--line); border-radius:3px; box-shadow:var(--shadow)}
.round > summary{
  display:grid; grid-template-columns:auto 1fr auto; gap:14px; align-items:center;
  padding:13px 15px; cursor:pointer; list-style:none;
}
.round > summary::-webkit-details-marker{display:none}
.round > summary:focus-visible{outline:2px solid var(--pencil); outline-offset:-2px}
.round-when{
  text-align:center; font-family:var(--font-display); line-height:1.05;
  border-right:1px solid var(--line-soft); padding-right:14px; min-width:52px;
}
.round-date{display:block; font-size:1rem; color:var(--ink); font-weight:700; text-transform:uppercase; letter-spacing:.03em}
.round-year{display:block; font-size:.68rem; color:var(--faint); letter-spacing:.08em}
.round-what{min-width:0}
.round-what h3{font-size:1.1rem}
.round-what p{margin:1px 0 0; font-size:.88rem; color:var(--muted)}
.chev{
  width:8px; height:8px; border-right:1.5px solid var(--faint); border-bottom:1.5px solid var(--faint);
  transform:rotate(45deg); transition:transform .18s ease; margin-right:4px;
}
.round[open] .chev{transform:rotate(-135deg)}
.round-body{padding:0 15px 16px; display:flex; flex-direction:column; gap:12px}

.card-scroll{overflow-x:auto; -webkit-overflow-scrolling:touch; border:1px solid var(--line); border-radius:2px}
table.card{border-collapse:collapse; font-family:var(--font-data); font-size:.8rem; width:100%; font-variant-numeric:tabular-nums}
table.card th, table.card td{
  border-right:1px solid var(--line-soft); border-bottom:1px solid var(--line-soft);
  padding:0; text-align:center; min-width:26px; height:29px;
}
table.card thead th{
  background:var(--sunk); color:var(--muted); font-family:var(--font-display);
  font-size:.72rem; font-weight:700; letter-spacing:.04em;
}
table.card th[scope="row"], table.card .corner{
  text-align:left; padding:0 11px 0 9px; position:sticky; left:0; z-index:1;
  background:var(--surface); font-family:var(--font-display); font-size:.85rem;
  color:var(--ink); white-space:nowrap; border-right:1px solid var(--line);
  min-width:74px; letter-spacing:.02em;
}
table.card .corner{background:var(--sunk); color:var(--muted); font-size:.72rem}
table.card .parrow th[scope="row"], table.card .parrow td{background:var(--sunk); color:var(--muted)}
table.card .side{background:var(--sunk); font-weight:700; color:var(--ink)}
table.card .tot{border-left:1px solid var(--line)}
table.card tr.win th[scope="row"]{color:var(--pencil)}
.flag{margin-left:5px; color:var(--pencil-bright)}
.cell.empty{color:var(--faint)}
.mark{
  display:inline-flex; align-items:center; justify-content:center;
  width:21px; height:21px; line-height:1; color:var(--ink);
}
.mark.birdie{border:1.5px solid var(--under); border-radius:50%; color:var(--under)}
.mark.eagle{border:1.5px solid var(--under); border-radius:50%; color:var(--under); box-shadow:0 0 0 2.5px var(--surface),0 0 0 4px var(--under)}
.mark.bogey{border:1.5px solid var(--over); color:var(--over)}
.mark.double{border:1.5px solid var(--over); background:color-mix(in srgb, var(--over) 16%, transparent); color:var(--over)}

.chips{display:flex; flex-wrap:wrap; gap:6px}
.chip{
  font-family:var(--font-data); font-size:.78rem; padding:3px 9px; border-radius:2px;
  border:1px solid var(--line); color:var(--muted); background:var(--sunk);
}
.chip.up{color:var(--under); border-color:color-mix(in srgb, var(--under) 40%, var(--line))}
.chip.down{color:var(--over); border-color:color-mix(in srgb, var(--over) 40%, var(--line))}
.notes{margin:0; font-size:.9rem; color:var(--muted); font-style:italic; max-width:62ch}
.course-sub{
  font-family:var(--font-display); font-size:.76rem; letter-spacing:.1em;
  text-transform:uppercase; color:var(--faint);
}

/* the arc */
.arc{
  border-top:1px solid var(--line); padding-top:15px; margin-top:3px;
  display:flex; flex-direction:column; gap:11px;
}
.arc h4{font-size:.72rem; letter-spacing:.18em; text-transform:uppercase; color:var(--muted)}
.arc-chart{overflow-x:auto; -webkit-overflow-scrolling:touch}
.arc-chart svg{display:block; width:100%; min-width:520px; height:auto}
.arc-chart .ax{stroke:var(--line-soft); stroke-width:1}
.arc-chart .turn{stroke:var(--line); stroke-width:1; stroke-dasharray:2 4}
.arc-chart .ax-t{
  font-family:var(--font-data); font-size:9px; fill:var(--faint);
}
.arc-chart .trace{fill:none; stroke-width:2; stroke-linejoin:round; stroke-linecap:round}
.arc-chart .trace-dot{stroke:var(--surface); stroke-width:1.5}
.arc-chart .tether{stroke-width:1; opacity:.55}
.arc-chart .trace-t{font-family:var(--font-display); font-size:11px; font-weight:700}
.arc-key{margin:0; font-family:var(--font-data); font-size:.7rem; color:var(--faint)}
.arc-text{display:flex; flex-direction:column; gap:10px; max-width:64ch}
.arc-text p{margin:0; font-size:.96rem; line-height:1.65; color:var(--body)}
.arc-text p:first-child{
  font-size:1.12rem; line-height:1.45; color:var(--ink);
  font-family:var(--font-display); letter-spacing:.005em;
}
.arc-text p:last-child{
  font-family:var(--font-data); font-size:.86rem; color:var(--muted);
  border-left:2px solid var(--pencil); padding-left:11px;
}

/* matrix */
table.matrix{border-collapse:collapse; width:100%; font-family:var(--font-data); font-size:.85rem; font-variant-numeric:tabular-nums}
table.matrix th, table.matrix td{border:1px solid var(--line-soft); padding:8px 10px; text-align:center; white-space:nowrap}
table.matrix thead th, table.matrix th[scope="row"]{
  font-family:var(--font-display); font-size:.82rem; color:var(--ink);
  background:var(--sunk); letter-spacing:.02em;
}
table.matrix th[scope="row"]{text-align:left; position:sticky; left:0; z-index:1}
table.matrix .corner{background:var(--sunk); border-color:var(--line-soft)}
.h2h.up{color:var(--under)} .h2h.down{color:var(--over)} .h2h.flat{color:var(--muted)}
.self{background:var(--sunk); color:var(--faint)}

/* holes */
.holes-course{display:flex; flex-direction:column; gap:11px}
.holes-course h3{font-size:1.02rem}
.holes-pair{display:grid; grid-template-columns:1fr; gap:16px}
@media(min-width:620px){.holes-pair{grid-template-columns:1fr 1fr; gap:26px}}
.holes-pair h4{
  font-size:.7rem; letter-spacing:.14em; text-transform:uppercase; color:var(--faint); margin-bottom:7px;
}
ul.holes{list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:7px}
ul.holes li{display:grid; grid-template-columns:22px 44px 1fr 40px; gap:8px; align-items:center}
.hole-no{font-family:var(--font-display); font-size:1rem; color:var(--ink); font-weight:700; text-align:right}
.hole-par, .hole-avg{font-family:var(--font-data); font-size:.75rem; color:var(--faint)}
.hole-avg{text-align:right; color:var(--muted); font-variant-numeric:tabular-nums}
.bar{display:block; height:6px; background:var(--sunk); border-radius:1px; overflow:hidden}
.bar-fill{display:block; height:100%; border-radius:1px}
.bar-fill.bad{background:var(--over)} .bar-fill.good{background:var(--under)}

footer{
  border-top:1px solid var(--line); padding-top:14px; color:var(--faint);
  font-family:var(--font-data); font-size:.74rem; line-height:1.7;
}
footer .key{display:flex; flex-wrap:wrap; gap:6px 16px; margin-bottom:9px; align-items:center}
footer .foot-link{
  color:var(--pencil); text-decoration:none; font-family:var(--font-display);
  letter-spacing:.06em; text-transform:uppercase; border-bottom:1px solid var(--pencil);
}
footer .foot-link:hover, footer .foot-link:focus-visible{color:var(--ink); border-color:var(--ink)}
footer .key span{display:inline-flex; align-items:center; gap:6px}

@media(max-width:470px){
  .rank{grid-template-columns:auto 1fr; gap:11px}
  .rank-form{grid-column:2; flex-direction:row; align-items:center; gap:8px; padding-top:0}
  .stats{gap:5px 14px}
  .n-full{display:none}
  .n-short{display:inline}
}
@media(prefers-reduced-motion:reduce){*{transition:none !important; animation:none !important}}
"""


def render(a, data):
    span = ""
    if a["span"]:
        span = (nice_date_full(a["span"][0]) if a["span"][0] == a["span"][1]
                else f"{nice_date_full(a['span'][0])} &ndash; {nice_date_full(a['span'][1])}")

    banner = ""
    if a["is_demo"]:
        banner = ('<div class="banner"><b>Sample data.</b> These two rounds are here so you can see '
                  'the layout. Send in a real scorecard and they go away.</div>')
    if not a["n_rounds"]:
        banner = ('<div class="banner"><b>No rounds yet.</b> Send a photo of the scorecard and the '
                  'first one lands here.</div>')

    cards = "".join(card_html(e, i == 0) for i, e in enumerate(a["enriched"]))
    rounds_block = f"""
    <section class="block">
      <h2>Rounds</h2>
      <div class="rounds">{cards}</div>
    </section>""" if cards else ""

    standings = standings_html(a)
    standings_block = f"""
    <section class="block">
      <h2>Standings</h2>
      <p class="lede">Ranked by average strokes to par per hole, so short rounds still count.</p>
      {standings}
    </section>""" if standings else ""

    stamp = date.today().strftime("%b %#d, %Y" if sys.platform == "win32" else "%b %-d, %Y")

    return f"""<title>{esc(data.get('group', 'Golf'))}</title>
<style>{CSS}</style>
<div class="wrap">
  <header class="masthead">
    <p class="eyebrow">Scorecard ledger</p>
    <h1>{esc(data.get('group', 'Golf'))}</h1>
    <p>{esc(data.get('tagline', ''))}</p>
    <div class="meta">
      <span>{a['n_rounds']} round{'' if a['n_rounds'] == 1 else 's'}</span>
      <span>{len(a['standings'])} players</span>
      {f'<span>{span}</span>' if span else ''}
    </div>
  </header>
  {banner}
  {standings_block}
  {rounds_block}
  {h2h_html(a)}
  {holes_html(a)}
  <footer>
    <div class="key">
      <span><span class="mark birdie">3</span> birdie or better</span>
      <span><span class="mark bogey">5</span> bogey</span>
      <span><span class="mark double">7</span> double or worse</span>
    </div>
    Updated {stamp}. New scorecard? Send the photo &mdash; it gets read, added, and this page updates at the same link.<br>
    <a class="foot-link" href="map.html">Live yardage view &rarr;</a> &nbsp;Sunland Springs, all 27 holes, GPS distances.
  </footer>
</div>
"""


def standalone(fragment, data):
    """Wrap the fragment in a real document for GitHub Pages."""
    title = esc(data.get("group", "Golf"))
    desc = esc(data.get("tagline", ""))
    body = fragment.split("\n", 1)[1] if fragment.startswith("<title>") else fragment
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow, noarchive">
<meta name="referrer" content="no-referrer">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#F2F4EE" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0F1714" media="(prefers-color-scheme: dark)">
<meta name="apple-mobile-web-app-title" content="{title}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ctext y='26' font-size='26'%3E%E2%9B%B3%3C/text%3E%3C/svg%3E">
<title>{title}</title>
</head>
<body>
{body}
</body>
</html>
"""


def main():
    data = load()
    if "--reset" in sys.argv:
        data["rounds"] = [r for r in data["rounds"] if not r.get("demo")]
        with DATA.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        print("Sample rounds removed.")
    a = analyse(data)
    fragment = render(a, data)
    OUT.write_text(fragment, encoding="utf-8")
    SITE.parent.mkdir(exist_ok=True)
    SITE.write_text(standalone(fragment, data), encoding="utf-8")
    print(f"{OUT}\n{SITE}\n({a['n_rounds']} rounds, {len(a['standings'])} players)")


if __name__ == "__main__":
    main()
