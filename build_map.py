#!/usr/bin/env python3
"""Generate the live yardage view from a fetched course file.

    python build_map.py sunland

Writes docs/map.html - a standalone page with the hole geometry inlined, so it
works offline once loaded. Uses the browser's GPS for live distances.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "docs" / "map.html"

CSS = """
:root{
  --paper:#F2F4EE; --surface:#FCFCF9; --sunk:#E9ECE4;
  --ink:#15211C; --body:#2E3A34; --muted:#63706A; --faint:#8D9891;
  --line:#DBE0D7; --line-soft:#E7EBE3;
  --pencil:#B0821A; --pencil-bright:#D9A227;
  --turf:#CFDCC4; --turf-deep:#9FBE93; --green:#6FA86A; --sand:#E4D3A8;
  --water:#8FB4C4; --you:#B03A2E;
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
    --turf:#1E2E22; --turf-deep:#2C4433; --green:#4E8A54; --sand:#6B5C39;
    --water:#2F4C5C; --you:#E37766;
  }
}
:root[data-theme="light"]{
  --paper:#F2F4EE; --surface:#FCFCF9; --sunk:#E9ECE4; --ink:#15211C; --body:#2E3A34;
  --muted:#63706A; --faint:#8D9891; --line:#DBE0D7; --line-soft:#E7EBE3;
  --pencil:#B0821A; --pencil-bright:#D9A227;
  --turf:#CFDCC4; --turf-deep:#9FBE93; --green:#6FA86A; --sand:#E4D3A8;
  --water:#8FB4C4; --you:#B03A2E;
}
:root[data-theme="dark"]{
  --paper:#0F1714; --surface:#161F1B; --sunk:#121A17; --ink:#E9EEE8; --body:#CBD4CD;
  --muted:#8FA098; --faint:#6D7C75; --line:#25302B; --line-soft:#1E2723;
  --pencil:#E3B04B; --pencil-bright:#F0C468;
  --turf:#1E2E22; --turf-deep:#2C4433; --green:#4E8A54; --sand:#6B5C39;
  --water:#2F4C5C; --you:#E37766;
}

*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--body);font-family:var(--font-body);
     font-size:16px;line-height:1.5;-webkit-text-size-adjust:100%}
.wrap{max-width:720px;margin:0 auto;padding:22px 16px 60px;display:flex;flex-direction:column;gap:18px}
h1,h2,h3{font-family:var(--font-display);color:var(--ink);margin:0;font-weight:700}

.masthead{border-bottom:2px solid var(--ink);padding-bottom:11px}
.eyebrow{font-family:var(--font-display);font-size:.7rem;letter-spacing:.2em;text-transform:uppercase;
         color:var(--pencil);margin:0 0 5px}
.masthead h1{font-size:clamp(1.7rem,7vw,2.4rem);text-transform:uppercase;line-height:.98}
.masthead p{margin:7px 0 0;color:var(--muted);font-size:.85rem}
.back{color:var(--muted);text-decoration:none;font-family:var(--font-display);font-size:.78rem;
      letter-spacing:.1em;text-transform:uppercase;border-bottom:1px solid var(--line)}
.back:hover,.back:focus-visible{color:var(--pencil);border-color:var(--pencil)}

.picker{display:flex;flex-direction:column;gap:8px}
.row{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.row-label{font-family:var(--font-display);font-size:.66rem;letter-spacing:.14em;
           text-transform:uppercase;color:var(--faint);width:100%}
button.chip{
  font-family:var(--font-display);font-size:.9rem;font-weight:700;letter-spacing:.03em;
  padding:7px 13px;border:1px solid var(--line);background:var(--surface);color:var(--body);
  border-radius:2px;cursor:pointer;min-width:38px;
}
button.chip:hover{border-color:var(--pencil)}
button.chip:focus-visible{outline:2px solid var(--pencil);outline-offset:1px}
button.chip[aria-pressed="true"]{background:var(--ink);color:var(--paper);border-color:var(--ink)}

.stage{background:var(--surface);border:1px solid var(--line);border-radius:3px;overflow:hidden}
.hole-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;
           padding:12px 14px;border-bottom:1px solid var(--line-soft)}
.hole-head h2{font-size:1.15rem}
.hole-head .par{font-family:var(--font-data);color:var(--muted);font-size:.85rem}
svg.hole{display:block;width:100%;height:auto;background:var(--turf)}
.g-green{fill:var(--green)}
.g-bunker{fill:var(--sand)}
.g-tee{fill:var(--turf-deep)}
.g-line{fill:none;stroke:var(--ink);stroke-width:1.2;stroke-dasharray:4 5;opacity:.35}
.g-pin{fill:var(--paper);stroke:var(--ink);stroke-width:1.4}
.g-flag{fill:var(--you)}
.g-you{fill:var(--you);stroke:var(--paper);stroke-width:2}
.g-halo{fill:var(--you);opacity:.16}
.g-shot{stroke:var(--you);stroke-width:1.6;stroke-dasharray:3 4;fill:none;opacity:.8}
.g-label{font-family:var(--font-data);font-size:9px;fill:var(--ink);opacity:.6}

.yards{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line-soft)}
.yard{background:var(--surface);padding:12px 10px;text-align:center}
.yard dt{font-family:var(--font-display);font-size:.62rem;letter-spacing:.12em;
         text-transform:uppercase;color:var(--faint);margin-bottom:3px}
.yard dd{margin:0;font-family:var(--font-data);font-size:1.6rem;font-weight:600;color:var(--ink);
         font-variant-numeric:tabular-nums;line-height:1.1}
.yard dd small{font-size:.6rem;color:var(--faint);font-weight:400}
.yard.center dd{color:var(--pencil)}

.gps{display:flex;align-items:center;gap:11px;flex-wrap:wrap;
     background:var(--surface);border:1px solid var(--line);border-radius:3px;padding:12px 14px}
button.go{
  font-family:var(--font-display);font-size:.9rem;font-weight:700;letter-spacing:.06em;
  text-transform:uppercase;padding:9px 17px;border:1px solid var(--ink);background:var(--ink);
  color:var(--paper);border-radius:2px;cursor:pointer;
}
button.go[data-on="1"]{background:var(--surface);color:var(--ink)}
button.go:focus-visible{outline:2px solid var(--pencil);outline-offset:2px}
.status{font-family:var(--font-data);font-size:.74rem;color:var(--muted);flex:1;min-width:150px}
.status b{color:var(--ink);font-weight:600}
.status.err{color:var(--you)}

.note{font-size:.84rem;color:var(--muted);max-width:62ch}
.note code{font-family:var(--font-data);font-size:.9em;background:var(--sunk);padding:1px 4px;border-radius:2px}
footer{border-top:1px solid var(--line);padding-top:12px;color:var(--faint);
       font-family:var(--font-data);font-size:.7rem;line-height:1.7}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
"""

JS = r"""
const R = 6371000, M2Y = 1.09361;
const rad = d => d * Math.PI / 180;

function metres(a, b) {                     // haversine, metres
  const p1 = rad(a[0]), p2 = rad(b[0]);
  const dp = p2 - p1, dl = rad(b[1] - a[1]);
  const x = Math.sin(dp/2)**2 + Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;
  return 2 * R * Math.asin(Math.sqrt(x));
}
const yards = (a, b) => metres(a, b) * M2Y;

// local flat projection around a hole, then rotated so the hole plays upward
function makeProjection(hole) {
  const c = hole.center;
  const kx = Math.cos(rad(c[0])) * 111320, ky = 110540;
  const flat = p => [(p[1] - c[1]) * kx, (p[0] - c[0]) * ky];
  const tee = flat(backTee(hole)), pin = flat(hole.pin);
  const ang = Math.atan2(pin[0] - tee[0], pin[1] - tee[1]);   // bearing tee->pin
  const cs = Math.cos(-ang), sn = Math.sin(-ang);
  return p => { const [x, y] = flat(p); return [x*cs - y*sn, x*sn + y*cs]; };
}

function backTee(hole) {
  if (!hole.tees.length) return hole.line[0];
  let best = hole.tees[0][0], bd = -1;
  for (const t of hole.tees) { const d = metres(t[0], hole.pin); if (d > bd) { bd = d; best = t[0]; } }
  return best;
}

function routedYards(hole) {                 // along the centreline, not straight
  const pts = [backTee(hole), ...hole.line.slice(1), hole.pin];
  let m = 0;
  for (let i = 0; i < pts.length - 1; i++) m += metres(pts[i], pts[i+1]);
  return m * M2Y;
}

function greenEdges(hole, from) {             // front / back of the green
  if (!hole.green || !hole.green.length) return null;
  let lo = Infinity, hi = -Infinity;
  for (const p of hole.green) { const d = yards(from, p); if (d < lo) lo = d; if (d > hi) hi = d; }
  return { front: lo, back: hi };
}

let state = { nine: 0, ref: "1", pos: null, acc: null, watch: null };

function holesFor(n) {
  return COURSE.holes.filter(h => h.nine === n)
    .sort((a, b) => (+a.ref || 99) - (+b.ref || 99));
}
const current = () => holesFor(state.nine).find(h => h.ref === state.ref) || holesFor(state.nine)[0];

function render() {
  const hole = current();
  if (!hole) return;

  document.getElementById("hole-title").textContent = `${NINE_NAMES[state.nine]} · Hole ${hole.ref}`;
  document.getElementById("hole-par").textContent =
    `Par ${hole.par ?? "?"} · ${Math.round(routedYards(hole))} yd from the back tee`;

  const proj = makeProjection(hole);
  const parts = [hole.line, hole.green || [], ...(hole.tees || []), ...(hole.bunkers || []), [hole.pin]];
  const pts = parts.flat().filter(Boolean).map(proj);
  if (state.pos) pts.push(proj(state.pos));

  const pad = 22;
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
  const x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad;
  const y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
  const w = x1 - x0, h = y1 - y0;
  // screen y grows downward, and the hole should play up the page
  const S = p => `${(p[0] - x0).toFixed(1)},${(y1 - p[1]).toFixed(1)}`;
  const poly = (ps, cls) => ps.length ? `<polygon class="${cls}" points="${ps.map(proj).map(S).join(" ")}"/>` : "";

  let svg = "";
  for (const t of hole.tees || []) svg += poly(t, "g-tee");
  for (const b of hole.bunkers || []) svg += poly(b, "g-bunker");
  svg += `<polyline class="g-line" points="${hole.line.map(proj).map(S).join(" ")}"/>`;
  svg += poly(hole.green || [], "g-green");

  const pin = proj(hole.pin), P = S(pin);
  const [px, py] = P.split(",").map(Number);
  svg += `<line class="g-pin" x1="${px}" y1="${py}" x2="${px}" y2="${py - 13}"/>`;
  svg += `<polygon class="g-flag" points="${px},${py-13} ${px+9},${py-10} ${px},${py-7}"/>`;
  svg += `<circle class="g-pin" cx="${px}" cy="${py}" r="2.2"/>`;

  if (state.pos) {
    const me = S(proj(state.pos));
    const [mx, my] = me.split(",").map(Number);
    const accPx = state.acc ? Math.max(4, state.acc * (1)) : 0;   // metres == svg units
    svg += `<circle class="g-halo" cx="${mx}" cy="${my}" r="${accPx.toFixed(1)}"/>`;
    svg += `<line class="g-shot" x1="${mx}" y1="${my}" x2="${px}" y2="${py}"/>`;
    svg += `<circle class="g-you" cx="${mx}" cy="${my}" r="4.5"/>`;
  }

  document.getElementById("map").outerHTML =
    `<svg id="map" class="hole" viewBox="0 0 ${w.toFixed(1)} ${h.toFixed(1)}"
          role="img" aria-label="Hole ${hole.ref} layout, tee at the bottom">${svg}</svg>`;

  const from = state.pos || backTee(hole);
  const edge = greenEdges(hole, from);
  set("y-front", edge ? Math.round(edge.front) : "–");
  set("y-pin", Math.round(yards(from, hole.pin)));
  set("y-back", edge ? Math.round(edge.back) : "–");
  document.getElementById("y-source").textContent =
    state.pos ? "from your position" : "from the back tee";
}

const set = (id, v) => { document.getElementById(id).firstChild.nodeValue = v; };

function buildPickers() {
  const nineRow = document.getElementById("nines");
  nineRow.innerHTML = NINE_NAMES.map((n, i) =>
    `<button class="chip" data-nine="${i}" aria-pressed="${i === state.nine}">${n}</button>`).join("");
  const holeRow = document.getElementById("holes");
  holeRow.innerHTML = holesFor(state.nine).map(h =>
    `<button class="chip" data-ref="${h.ref}" aria-pressed="${h.ref === state.ref}">${h.ref}</button>`).join("");
}

document.addEventListener("click", e => {
  const b = e.target.closest("button.chip");
  if (!b) return;
  if (b.dataset.nine !== undefined) { state.nine = +b.dataset.nine; state.ref = holesFor(state.nine)[0].ref; }
  else if (b.dataset.ref !== undefined) { state.ref = b.dataset.ref; }
  buildPickers(); render();
});

const statusEl = () => document.getElementById("status");

document.getElementById("gps").addEventListener("click", function () {
  const on = this.dataset.on === "1";
  if (on) {
    navigator.geolocation.clearWatch(state.watch);
    state.watch = null; state.pos = null; state.acc = null;
    this.dataset.on = "0"; this.textContent = "Use my location";
    statusEl().className = "status";
    statusEl().innerHTML = "GPS off.";
    render();
    return;
  }
  if (!navigator.geolocation) {
    statusEl().className = "status err";
    statusEl().textContent = "This browser has no geolocation.";
    return;
  }
  statusEl().className = "status";
  statusEl().textContent = "Getting a fix…";
  this.dataset.on = "1"; this.textContent = "Stop";
  state.watch = navigator.geolocation.watchPosition(p => {
    state.pos = [p.coords.latitude, p.coords.longitude];
    state.acc = p.coords.accuracy;
    statusEl().className = "status";
    statusEl().innerHTML = `Live · accuracy <b>±${Math.round(p.coords.accuracy)} m</b>`;
    autoHole();
    render();
  }, err => {
    statusEl().className = "status err";
    statusEl().textContent = err.code === 1
      ? "Location permission denied — allow it in your browser settings."
      : "Couldn't get a fix. Open sky helps.";
    document.getElementById("gps").dataset.on = "0";
    document.getElementById("gps").textContent = "Use my location";
  }, { enableHighAccuracy: true, maximumAge: 2000, timeout: 15000 });
});

// jump to whichever hole you're standing on
function autoHole() {
  if (!document.getElementById("auto").checked || !state.pos) return;
  let best = null, bd = Infinity;
  for (const h of COURSE.holes) {
    const d = Math.min(metres(state.pos, h.pin), metres(state.pos, h.line[0]));
    if (d < bd) { bd = d; best = h; }
  }
  if (best && bd < 250 && (best.nine !== state.nine || best.ref !== state.ref)) {
    state.nine = best.nine; state.ref = best.ref; buildPickers();
  }
}

buildPickers();
render();
"""


def main():
    slug = sys.argv[1] if len(sys.argv) > 1 else "sunland"
    course = json.loads((HERE / "courses" / f"{slug}.json").read_text(encoding="utf-8"))

    nines = sorted({h["nine"] for h in course["holes"]})
    names = json.dumps(NINE_NAMES.get(slug) or [f"Nine {i+1}" for i in nines])

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow, noarchive">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#F2F4EE" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0F1714" media="(prefers-color-scheme: dark)">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ctext y='26' font-size='26'%3E%E2%9B%B3%3C/text%3E%3C/svg%3E">
<title>{course['name']} — yardages</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <p class="eyebrow">Live yardage · prototype</p>
    <h1>{course['name']}</h1>
    <p>{len(course['holes'])} holes mapped. Distances update from your phone's GPS as you walk.</p>
    <p style="margin-top:9px"><a class="back" href="./">← back to the tour</a></p>
  </header>

  <div class="picker">
    <div class="row"><span class="row-label">Nine</span></div>
    <div class="row" id="nines"></div>
    <div class="row"><span class="row-label">Hole</span></div>
    <div class="row" id="holes"></div>
  </div>

  <div class="stage">
    <div class="hole-head">
      <h2 id="hole-title">–</h2>
      <span class="par" id="hole-par"></span>
    </div>
    <svg id="map" class="hole" viewBox="0 0 100 100"></svg>
    <dl class="yards">
      <div class="yard"><dt>Front</dt><dd id="y-front">–</dd></div>
      <div class="yard center"><dt>Pin</dt><dd id="y-pin">–</dd></div>
      <div class="yard"><dt>Back</dt><dd id="y-back">–</dd></div>
    </dl>
  </div>

  <div class="gps">
    <button class="go" id="gps" data-on="0">Use my location</button>
    <span class="status" id="status">GPS off. Yardages shown are from the back tee.</span>
    <label style="font-family:var(--font-data);font-size:.74rem;color:var(--muted);display:flex;
                  align-items:center;gap:6px">
      <input type="checkbox" id="auto" checked> auto-pick hole
    </label>
  </div>

  <p class="note">
    <b>What this proves.</b> Every polygon here is real course geometry, pulled free from
    OpenStreetMap — greens, tee boxes, bunkers, centrelines. Yardages land within about 3% of
    the printed card. Nothing was hand-drawn and no data was bought.
    <span id="y-source" hidden></span>
  </p>
  <p class="note">
    <b>What it can't do yet.</b> The screen has to stay awake — phones suspend background
    JavaScript, so a web page can't track you with your pocket closed. That's the wall that
    pushes real shot tracking toward a native app.
  </p>

  <footer>
    Course geometry © OpenStreetMap contributors, ODbL. Pin positions are the mapped
    centre, not today's actual cup.
  </footer>
</div>
<script>
const COURSE = {json.dumps(course, separators=(",", ":"))};
const NINE_NAMES = {names};
{JS}
</script>
</body>
</html>
"""
    OUT.write_text(html, encoding="utf-8")
    print(f"{OUT}  ({OUT.stat().st_size // 1024} KB, {len(course['holes'])} holes)")


# Cluster order is west-to-east; for Sunland that lines up with these nines.
NINE_NAMES = {
    "sunland": ["Sunland", "Superstition", "San Tan"],
}

if __name__ == "__main__":
    main()
