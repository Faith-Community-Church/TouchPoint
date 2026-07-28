# VBS Home Base

TouchPoint **PyScriptForm** for Vacation Bible School ops: group assignment, rosters, counts, attendance, allergies, and daily cash offering totals.

| | |
|---|---|
| **App title** | VBS Home Base 2026 |
| **Source (bvcms)** | [`VBSGroupTool.py`](../VBSGroupTool.py) |
| **Requirements** | [`VBS_Group_Tool_Requirements.md`](../VBS_Group_Tool_Requirements.md) |
| **Author** | Jake Pierson |
| **Runtime** | IronPython 2.7 inside TouchPoint |

---

## Run

Special Content → **Python Scripts** → paste the script (name can differ).

```text
/PyScriptForm/VBSGroupTool
```

If the Special Content entry is renamed (e.g. `VBSHomeBaseDashboard`), use that name instead. Internal links use `model.ScriptName` — do not hardcode the content name in the script.

---

## Roles

| Role | Access |
|------|--------|
| **Access** | View Home, lists, Counts, print views |
| **Admin** or **VBSAdmin** | Assign groups/roles |
| **Admin** | Settings (pool OrganizationIds, VBS week Monday) |

Header: `#Roles=Access`

---

## Features

### Home / Dashboard
- Enrolled count tiles (Volunteers, K-5, Pre-K, Nursery)
- **Weekly Attendance** — Mon–Fri present counts from Meetings + stacked chart
- **Cash Offerings** — manual Mon–Fri dollar totals (not Contributions)
- **Shepherding Insights** — `nohomechurch` SubGroup list + Decisions placeholder

### Master Lists
- Volunteers, K-5, Pre-K, Nursery rosters  
- T-Shirts, All Allergies (filtered placeholders; printable)

### VBS Ops
- **By Group** — one printable sheet per Group N (filter dropdown)
- **Group Leaders** — staffing cards (filter dropdown)
- **Counts** — headcounts + Enrolled / Mon–Fri attendance toggles + drill-down / Add to Tag

### Admin
- **Assign** — create Group N, place Small Group Leaders and K-5 kids
- **Settings** — pool OrgIds + VBS week start (Monday)

---

## Involvements (pools)

Defaults (overridable in Settings → JsonDocumentRecords):

| Pool | Default OrgId |
|------|----------------|
| Volunteers | 1894 |
| K-5 | 1893 |
| Pre-K | 1896 |
| Nursery | 1895 |

Only **Small Group Leader** volunteers get a Group N. Other service areas leave Group blank on the Volunteers list.

---

## Persistence (`custom.JsonDocumentRecords`)

Section: `VBS2026` (from `VBS_YEAR`)

| Id1 | Purpose |
|-----|---------|
| `settings` | Pool OrgIds + week start Monday |
| `groups` | Group N registry |
| `offerings` | Manual Mon–Fri cash totals for the current VBS week |

Assignments sync to involvement **SubGroups** (`AddSubGroup` / `RemoveSubGroup`) for check-in and rollsheets — not to Contribution/Transaction tables.

Offerings are a lightweight ops notepad: saved in JSON only. Changing the VBS week and saving again overwrites the single `offerings` record for the new week.

---

## Print

- Running page header matches the current view (e.g. `VBS All Allergies Master`, `VBS Home Base 2026 — By Group`)
- Footer: print timestamp
- Prefer **Default** margins (script sets `@page { margin: 0.75in }`)
- By Group: one group per page; top padding clears the running header

---

## Brand colors

| Role | Hex |
|------|-----|
| Primary | `#19283B` |
| Secondary | `#6699ea`, `#b5cfd9` |
| Tertiary | `#d2836a`, `#87d091` |

Nav: Master Lists → secondary blue · VBS Ops → green · Admin → tangerine · All Allergies → tangerine

---

## IronPython / PyScriptForm notes

- `except Exception, ex` (not `as`)
- UI on GET → `model.Form` (not `Output`)
- Prefer `model.DynamicData()` for SQL params
- Prefer string concat / token replace over `.format()` for large HTML
- Avoid CSS property name `content` near `{{{CONTENT}}}` tokens

---

## Deploy checklist

1. Paste latest script into Special Content → Python Scripts  
2. Confirm `#Roles=Access` and that **VBSAdmin** exists if staff need Assign  
3. Open Settings → set pool OrgIds + **VBS week start (Monday)**  
4. Create Mon–Fri **Meetings** on each pool for attendance  
5. Hard-refresh `/PyScriptForm/<name>`  

---

## Related

- Church packaging (optional): `TouchPoint-FCC/PythonTools/VBSHomeBase/`  
- Detailed v1 requirements: `VBS_Group_Tool_Requirements.md`

