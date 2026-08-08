# Bird to Boge — scorecard ledger

Photo of a scorecard in, dashboard out. Styled as a tabloid back page — every
round is a headline, every table is a box score. Everything lives in two files.

| File | What it is |
|---|---|
| `rounds.json` | The only source of truth: players, courses, every round |
| `build.py` | Reads `rounds.json`, writes `dashboard.html` (stdlib only, no deps) |
| `dashboard.html` | Generated. Never edit by hand — it gets overwritten |

## Adding a round

1. Send me the scorecard photo (front nine + back nine legible).
2. I read the hole-by-hole scores, append a round to `rounds.json`, rebuild, and republish to the same URL.

To rebuild by hand:

```bash
C:\Users\Jeremy\AppData\Local\Programs\Python\Python312\python.exe C:\Users\Jeremy\Cwod\golf\build.py
```

Drop the two sample rounds:

```bash
C:\Users\Jeremy\AppData\Local\Programs\Python\Python312\python.exe C:\Users\Jeremy\Cwod\golf\build.py --reset
```

## Data shape

```jsonc
{
  "group": "Saturday Golf",              // page title
  "tagline": "Rounds, standings, and who owes who.",
  "players": [
    { "id": "jeremy", "name": "Jeremy", "handicap": null }
  ],
  "courses": [
    {
      "id": "riverbend",
      "name": "Riverbend Muni",
      "par": [4,4,3,5,4,4,3,4,5, 4,5,3,4,4,3,4,4,5]   // 18 entries, front then back
    }
  ],
  "rounds": [
    {
      "date": "2026-08-02",              // YYYY-MM-DD, sorting depends on it
      "course": "riverbend",             // must match a course id
      "tees": "White",                   // optional
      "headline": "Jeremy nips it by one",      // optional, back-page headline; auto-written if omitted
      "deck": "Jeremy 84, Chris 85 — wind off the water all day.",  // optional subhead under the headline
      "notes": "Wind off the water all day.",   // optional
      "scores": {
        "jeremy": [5,4,4,6,4,5,3,5,6, 5,6,4,4,5,3,5,4,6]   // 18 entries; null for a hole not played
      },
      "money": { "jeremy": -8, "chris": 18 }              // optional, whole dollars, +/-
    }
  ]
}
```

Rules the builder follows:

- **Nine-hole rounds** — put `null` in the nine holes nobody played. Totals and standings adjust.
- **Someone sat out** — just leave them out of that round's `scores`. The card gets a field-size tag (Twosome, Threesome, Foursome) and lists who played, so a short group never reads as missing scores.
- **New player** — add to `players`, use the `id` in `scores`. Stats start from their first round.
- **New course** — add to `courses` with its par array. Different courses compare fine, since standings rank on strokes-to-par per hole.
- **Money is optional** — leave `money` off entirely and the dollar columns disappear.
- **Ties** — a shared low round counts as half a win each.
- **Headline and deck are optional** — leave them off and the builder writes a formulaic one from the scores (`"Jeremy wins by 4"`). Write your own when a round deserves better copy; that's most of them.

## What the page computes

- **Standings** — average strokes to par per hole, so a nine-hole round doesn't distort the table. Plus scoring average, best round, wins out of rounds played, birdies, running money, and a form line over the last eight rounds.
- **Beat rate** — appears once the tour has rounds with different group sizes. The share of head-to-head match-ups won (ties count a half), with the number faced in parentheses. Winning a twosome is one opponent beaten, winning a foursome is three, so field size stops flattering anyone.
- **Rounds** — a real scorecard grid per round: circles for birdie-or-better, squares for bogey-or-worse, OUT/IN/TOT, and the winner flagged. Each card is tagged with its field size. Once there are five or more rounds across mixed group sizes, a filter appears above them — All / Full field / Small groups. Standings always cover every round; the filter only narrows the list of cards.
- **Head to head** — low-gross record against each other person, counting only rounds you both played.
- **The holes** — once a course has two or more rounds, the three that play hardest and the three that give strokes back.
