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
            "beat": 0.0,            # opponents beaten, halves for ties
            "faced": 0,             # opponents faced, across every field size
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
            # field-size neutral: a twosome win is one opponent beaten, not three
            opps = [o for o in rows if o["id"] != r["id"]]
            s["faced"] += len(opps)
            s["beat"] += sum(1.0 if r["gross"] < o["gross"]
                             else 0.5 if r["gross"] == o["gross"] else 0.0
                             for o in opps)
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

        enriched.append({"round": rnd, "course": course, "rows": rows,
                         "field": len(rows)})

    played = [s for s in stats.values() if s["rounds"]]
    for s in played:
        s["avg_to_par"] = s["to_par"] / s["rounds"]
        s["avg_gross"] = s["gross"] / s["rounds"]
        s["per_hole"] = s["to_par"] / s["holes"] if s["holes"] else 0
        s["beat_rate"] = s["beat"] / s["faced"] if s["faced"] else None
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
        "mixed_fields": len({e["field"] for e in enriched}) > 1,
        "is_demo": bool(rounds) and all(r.get("demo") for r in rounds),
        "n_rounds": len(enriched),
        "span": (rounds[0]["date"], rounds[-1]["date"]) if rounds else None,
    }


# -------------------------------------------------------------------- render

def esc(s):
    return html.escape(str(s), quote=True)


FIELD_WORDS = {1: "Solo", 2: "Twosome", 3: "Threesome", 4: "Foursome", 5: "Fivesome"}


def field_word(n):
    return FIELD_WORDS.get(n, f"{n} players")


def auto_headline(rows, low):
    """Formulaic back-page headline for a round with no hand-written one."""
    winners = [r for r in rows if r["won"]]
    if len(winners) > 1:
        return f'{" & ".join(w["name"] for w in winners)} share the spoils'
    w = winners[0]
    field = sorted((r["gross"] for r in rows if not r["won"]), default=None)
    if field:
        margin = field[0] - low
        if margin == 1:
            return f'{w["name"]} nips it by one'
        if margin >= 8:
            return f'{w["name"]} runs away with it'
        return f'{w["name"]} wins by {margin}'
    return f'{w["name"]} cards a {low}'


def auto_deck(rows, course):
    """Fallback subhead when a round has no hand-written deck. Caller escapes it."""
    line = ", ".join(f'{r["name"]} {r["gross"]}' for r in sorted(rows, key=lambda r: r["gross"]))
    return f'{course["name"]}: {line}.'


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
        wins_txt += f' <span class="sub">of {s["rounds"]}</span>'
        beat = ""
        if a["mixed_fields"] and s["beat_rate"] is not None:
            beat = (f'<div class="stat"><dt>Beat rate</dt>'
                    f'<dd>{s["beat_rate"] * 100:.0f}% '
                    f'<span class="sub">({s["faced"]})</span></dd></div>')
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
            {beat}
            <div class="stat"><dt>Birdies+</dt><dd>{s['birdies'] + s['eagles']}</dd></div>
            {money}
          </dl>
        </div>
        {form}
      </li>""")
    return f'<ol class="ranks">{"".join(out)}</ol>'


def card_html(e, open_first, roster=0):
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
    tees = f', {esc(rnd["tees"])} tees' if rnd.get("tees") else ""
    holes_played = max(r["holes"] for r in rows)
    hole_note = f', {holes_played} holes' if holes_played != n else ""

    # who was in the field, so a twosome never reads as three guys with missing scores
    field = len(rows)
    who = (f' &middot; {esc(", ".join(r["name"] for r in rows))}'
           if roster and field < roster else "")
    size_cls = "full" if not roster or field >= roster else "small"

    kicker = f'{esc(course["name"]).upper()} &middot; {esc(field_word(field)).upper()}{who}{tees}{hole_note}'
    headline = esc(rnd.get("headline") or auto_headline(rows, low))
    deck_src = rnd.get("deck") or auto_deck(rows, course)
    deck = f'<p class="deck">{esc(deck_src)}</p>'

    return f"""
      <details class="round {size_cls}"{" open" if open_first else ""}>
        <summary>
          <p class="kicker">{kicker}</p>
          <h3 class="headline">{headline}</h3>
          <p class="result">{esc(', '.join(winners))} took it at {low} &middot; {nice_date(rnd['date'])}, {rnd['date'][:4]}
            <span class="chev" aria-hidden="true"></span></p>
        </summary>
        <div class="round-body">
          {deck}
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
    # 5.6px/char assumes Arial Narrow actually loaded; budget for a wider fallback
    PAD_R = max(78, min(200, round(longest * 6.4) + 16))
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
@font-face{
  font-family:'Anton';
  font-style:normal;
  font-weight:400;
  font-display:swap;
  src:url(data:font/woff2;base64,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) format('woff2');
  unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215;
}
/* The Back Page — single-theme newsprint, committed. Red is reserved for
   under-par numbers and front-page emphasis, the way sports agate uses it. */
:root{
  --news:#EFEDE6; --paper:#F5F3EC; --sunk:#E7E4D8;
  --ink:#17150F; --body:#333026; --muted:#6E6A5C; --faint:#98937F;
  --red:#C22030; --line:#C9C5B6; --line-soft:#DDD9CB;
  --under:#C22030; --over:#17150F;
  --p0:#3E6B4E; --p1:#C22030; --p2:#2E5A87; --p3:#6E3A5E; --p4:#8A6D1F; --p5:#17150F;
  --font-display:Anton,"Archivo Black",Haettenschweiler,"Arial Narrow","Liberation Sans Narrow",system-ui,sans-serif;
  --font-body:Georgia,"Iowan Old Style","Times New Roman",serif;
  --font-data:ui-monospace,"SF Mono","Cascadia Mono",Consolas,"Roboto Mono",monospace;
}

*{box-sizing:border-box}
body{
  margin:0; background:var(--news); color:var(--body);
  font-family:var(--font-body); font-size:16px; line-height:1.55;
  -webkit-text-size-adjust:100%;
}
.wrap{max-width:860px; margin:0 auto; padding:24px 18px 72px; display:flex; flex-direction:column; gap:36px}
h1,h2,h3,h4{font-family:var(--font-display); color:var(--ink); margin:0; font-weight:400; letter-spacing:.01em}
.sub{color:var(--faint); font-size:.82em; font-family:var(--font-data)}
.lede{color:var(--muted); margin:.35rem 0 0; font-size:.9rem; max-width:60ch}

/* nameplate */
.masthead{border-top:4px solid var(--ink); border-bottom:4px solid var(--ink); padding:10px 0 14px}
.strap{
  display:flex; justify-content:space-between; gap:8px 18px; flex-wrap:wrap;
  font-family:var(--font-data); font-size:.66rem; letter-spacing:.14em;
  text-transform:uppercase; color:var(--muted);
}
.masthead h1{
  font-size:clamp(3rem,13vw,5.4rem); line-height:.94; text-transform:uppercase;
  margin-top:2px;
}
.masthead h1 .enddot{color:var(--red)}
.masthead .tagline{margin:6px 0 0; color:var(--muted); font-style:italic; font-size:.95rem}
.meta{
  display:flex; flex-wrap:wrap; gap:6px 14px; margin-top:10px;
  font-family:var(--font-data); font-size:.68rem; color:var(--faint);
  text-transform:uppercase; letter-spacing:.1em;
}

.banner{
  border:2px solid var(--ink); padding:11px 14px;
  color:var(--muted); font-size:.9rem; background:var(--paper);
}
.banner b{color:var(--red); font-family:var(--font-display); font-weight:400; text-transform:uppercase; letter-spacing:.04em}

.block{display:flex; flex-direction:column; gap:14px}
.block > h2{
  font-size:1.5rem; text-transform:uppercase; color:var(--ink);
  border-bottom:2px solid var(--ink); padding-bottom:6px;
}
.block > h2 + .lede{margin-top:-8px; font-family:var(--font-data); font-size:.72rem; letter-spacing:.06em; text-transform:uppercase}

/* the table (standings) */
.ranks{list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:0;
  border:2px solid var(--ink); background:var(--paper)}
.rank{
  display:grid; grid-template-columns:auto 1fr auto; gap:14px; align-items:start;
  padding:14px 16px; border-bottom:1px solid var(--line);
}
.rank:last-child{border-bottom:none}
.rank-num{
  font-family:var(--font-display); font-size:1.9rem; color:var(--faint);
  line-height:1; padding-top:2px; font-variant-numeric:tabular-nums; width:30px; text-align:center;
}
.rank:first-child .rank-num{color:var(--red)}
.rank-main{min-width:0; display:flex; flex-direction:column; gap:8px}
.rank-head{display:flex; align-items:baseline; justify-content:space-between; gap:12px}
.rank-head h3{font-size:1.4rem; text-transform:uppercase; letter-spacing:.02em}
.n-short{display:none}
.rank-score{text-align:right; display:flex; align-items:baseline; gap:6px; flex:0 0 auto}
.rank-score .sub{font-size:.62rem; text-transform:uppercase; letter-spacing:.1em; white-space:nowrap}
.to-par{font-family:var(--font-display); font-size:1.5rem; color:var(--ink); font-variant-numeric:tabular-nums}
.to-par.under{color:var(--red)}
.stats{display:flex; flex-wrap:wrap; gap:5px 18px; margin:0}
.stat dt{
  font-family:var(--font-data); font-size:.62rem; text-transform:uppercase;
  letter-spacing:.1em; color:var(--faint);
}
.stat dd{margin:0; font-family:var(--font-data); font-size:.9rem; color:var(--ink); font-variant-numeric:tabular-nums}
.stat dd .sub{font-family:var(--font-data)}
.money.up{color:var(--ink); font-weight:700} .money.down{color:var(--red)} .money.flat{color:var(--muted)}
.rank-form{display:flex; flex-direction:column; align-items:center; gap:3px; padding-top:6px}
.form-label{font-family:var(--font-data); font-size:.58rem; letter-spacing:.16em; text-transform:uppercase; color:var(--faint)}
.spark{display:block; overflow:visible}
.spark-line{fill:none; stroke:var(--ink); stroke-width:1.5; stroke-linejoin:round; stroke-linecap:round}
.spark-fill{fill:var(--sunk); opacity:.9}
.spark-dot{fill:var(--red); stroke:var(--paper); stroke-width:1.4}
.spark-empty{font-family:var(--font-data); color:var(--faint); font-size:.85rem}

/* stories (rounds) */
.rounds{display:flex; flex-direction:column; gap:14px}
.round{background:var(--paper); border:2px solid var(--ink)}
.round > summary{
  display:flex; flex-direction:column; gap:4px;
  padding:16px 18px 14px; cursor:pointer; list-style:none;
}
.round > summary::-webkit-details-marker{display:none}
.round > summary:focus-visible{outline:2px solid var(--red); outline-offset:-2px}
.kicker{
  margin:0; font-family:var(--font-data); font-size:.66rem; letter-spacing:.2em;
  text-transform:uppercase; color:var(--red); font-weight:700;
}
.headline{
  font-size:clamp(1.5rem,5.4vw,2.3rem); line-height:1.02; text-transform:uppercase;
  text-wrap:balance;
}
.lead .headline{font-size:clamp(2rem,8vw,3.3rem); line-height:.97}
.result{
  margin:2px 0 0; display:flex; align-items:center; gap:10px;
  font-family:var(--font-data); font-size:.74rem; color:var(--muted); letter-spacing:.04em;
}
.chev{
  width:8px; height:8px; border-right:2px solid var(--faint); border-bottom:2px solid var(--faint);
  transform:rotate(45deg); transition:transform .18s ease; margin-left:auto; flex:0 0 auto;
}
.round[open] .chev{transform:rotate(-135deg)}
.round-body{padding:0 18px 18px; display:flex; flex-direction:column; gap:14px}
.deck{
  margin:0; font-style:italic; font-size:1.1rem; line-height:1.5; color:var(--muted);
  border-top:1px solid var(--line); padding-top:12px; max-width:60ch;
}
.course-sub{
  font-family:var(--font-data); font-size:.68rem; letter-spacing:.14em;
  text-transform:uppercase; color:var(--faint);
}

/* box score grid */
.card-scroll{overflow-x:auto; -webkit-overflow-scrolling:touch; border:2px solid var(--ink)}
table.card{border-collapse:collapse; font-family:var(--font-data); font-size:.8rem; width:100%; font-variant-numeric:tabular-nums; background:var(--paper)}
table.card th, table.card td{
  border-right:1px solid var(--line-soft); border-bottom:1px solid var(--line-soft);
  padding:0; text-align:center; min-width:26px; height:29px;
}
table.card thead th{
  background:var(--ink); color:var(--news); font-size:.66rem; font-weight:400;
  letter-spacing:.08em; border-right-color:#3A362A;
}
table.card th[scope="row"], table.card .corner{
  text-align:left; padding:0 11px 0 9px; position:sticky; left:0; z-index:1;
  background:var(--paper); font-family:var(--font-display); font-size:.85rem;
  color:var(--ink); white-space:nowrap; border-right:1px solid var(--ink);
  min-width:74px; letter-spacing:.05em; text-transform:uppercase; font-weight:400;
}
table.card .corner{background:var(--ink); color:var(--news); font-size:.66rem; font-family:var(--font-data)}
table.card .parrow th[scope="row"], table.card .parrow td{background:var(--sunk); color:var(--muted)}
table.card .side{background:var(--sunk); font-weight:700; color:var(--ink)}
table.card .tot{border-left:1px solid var(--ink)}
table.card tr.win th[scope="row"]{color:var(--red)}
.flag{margin-left:5px; color:var(--red)}
.cell.empty{color:var(--faint)}
.mark{
  display:inline-flex; align-items:center; justify-content:center;
  width:21px; height:21px; line-height:1; color:var(--ink);
}
.mark.birdie{border:2px solid var(--red); border-radius:50%; color:var(--red)}
.mark.eagle{border:2px solid var(--red); border-radius:50%; color:var(--red); box-shadow:0 0 0 2px var(--paper),0 0 0 3.5px var(--red)}
.mark.bogey{border:1.5px solid var(--ink)}
.mark.double{background:var(--ink); color:var(--news)}

.chips{display:flex; flex-wrap:wrap; gap:6px}
.chip{
  font-family:var(--font-data); font-size:.76rem; padding:3px 9px;
  border:1px solid var(--ink); color:var(--ink); background:var(--paper);
}
.chip.up{font-weight:700}
.chip.down{color:var(--red); border-color:var(--red)}
.notes{margin:0; font-size:.9rem; color:var(--muted); font-style:italic; max-width:62ch}

/* how it went */
.arc{
  border-top:1px solid var(--line); padding-top:15px; margin-top:2px;
  display:flex; flex-direction:column; gap:12px;
}
.arc h4{font-size:.95rem; letter-spacing:.05em; text-transform:uppercase; color:var(--ink);
  display:flex; align-items:center; gap:10px}
.arc h4::after{content:""; flex:1; height:1px; background:var(--line)}
.arc-chart{overflow-x:auto; -webkit-overflow-scrolling:touch}
.arc-chart svg{display:block; width:100%; min-width:520px; height:auto}
.arc-chart .ax{stroke:var(--line-soft); stroke-width:1}
.arc-chart .turn{stroke:var(--line); stroke-width:1; stroke-dasharray:2 4}
.arc-chart .ax-t{font-family:var(--font-data); font-size:9px; fill:var(--faint)}
.arc-chart .trace{fill:none; stroke-width:2; stroke-linejoin:round; stroke-linecap:round}
.arc-chart .trace-dot{stroke:var(--paper); stroke-width:1.5}
.arc-chart .tether{stroke-width:1; opacity:.55}
.arc-chart .trace-t{font-family:var(--font-data); font-size:10px; font-weight:700}
.arc-key{margin:0; font-family:var(--font-data); font-size:.68rem; color:var(--faint)}
.arc-text{display:flex; flex-direction:column; gap:11px; max-width:64ch; margin-top:2px}
.arc-text p{margin:0; font-size:.98rem; line-height:1.65; color:var(--body)}
.arc-text p:first-child::first-letter{
  font-family:var(--font-display); font-size:2.9em; float:left; line-height:.82;
  padding:4px 8px 0 0; color:var(--red);
}
.arc-text p:last-child{
  font-family:var(--font-data); font-size:.84rem; color:var(--ink);
  border-left:3px solid var(--red); padding-left:11px;
}
.arc-text p:last-child::first-letter{font-family:var(--font-data); font-size:1em; float:none; padding:0; color:var(--ink)}

/* filter */
.filter{display:flex; flex-wrap:wrap; gap:6px; margin-top:-4px}
.filter input{position:absolute; opacity:0; pointer-events:none}
.filter label{
  font-family:var(--font-data); font-size:.68rem; letter-spacing:.12em;
  text-transform:uppercase; color:var(--muted); background:var(--paper);
  border:1px solid var(--ink); padding:5px 12px; cursor:pointer;
}
.filter label:hover{color:var(--ink)}
.filter input:checked + label{color:var(--news); background:var(--ink)}
.filter input:focus-visible + label{outline:2px solid var(--red); outline-offset:2px}
.rounds-block:has(#ff-full:checked) .round.small{display:none}
.rounds-block:has(#ff-small:checked) .round.full{display:none}

/* grudge matrix */
table.matrix{border-collapse:collapse; width:100%; font-family:var(--font-data); font-size:.85rem; font-variant-numeric:tabular-nums; background:var(--paper); border:2px solid var(--ink)}
table.matrix th, table.matrix td{border:1px solid var(--line); padding:8px 10px; text-align:center; white-space:nowrap}
table.matrix thead th, table.matrix th[scope="row"]{
  font-family:var(--font-display); font-size:.8rem; font-weight:400; color:var(--ink);
  background:var(--sunk); letter-spacing:.05em; text-transform:uppercase;
}
table.matrix th[scope="row"]{text-align:left; position:sticky; left:0; z-index:1}
table.matrix .corner{background:var(--sunk); border-color:var(--line)}
.h2h.up{color:var(--ink); font-weight:700} .h2h.down{color:var(--red)} .h2h.flat{color:var(--muted)}
.self{background:var(--sunk); color:var(--faint)}

/* holes */
.holes-course{display:flex; flex-direction:column; gap:11px}
.holes-course h3{font-size:1.15rem; text-transform:uppercase}
.holes-pair{display:grid; grid-template-columns:1fr; gap:16px}
@media(min-width:620px){.holes-pair{grid-template-columns:1fr 1fr; gap:26px}}
.holes-pair h4{
  font-size:.85rem; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); margin-bottom:7px;
}
ul.holes{list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:7px}
ul.holes li{display:grid; grid-template-columns:26px 44px 1fr 40px; gap:8px; align-items:center}
.hole-no{font-family:var(--font-display); font-size:1.1rem; color:var(--ink); text-align:right}
.hole-par, .hole-avg{font-family:var(--font-data); font-size:.75rem; color:var(--faint)}
.hole-avg{text-align:right; color:var(--muted); font-variant-numeric:tabular-nums}
.bar{display:block; height:7px; background:var(--sunk); overflow:hidden}
.bar-fill{display:block; height:100%}
.bar-fill.bad{background:var(--ink)} .bar-fill.good{background:var(--red)}

footer{
  border-top:4px solid var(--ink); padding-top:14px; color:var(--muted);
  font-family:var(--font-data); font-size:.7rem; line-height:1.9;
  letter-spacing:.06em; text-transform:uppercase;
}
footer .key{display:flex; flex-wrap:wrap; gap:6px 16px; margin-bottom:9px; align-items:center}
footer .key span{display:inline-flex; align-items:center; gap:6px}

@media(max-width:470px){
  .rank{grid-template-columns:auto 1fr; gap:11px}
  .rank-form{grid-column:2; flex-direction:row; align-items:center; gap:8px; padding-top:0}
  .stats{gap:5px 14px}
  .n-full{display:none}
  .n-short{display:inline}
  .strap span:nth-child(3){display:none}
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

    # the roster is everyone who has played, not just the biggest group that showed up
    roster = max([len(a["standings"])] + [e["field"] for e in a["enriched"]])
    cards = "".join(card_html(e, i == 0, roster) for i, e in enumerate(a["enriched"]))

    # the filter only earns its keep once there are enough rounds to scroll past
    filt = ""
    if a["mixed_fields"] and a["n_rounds"] >= 5:
        filt = """
      <div class="filter" role="group" aria-label="Filter rounds by field size">
        <input type="radio" name="fieldf" id="ff-all" checked><label for="ff-all">All</label>
        <input type="radio" name="fieldf" id="ff-full"><label for="ff-full">Full field</label>
        <input type="radio" name="fieldf" id="ff-small"><label for="ff-small">Small groups</label>
      </div>"""

    rounds_block = f"""
    <section class="block rounds-block">
      <h2>Rounds</h2>
      {filt}
      <div class="rounds">{cards}</div>
    </section>""" if cards else ""

    standings = standings_html(a)
    fair = (" Beat rate is the share of head-to-head match-ups won, so a twosome "
            "and a foursome carry the same weight." if a["mixed_fields"] else "")
    standings_block = f"""
    <section class="block">
      <h2>The Table</h2>
      <p class="lede">Ranked by average strokes to par per hole, so short rounds still count.{fair}</p>
      {standings}
    </section>""" if standings else ""

    today = date.today()
    stamp = today.strftime("%b %#d, %Y" if sys.platform == "win32" else "%b %-d, %Y")
    dateline = today.strftime("%A, %B %#d, %Y" if sys.platform == "win32" else "%A, %B %-d, %Y").upper()

    return f"""<title>{esc(data.get('group', 'Golf'))}</title>
<style>{CSS}</style>
<div class="wrap">
  <header class="masthead">
    <div class="strap">
      <span>Vol. 1 &middot; No. {max(a['n_rounds'], 1)}</span>
      <span>{dateline}</span>
      <span>Price: Your Dignity</span>
    </div>
    <h1>{esc(data.get('group', 'Golf'))}<span class="enddot">.</span></h1>
    <p class="tagline">{esc(data.get('tagline', ''))}</p>
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
    Updated {stamp}. New scorecard? Send the photo &mdash; it gets read, added, and this page updates at the same link.
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
<meta name="color-scheme" content="light">
<meta name="theme-color" content="#EFEDE6">
<meta name="apple-mobile-web-app-title" content="{title}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ctext y='26' font-size='26'%3E%F0%9F%97%9E%EF%B8%8F%3C/text%3E%3C/svg%3E">
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
