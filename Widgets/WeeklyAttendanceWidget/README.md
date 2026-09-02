# Weekly Attendance Widget

Homepage widget for the latest Sunday worship attendance. Shows three tiles — **In Person**, **Online**, and **Total Attendance** — with week-over-week percent change.

| | |
|---|---|
| **TouchPoint type** | Homepage Widget (Python + SQL + HTML) |
| **Author** | Jake Pierson |
| **Write risk** | None — read-only `Meetings.HeadCount` |

---

## What it shows

- Latest Sunday that has a worship meeting (onsite involvement **35**, online **466**)
- **In Person** = 9:00 AM + 11:00 AM HeadCount, with those two counts as subtext
- **Online** = that Sunday’s online involvement HeadCount
- **Total** = In Person + Online
- Week-over-week **percent** on every tile, compared to the **previous calendar Sunday** (counts are 0 if that Sunday had no meetings)
- If last week’s count is 0, the percent is **—** (undefined)

### Missing head count

SQL marks a missing head count by returning a **negative** `MeetingId` (and also
never-null `*NeedsCount` flags). Display totals still coerce NULL → 0. A meeting
that exists with `HeadCount` **NULL** is not treated as a real 0. Instead:

- **9:00 AM / 11:00 AM** subtext shows **Add Head Count** → `/Meeting/{MeetingId}`
- **Online** tile value shows **Add Head Count** → that meeting
- An entered **0** still displays as 0
- Week-over-week percent is **—** on any tile that still has a missing count (so a fake 0 does not look like −100%)

Set the widget cache to **every page load** so the number updates after you enter head count and return to Home.

### Meeting links

- **9:00 AM** and **11:00 AM** subtext → that meeting (`/Meeting/{MeetingId}`)
- **Online** tile → that meeting
- **Total** has no single meeting, so it is not a link

---

## Install

Paste each file into the existing **Recent Worship Service** homepage widget (or a new widget with the same Special Content names):

| File | Paste into |
|------|------------|
| `WidgetRecentWorshipServicePython` | Widget **Python** |
| `WidgetRecentWorshipServiceSQL` | Widget **SQL** — Special Content name must stay `WidgetRecentWorshipServiceSQL` |
| `WidgetRecentWorshipServiceHTML` | Widget **HTML** |

Python prefers `Data.SQLContent` (whatever SQL Special Content is selected on the
homepage widget’s **Data (SQL)** dropdown), then falls back to
`model.SqlContent('WidgetRecentWorshipServiceSQL')`. After editing SQL, confirm
the widget dropdown still points at that Special Content.

On the widget’s cache settings, use **every page load** so Add count / numbers refresh after you save a meeting.

---

## Config

At the top of the SQL file:

| Variable | Default | Meaning |
|----------|---------|---------|
| `@OnsiteOrgId` | 35 | In-person worship involvement |
| `@OnlineOrgId` | 466 | Online worship involvement |
| `@NineHour` | 9 | Hour of the 9:00 AM meeting |
| `@ElevenHour` | 11 | Hour of the 11:00 AM meeting |

---

## Roles

Same as the homepage that embeds the widget. The script does not set `#Roles`.
