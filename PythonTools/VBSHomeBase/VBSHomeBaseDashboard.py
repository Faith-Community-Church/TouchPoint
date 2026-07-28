#Roles=Access
# coding: utf-8
# Script: VBSGroupTool.py
# Purpose: Vacation Bible School group assignment and roster tool.
#   Pulls Leaders (1894), K-5 (1893), Pre-K (1896), and Nursery (1895).
#   Creates Group N registry; syncs SubGroups for check-in/rollsheets.
#   Leaders: primary service area + optional Also serves (Skits / Choreography).
#   Only Small Group Leader gets Group N; all service areas get a role.
#   Roles Leader / Co-leader / Assistant Leader on the Leaders involvement.
#   Admin or VBSAdmin may assign; everyone else is view-only.
#   View access (Access role) includes allergy/emergency fields from RecReg.
# Author: Jake Pierson
# Date: 2026-07-27
#
# Install: Special Content -> Python Scripts
#   Name may be VBSGroupTool or a rename (e.g. VBS Master Organizer).
#   Runtime URLs use model.ScriptName — do not hardcode the Special Content name in links.
# Run: /PyScriptForm/<Special Content name>
# Requirements: Scripts/VBS_Group_Tool_Requirements.md
#
# IronPython notes (TouchPoint embeds IronPython 2.7):
#   - Use print without parentheses; except Exception, ex
#   - Put UI in model.Form on GET (PyScriptForm ignores Output)
#   - Prefer model.DynamicData() for SQL params
#   - Prefer token replace / concat over .format() for large HTML
#   - Never rely on CSS property name "content" near {{{CONTENT}}} tokens

import json
try:
    import sys
    reload(sys)
    sys.setdefaultencoding('latin-1')
except:
    pass

# Do not hardcode the Special Content name -- live script may be renamed
# (e.g. "VBS Master Organizer"). Resolved at runtime via model.ScriptName.
VBS_YEAR = '2026'
APP_TITLE = 'VBS Home Base ' + VBS_YEAR
# Brand palette (VBS '26)
# Primary: #19283B
# Secondary: #6699ea, #b5cfd9
# Tertiary: #d2836a, #87d091
COLOR_PRIMARY = '#19283B'
COLOR_SECONDARY = '#6699ea'
COLOR_SECONDARY_LIGHT = '#b5cfd9'
COLOR_TERTIARY_WARM = '#d2836a'
COLOR_TERTIARY_GREEN = '#87d091'
JSON_SECTION = 'VBS' + VBS_YEAR
REGISTRY_ID1 = 'groups'
SETTINGS_ID1 = 'settings'
OFFERINGS_ID1 = 'offerings'  # manual Mon–Fri cash totals (not Contributions)

# Soft warnings from SQL/registry reads (shown once in the page banner).
_LOAD_WARNINGS = []

# Default pool OrganizationIds (overridden by Admin Settings tab / JsonDocumentRecords).
ORG_LEADERS = 1894
ORG_K5 = 1893
ORG_PREK = 1896
ORG_NURSERY = 1895
VBS_WEEK_START = ''  # YYYY-MM-DD Monday; from Settings or computed

POOLS = [
    ('leaders', ORG_LEADERS, 'Volunteers'),
    ('k5', ORG_K5, 'K-5'),
    ('prek', ORG_PREK, 'Pre-K'),
    ('nursery', ORG_NURSERY, 'Nursery'),
]
PARTICIPANT_ORG_IDS = (ORG_K5, ORG_PREK, ORG_NURSERY)
ALL_ORG_IDS = (ORG_LEADERS, ORG_K5, ORG_PREK, ORG_NURSERY)

ROLE_LEADER = 'Leader'
ROLE_COLEADER = 'Co-leader'
ROLE_ASSISTANT = 'Assistant Leader'
ROLE_NAMES = (ROLE_LEADER, ROLE_COLEADER, ROLE_ASSISTANT)
SINGLE_ROLES = (ROLE_LEADER, ROLE_COLEADER)  # one per group

# Service areas on Leaders involvement (SubGroups). Only Small Group Leader gets Group N.
SERVICE_SMALL_GROUP = 'Small Group Leader'
SERVICE_NURSERY = 'Nursery'
SERVICE_PREK = 'Pre-K'
SERVICE_CRAFTS = 'Crafts'
SERVICE_KITCHEN = 'Kitchen'
SERVICE_GAMES = 'Games'
SERVICE_SECURITY = 'Security'
SERVICE_SKITS = 'Skits'
SERVICE_CHOREOGRAPHY = 'Choreography'
SERVICE_AV_TECH = 'AV Tech'
SERVICE_OTHER = 'Other'
SERVICE_AREAS = (
    SERVICE_SMALL_GROUP,
    SERVICE_NURSERY,
    SERVICE_PREK,
    SERVICE_CRAFTS,
    SERVICE_KITCHEN,
    SERVICE_GAMES,
    SERVICE_SECURITY,
    SERVICE_SKITS,
    SERVICE_CHOREOGRAPHY,
    SERVICE_AV_TECH,
    SERVICE_OTHER,
)
# Can be primary OR secondary ("Also serves") without replacing the primary area.
SECONDARY_AREAS = (SERVICE_SKITS, SERVICE_CHOREOGRAPHY)
ALSO_PREFIX = 'Also: '

# Counts tab volunteer rows (non-classroom service areas)
SERVICE_COUNT_ROWS = (
    (SERVICE_CRAFTS, 'Crafts'),
    (SERVICE_KITCHEN, 'Kitchen'),
    (SERVICE_GAMES, 'Games'),
    (SERVICE_SECURITY, 'Security'),
    (SERVICE_SKITS, 'Skits'),
    (SERVICE_CHOREOGRAPHY, 'Choreography'),
    (SERVICE_AV_TECH, 'AV Tech'),
    (SERVICE_OTHER, 'Other'),
)

GROUP_PREFIX = 'Group '


def _also_tag(area_name):
    """SubGroup name for a secondary (Also serves) area."""
    return ALSO_PREFIX + _s(area_name)


def _parse_also_tag(tag_name):
    """Return secondary area name from 'Also: Skits', or ''."""
    s = _s(tag_name)
    if s.startswith(ALSO_PREFIX):
        area = s[len(ALSO_PREFIX):].strip()
        if area in SECONDARY_AREAS:
            return area
    return ''


def _split_pipe_names(raw):
    out = []
    for part in _s(raw).split('|'):
        part = part.strip()
        if part:
            out.append(part)
    return out


def _resolve_service_and_also(service_areas_raw, also_serves_raw):
    """
    Pick one primary service area + also-serves list.
    Legacy: multiple bare SERVICE_AREAS tags → non-secondary wins as primary;
    leftover SECONDARY_AREAS become also-serves.
    """
    areas = []
    seen = {}
    for a in _split_pipe_names(service_areas_raw):
        if a in SERVICE_AREAS and a not in seen:
            seen[a] = True
            areas.append(a)

    also = []
    also_seen = {}
    for tag in _split_pipe_names(also_serves_raw):
        area = _parse_also_tag(tag)
        if area and area not in also_seen:
            also_seen[area] = True
            also.append(area)

    primary = ''
    if len(areas) == 1:
        primary = areas[0]
    elif len(areas) > 1:
        for a in areas:
            if a not in SECONDARY_AREAS:
                primary = a
                break
        if not primary:
            primary = areas[0]
        for a in areas:
            if a != primary and a in SECONDARY_AREAS and a not in also_seen:
                also_seen[a] = True
                also.append(a)

    # Never list primary again under Also serves
    also = [a for a in also if a != primary]
    return primary, also


def _parse_also_serves_form(raw, primary):
    """Parse form also_serves (comma/pipe) into valid secondary list."""
    primary = _s(primary)
    out = []
    seen = {}
    for part in _s(raw).replace(';', ',').replace('|', ',').split(','):
        part = part.strip()
        if part in SECONDARY_AREAS and part != primary and part not in seen:
            seen[part] = True
            out.append(part)
    return out


def _service_display(person):
    """Primary service area, with (+ Also) when present."""
    area = _s(person.get('service_area')) or 'Unassigned'
    also = person.get('also_serves') or []
    if also:
        return area + ' (+ ' + ', '.join(also) + ')'
    return area


TITLE_MAP = {
    'home': 'Welcome',
    'assign': 'Assign',
    'settings': 'Settings',
    'leaders': 'Volunteers',
    'participants': 'K-5 Participants',
    'findgroup': 'Find Your Group (K-5)',
    'prek': 'Pre-K Roster',
    'nursery': 'Nursery Roster',
    'counts': 'Counts',
    'byleader': 'Group Leaders',
    'blocks': 'By Group',
    'allergies': 'All Allergies',
    'tshirts': 'T-Shirt Report',
}


def _print_doc_title(view):
    """Running print header + default Save-as PDF name for the current view."""
    view = _s(view)
    # Special / branded print document names
    if view == 'allergies':
        return 'VBS All Allergies Master'
    if view == 'findgroup':
        return 'VBS Find Your Group'
    if view == 'blocks':
        g = _s(_form_val('group', 'all'))
        if g and g.lower() != 'all':
            return APP_TITLE + ' — ' + g
        return APP_TITLE + ' — By Group'
    if view == 'byleader':
        g = _s(_form_val('group', 'all'))
        if g and g.lower() != 'all':
            return APP_TITLE + ' — ' + g + ' Leaders'
        return APP_TITLE + ' — Group Leaders'
    if view == 'tshirts':
        who = _s(_form_val('who', 'all')).lower()
        if who == 'volunteers':
            return 'VBS Volunteer T-Shirts'
        if who == 'participants':
            return 'VBS Participant T-Shirts'
        return 'VBS T-Shirt Report'
    label = TITLE_MAP.get(view, '')
    if label:
        return APP_TITLE + ' — ' + label
    return APP_TITLE


# Nav label + legend description for the cover page (Assign last; Settings added for Admin).
TAB_ITEMS = [
    ('leaders', 'Volunteers', 'Everyone on the volunteer team — see their service area, role, group, and any Also Serves (Skits / Choreography).'),
    ('participants', 'K-5', 'K–5 kids and which Group they are in. Print the full roster or a “Find Your Group” sheet on 11×17.'),
    ('prek', 'Pre-K', 'Kids in the Pre-K pool (students only).'),
    ('nursery', 'Nursery', 'Kids in the Nursery / zero-to-two pool (students only).'),
    ('tshirts', 'T-Shirts', 'Shirt sizes for volunteers or K–5/Pre-K participants — summary tiles plus a printable two-column list.'),
    ('allergies', 'All Allergies', 'Everyone with allergy notes on file across VBS — one combined list.'),
    ('blocks', 'By Group', 'One printable sheet per Group. Toggle T-Shirt and Allergies columns on/off for the student table.'),
    ('byleader', 'Group Leaders', 'Each Group with its Leader, Co-leader, and assistants — printable staffing list on 8.5×11.'),
    ('counts', 'Counts', 'Quick headcounts with drill-down lists (and Add to Tag): Pre-K & Nursery, volunteer areas, and each Group — printable on 8.5×11.'),
    ('assign', 'Assign', 'Create Groups and place leaders and K–5 kids. Requires Admin or VBSAdmin.'),
]

# Centered segmented nav: (segment label or '', [(view_key, tab_label), ...])
NAV_SEGMENTS = [
    ('', [('home', 'Home / Dashboard')]),
    ('Master Lists', [
        ('leaders', 'Volunteers'),
        ('participants', 'K-5'),
        ('prek', 'Pre-K'),
        ('nursery', 'Nursery'),
        ('tshirts', 'T-Shirts'),
        ('allergies', 'All Allergies'),
    ]),
    ('VBS Ops', [
        ('blocks', 'By Group'),
        ('byleader', 'Group Leaders'),
        ('counts', 'Counts'),
    ]),
    ('Admin', [
        ('assign', 'Assign'),
        ('settings', 'Settings'),
    ]),
]


def _is_null(val):
    if val is None:
        return True
    try:
        from System import DBNull
        if val is DBNull.Value:
            return True
    except:
        pass
    return False


def _s(val, default=''):
    if _is_null(val):
        return default
    try:
        if hasattr(val, 'ToString'):
            try:
                s = unicode(val.ToString()).strip()
            except:
                s = unicode(val).strip()
        else:
            s = unicode(val).strip()
    except:
        try:
            s = str(val).strip()
        except:
            return default
    if s == '' or s == 'None' or s == 'null':
        return default
    return s


def _i(val, default=None):
    s = _s(val)
    if not s:
        return default
    try:
        return int(s)
    except:
        try:
            return int(float(s))
        except:
            return default


def _html(val):
    try:
        s = _s(val)
    except:
        s = ''
    s = s.replace('&', '&amp;')
    s = s.replace('<', '&lt;')
    s = s.replace('>', '&gt;')
    s = s.replace('"', '&quot;')
    return s


def _allergy_text_meaningful(text):
    """True only when MedicalDescription looks like a real allergy note."""
    t = _s(text).lower()
    if not t:
        return False
    t = ' '.join(t.split())
    if not t:
        return False
    # Strip trailing punctuation for matches like "n/a." or "none."
    t_bare = t.rstrip('.,;:')
    ignore = (
        'none', 'n/a', 'na', 'n.a.', 'n.a', 'no', 'nope', '-', '--', '.',
        'none known', 'no known', 'no known allergies', 'n/a.', 'nil',
        'nothing', 'unknown', 'unk',
        'nka', 'nkda', 'n.k.a', 'n.k.a.', 'n.k.d.a', 'n.k.d.a.',
        'no allergies', 'no allergy', 'none listed', 'not applicable',
    )
    if t in ignore or t_bare in ignore:
        return False
    return True


def _person_has_allergy(med, allergy_text):
    """True only when allergy text is a real note (not blank / NA / NKA / none / no).

    MedAllergy bit alone does not count — empty or placeholder text is filtered out.
    """
    return _allergy_text_meaningful(allergy_text)


def _dd():
    return model.DynamicData()


def _warn(msg):
    """Record a non-fatal load/save warning for the page banner."""
    global _LOAD_WARNINGS
    msg = _s(msg)
    if msg and msg not in _LOAD_WARNINGS:
        _LOAD_WARNINGS.append(msg)


def _clear_warnings():
    global _LOAD_WARNINGS
    _LOAD_WARNINGS = []


def _ex_msg(ex):
    try:
        return _s(ex.ToString()) or str(ex)
    except:
        try:
            return str(ex)
        except:
            return 'Unknown error'


def _script_path():
    """PyScriptForm URL for this Special Content script (handles renamed scripts)."""
    name = ''
    try:
        name = _s(model.ScriptName)
    except:
        name = ''
    if not name:
        name = 'VBSGroupTool'
    try:
        enc = model.UrlEncode(name).replace('+', '%20')
    except:
        enc = name.replace(' ', '%20')
    return '/PyScriptForm/' + enc


def _form_val(name, default=''):
    """Read query/form value via model.Dictionary (reliable for PyScriptForm)."""
    try:
        v = model.Dictionary(name)
    except:
        v = None
    if v is None:
        return default
    return _s(v, default)


def _resolve_view(can_assign, can_admin=False):
    view = _form_val('view', '')
    if not view:
        view = _form_val('p1', '')
    view = _s(view).lower().replace(' ', '')
    aliases = {
        'leader': 'leaders',
        'participant': 'participants',
        'k5': 'participants',
        'findyourgroup': 'findgroup',
        'k5find': 'findgroup',
        'groupcounts': 'counts',
        'groupsbyleader': 'byleader',
        'groupblocks': 'blocks',
        'allergy': 'allergies',
        'allergyblocks': 'blocks',
        'allergybygroup': 'blocks',
        'blocksallergy': 'blocks',
        'blocks_allergy': 'blocks',
        'tshirt': 'tshirts',
        'tshirts': 'tshirts',
        'shirts': 'tshirts',
        'shirtsizes': 'tshirts',
    }
    if view in aliases:
        view = aliases[view]
    if view not in TITLE_MAP:
        view = 'home'
    if view == 'assign' and not can_assign:
        view = 'home'
    if view == 'settings' and not can_admin:
        view = 'home'
    return view


def _can_assign():
    return model.UserIsInRole('Admin') or model.UserIsInRole('VBSAdmin')


def _can_admin():
    return model.UserIsInRole('Admin')


def _default_org_config():
    return {
        'leaders': 1894,
        'k5': 1893,
        'prek': 1896,
        'nursery': 1895,
        'week_start': '',  # YYYY-MM-DD Monday of VBS week (optional)
    }


def _apply_org_config(cfg):
    """Refresh module-level org IDs used by SQL and write paths."""
    global ORG_LEADERS, ORG_K5, ORG_PREK, ORG_NURSERY, VBS_WEEK_START
    global POOLS, PARTICIPANT_ORG_IDS, ALL_ORG_IDS
    defaults = _default_org_config()
    if not cfg:
        cfg = defaults
    ORG_LEADERS = _i(cfg.get('leaders'), defaults['leaders'])
    ORG_K5 = _i(cfg.get('k5'), defaults['k5'])
    ORG_PREK = _i(cfg.get('prek'), defaults['prek'])
    ORG_NURSERY = _i(cfg.get('nursery'), defaults['nursery'])
    VBS_WEEK_START = _s(cfg.get('week_start'), '')
    POOLS = [
        ('leaders', ORG_LEADERS, 'Volunteers'),
        ('k5', ORG_K5, 'K-5'),
        ('prek', ORG_PREK, 'Pre-K'),
        ('nursery', ORG_NURSERY, 'Nursery'),
    ]
    PARTICIPANT_ORG_IDS = (ORG_K5, ORG_PREK, ORG_NURSERY)
    ALL_ORG_IDS = (ORG_LEADERS, ORG_K5, ORG_PREK, ORG_NURSERY)


def _load_settings():
    """Load pool org IDs from JsonDocumentRecords (falls back to defaults)."""
    cfg = _default_org_config()
    try:
        sql = """
SELECT TOP 1 [Json]
FROM custom.JsonDocumentRecords
WHERE Section = @section AND Id1 = @id1 AND Id2 = '' AND Id3 = '' AND Id4 = ''
"""
        p = _dd()
        p.AddValue('section', JSON_SECTION)
        p.AddValue('id1', SETTINGS_ID1)
        rows = list(q.QuerySql(sql, p))
    except Exception, ex:
        _warn('Settings read failed: ' + _ex_msg(ex))
        return cfg
    if not rows:
        return cfg
    raw = _s(rows[0].Json)
    if not raw:
        return cfg
    try:
        data = json.loads(raw)
    except:
        return cfg
    key_map = {
        'leaders': ('Leaders', 'OrgLeaders', 'leaders', 'ORG_LEADERS'),
        'k5': ('K5', 'OrgK5', 'k5', 'ORG_K5'),
        'prek': ('PreK', 'OrgPreK', 'prek', 'ORG_PREK'),
        'nursery': ('Nursery', 'OrgNursery', 'nursery', 'ORG_NURSERY'),
    }
    for dest, aliases in key_map.items():
        for ak in aliases:
            if ak in data:
                val = _i(data.get(ak))
                if val and val > 0:
                    cfg[dest] = val
                    break
    for ak in ('WeekStart', 'week_start', 'VbsWeekStart'):
        if ak in data:
            ws = _s(data.get(ak))
            if len(ws) >= 10:
                cfg['week_start'] = ws[:10]
                break
    return cfg


def _persist_settings(cfg):
    try:
        dd = _dd()
        dd.AddValue('Leaders', cfg['leaders'])
        dd.AddValue('K5', cfg['k5'])
        dd.AddValue('PreK', cfg['prek'])
        dd.AddValue('Nursery', cfg['nursery'])
        dd.AddValue('WeekStart', _s(cfg.get('week_start')))
        model.AddUpdateJsonRecord(dd, JSON_SECTION, SETTINGS_ID1)
        return True, 'Pool involvements saved.'
    except Exception, ex:
        return False, 'Settings save failed: ' + _ex_msg(ex)


def _parse_money(raw):
    """Parse a dollar amount from form/JSON text → float >= 0."""
    s = _s(raw).replace(',', '').replace('$', '').strip()
    if not s:
        return 0.0
    try:
        n = float(s)
    except:
        return 0.0
    if n < 0:
        return 0.0
    return n


def _format_money(n):
    """Display as $1,234.56."""
    try:
        n = float(n)
    except:
        n = 0.0
    if n < 0:
        n = 0.0
    s = '%.2f' % n
    parts = s.split('.')
    whole = parts[0]
    dec = parts[1] if len(parts) > 1 else '00'
    # thousand separators (IronPython 2.7 — no f-strings)
    neg = ''
    if whole.startswith('-'):
        neg = '-'
        whole = whole[1:]
    out = ''
    while len(whole) > 3:
        out = ',' + whole[-3:] + out
        whole = whole[:-3]
    out = whole + out
    return '$' + neg + out + '.' + dec


def _default_offerings(week_start=''):
    return {
        'week_start': _s(week_start),
        'mon': 0.0,
        'tue': 0.0,
        'wed': 0.0,
        'thu': 0.0,
        'fri': 0.0,
    }


def _load_offerings():
    """Load manual cash offering totals for the current VBS week (soft-fail).

    If stored week_start does not match current VBS Monday, return zeros for the new week.
    """
    mon = _vbs_week_monday_ymd()
    data = _default_offerings(mon)
    try:
        sql = """
SELECT TOP 1 [Json]
FROM custom.JsonDocumentRecords
WHERE Section = @section AND Id1 = @id1 AND Id2 = '' AND Id3 = '' AND Id4 = ''
"""
        p = _dd()
        p.AddValue('section', JSON_SECTION)
        p.AddValue('id1', OFFERINGS_ID1)
        rows = list(q.QuerySql(sql, p))
    except Exception, ex:
        _warn('Offerings read failed: ' + _ex_msg(ex))
        return data
    if not rows:
        return data
    raw = _s(rows[0].Json)
    if not raw:
        return data
    try:
        parsed = json.loads(raw)
    except:
        return data
    stored_week = ''
    for ak in ('WeekStart', 'week_start'):
        if ak in parsed:
            stored_week = _s(parsed.get(ak))[:10]
            break
    if mon and stored_week and stored_week != mon:
        # Different VBS week — start clean rather than showing last week's totals
        return data
    day_aliases = {
        'mon': ('Mon', 'mon', 'Monday'),
        'tue': ('Tue', 'tue', 'Tuesday'),
        'wed': ('Wed', 'wed', 'Wednesday'),
        'thu': ('Thu', 'thu', 'Thursday'),
        'fri': ('Fri', 'fri', 'Friday'),
    }
    for day, aliases in day_aliases.items():
        for ak in aliases:
            if ak in parsed:
                data[day] = _parse_money(parsed.get(ak))
                break
    data['week_start'] = mon or stored_week
    return data


def _persist_offerings(data):
    """Save Mon–Fri cash totals to JsonDocumentRecords (not Contributions)."""
    try:
        dd = _dd()
        dd.AddValue('WeekStart', _s(data.get('week_start')))
        # Store as decimal strings for stable JsonDocumentRecords serialization
        dd.AddValue('Mon', '%.2f' % _parse_money(data.get('mon')))
        dd.AddValue('Tue', '%.2f' % _parse_money(data.get('tue')))
        dd.AddValue('Wed', '%.2f' % _parse_money(data.get('wed')))
        dd.AddValue('Thu', '%.2f' % _parse_money(data.get('thu')))
        dd.AddValue('Fri', '%.2f' % _parse_money(data.get('fri')))
        model.AddUpdateJsonRecord(dd, JSON_SECTION, OFFERINGS_ID1)
        return True, 'Cash offerings saved.'
    except Exception, ex:
        return False, 'Offerings save failed: ' + _ex_msg(ex)


def _save_offerings_from_form():
    if not _can_assign():
        return False, 'Admin or VBSAdmin required to save cash offerings.'
    mon = _vbs_week_monday_ymd()
    data = {
        'week_start': mon,
        'mon': _parse_money(_form_val('off_mon')),
        'tue': _parse_money(_form_val('off_tue')),
        'wed': _parse_money(_form_val('off_wed')),
        'thu': _parse_money(_form_val('off_thu')),
        'fri': _parse_money(_form_val('off_fri')),
    }
    return _persist_offerings(data)


def _org_name(org_id):
    org_id = _i(org_id)
    if not org_id:
        return ''
    try:
        p = _dd()
        p.AddValue('oid', org_id)
        rows = list(q.QuerySql(
            'SELECT TOP 1 OrganizationName FROM dbo.Organizations WHERE OrganizationId = @oid',
            p,
        ))
        if rows:
            return _s(rows[0].OrganizationName)
    except:
        pass
    return ''


def _org_hero_url(org_id):
    """Sites/Mobile title graphic or Organizations.ImageUrl (same source as InvolvementDashboard)."""
    org_id = _i(org_id)
    if not org_id:
        return ''
    try:
        sql = """
SELECT TOP 1 COALESCE(
    NULLIF(LTRIM(RTRIM(oe.Data)), ''),
    NULLIF(LTRIM(RTRIM(oe.StrValue)), ''),
    NULLIF(LTRIM(RTRIM(o.ImageUrl)), '')
) AS TitleGraphicUrl
FROM dbo.Organizations o
LEFT JOIN dbo.Setting s ON s.Id = 'SitesDataHeroImageEv'
LEFT JOIN dbo.OrganizationExtra oe
    ON oe.OrganizationId = o.OrganizationId
   AND s.Setting IS NOT NULL
   AND LTRIM(RTRIM(s.Setting)) <> ''
   AND oe.Field = s.Setting
WHERE o.OrganizationId = @oid
"""
        p = _dd()
        p.AddValue('oid', org_id)
        rows = list(q.QuerySql(sql, p))
        if rows:
            return _s(rows[0].TitleGraphicUrl)
    except:
        pass
    return ''


def _save_pool_settings():
    if not _can_admin():
        return False, 'Admin role required to change settings.'
    leaders = _i(_form_val('org_leaders'))
    k5 = _i(_form_val('org_k5'))
    prek = _i(_form_val('org_prek'))
    nursery = _i(_form_val('org_nursery'))
    if not leaders or not k5 or not prek or not nursery:
        return False, 'Enter a valid OrganizationId for each pool.'
    if leaders <= 0 or k5 <= 0 or prek <= 0 or nursery <= 0:
        return False, 'OrganizationIds must be positive integers.'
    ids = [leaders, k5, prek, nursery]
    if len(set(ids)) < 4:
        return False, 'Each pool must use a different involvement.'
    missing = []
    labels = ['Volunteers', 'K-5', 'Pre-K', 'Nursery']
    for oid, label in zip(ids, labels):
        if not _org_name(oid):
            missing.append(label + ' (' + str(oid) + ')')
    if missing:
        return False, 'Involvement not found: ' + ', '.join(missing)
    cfg = {
        'leaders': leaders,
        'k5': k5,
        'prek': prek,
        'nursery': nursery,
        'week_start': _s(_form_val('week_start')),
    }
    ws = cfg['week_start']
    if ws and len(ws) >= 10:
        cfg['week_start'] = ws[:10]
    else:
        cfg['week_start'] = ''
    ok, message = _persist_settings(cfg)
    if ok:
        _apply_org_config(cfg)
    return ok, message


def _is_group_name(name):
    name = _s(name)
    if not name.startswith(GROUP_PREFIX):
        return False
    rest = name[len(GROUP_PREFIX):]
    if not rest:
        return False
    try:
        n = int(rest)
    except:
        return False
    return n > 0 and str(n) == rest


def _group_number(name):
    if not _is_group_name(name):
        return None
    return _i(name[len(GROUP_PREFIX):])


def _group_name(n):
    return GROUP_PREFIX + str(int(n))


def _pool_label(org_id):
    for key, oid, label in POOLS:
        if oid == org_id:
            return label
    return 'Org ' + str(org_id)


def _pool_key(org_id):
    for key, oid, label in POOLS:
        if oid == org_id:
            return key
    return ''


def _show(html):
    if model.HttpMethod == 'get':
        model.Form = html
    else:
        print html


def _redirect(msg='', view=''):
    qs = []
    if view:
        qs.append('view=' + view)
    if msg:
        qs.append('msg=' + model.UrlEncode(msg))
    url = _script_path()
    if qs:
        url = url + '?' + '&'.join(qs)
    print 'REDIRECT=' + url


# ---------------------------------------------------------------------------
# Registry (empty Group Ns before anyone is assigned)
# ---------------------------------------------------------------------------

def _load_registry_groups():
    """Return sorted list of Group N names from JsonDocumentRecords (soft-fail)."""
    try:
        sql = """
SELECT TOP 1 [Json]
FROM custom.JsonDocumentRecords
WHERE Section = @section AND Id1 = @id1 AND Id2 = '' AND Id3 = '' AND Id4 = ''
"""
        p = _dd()
        p.AddValue('section', JSON_SECTION)
        p.AddValue('id1', REGISTRY_ID1)
        rows = list(q.QuerySql(sql, p))
    except Exception, ex:
        _warn('Group registry read failed: ' + _ex_msg(ex))
        return []
    names = []
    if rows:
        raw = _s(rows[0].Json)
        if raw:
            pipe = ''
            try:
                data = json.loads(raw)
                pipe = _s(data.get('Groups', ''))
            except:
                pipe = ''
            if not pipe and 'Group ' in raw:
                pipe = raw
            for part in pipe.split('|'):
                part = part.strip().strip('"').strip("'")
                if _is_group_name(part):
                    names.append(part)
    return _unique_sorted_groups(names)


def _save_registry_groups(names):
    """Persist Group N list. Returns (ok, message)."""
    names = _unique_sorted_groups(names)
    try:
        dd = _dd()
        dd.AddValue('Groups', '|'.join(names))
        model.AddUpdateJsonRecord(dd, JSON_SECTION, REGISTRY_ID1)
        return True, ''
    except Exception, ex:
        return False, 'Group registry save failed: ' + _ex_msg(ex)


def _unique_sorted_groups(names):
    seen = {}
    out = []
    for n in names:
        if _is_group_name(n) and n not in seen:
            seen[n] = True
            out.append(n)
    out.sort(key=lambda x: _group_number(x))
    return out


def _discover_subgroup_groups():
    """Group N names that already exist as MemberTags on any VBS org (soft-fail)."""
    try:
        sql = """
SELECT DISTINCT mt.Name
FROM dbo.MemberTags mt
WHERE mt.OrgId IN (@o1, @o2, @o3, @o4)
  AND mt.Name LIKE @pat
"""
        p = _dd()
        p.AddValue('o1', ORG_LEADERS)
        p.AddValue('o2', ORG_K5)
        p.AddValue('o3', ORG_PREK)
        p.AddValue('o4', ORG_NURSERY)
        p.AddValue('pat', GROUP_PREFIX + '%')
        rows = list(q.QuerySql(sql, p))
    except Exception, ex:
        _warn('SubGroup discovery failed: ' + _ex_msg(ex))
        return []
    names = []
    for r in rows:
        name = _s(r.Name)
        if _is_group_name(name):
            names.append(name)
    return names


def _all_group_names():
    try:
        return _unique_sorted_groups(_load_registry_groups() + _discover_subgroup_groups())
    except Exception, ex:
        _warn('Group list failed: ' + _ex_msg(ex))
        return []


def _next_group_name():
    names = _all_group_names()
    max_n = 0
    for n in names:
        num = _group_number(n)
        if num and num > max_n:
            max_n = num
    return _group_name(max_n + 1)


def _create_group():
    if not _can_assign():
        return False, 'Not authorized to create groups.'
    name = _next_group_name()
    names = _all_group_names()
    if name not in names:
        names.append(name)
    ok, err = _save_registry_groups(names)
    if not ok:
        return False, err or ('Could not create ' + name + '.')
    return True, 'Created ' + name + '.'


# ---------------------------------------------------------------------------
# People / SubGroup reads
# ---------------------------------------------------------------------------

def _load_pool(org_id, members_only=False):
    """Load one involvement roster. Returns [] on failure (never throws).
    members_only: keep MemberType Description = Member (exclude Leader, etc.).
    """
    try:
        p = _dd()
        p.AddValue('orgId', org_id)
        sql = """
SELECT
    om.OrganizationId,
    om.PeopleId,
    p.FirstName,
    p.LastName,
    ISNULL(p.Name2, LTRIM(RTRIM(ISNULL(p.FirstName,'') + ' ' + ISNULL(p.LastName,'')))) AS PersonName,
    p.Age,
    g.Description AS Gender,
    gl.Description AS Grade,
    mtype.Description AS MemberTypeName,
    rr.emcontact AS EmContact,
    rr.emphone AS EmPhone,
    rr.MedAllergy,
    rr.MedicalDescription AS AllergyText,
    (
        SELECT TOP 1 mt.Name
        FROM dbo.OrgMemMemTags omt
        INNER JOIN dbo.MemberTags mt ON mt.Id = omt.MemberTagId AND mt.OrgId = omt.OrgId
        WHERE omt.OrgId = om.OrganizationId
          AND omt.PeopleId = om.PeopleId
          AND mt.Name LIKE @gpat
        ORDER BY mt.Name
    ) AS GroupName,
    (
        SELECT STUFF((
            SELECT N'|' + mt2.Name
            FROM dbo.OrgMemMemTags omt2
            INNER JOIN dbo.MemberTags mt2 ON mt2.Id = omt2.MemberTagId AND mt2.OrgId = omt2.OrgId
            WHERE omt2.OrgId = om.OrganizationId
              AND omt2.PeopleId = om.PeopleId
              AND mt2.Name IN (N'Leader', N'Co-leader', N'Assistant Leader')
            FOR XML PATH(''), TYPE
        ).value('.', 'nvarchar(max)'), 1, 1, N'')
    ) AS RoleNames,
    (
        SELECT STUFF((
            SELECT N'|' + mt3.Name
            FROM dbo.OrgMemMemTags omt3
            INNER JOIN dbo.MemberTags mt3 ON mt3.Id = omt3.MemberTagId AND mt3.OrgId = omt3.OrgId
            WHERE omt3.OrgId = om.OrganizationId
              AND omt3.PeopleId = om.PeopleId
              AND mt3.Name IN (
                  N'Small Group Leader', N'Nursery', N'Pre-K', N'Crafts',
                  N'Kitchen', N'Games', N'Security', N'Skits', N'Choreography',
                  N'AV Tech', N'Other'
              )
            FOR XML PATH(''), TYPE
        ).value('.', 'nvarchar(max)'), 1, 1, N'')
    ) AS ServiceAreas,
    (
        SELECT STUFF((
            SELECT N'|' + mt4.Name
            FROM dbo.OrgMemMemTags omt4
            INNER JOIN dbo.MemberTags mt4 ON mt4.Id = omt4.MemberTagId AND mt4.OrgId = omt4.OrgId
            WHERE omt4.OrgId = om.OrganizationId
              AND omt4.PeopleId = om.PeopleId
              AND mt4.Name IN (N'Also: Skits', N'Also: Choreography')
            FOR XML PATH(''), TYPE
        ).value('.', 'nvarchar(max)'), 1, 1, N'')
    ) AS AlsoServes,
    COALESCE(NULLIF(LTRIM(RTRIM(om.ShirtSize)), N''), ss.Description) AS ShirtSize
FROM dbo.OrganizationMembers om
INNER JOIN dbo.People p ON p.PeopleId = om.PeopleId
LEFT JOIN lookup.Gender g ON g.Id = p.GenderId
LEFT JOIN lookup.GradeLevel gl ON gl.Id = p.GradeLevelId
LEFT JOIN lookup.MemberType mtype ON mtype.Id = om.MemberTypeId
LEFT JOIN lookup.ShirtSize ss ON ss.Id = p.ShirtSizeId
LEFT JOIN dbo.RecReg rr ON rr.PeopleId = p.PeopleId
WHERE om.OrganizationId = @orgId
  AND ISNULL(p.IsDeceased, 0) = 0
ORDER BY p.LastName, p.FirstName
"""
        p.AddValue('gpat', GROUP_PREFIX + '%')
        rows = list(q.QuerySql(sql, p))
    except Exception, ex:
        _warn('Roster load failed for org ' + str(org_id) + ': ' + _ex_msg(ex))
        return []

    people = []
    for r in rows:
        try:
            mtype_name = _s(r.MemberTypeName)
            if members_only and mtype_name.lower() != 'member':
                continue
            roles = []
            for part in _s(r.RoleNames).split('|'):
                part = part.strip()
                if part:
                    roles.append(part)
            allergy = _s(r.AllergyText)
            med = r.MedAllergy
            has_allergy = _person_has_allergy(med, allergy)
            # Display blank for placeholder none/N/A text
            if not _allergy_text_meaningful(allergy):
                allergy = ''
            em = _s(r.EmContact)
            phone = _s(r.EmPhone)
            if em and phone:
                emergency = em + ' / ' + phone
            else:
                emergency = em or phone
            gname = _s(r.GroupName)
            if gname and not _is_group_name(gname):
                gname = ''
            age_val = _i(r.Age)
            if age_val is None:
                age_band = 'Unknown'
            elif age_val >= 18:
                age_band = 'Adult'
            else:
                age_band = 'Minor'
            service_raw = ''
            also_raw = ''
            try:
                service_raw = _s(r.ServiceAreas)
            except:
                try:
                    service_raw = _s(r.ServiceArea)
                except:
                    service_raw = ''
            try:
                also_raw = _s(r.AlsoServes)
            except:
                also_raw = ''
            service_area, also_serves = _resolve_service_and_also(service_raw, also_raw)
            shirt_size = ''
            try:
                shirt_size = _s(r.ShirtSize)
            except:
                shirt_size = ''
            people.append({
                'org_id': _i(r.OrganizationId),
                'people_id': _i(r.PeopleId),
                'first': _s(r.FirstName),
                'last': _s(r.LastName),
                'name': _s(r.PersonName, '(Unknown)'),
                'age': _s(r.Age),
                'age_band': age_band,
                'gender': _s(r.Gender),
                'grade': _s(r.Grade),
                'member_type': mtype_name,
                'emergency': emergency,
                'allergy': allergy,
                'has_allergy': has_allergy,
                'group': gname if gname else 'Unassigned',
                'group_raw': gname,
                'roles': roles,
                'role_display': ', '.join(roles) if roles else '',
                'service_area': service_area,
                'also_serves': also_serves,
                'shirt_size': shirt_size,
            })
        except:
            continue
    return people


def _load_all_pools():
    data = {}
    for key, oid, label in POOLS:
        # Kid pools: Member member-type only (exclude Leader, etc.)
        members_only = oid in PARTICIPANT_ORG_IDS
        data[key] = {
            'org_id': oid,
            'label': label,
            'people': _load_pool(oid, members_only=members_only),
        }
    return data


def _person_in_org(people_id, org_id):
    return model.InOrg(people_id, org_id)


def _current_group_subgroups(people_id, org_id):
    """Return Group N subgroup names currently on this membership."""
    sql = """
SELECT mt.Name
FROM dbo.OrgMemMemTags omt
INNER JOIN dbo.MemberTags mt ON mt.Id = omt.MemberTagId AND mt.OrgId = omt.OrgId
WHERE omt.OrgId = @orgId AND omt.PeopleId = @pid AND mt.Name LIKE @gpat
"""
    p = _dd()
    p.AddValue('orgId', org_id)
    p.AddValue('pid', people_id)
    p.AddValue('gpat', GROUP_PREFIX + '%')
    rows = list(q.QuerySql(sql, p))
    out = []
    for r in rows:
        name = _s(r.Name)
        if _is_group_name(name):
            out.append(name)
    return out


def _current_role_subgroups(people_id, org_id):
    sql = """
SELECT mt.Name
FROM dbo.OrgMemMemTags omt
INNER JOIN dbo.MemberTags mt ON mt.Id = omt.MemberTagId AND mt.OrgId = omt.OrgId
WHERE omt.OrgId = @orgId AND omt.PeopleId = @pid
  AND mt.Name IN (N'Leader', N'Co-leader', N'Assistant Leader')
"""
    p = _dd()
    p.AddValue('orgId', org_id)
    p.AddValue('pid', people_id)
    rows = list(q.QuerySql(sql, p))
    return [_s(r.Name) for r in rows if _s(r.Name)]


def _current_service_subgroups(people_id):
    """Primary service-area SubGroups currently on the Leaders membership."""
    sql = """
SELECT mt.Name
FROM dbo.OrgMemMemTags omt
INNER JOIN dbo.MemberTags mt ON mt.Id = omt.MemberTagId AND mt.OrgId = omt.OrgId
WHERE omt.OrgId = @orgId AND omt.PeopleId = @pid
  AND mt.Name IN (
      N'Small Group Leader', N'Nursery', N'Pre-K', N'Crafts',
      N'Kitchen', N'Games', N'Security', N'Skits', N'Choreography',
      N'AV Tech', N'Other'
  )
"""
    p = _dd()
    p.AddValue('orgId', ORG_LEADERS)
    p.AddValue('pid', people_id)
    rows = list(q.QuerySql(sql, p))
    return [_s(r.Name) for r in rows if _s(r.Name)]


def _current_also_subgroups(people_id):
    """Also-serves SubGroups (Also: Skits / Also: Choreography)."""
    sql = """
SELECT mt.Name
FROM dbo.OrgMemMemTags omt
INNER JOIN dbo.MemberTags mt ON mt.Id = omt.MemberTagId AND mt.OrgId = omt.OrgId
WHERE omt.OrgId = @orgId AND omt.PeopleId = @pid
  AND mt.Name IN (N'Also: Skits', N'Also: Choreography')
"""
    p = _dd()
    p.AddValue('orgId', ORG_LEADERS)
    p.AddValue('pid', people_id)
    rows = list(q.QuerySql(sql, p))
    return [_s(r.Name) for r in rows if _s(r.Name)]


def _leaders_in_group_with_role(group_name, role_name):
    """People on leaders org who have both group_name and role_name."""
    sql = """
SELECT omt.PeopleId
FROM dbo.OrgMemMemTags omt
INNER JOIN dbo.MemberTags mt ON mt.Id = omt.MemberTagId AND mt.OrgId = omt.OrgId
WHERE omt.OrgId = @orgId AND mt.Name = @gname
  AND EXISTS (
      SELECT 1
      FROM dbo.OrgMemMemTags omt2
      INNER JOIN dbo.MemberTags mt2 ON mt2.Id = omt2.MemberTagId AND mt2.OrgId = omt2.OrgId
      WHERE omt2.OrgId = @orgId AND omt2.PeopleId = omt.PeopleId AND mt2.Name = @role
  )
"""
    p = _dd()
    p.AddValue('orgId', ORG_LEADERS)
    p.AddValue('gname', group_name)
    p.AddValue('role', role_name)
    rows = list(q.QuerySql(sql, p))
    return [_i(r.PeopleId) for r in rows]


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def _clear_group_subgroups(people_id, org_id):
    for g in _current_group_subgroups(people_id, org_id):
        model.RemoveSubGroup(people_id, org_id, g)


def _clear_role_subgroups(people_id):
    for r in _current_role_subgroups(people_id, ORG_LEADERS):
        model.RemoveSubGroup(people_id, ORG_LEADERS, r)


def _clear_service_subgroups(people_id):
    for s in _current_service_subgroups(people_id):
        model.RemoveSubGroup(people_id, ORG_LEADERS, s)
    for s in _current_also_subgroups(people_id):
        model.RemoveSubGroup(people_id, ORG_LEADERS, s)


def _clear_leader_tags(people_id):
    """Clear service area, also-serves, role, and Group N on Leaders org."""
    _clear_service_subgroups(people_id)
    _clear_role_subgroups(people_id)
    _clear_group_subgroups(people_id, ORG_LEADERS)


def _apply_also_serves(people_id, also_list):
    for area in also_list or []:
        if area in SECONDARY_AREAS:
            model.AddSubGroup(people_id, ORG_LEADERS, _also_tag(area))


def _assign_group(people_id, org_id, group_name):
    if not _can_assign():
        return False, 'Not authorized to assign.'
    people_id = _i(people_id)
    org_id = _i(org_id)
    group_name = _s(group_name)
    if not people_id or not org_id:
        return False, 'Missing person or involvement.'
    if group_name != 'Unassigned' and not _is_group_name(group_name):
        return False, 'Invalid group name.'
    if org_id not in ALL_ORG_IDS:
        return False, 'Invalid involvement.'
    if not model.InOrg(people_id, org_id):
        return False, 'Person is not enrolled in that involvement.'

    _clear_group_subgroups(people_id, org_id)
    if group_name == 'Unassigned' or not group_name:
        return True, 'Cleared group assignment.'

    # Ensure registry knows this group (SubGroup is still applied if registry save fails)
    names = _all_group_names()
    reg_note = ''
    if group_name not in names:
        names.append(group_name)
        ok, err = _save_registry_groups(names)
        if not ok:
            reg_note = ' Note: ' + err

    model.AddSubGroup(people_id, org_id, group_name)
    return True, 'Assigned to ' + group_name + '.' + reg_note


def _assign_role(people_id, role_name, group_name, service_area='', also_serves=''):
    """
    Assign leader primary service area + role on Leaders org.
    Optional Also serves: Skits / Choreography (stored as Also: … tags).
    Small Group Leader also gets one Group N; other areas never get a Group N.
    """
    if not _can_assign():
        return False, 'Not authorized to assign.'
    people_id = _i(people_id)
    role_name = _s(role_name)
    group_name = _s(group_name)
    service_area = _s(service_area)
    also_list = _parse_also_serves_form(also_serves, service_area)
    if not people_id:
        return False, 'Missing person.'
    if not model.InOrg(people_id, ORG_LEADERS):
        return False, 'Person must be enrolled in the Leaders involvement.'

    # Unassigned / blank service area clears everything
    if not service_area or service_area == 'Unassigned':
        _clear_leader_tags(people_id)
        return True, 'Cleared leader assignment.'

    if service_area not in SERVICE_AREAS:
        return False, 'Invalid service area.'
    if role_name not in ROLE_NAMES:
        return False, 'Select a role.'

    also_note = ''
    if also_list:
        also_note = ' Also serves: ' + ', '.join(also_list) + '.'

    # Non-classroom areas: service area + role only (no Group N)
    if service_area != SERVICE_SMALL_GROUP:
        _clear_leader_tags(people_id)
        model.AddSubGroup(people_id, ORG_LEADERS, service_area)
        model.AddSubGroup(people_id, ORG_LEADERS, role_name)
        _apply_also_serves(people_id, also_list)
        return True, 'Assigned as ' + role_name + ' for ' + service_area + '.' + also_note

    # Small Group Leader: role required; group optional (Unassigned clears Group N)
    if group_name == 'Unassigned' or not group_name:
        _clear_leader_tags(people_id)
        model.AddSubGroup(people_id, ORG_LEADERS, SERVICE_SMALL_GROUP)
        model.AddSubGroup(people_id, ORG_LEADERS, role_name)
        _apply_also_serves(people_id, also_list)
        return True, 'Assigned as Small Group Leader (' + role_name + '); group cleared.' + also_note

    if not _is_group_name(group_name):
        return False, 'Invalid group name.'

    # Enforce single Leader / Co-leader per group: fully clear prior holder
    if role_name in SINGLE_ROLES:
        for other_pid in _leaders_in_group_with_role(group_name, role_name):
            if other_pid != people_id:
                _clear_leader_tags(other_pid)

    _clear_leader_tags(people_id)

    names = _all_group_names()
    reg_note = ''
    if group_name not in names:
        names.append(group_name)
        ok, err = _save_registry_groups(names)
        if not ok:
            reg_note = ' Note: ' + err

    model.AddSubGroup(people_id, ORG_LEADERS, SERVICE_SMALL_GROUP)
    model.AddSubGroup(people_id, ORG_LEADERS, role_name)
    model.AddSubGroup(people_id, ORG_LEADERS, group_name)
    _apply_also_serves(people_id, also_list)
    return True, 'Assigned as ' + role_name + ' (' + SERVICE_SMALL_GROUP + ') for ' + group_name + '.' + also_note + reg_note


def _clear_leader_assignment(people_id):
    if not _can_assign():
        return False, 'Not authorized.'
    people_id = _i(people_id)
    if not people_id or not model.InOrg(people_id, ORG_LEADERS):
        return False, 'Not a leaders involvement member.'
    _clear_leader_tags(people_id)
    return True, 'Cleared leader assignment.'


def _count_service_area(people, service_area):
    """How many leaders have this as their primary service area."""
    n = 0
    for person in people:
        if _s(person.get('service_area')) == service_area:
            n += 1
    return n


def _count_area_involved(people, service_area):
    """Unique people with area as primary OR Also serves (for Skits/Choreography)."""
    n = 0
    for person in people:
        if _s(person.get('service_area')) == service_area:
            n += 1
            continue
        also = person.get('also_serves') or []
        if service_area in also:
            n += 1
    return n


# Counts day toggles: enrolled headcounts vs Mon–Fri meeting attendance
COUNTS_DAY_KEYS = (
    ('enrolled', 'Enrolled'),
    ('mon', 'Mon'),
    ('tue', 'Tue'),
    ('wed', 'Wed'),
    ('thu', 'Thu'),
    ('fri', 'Fri'),
)
COUNTS_DAY_OFFSET = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4}

# Shepherding SubGroups (MemberTags) — must match involvement SubGroup names exactly
SUBGROUP_NO_HOME_CHURCH = 'nohomechurch'  # display label: No Home Church
SUBGROUP_NO_HOME_CHURCH_LABEL = 'No Home Church'


def _counts_day_mode():
    d = _s(_form_val('day', 'enrolled')).lower()
    for key, _lab in COUNTS_DAY_KEYS:
        if d == key:
            return d
    return 'enrolled'


def _monday_ymd_default():
    """Monday of the current week as YYYY-MM-DD (.NET DateTime)."""
    try:
        from System import DateTime
        today = DateTime.Today
        dow = int(today.DayOfWeek)  # Sunday=0 … Saturday=6
        delta = 6 if dow == 0 else (dow - 1)
        mon = today.AddDays(-delta)
        return '%04d-%02d-%02d' % (mon.Year, mon.Month, mon.Day)
    except:
        return ''


def _ymd_add_days(ymd, days):
    ymd = _s(ymd)
    if len(ymd) < 10:
        return ''
    try:
        from System import DateTime
        dt = DateTime.Parse(ymd[:10])
        nd = dt.AddDays(int(days))
        return '%04d-%02d-%02d' % (nd.Year, nd.Month, nd.Day)
    except:
        return ''


def _vbs_week_monday_ymd():
    """VBS week Monday: Settings WeekStart, else current week's Monday."""
    ws = _s(VBS_WEEK_START)
    if len(ws) >= 10:
        return ws[:10]
    return _monday_ymd_default()


def _counts_day_ymd(day_mode):
    """Calendar date for a Counts day toggle (or '' for enrolled)."""
    if day_mode == 'enrolled' or day_mode not in COUNTS_DAY_OFFSET:
        return ''
    mon = _vbs_week_monday_ymd()
    if not mon:
        return ''
    return _ymd_add_days(mon, COUNTS_DAY_OFFSET[day_mode])


def _attend_present_ids(org_id, meet_day_ymd):
    """PeopleIds with AttendanceFlag=1 on this org for the calendar date."""
    org_id = _i(org_id)
    meet_day_ymd = _s(meet_day_ymd)
    if not org_id or len(meet_day_ymd) < 10:
        return []
    try:
        sql = """
SELECT DISTINCT a.PeopleId
FROM dbo.Attend a
WHERE a.OrganizationId = @oid
  AND a.AttendanceFlag = 1
  AND CAST(a.MeetingDate AS date) = @day
"""
        p = _dd()
        p.AddValue('oid', org_id)
        p.AddValue('day', meet_day_ymd[:10])
        rows = list(q.QuerySql(sql, p))
        out = []
        for r in rows:
            pid = _i(r.PeopleId)
            if pid:
                out.append(pid)
        return out
    except Exception, ex:
        _warn('Attendance read failed (org ' + str(org_id) + '): ' + _ex_msg(ex))
        return []


def _attend_present_count(org_id, meet_day_ymd):
    return len(_attend_present_ids(org_id, meet_day_ymd))


def _week_attendance_buckets():
    """Mon–Fri present counts: volunteers (1894), k5 (1893), prek_nur (1895+1896).

    Returns list of dicts: day_key, label, ymd, volunteers, k5, prek_nur, total.
    Uses Meetings AttendanceFlag=1 on each pool involvement for that calendar day.
    """
    mon = _vbs_week_monday_ymd()
    days = []
    for key, lab in COUNTS_DAY_KEYS:
        if key == 'enrolled':
            continue
        ymd = _counts_day_ymd(key)
        vol = _attend_present_count(ORG_LEADERS, ymd) if ymd else 0
        k5 = _attend_present_count(ORG_K5, ymd) if ymd else 0
        prek = _attend_present_count(ORG_PREK, ymd) if ymd else 0
        nur = _attend_present_count(ORG_NURSERY, ymd) if ymd else 0
        prek_nur = prek + nur
        days.append({
            'day_key': key,
            'label': lab,
            'ymd': ymd or '',
            'volunteers': vol,
            'k5': k5,
            'prek_nur': prek_nur,
            'total': vol + k5 + prek_nur,
        })
    return days, mon


def _nice_axis_max(n):
    """Round up to a clean Y-axis max for chart ticks."""
    n = _i(n)
    if n <= 0:
        return 10
    if n <= 10:
        return 10
    # step ~ 1/5 of range, round up to 5/10/25/50…
    step = 5
    if n > 40:
        step = 10
    if n > 100:
        step = 25
    if n > 250:
        step = 50
    if n > 500:
        step = 100
    return ((n + step - 1) / step) * step


def _attend_present_in_group_count(org_id, group_name, meet_day_ymd):
    """Present people on org that day who currently have MemberTag group_name."""
    org_id = _i(org_id)
    group_name = _s(group_name)
    meet_day_ymd = _s(meet_day_ymd)
    if not org_id or not group_name or len(meet_day_ymd) < 10:
        return 0
    try:
        sql = """
SELECT COUNT(DISTINCT a.PeopleId) AS Cnt
FROM dbo.Attend a
INNER JOIN dbo.OrgMemMemTags omt
    ON omt.OrgId = a.OrganizationId AND omt.PeopleId = a.PeopleId
INNER JOIN dbo.MemberTags mt
    ON mt.Id = omt.MemberTagId AND mt.OrgId = omt.OrgId
WHERE a.OrganizationId = @oid
  AND a.AttendanceFlag = 1
  AND CAST(a.MeetingDate AS date) = @day
  AND mt.Name = @gname
"""
        p = _dd()
        p.AddValue('oid', org_id)
        p.AddValue('day', meet_day_ymd[:10])
        p.AddValue('gname', group_name)
        rows = list(q.QuerySql(sql, p))
        if rows:
            return _i(rows[0].Cnt, 0) or 0
    except Exception, ex:
        _warn('Group attendance read failed: ' + _ex_msg(ex))
    return 0


def _count_people_present(people, present_ids):
    """How many of these person-dicts appear in present_ids."""
    if not present_ids:
        return 0
    seen = {}
    for pid in present_ids:
        seen[pid] = True
    n = 0
    for person in people or []:
        pid = _i(person.get('people_id'))
        if pid and pid in seen:
            n += 1
    return n


def _merge_people(*lists):
    """Unique people by PeopleId, preserving first-seen order."""
    out = []
    seen = {}
    for lst in lists:
        if not lst:
            continue
        for person in lst:
            pid = _i(person.get('people_id'))
            if not pid or pid in seen:
                continue
            seen[pid] = True
            out.append(person)
    return out


def _sort_people_name(people):
    out = list(people or [])
    try:
        out.sort(key=lambda p: (
            _s(p.get('last', '')).lower(),
            _s(p.get('first', '')).lower(),
            _s(p.get('name', '')).lower(),
        ))
    except:
        pass
    return out


def _people_with_service(people, service_area, involved=False):
    """Leaders matching primary service area (or primary/Also when involved=True)."""
    out = []
    for person in people or []:
        if _s(person.get('service_area')) == service_area:
            out.append(person)
            continue
        if involved:
            also = person.get('also_serves') or []
            if service_area in also:
                out.append(person)
    return out


def _people_in_group_sgl(people, gname):
    """Small Group Leaders (or legacy no-area) assigned to Group N."""
    out = []
    for person in people or []:
        if person.get('group_raw') != gname:
            continue
        area = _s(person.get('service_area'))
        if not area or area == SERVICE_SMALL_GROUP:
            out.append(person)
    return out


def _counts_drill_resolve(pools, drill):
    """
    Resolve Counts drill key → (people, title, tag_suggest) or None.
    Keys: prek | nursery | area:<ServiceArea> | group:<Group N> | ua:vol | ua:k5
    """
    drill = _s(drill)
    if not drill:
        return None
    leaders = pools['leaders']['people']
    year = VBS_YEAR

    if drill == 'prek':
        people = _merge_people(
            pools['prek']['people'],
            _people_with_service(leaders, SERVICE_PREK),
        )
        return (
            _sort_people_name(people),
            'Pre-K — students + leaders',
            'VBS ' + year + ' Pre-K',
        )
    if drill == 'nursery':
        people = _merge_people(
            pools['nursery']['people'],
            _people_with_service(leaders, SERVICE_NURSERY),
        )
        return (
            _sort_people_name(people),
            'Nursery — students + leaders',
            'VBS ' + year + ' Nursery',
        )
    if drill == 'ua:vol':
        people = [p for p in leaders if not _s(p.get('service_area'))]
        return (
            _sort_people_name(people),
            'Unassigned volunteers (no service area)',
            'VBS ' + year + ' Unassigned Volunteers',
        )
    if drill == 'ua:k5':
        people = [p for p in pools['k5']['people'] if not p.get('group_raw')]
        return (
            _sort_people_name(people),
            'Unassigned K-5 (no Group)',
            'VBS ' + year + ' Unassigned K-5',
        )
    if drill.startswith('area:'):
        area = drill[5:]
        if area not in SERVICE_AREAS:
            return None
        involved = area in SECONDARY_AREAS
        people = _people_with_service(leaders, area, involved=involved)
        label = area
        for aname, alabel in SERVICE_COUNT_ROWS:
            if aname == area:
                label = alabel
                break
        return (
            _sort_people_name(people),
            'Volunteers — ' + label,
            'VBS ' + year + ' ' + label,
        )
    if drill.startswith('group:'):
        gname = drill[6:]
        if not gname:
            return None
        people = _merge_people(
            _people_in_group_sgl(leaders, gname),
            [p for p in pools['k5']['people'] if p.get('group_raw') == gname],
        )
        return (
            _sort_people_name(people),
            gname + ' — Small Group Leaders + K-5',
            'VBS ' + year + ' ' + gname,
        )
    return None


def _counts_drill_href(drill_key, day_mode=''):
    try:
        enc = model.UrlEncode(_s(drill_key)).replace('+', '%20')
    except:
        enc = _s(drill_key).replace(' ', '%20')
    href = _script_path() + '?view=counts&drill=' + enc
    day_mode = _s(day_mode) or _counts_day_mode()
    if day_mode and day_mode != 'enrolled':
        href += '&day=' + day_mode
    return href


def _counts_drill_link(label, drill_key, active_drill, day_mode=''):
    """Clickable Area/Group name for Counts drill-down."""
    cls = 'counts-drill-link'
    if _s(active_drill) == _s(drill_key):
        cls += ' active'
    return (
        '<a class="' + cls + '" href="' + _counts_drill_href(drill_key, day_mode=day_mode) + '">'
        + _html(label) + '</a>'
    )


def _counts_day_toggles(day_mode, meet_day_ymd=''):
    """Enrolled / Mon–Fri toggle strip for Counts Pre-K and Groups sections."""
    html = '<div class="counts-day-toggles vbs-screen-only">'
    for key, lab in COUNTS_DAY_KEYS:
        cls = 'btn-col-toggle'
        if key == day_mode:
            cls += ' is-on'
        href = _script_path() + '?view=counts&day=' + key
        html += '<a class="' + cls + '" href="' + href + '" style="text-decoration:none">' + _html(lab) + '</a>'
    html += '</div>'
    if day_mode != 'enrolled' and meet_day_ymd:
        html += '<p class="meta-line vbs-screen-only" style="margin:8px 0 0 0">Attendance date: <strong>' + _html(meet_day_ymd) + '</strong> '
        html += '(from Meetings on each involvement; Week start in Settings).</p>'
    elif day_mode != 'enrolled':
        html += '<p class="meta-line vbs-screen-only" style="margin:8px 0 0 0">Set <strong>VBS week (Monday)</strong> in Settings so Mon–Fri map to calendar dates.</p>'
    return html


def _counts_drill_panel(pools, drill):
    """People list + Add to Tag for an active Counts drill."""
    resolved = _counts_drill_resolve(pools, drill)
    if not resolved:
        return (
            '<div class="vbs-card vbs-screen-only">'
            '<div class="info-banner danger">Unknown drill-down. '
            '<a href="' + _script_path() + '?view=counts">Back to Counts</a></div></div>'
        )
    people, title, tag_suggest = resolved
    html = '<div class="vbs-card counts-drill-panel vbs-screen-only" id="counts-drill">'
    html += '<div class="list-actions" style="margin-bottom:10px">'
    html += '<div class="vbs-card-title" style="margin:0">' + _html(title) + '</div>'
    html += '<div>'
    html += '<a class="btn-secondary" href="' + _script_path() + '?view=counts" style="display:inline-block;text-decoration:none;margin-right:8px">Close</a>'
    html += _tag_add_button(people, tag_suggest)
    html += '</div></div>'
    html += '<p class="meta-line"><strong>' + str(len(people)) + '</strong> people · click a column header to sort</p>'
    html += '<div class="table-scroll"><table class="people-table vbs-sortable"><thead><tr>'
    html += _sort_th('Name', 'text')
    html += _sort_th('Service area', 'text')
    html += _sort_th('Role', 'text')
    html += _sort_th('Group', 'group')
    html += _sort_th('Grade', 'text')
    html += '</tr></thead><tbody>'
    for p in people:
        html += '<tr>'
        html += '<td>' + _person_link(p) + '</td>'
        html += '<td>' + _html(p.get('service_area') or '') + '</td>'
        html += '<td>' + _html(p.get('role_display') or '') + '</td>'
        html += '<td>' + _html(p.get('group') or '') + '</td>'
        html += '<td>' + _html(p.get('grade') or '') + '</td>'
        html += '</tr>'
    if not people:
        html += '<tr><td colspan="5"><div class="empty-state">No people in this drill-down</div></td></tr>'
    html += '</tbody></table></div></div>'
    return html


def _parse_people_ids(raw):
    """Parse a comma-separated PeopleId list into unique positive ints."""
    ids = []
    seen = {}
    for part in _s(raw).replace(';', ',').split(','):
        part = part.strip()
        if not part:
            continue
        try:
            pid = int(part)
        except:
            continue
        if pid > 0 and pid not in seen:
            seen[pid] = True
            ids.append(pid)
    return ids


def _add_people_to_tag(people_ids_raw, tag_name, clear_first):
    """
    Add people to a personal tag owned by the current user.
    Same pattern as InvolvementDashboard (model.AddTag).
    """
    owner_id = model.UserPeopleId
    if not owner_id:
        return {'error': 'You must be signed in to add people to a tag.'}

    tag_name = _s(tag_name).replace('!', '_').strip()
    if not tag_name:
        return {'error': 'Tag name is required.'}
    if len(tag_name) > 50:
        return {'error': 'Tag name is too long (max 50 characters).'}

    people_ids = _parse_people_ids(people_ids_raw)
    if not people_ids:
        return {'error': 'No people to add to the tag.'}

    clear = False
    clear_s = _s(clear_first).lower()
    if clear_s in ('1', 'true', 'yes', 'clear'):
        clear = True

    query = "peopleids='" + ','.join([str(pid) for pid in people_ids]) + "'"
    model.AddTag(query, tag_name, int(owner_id), clear)

    try:
        import urllib
        tag_q = urllib.quote(tag_name.encode('utf-8'))
    except:
        tag_q = tag_name.replace(' ', '%20')

    return {
        'ok': True,
        'tag_name': tag_name,
        'count': len(people_ids),
        'cleared': clear,
        'tag_url': '/Tags?tag=' + tag_q,
    }


def _json_out(obj):
    print json.dumps(obj)


# ---------------------------------------------------------------------------
# Aggregations for views
# ---------------------------------------------------------------------------

def _blocks_selected_group(group_names):
    """By Group filter: 'all' or a Group N name from ?group=."""
    raw = _s(_form_val('group', 'all'))
    if not raw or raw.lower() == 'all':
        return 'all'
    for g in group_names or []:
        if _s(g) == raw:
            return _s(g)
    # Case-insensitive fallback
    low = raw.lower()
    for g in group_names or []:
        if _s(g).lower() == low:
            return _s(g)
    return 'all'


def _filter_group_bundles(bundles, selected):
    """Keep all bundles, or only the selected Group N."""
    selected = _s(selected)
    if not selected or selected.lower() == 'all':
        return bundles
    out = []
    for b in bundles or []:
        if _s(b.get('group')) == selected:
            out.append(b)
    return out


def _build_group_bundles(pools, group_names, allergy_only=False):
    """One dict per Group N with leaders + kids + counts."""
    bundles = []
    for gname in group_names:
        leaders = []
        coleaders = []
        assistants = []
        kids = []
        for person in pools['leaders']['people']:
            if person['group_raw'] != gname:
                continue
            roles = person['roles']
            if ROLE_LEADER in roles:
                leaders.append(person)
            elif ROLE_COLEADER in roles:
                coleaders.append(person)
            elif ROLE_ASSISTANT in roles:
                assistants.append(person)
            else:
                # In group but no role yet
                pass
        for key in ('k5', 'prek', 'nursery'):
            for person in pools[key]['people']:
                if person['group_raw'] != gname:
                    continue
                if allergy_only and not person['has_allergy']:
                    continue
                kids.append(person)
        boys = 0
        girls = 0
        for k in kids:
            gen = _s(k['gender']).lower()
            if gen.startswith('m'):
                boys += 1
            elif gen.startswith('f'):
                girls += 1
        team = len(leaders) + len(coleaders) + len(assistants) + len(kids)
        bundles.append({
            'group': gname,
            'leaders': leaders,
            'coleaders': coleaders,
            'assistants': assistants,
            'kids': kids,
            'team_count': team,
            'student_count': len(kids),
            'boys': boys,
            'girls': girls,
        })
    return bundles


def _grade_sort_key(grade):
    """Sort grade labels: Kindergarten, then numeric grades, then other text."""
    s = _s(grade).strip().lower()
    if not s:
        return (999, '')
    if 'kinder' in s or s in ('k', 'kg', 'prek', 'pre-k', 'pre k'):
        return (0, s)
    try:
        import re
        m = re.search(r'(\d+)', s)
        if m:
            return (int(m.group(1)), s)
    except:
        pass
    return (500, s)


def _unique_grades_csv(people):
    """Comma-separated unique grades from a people list (students)."""
    seen = {}
    grades = []
    for person in people:
        g = _s(person.get('grade', '')).strip()
        if g and g not in seen:
            seen[g] = True
            grades.append(g)
    try:
        grades.sort(key=_grade_sort_key)
    except:
        grades.sort()
    return ', '.join(grades)


def _grade_short(grade):
    """Compact grade for Group titles: K, 1st, 2nd, …"""
    s = _s(grade).strip()
    if not s:
        return ''
    low = s.lower()
    if 'kinder' in low or low in ('k', 'kg'):
        return 'K'
    try:
        import re
        m = re.search(r'(\d+)\s*(st|nd|rd|th)?', low, re.I)
        if m:
            n = int(m.group(1))
            suf = _s(m.group(2)).lower()
            if not suf:
                if n % 10 == 1 and n % 100 != 11:
                    suf = 'st'
                elif n % 10 == 2 and n % 100 != 12:
                    suf = 'nd'
                elif n % 10 == 3 and n % 100 != 13:
                    suf = 'rd'
                else:
                    suf = 'th'
            return str(n) + suf
    except:
        pass
    return s


def _unique_grades_slash(people):
    """Slash-separated short grades for Group titles (e.g. K/1st/2nd)."""
    seen = {}
    grades = []
    for person in people:
        short = _grade_short(person.get('grade', ''))
        if short and short not in seen:
            seen[short] = True
            grades.append(short)
    try:
        grades.sort(key=_grade_sort_key)
    except:
        grades.sort()
    return '/'.join(grades)


def _gender_mix_label(boys, girls):
    """Male / Female / Mixed from student boy/girl counts."""
    if boys and girls:
        return 'Mixed'
    if boys and not girls:
        return 'Male'
    if girls and not boys:
        return 'Female'
    return 'Mixed'


def _group_block_title(bundle):
    """Group N - K/1st/2nd, Mixed|Male|Female"""
    gname = _s(bundle.get('group'))
    grades = _unique_grades_slash(bundle.get('kids') or [])
    if not grades:
        grades = '—'
    mix = _gender_mix_label(bundle.get('boys', 0), bundle.get('girls', 0))
    return gname + ' - ' + grades + ', ' + mix


def _tshirt_people(pools, who='all'):
    """
    Unique people for T-shirt report.
    who: all | volunteers (Leaders) | participants (K-5 + Pre-K).
    Returns (people_list, who_key, who_label).
    """
    who = _s(who).lower()
    if who in ('volunteers', 'volunteer', 'leaders', 'leader'):
        keys = ('leaders',)
        who = 'volunteers'
        label = 'Volunteers'
    elif who in ('participants', 'participant', 'kids', 'students'):
        keys = ('k5', 'prek')
        who = 'participants'
        label = 'Participants (K-5 & Pre-K)'
    else:
        keys = ('leaders', 'k5', 'prek', 'nursery')
        who = 'all'
        label = 'All'

    seen = {}
    out = []
    for key in keys:
        try:
            people = pools[key]['people']
        except:
            people = []
        for person in people:
            pid = _i(person.get('people_id'))
            if not pid or pid in seen:
                continue
            seen[pid] = True
            out.append(person)
    try:
        out.sort(key=lambda x: (
            _s(x.get('last', '')).lower(),
            _s(x.get('first', '')).lower(),
            _s(x.get('name', '')).lower(),
        ))
    except:
        pass
    return out, who, label


def _tshirt_size_tiles(people):
    """Ordered (size, count) list for summary tiles."""
    counts = {}
    for person in people:
        size = _s(person.get('shirt_size')) or 'Unknown'
        if size not in counts:
            counts[size] = 0
        counts[size] += 1
    sizes = list(counts.keys())

    def _size_key(s):
        if s == 'Unknown':
            return (999, s.lower())
        return (0, s.lower())

    try:
        sizes.sort(key=_size_key)
    except:
        sizes.sort()
    return [(s, counts[s]) for s in sizes]


def _count_rows(pools, group_names):
    """Per Group N: students (K-5), Small Group Leaders, total, and student grades."""
    rows = []
    for gname in group_names:
        c_lead = 0
        students = []
        for person in pools['leaders']['people']:
            if person['group_raw'] != gname:
                continue
            area = _s(person.get('service_area'))
            # Count SGL (or legacy assigns with a Group N but no service area yet)
            if not area or area == SERVICE_SMALL_GROUP:
                c_lead += 1
        for person in pools['k5']['people']:
            if person['group_raw'] == gname:
                students.append(person)
        c_students = len(students)
        rows.append({
            'group': gname,
            'leaders': c_lead,
            'students': c_students,
            'total': c_lead + c_students,
            'grades': _unique_grades_csv(students),
        })
    return rows


def _pool_count_line(people):
    """Placed / unassigned / total for a kid pool (own Counts line)."""
    placed = 0
    unassigned = 0
    for person in people:
        if person.get('group_raw'):
            placed += 1
        else:
            unassigned += 1
    return {
        'placed': placed,
        'unassigned': unassigned,
        'total': placed + unassigned,
    }


def _allergy_people(pools):
    """People with a real allergy note (excludes blank, space, NA/N/A/NKA/none/no)."""
    out = []
    for key in ('k5', 'prek', 'nursery', 'leaders'):
        for person in pools[key]['people']:
            if _allergy_text_meaningful(person.get('allergy')):
                row = dict(person)
                row['pool'] = pools[key]['label']
                out.append(row)
    out.sort(key=lambda x: (x['last'], x['first']))
    return out


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _nav_segment_class(seg_label):
    """CSS class for nav segment highlight colors."""
    s = _s(seg_label).lower()
    if s == 'master lists':
        return 'seg-master'
    if s == 'vbs ops':
        return 'seg-ops'
    if s == 'admin':
        return 'seg-admin'
    return 'seg-home'


def _nav(view, can_assign, can_admin=False):
    # Compact centered segments + caret collapse (no extra toolbar row).
    bits = []
    bits.append('<nav class="dash-nav" id="vbs-dash-nav" aria-label="' + _html(APP_TITLE) + '" data-view="' + _html(view) + '">')
    bits.append('<button type="button" class="dash-nav-caret" id="vbs-nav-caret" '
                'aria-expanded="true" title="Collapse menu" aria-label="Collapse menu">'
                '<i class="fa fa-caret-up" aria-hidden="true"></i></button>')
    bits.append('<div class="dash-nav-body" id="vbs-nav-body">')
    for seg_label, tabs in NAV_SEGMENTS:
        links = []
        for key, label in tabs:
            if key == 'assign' and not can_assign:
                continue
            if key == 'settings' and not can_admin:
                continue
            cls = 'dash-tab' + (' active' if key == view else '')
            if key in ('allergies',):
                cls += ' dash-tab-allergy'
            href = _script_path() + '?view=' + key
            links.append('<a class="' + cls + '" href="' + href + '">' + _html(label) + '</a>')
        if not links:
            continue
        bits.append('<div class="dash-nav-segment ' + _nav_segment_class(seg_label) + '">')
        if seg_label:
            bits.append('<span class="dash-nav-label">' + _html(seg_label) + '</span>')
        bits.append('<div class="dash-tabs">')
        bits.extend(links)
        bits.append('</div></div>')
    bits.append('</div></nav>')
    return ''.join(bits)


def _home_attendance_section():
    """Mon–Fri attendance tiles + stacked bar chart for Home dashboard."""
    days, mon = _week_attendance_buckets()
    max_tot = 0
    for d in days:
        if d['total'] > max_tot:
            max_tot = d['total']
    ymax = _nice_axis_max(max_tot)

    # Stack colors: K-5 bottom, Pre-K/Nursery middle, Volunteers top (brand palette)
    c_k5 = COLOR_PRIMARY
    c_prek = COLOR_TERTIARY_GREEN
    c_vol = COLOR_SECONDARY

    html = '<div class="cover-attendance">'
    html += '<div class="cover-attendance-head">'
    html += '<h3 class="cover-attendance-title">Weekly Attendance</h3>'
    if mon:
        fri = _ymd_add_days(mon, 4)
        html += '<p class="meta-line cover-attendance-range">Week of ' + _html(mon)
        if fri:
            html += ' – ' + _html(fri)
        html += ' · from Meetings (present)</p>'
    else:
        html += '<p class="meta-line cover-attendance-range">Set VBS week start (Monday) in Settings for dated Meetings.</p>'
    html += '</div>'

    # Day tiles
    html += '<div class="att-day-grid">'
    for d in days:
        html += '<div class="att-day-tile">'
        html += '<div class="att-day-name">' + _html(d['label']) + '</div>'
        html += '<div class="att-day-total-label">Total Attendance</div>'
        html += '<div class="att-day-total">' + str(d['total']) + '</div>'
        html += '<ul class="att-day-breakdown">'
        html += '<li><span class="att-swatch" style="background:' + c_vol + '"></span>'
        html += 'Volunteers <strong>' + str(d['volunteers']) + '</strong></li>'
        html += '<li><span class="att-swatch" style="background:' + c_k5 + '"></span>'
        html += 'K-5 <strong>' + str(d['k5']) + '</strong></li>'
        html += '<li><span class="att-swatch" style="background:' + c_prek + '"></span>'
        html += 'Pre-K / Nursery <strong>' + str(d['prek_nur']) + '</strong></li>'
        html += '</ul></div>'
    html += '</div>'

    # Stacked bar chart (SVG) — K-5 bottom, Pre-K/Nursery, Volunteers top
    chart_w = 560
    chart_h = 260
    pad_l = 42
    pad_r = 16
    pad_t = 16
    pad_b = 36
    plot_w = chart_w - pad_l - pad_r
    plot_h = chart_h - pad_t - pad_b
    n_days = len(days) or 1
    slot = float(plot_w) / float(n_days)
    bar_w = slot * 0.55
    if bar_w < 28:
        bar_w = 28.0
    if bar_w > 64:
        bar_w = 64.0

    html += '<div class="shepherd-block att-chart-block is-collapsed" data-shepherd-key="att-chart" id="vbs-att-chart">'
    html += '<div class="shepherd-block-header">'
    html += '<div class="shepherd-block-heading">'
    html += '<span class="shepherd-block-name">Attendance chart</span>'
    html += '</div>'
    html += '<button type="button" class="shepherd-block-caret" '
    html += 'aria-expanded="false" title="Show chart" aria-label="Show attendance chart">'
    html += '<i class="fa fa-caret-down" aria-hidden="true"></i></button>'
    html += '</div>'
    html += '<div class="shepherd-block-body">'
    html += '<div class="att-chart-wrap">'
    html += '<div class="att-chart-legend">'
    html += '<span class="att-legend-item"><span class="att-swatch" style="background:' + c_vol + '"></span>Volunteers</span>'
    html += '<span class="att-legend-item"><span class="att-swatch" style="background:' + c_prek + '"></span>Pre-K / Nursery</span>'
    html += '<span class="att-legend-item"><span class="att-swatch" style="background:' + c_k5 + '"></span>K-5</span>'
    html += '</div>'
    html += '<svg class="att-chart" viewBox="0 0 ' + str(chart_w) + ' ' + str(chart_h) + '" '
    html += 'role="img" aria-label="Weekly attendance stacked bar chart">'

    ticks = 5
    for i in range(ticks + 1):
        val = (ymax * i) / ticks
        y = pad_t + plot_h - (float(val) / float(ymax)) * plot_h
        html += '<line x1="' + str(pad_l) + '" y1="' + ('%.1f' % y) + '" x2="' + str(pad_l + plot_w) + '" '
        html += 'y2="' + ('%.1f' % y) + '" class="att-grid" />'
        html += '<text x="' + str(pad_l - 6) + '" y="' + ('%.1f' % (y + 4)) + '" class="att-y-label" '
        html += 'text-anchor="end">' + str(val) + '</text>'

    for idx in range(len(days)):
        d = days[idx]
        cx = pad_l + slot * idx + slot / 2.0
        x = cx - bar_w / 2.0
        y_base = pad_t + plot_h
        segments = (
            (d['k5'], c_k5),
            (d['prek_nur'], c_prek),
            (d['volunteers'], c_vol),
        )
        for cnt, color in segments:
            if cnt <= 0:
                continue
            h = (float(cnt) / float(ymax)) * plot_h
            y = y_base - h
            html += '<rect x="' + ('%.1f' % x) + '" y="' + ('%.1f' % y) + '" width="' + ('%.1f' % bar_w) + '" '
            html += 'height="' + ('%.1f' % h) + '" fill="' + color + '" rx="2" />'
            y_base = y
        html += '<text x="' + ('%.1f' % cx) + '" y="' + str(chart_h - 12) + '" class="att-x-label" '
        html += 'text-anchor="middle">' + _html(d['label']) + '</text>'
        if d['total'] > 0:
            top_y = y_base - 6
            html += '<text x="' + ('%.1f' % cx) + '" y="' + ('%.1f' % top_y) + '" class="att-bar-total" '
            html += 'text-anchor="middle">' + str(d['total']) + '</text>'

    html += '</svg></div></div></div></div>'
    return html


def _home_offerings_section(can_assign=False):
    """Home: Mon–Fri cash offering totals (manual — not Contributions)."""
    data = _load_offerings()
    mon = _s(data.get('week_start')) or _vbs_week_monday_ymd()
    fri = _ymd_add_days(mon, 4) if mon else ''
    days = (
        ('mon', 'Mon'),
        ('tue', 'Tue'),
        ('wed', 'Wed'),
        ('thu', 'Thu'),
        ('fri', 'Fri'),
    )
    week_total = 0.0
    for key, _lab in days:
        week_total += _parse_money(data.get(key))

    html = '<div class="cover-offerings">'
    html += '<div class="cover-offerings-head">'
    html += '<h3 class="cover-offerings-title">Cash Offerings</h3>'
    if mon:
        html += '<p class="meta-line cover-offerings-range">Week of ' + _html(mon)
        if fri:
            html += ' – ' + _html(fri)
        html += ' · manual totals (not Contributions)</p>'
    else:
        html += '<p class="meta-line cover-offerings-range">Set VBS week start (Monday) in Settings.</p>'
    html += '</div>'

    html += '<div class="offering-week-total">'
    html += '<div class="offering-week-total-label">Week total</div>'
    html += '<div class="offering-week-total-value">' + _html(_format_money(week_total)) + '</div>'
    html += '</div>'

    if can_assign:
        html += '<form method="post" action="' + _script_path() + '" class="offering-form">'
        html += '<input type="hidden" name="action" value="save_offerings" />'
        html += '<input type="hidden" name="view" value="home" />'

    html += '<div class="offering-day-grid">'
    for key, lab in days:
        amt = _parse_money(data.get(key))
        ymd = _ymd_add_days(mon, COUNTS_DAY_OFFSET.get(key, 0)) if mon else ''
        html += '<div class="offering-day-tile">'
        html += '<div class="offering-day-name">' + _html(lab) + '</div>'
        if ymd:
            html += '<div class="offering-day-date">' + _html(ymd) + '</div>'
        if can_assign:
            html += '<label class="offering-input-wrap" for="off_' + key + '">'
            html += '<span class="offering-dollar">$</span>'
            html += '<input type="text" inputmode="decimal" name="off_' + key + '" id="off_' + key + '" '
            html += 'value="' + _html('%.2f' % amt) + '" placeholder="0.00" maxlength="12" />'
            html += '</label>'
        else:
            html += '<div class="offering-day-amount">' + _html(_format_money(amt)) + '</div>'
        html += '</div>'
    html += '</div>'

    if can_assign:
        html += '<div class="offering-actions">'
        html += '<button type="submit" class="btn-primary">Save offerings</button>'
        html += '<span class="meta-line" style="margin:0">Admin / VBSAdmin only. Stored with VBS Home Base — not linked to giving records.</span>'
        html += '</div></form>'

    html += '</div>'
    return html


def _pool_people_index(pools):
    """PeopleId → person dict from loaded pools (first match wins)."""
    idx = {}
    try:
        for key, _oid, label in POOLS:
            for p in pools.get(key, {}).get('people') or []:
                pid = _i(p.get('people_id'))
                if pid and pid not in idx:
                    row = dict(p)
                    row['pool'] = label
                    idx[pid] = row
    except:
        pass
    return idx


def _people_with_subgroup(pools, tag_name):
    """People in any VBS pool involvement who have the given SubGroup (MemberTag)."""
    tag_name = _s(tag_name)
    if not tag_name:
        return []
    org_ids = []
    for _k, oid, _lab in POOLS:
        oid = _i(oid)
        if oid:
            org_ids.append(oid)
    if not org_ids:
        return []
    try:
        # Build IN list (org ids are ints from Settings — safe)
        in_list = ','.join([str(x) for x in org_ids])
        sql = """
SELECT DISTINCT
    omt.OrgId AS OrganizationId,
    omt.PeopleId,
    p.FirstName,
    p.LastName,
    ISNULL(p.Name2, LTRIM(RTRIM(ISNULL(p.FirstName,'') + ' ' + ISNULL(p.LastName,'')))) AS PersonName,
    p.Age,
    gl.Description AS Grade
FROM dbo.OrgMemMemTags omt
INNER JOIN dbo.MemberTags mt
    ON mt.Id = omt.MemberTagId AND mt.OrgId = omt.OrgId
INNER JOIN dbo.People p ON p.PeopleId = omt.PeopleId
LEFT JOIN lookup.GradeLevel gl ON gl.Id = p.GradeLevelId
WHERE omt.OrgId IN (""" + in_list + """)
  AND mt.Name = @tname
  AND ISNULL(p.IsDeceased, 0) = 0
ORDER BY p.LastName, p.FirstName
"""
        p = _dd()
        p.AddValue('tname', tag_name)
        rows = list(q.QuerySql(sql, p))
    except Exception, ex:
        _warn('SubGroup list failed (' + tag_name + '): ' + _ex_msg(ex))
        return []

    pool_idx = _pool_people_index(pools)
    org_label = {}
    for key, oid, label in POOLS:
        org_label[_i(oid)] = label

    out = []
    seen = {}
    for r in rows:
        try:
            pid = _i(r.PeopleId)
            if not pid or pid in seen:
                continue
            seen[pid] = True
            if pid in pool_idx:
                person = dict(pool_idx[pid])
            else:
                person = {
                    'people_id': pid,
                    'first': _s(r.FirstName),
                    'last': _s(r.LastName),
                    'name': _s(r.PersonName, '(Unknown)'),
                    'age': _s(r.Age),
                    'grade': _s(r.Grade),
                    'group': '',
                    'pool': org_label.get(_i(r.OrganizationId), ''),
                    'org_id': _i(r.OrganizationId),
                }
            if not _s(person.get('pool')):
                person['pool'] = org_label.get(_i(r.OrganizationId), '')
            out.append(person)
        except:
            continue
    return out


def _shepherding_insights_section(pools):
    """Home: actionable shepherding lists (No Home Church) + Decisions placeholder."""
    nhc = _people_with_subgroup(pools, SUBGROUP_NO_HOME_CHURCH)
    n = len(nhc)
    tag_suggest = 'VBS ' + VBS_YEAR + ' No Home Church'
    nhc_label = SUBGROUP_NO_HOME_CHURCH_LABEL

    html = '<div class="cover-shepherding">'
    html += '<div class="cover-shepherding-head">'
    html += '<h3 class="cover-shepherding-title">Shepherding Insights</h3>'
    html += '<p class="meta-line" style="margin:0">Follow-up lists from involvement SubGroups.</p>'
    html += '</div>'

    # No Home Church — collapsible actionable list (SubGroup: nohomechurch on each pool)
    html += '<div class="shepherd-block is-collapsed" data-shepherd-key="nhc" id="vbs-shepherd-nhc">'
    html += '<div class="shepherd-block-header">'
    html += '<div class="shepherd-block-heading">'
    html += '<span class="shepherd-block-name">' + _html(nhc_label) + '</span>'
    html += '<span class="shepherd-count">' + str(n) + '</span>'
    html += '</div>'
    html += '<button type="button" class="shepherd-block-caret" '
    html += 'aria-expanded="false" title="Show list" aria-label="Show ' + _html(nhc_label) + ' list">'
    html += '<i class="fa fa-caret-down" aria-hidden="true"></i></button>'
    html += '</div>'
    html += '<div class="shepherd-block-body">'
    html += '<div class="list-actions" style="margin-bottom:10px">'
    html += '<p class="meta-line" style="margin:0"><strong>' + str(n) + '</strong> people in SubGroup '
    html += '<code>' + _html(SUBGROUP_NO_HOME_CHURCH) + '</code> across VBS pools</p>'
    html += _tag_add_button(nhc, tag_suggest)
    html += '</div>'
    html += '<div class="table-scroll"><table class="people-table vbs-sortable"><thead><tr>'
    html += _sort_th('Name', 'text')
    html += _sort_th('Pool', 'text')
    html += _sort_th('Group', 'group')
    html += _sort_th('Grade', 'text')
    html += _sort_th('Age', 'num')
    html += '</tr></thead><tbody>'
    for person in nhc:
        html += '<tr>'
        html += '<td>' + _person_link(person) + '</td>'
        html += '<td>' + _html(person.get('pool') or '') + '</td>'
        html += '<td>' + _html(person.get('group') or '') + '</td>'
        html += '<td>' + _html(person.get('grade') or '') + '</td>'
        html += '<td>' + _html(person.get('age') or '') + '</td>'
        html += '</tr>'
    if n == 0:
        html += '<tr><td colspan="5"><div class="empty-state">No one in SubGroup '
        html += '<code>' + _html(SUBGROUP_NO_HOME_CHURCH) + '</code> on Volunteers, K-5, Pre-K, or Nursery yet.</div></td></tr>'
    html += '</tbody></table></div></div></div>'

    # Decisions — placeholder
    html += '<div class="shepherd-block shepherd-placeholder" data-shepherd-key="decisions" id="vbs-shepherd-decisions">'
    html += '<div class="shepherd-block-header">'
    html += '<div class="shepherd-block-heading">'
    html += '<span class="shepherd-block-name">Decisions</span>'
    html += '<span class="shepherd-badge">Coming soon</span>'
    html += '</div>'
    html += '<button type="button" class="shepherd-block-caret" '
    html += 'aria-expanded="false" title="Show Decisions" aria-label="Show Decisions">'
    html += '<i class="fa fa-caret-down" aria-hidden="true"></i></button>'
    html += '</div>'
    html += '<div class="shepherd-block-body">'
    html += '<div class="info-banner" style="margin:0">Placeholder — Decisions follow-up will go here '
    html += '(salvation / baptism / rededication, etc.). Tell me what fields or SubGroups to pull when you are ready.</div>'
    html += '</div></div>'

    html += '</div>'
    return html


def _header_hero_html():
    """Small centered K-5 involvement graphic for the page header."""
    try:
        k5_oid = _i(ORG_K5)
    except:
        k5_oid = 0
    hero_url = _org_hero_url(k5_oid)
    if not hero_url:
        return ''
    k5_name = _org_name(k5_oid) or 'K-5'
    html = '<div class="vbs-header-hero">'
    html += '<a href="/Org/' + str(k5_oid) + '" target="_blank" rel="noopener" title="Open ' + _html(k5_name) + '">'
    html += '<img src="' + _html(hero_url) + '" alt="' + _html(k5_name) + '" />'
    html += '</a></div>'
    return html


def _cover_page(can_assign, pools, group_names, can_admin=False):
    total_enrolled = 0
    pool_tiles = []
    for key, oid, label in POOLS:
        try:
            n = len(pools[key]['people'])
        except:
            n = 0
        total_enrolled += n
        oid = _i(oid)
        org_nm = _org_name(oid) or ('Org #' + str(oid))
        pool_tiles.append((key, oid, label, n, org_nm))

    html = ''
    html += '<div class="vbs-card cover-card">'
    # Metrics dashboard first (tiles above welcome)
    html += '<div class="cover-metrics">'
    html += '<div class="stats-grid compact">'
    html += '<div class="stat-card cover-tile cover-tile-primary">'
    html += '<div class="stat-value">' + str(total_enrolled) + '</div>'
    html += '<div class="stat-label">Total Enrolled</div>'
    html += '<div class="stat-sub">All VBS pools</div>'
    html += '</div>'
    for key, oid, label, n, org_nm in pool_tiles:
        href = '/Org/' + str(oid)
        if key == 'leaders':
            tile_cls = 'cover-tile cover-tile-secondary'
        else:
            # K-5, Pre-K, Nursery — participants
            tile_cls = 'cover-tile cover-tile-green'
        html += '<a class="stat-card stat-card-link ' + tile_cls + '" href="' + href + '" target="_blank" rel="noopener" '
        html += 'title="Open ' + _html(org_nm) + '">'
        html += '<div class="stat-value">' + str(n) + '</div>'
        html += '<div class="stat-label">' + _html(label) + '</div>'
        html += '<div class="stat-sub">' + _html(org_nm) + '</div>'
        html += '</a>'
    html += '</div></div>'

    # Weekly attendance tiles + stacked chart (Meetings present)
    try:
        html += _home_attendance_section()
    except Exception, ex:
        _warn('Home attendance chart failed: ' + _ex_msg(ex))

    # Cash offerings (manual Mon–Fri totals)
    try:
        html += _home_offerings_section(can_assign=can_assign)
    except Exception, ex:
        _warn('Cash offerings section failed: ' + _ex_msg(ex))

    # Shepherding Insights (No Home Church + Decisions placeholder)
    try:
        html += _shepherding_insights_section(pools)
    except Exception, ex:
        _warn('Shepherding Insights failed: ' + _ex_msg(ex))

    html += '<div class="cover-welcome">'
    html += '<h2 class="vbs-card-title" style="margin-bottom:8px">Welcome to ' + _html(APP_TITLE) + '</h2>'
    html += '<p class="cover-lead">Plan VBS classrooms and volunteer teams in one place. '
    html += 'Assign Small Group Leaders and K–5 kids to shared Groups, track other volunteer areas, '
    html += 'and print rosters, Group sheets, and allergy lists. Changes sync to involvement SubGroups for check-in.</p>'
    html += '</div>'

    html += '<div class="cover-legend-wrap is-collapsed" id="vbs-cover-legend">'
    html += '<div class="cover-legend-header">'
    html += '<h3 class="cover-legend-heading">What each tab does</h3>'
    html += '<button type="button" class="cover-legend-caret" id="vbs-legend-caret" '
    html += 'aria-expanded="false" title="Show legend" aria-label="Show legend">'
    html += '<i class="fa fa-caret-down" aria-hidden="true"></i></button>'
    html += '</div>'
    html += '<div class="cover-legend-body" id="vbs-legend-body">'
    html += '<p class="meta-line">Click a tab below (or in the bar above) to open that view.</p>'
    html += '<div class="cover-legend">'
    for key, label, desc in TAB_ITEMS:
        if key == 'assign' and not can_assign:
            continue
        href = _script_path() + '?view=' + key
        pill_cls = 'dash-tab cover-pill'
        if key in ('allergies',):
            pill_cls += ' dash-tab-allergy'
        html += '<div class="cover-legend-row">'
        html += '<a class="' + pill_cls + '" href="' + href + '">' + _html(label) + '</a>'
        html += '<div class="cover-legend-desc">' + _html(desc) + '</div>'
        html += '</div>'
    if can_admin:
        html += '<div class="cover-legend-row">'
        html += '<a class="dash-tab cover-pill" href="' + _script_path() + '?view=settings">Settings</a>'
        html += '<div class="cover-legend-desc">Admin only: set which involvement each pool uses (Volunteers, K–5, Pre-K, Nursery).</div>'
        html += '</div>'
    html += '</div></div></div>'

    if can_assign:
        html += '<div class="cover-cta">'
        html += '<a class="btn-primary" href="' + _script_path() + '?view=assign" style="display:inline-block;text-decoration:none">Go to Assign</a>'
        html += '<a class="btn-secondary" href="' + _script_path() + '?view=leaders" style="display:inline-block;text-decoration:none;margin-left:10px">View Volunteers</a>'
        if can_admin:
            html += '<a class="btn-secondary" href="' + _script_path() + '?view=settings" style="display:inline-block;text-decoration:none;margin-left:10px">Settings</a>'
        html += '</div>'
    else:
        html += '<div class="cover-cta">'
        html += '<a class="btn-primary" href="' + _script_path() + '?view=leaders" style="display:inline-block;text-decoration:none">View Volunteers</a>'
        html += '<span class="meta-line" style="margin-left:12px;display:inline">You have view-only access.</span>'
        html += '</div>'

    html += '</div>'
    return html


def _person_display_name(person, first_last=False):
    """Default Name2 (Last, First). Pass first_last=True for First Last."""
    if first_last:
        first = _s(person.get('first'))
        last = _s(person.get('last'))
        fl = (first + ' ' + last).strip()
        if fl:
            return fl
    return _s(person.get('name'), '(Unknown)')


def _person_link(person, first_last=False):
    return (
        '<a href="/Person2/' + str(person['people_id']) + '" target="_blank">'
        + _html(_person_display_name(person, first_last=first_last))
        + '</a>'
    )


def _person_link_with_age_band(person, first_last=True):
    """Name link plus (Adult) / (Minor) from age_band."""
    band = _s(person.get('age_band'), 'Unknown')
    if band not in ('Adult', 'Minor'):
        band = 'Unknown'
    return _person_link(person, first_last=first_last) + ' (' + _html(band) + ')'


def _people_ids_csv(people):
    """Comma-separated unique PeopleIds from a list of person dicts."""
    ids = []
    seen = {}
    try:
        for p in people:
            pid = _i(p.get('people_id'))
            if pid and pid not in seen:
                seen[pid] = True
                ids.append(str(pid))
    except:
        pass
    return ','.join(ids)


def _tag_add_button(people, suggest=''):
    """Add to Tag control (same UX pattern as InvolvementDashboard)."""
    csv = _people_ids_csv(people)
    if not csv:
        return ''
    return (
        '<button type="button" class="btn-tag-add vbs-screen-only" '
        'data-people-ids="' + _html(csv) + '" '
        'data-tag-suggest="' + _html(suggest) + '">'
        '<i class="fa fa-tag"></i> Add to Tag</button>'
    )


def _list_toolbar(people, count_label, tag_suggest=''):
    """Count line + Add to Tag for any individual list."""
    html = '<div class="list-actions vbs-screen-only">'
    html += '<p class="meta-line" style="margin:0">' + count_label + '</p>'
    html += _tag_add_button(people, tag_suggest)
    html += '</div>'
    return html


def _bundle_people(bundle):
    """Flatten leaders + assistants + kids for one group block."""
    people = []
    for key in ('leaders', 'coleaders', 'assistants', 'kids'):
        for p in bundle.get(key) or []:
            people.append(p)
    return people


def _sort_th(label, kind='text'):
    """Clickable master-list header. kind: text | num | group."""
    return (
        '<th class="vbs-sort" data-sort="' + kind + '" title="Click to sort">'
        + _html(label) + '</th>'
    )


def _roster_table(people, include_role=False, include_pool=False, include_group=True, include_grade=True, include_age_band=False, include_service=False, tag_suggest='', blank_group_unless_sgl=False):
    n = 0
    try:
        n = len(people)
    except:
        n = 0
    html = _list_toolbar(
        people,
        '<strong>' + str(n) + '</strong> people · click a column header to sort',
        tag_suggest or ('VBS ' + VBS_YEAR),
    )
    html += '<div class="table-scroll"><table class="people-table vbs-sortable"><thead><tr>'
    html += _sort_th('Name', 'text')
    if include_pool:
        html += _sort_th('Pool', 'text')
    if include_service:
        html += _sort_th('Service area', 'text')
        html += _sort_th('Also Serves', 'text')
    if include_role:
        html += _sort_th('Role', 'text')
    if include_group:
        html += _sort_th('Group', 'group')
    html += _sort_th('Gender', 'text')
    html += _sort_th('Age', 'num')
    if include_age_band:
        html += _sort_th('Adult / Minor', 'text')
    if include_grade:
        html += _sort_th('Grade', 'text')
    html += '</tr></thead><tbody>'
    col_count = 3  # name, gender, age
    if include_pool:
        col_count += 1
    if include_service:
        col_count += 2  # service area + also serves
    if include_role:
        col_count += 1
    if include_group:
        col_count += 1
    if include_age_band:
        col_count += 1
    if include_grade:
        col_count += 1
    try:
        for p in people:
            html += '<tr>'
            html += '<td>' + _person_link(p) + '</td>'
            if include_pool:
                html += '<td>' + _html(p.get('pool', '')) + '</td>'
            if include_service:
                html += '<td>' + _html(p.get('service_area') or 'Unassigned') + '</td>'
                also = p.get('also_serves') or []
                html += '<td>' + _html(', '.join(also) if also else '') + '</td>'
            if include_role:
                html += '<td>' + _html(p.get('role_display', '')) + '</td>'
            if include_group:
                gdisp = _s(p.get('group', ''))
                if blank_group_unless_sgl:
                    # Only Small Group Leaders use Group N — blank for other areas
                    if _s(p.get('service_area')) != SERVICE_SMALL_GROUP:
                        gdisp = ''
                html += '<td>' + _html(gdisp) + '</td>'
            html += '<td>' + _html(p.get('gender', '')) + '</td>'
            html += '<td>' + _html(p.get('age', '')) + '</td>'
            if include_age_band:
                html += '<td>' + _html(p.get('age_band', 'Unknown')) + '</td>'
            if include_grade:
                html += '<td>' + _html(p.get('grade', '')) + '</td>'
            html += '</tr>'
    except Exception, ex:
        html += '<tr><td colspan="' + str(col_count) + '"><div class="info-banner danger">Roster row error: ' + _html(_ex_msg(ex)) + '</div></td></tr>'
    if n == 0:
        html += '<tr><td colspan="' + str(col_count) + '"><div class="empty-state">No people</div></td></tr>'
    html += '</tbody></table></div>'
    return html


def _find_group_sorted(people):
    """K-5 "Find Your Group" sheet: last name A-Z, then first name."""
    rows = []
    try:
        rows = list(people)
    except:
        rows = []

    def _key(p):
        return (
            _s(p.get('last', '')).lower(),
            _s(p.get('first', '')).lower(),
            _s(p.get('name', '')).lower(),
        )

    try:
        rows.sort(key=_key)
    except:
        pass
    return rows


def _find_group_table(people):
    """Name + Group only — wall/posted 11x17 "Find Your Group" sheet."""
    people = _find_group_sorted(people)
    n = len(people)
    html = _list_toolbar(
        people,
        '<strong>' + str(n) + '</strong> K-5 participants · Name and Group only · default sort: last name · click a header to re-sort',
        'VBS ' + VBS_YEAR + ' Find Your Group',
    )
    html += '<div class="table-scroll"><table class="people-table vbs-sortable vbs-find-table"><thead><tr>'
    html += _sort_th('Name', 'text')
    html += _sort_th('Group', 'group')
    html += '</tr></thead><tbody>'
    for p in people:
        html += '<tr>'
        html += '<td>' + _html(p.get('name', '')) + '</td>'
        html += '<td>' + _html(p.get('group', 'Unassigned')) + '</td>'
        html += '</tr>'
    if n == 0:
        html += '<tr><td colspan="2"><div class="empty-state">No K-5 participants</div></td></tr>'
    html += '</tbody></table></div>'
    return html


def _table_sort_script():
    # ES5-friendly; assigned to model.Script (PyScriptForm wraps in <script>).
    # Includes sortable headers + Add to Tag modal (InvolvementDashboard pattern).
    script_url = _script_path()
    return r"""
(function () {
  function textOf(el) {
    return (el.textContent || el.innerText || '').replace(/^\s+|\s+$/g, '');
  }
  function sortKey(td, kind) {
    var t = textOf(td);
    if (kind === 'num') {
      var n = parseFloat(String(t).replace(/[^0-9.\-]/g, ''));
      return isNaN(n) ? -1e99 : n;
    }
    if (kind === 'group') {
      var gm = /^Group\s+(\d+)$/i.exec(t);
      if (gm) return parseInt(gm[1], 10);
      if (/^unassigned$/i.test(t)) return 1e9;
      return 1e8;
    }
    var m = /^Group\s+(\d+)$/i.exec(t);
    if (m) return 'g' + ('00000' + m[1]).slice(-5);
    if (/^unassigned$/i.test(t)) return 'zzzz-unassigned';
    return t.toLowerCase();
  }
  function hasClass(el, name) {
    return (' ' + (el.className || '') + ' ').indexOf(' ' + name + ' ') >= 0;
  }
  function addClass(el, name) {
    if (!hasClass(el, name)) el.className = ((el.className || '') + ' ' + name).replace(/^\s+|\s+$/g, '');
  }
  function removeClass(el, name) {
    el.className = (' ' + (el.className || '') + ' ').replace(' ' + name + ' ', ' ').replace(/^\s+|\s+$/g, '');
  }
  function resetMarks(table) {
    var ths = table.querySelectorAll('th.vbs-sort');
    for (var i = 0; i < ths.length; i++) {
      removeClass(ths[i], 'vbs-sort-asc');
      removeClass(ths[i], 'vbs-sort-desc');
    }
  }
  function sortTable(table, colIndex, kind) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = [];
    var i;
    for (i = 0; i < tbody.rows.length; i++) rows.push(tbody.rows[i]);
    var prevCol = table.getAttribute('data-vbs-col');
    var prevDir = table.getAttribute('data-vbs-dir');
    var dir = (prevCol === String(colIndex) && prevDir === 'asc') ? 'desc' : 'asc';
    rows.sort(function (a, b) {
      var aEmpty = a.querySelector('.empty-state');
      var bEmpty = b.querySelector('.empty-state');
      if (aEmpty && !bEmpty) return 1;
      if (bEmpty && !aEmpty) return -1;
      if (!a.cells[colIndex] || !b.cells[colIndex]) return 0;
      var ka = sortKey(a.cells[colIndex], kind);
      var kb = sortKey(b.cells[colIndex], kind);
      if (ka < kb) return dir === 'asc' ? -1 : 1;
      if (ka > kb) return dir === 'asc' ? 1 : -1;
      return 0;
    });
    table.setAttribute('data-vbs-dir', dir);
    table.setAttribute('data-vbs-col', String(colIndex));
    resetMarks(table);
    if (table.tHead && table.tHead.rows[0] && table.tHead.rows[0].cells[colIndex]) {
      addClass(table.tHead.rows[0].cells[colIndex], dir === 'asc' ? 'vbs-sort-asc' : 'vbs-sort-desc');
    }
    for (i = 0; i < rows.length; i++) tbody.appendChild(rows[i]);
  }
  function bind(table) {
    if (!table.tHead || !table.tHead.rows.length) return;
    var ths = table.tHead.rows[0].cells;
    for (var i = 0; i < ths.length; i++) {
      (function (idx) {
        var th = ths[idx];
        addClass(th, 'vbs-sort');
        th.style.cursor = 'pointer';
        th.onclick = function () {
          sortTable(table, idx, th.getAttribute('data-sort') || 'text');
        };
      })(i);
    }
  }
  function initSort() {
    var tables = document.querySelectorAll('table.vbs-sortable');
    for (var i = 0; i < tables.length; i++) bind(tables[i]);
  }

  var scriptUrl = """ + json.dumps(script_url) + r""";
  var pendingTagPeopleIds = [];

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }
  function $all(sel, root) {
    return (root || document).querySelectorAll(sel);
  }
  function parseIds(csv) {
    var out = [];
    var seen = {};
    String(csv || '').split(',').forEach(function (x) {
      var n = parseInt(x, 10);
      if (n > 0 && !seen[n]) {
        seen[n] = true;
        out.push(n);
      }
    });
    return out;
  }
  function openTagModal(peopleIds, suggestedName) {
    pendingTagPeopleIds = peopleIds || [];
    if (!pendingTagPeopleIds.length) {
      alert('No people in this list to tag.');
      return;
    }
    var countEl = $('#tag-modal-count');
    var input = $('#tag-name-input');
    var overlay = $('#tag-modal-overlay');
    if (countEl) countEl.textContent = pendingTagPeopleIds.length + ' people will be added to this tag.';
    if (input) input.value = suggestedName || '';
    var append = $('input[name="tag-mode"][value="append"]');
    if (append) append.checked = true;
    var openDone = $('#tag-open-when-done');
    if (openDone) openDone.checked = true;
    if (overlay) addClass(overlay, 'visible');
    if (input) {
      setTimeout(function () {
        input.focus();
        input.select();
      }, 50);
    }
  }
  function closeTagModal() {
    var overlay = $('#tag-modal-overlay');
    if (overlay) removeClass(overlay, 'visible');
    pendingTagPeopleIds = [];
  }
  function submitAddToTag() {
    var input = $('#tag-name-input');
    var tagName = input ? String(input.value || '').replace(/^\s+|\s+$/g, '') : '';
    if (!tagName) {
      alert('Enter a tag name.');
      if (input) input.focus();
      return;
    }
    if (!pendingTagPeopleIds.length) {
      alert('No people to tag.');
      return;
    }
    var mode = $('input[name="tag-mode"]:checked');
    var clearFirst = mode && mode.value === 'clear';
    var openEl = $('#tag-open-when-done');
    var openWhenDone = openEl ? !!openEl.checked : true;
    var idsCsv = pendingTagPeopleIds.join(',');
    closeTagModal();

    var body = 'ajax=true'
      + '&action=add_to_tag'
      + '&people_ids=' + encodeURIComponent(idsCsv)
      + '&tag_name=' + encodeURIComponent(tagName)
      + '&clear_first=' + (clearFirst ? '1' : '0');

    var xhr = new XMLHttpRequest();
    xhr.open('POST', scriptUrl, true);
    xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      var data = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch (e) {
        alert('Tag request failed (invalid response).');
        return;
      }
      if (!data) {
        alert('Tag request failed.');
        return;
      }
      if (data.error) {
        alert(data.error);
        openTagModal(parseIds(idsCsv), tagName);
        return;
      }
      var msg = (data.count || 0) + ' people added to tag "' + (data.tag_name || tagName) + '"';
      if (data.cleared) msg += ' (tag cleared first)';
      if (openWhenDone && data.tag_url) {
        window.open(data.tag_url, '_blank', 'noopener');
      } else {
        alert(msg + '.');
      }
    };
    xhr.send(body);
  }
  function closest(el, predicate) {
    while (el && el !== document) {
      if (predicate(el)) return el;
      el = el.parentNode;
    }
    return null;
  }
  function initTag() {
    document.addEventListener('click', function (e) {
      var t = e.target;
      var addBtn = closest(t, function (el) {
        return el.className && (' ' + el.className + ' ').indexOf(' btn-tag-add ') >= 0;
      });
      if (addBtn) {
        e.preventDefault();
        openTagModal(parseIds(addBtn.getAttribute('data-people-ids')), String(addBtn.getAttribute('data-tag-suggest') || ''));
        return;
      }
      var cancelBtn = closest(t, function (el) { return el.id === 'btn-tag-cancel'; });
      if (cancelBtn) {
        e.preventDefault();
        closeTagModal();
        return;
      }
      var confirmBtn = closest(t, function (el) { return el.id === 'btn-tag-confirm'; });
      if (confirmBtn) {
        e.preventDefault();
        submitAddToTag();
        return;
      }
      if (e.target && e.target.id === 'tag-modal-overlay') {
        closeTagModal();
      }
    });
    var input = $('#tag-name-input');
    if (input) {
      input.addEventListener('keydown', function (e) {
        if (e.which === 13 || e.keyCode === 13) {
          e.preventDefault();
          submitAddToTag();
        } else if (e.which === 27 || e.keyCode === 27) {
          closeTagModal();
        }
      });
    }
  }

  function stampPrintFooter() {
    var el = document.getElementById('vbs-print-footer');
    if (!el) return;
    var d = new Date();
    var stamp = d.toLocaleString(undefined, {
      weekday: 'short',
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit'
    });
    el.textContent = 'Printed: ' + stamp;
  }
  function initPrintFooter() {
    stampPrintFooter();
    var footer = document.getElementById('vbs-print-footer');
    var printTitle = footer ? (footer.getAttribute('data-print-title') || '') : '';
    var prevTitle = document.title;
    function applyPrintTitle() {
      stampPrintFooter();
      if (printTitle) document.title = printTitle;
    }
    function restoreTitle() {
      if (printTitle) document.title = prevTitle;
    }
    if (window.addEventListener) {
      window.addEventListener('beforeprint', applyPrintTitle);
      window.addEventListener('afterprint', restoreTitle);
    }
    // Safari / some WebKit: matchMedia print
    if (window.matchMedia) {
      try {
        var mql = window.matchMedia('print');
        if (mql && mql.addListener) {
          mql.addListener(function (m) {
            if (m.matches) applyPrintTitle();
            else restoreTitle();
          });
        }
      } catch (err) {}
    }
  }

  function initBlocksColToggles() {
    var root = document.getElementById('vbs-blocks-view');
    if (!root) return;
    var KEY_SHIRT = 'vbs-blocks-show-shirt';
    var KEY_ALLERGY = 'vbs-blocks-show-allergy';
    function apply(col, on) {
      var cls = col === 'shirt' ? 'show-shirt' : 'show-allergy';
      if (on) addClass(root, cls);
      else removeClass(root, cls);
      var btns = root.querySelectorAll('.btn-col-toggle[data-col="' + col + '"]');
      for (var i = 0; i < btns.length; i++) {
        if (on) addClass(btns[i], 'is-on');
        else removeClass(btns[i], 'is-on');
        btns[i].setAttribute('aria-pressed', on ? 'true' : 'false');
      }
    }
    function read(key) {
      try {
        return window.localStorage && localStorage.getItem(key) === '1';
      } catch (e) {
        return false;
      }
    }
    function write(key, on) {
      try {
        if (window.localStorage) localStorage.setItem(key, on ? '1' : '0');
      } catch (e) {}
    }
    apply('shirt', read(KEY_SHIRT));
    apply('allergy', read(KEY_ALLERGY));
    var toggles = root.querySelectorAll('.btn-col-toggle');
    for (var t = 0; t < toggles.length; t++) {
      toggles[t].addEventListener('click', function (e) {
        e.preventDefault();
        var col = this.getAttribute('data-col') || '';
        if (col !== 'shirt' && col !== 'allergy') return;
        var on = !hasClass(root, col === 'shirt' ? 'show-shirt' : 'show-allergy');
        apply(col, on);
        write(col === 'shirt' ? KEY_SHIRT : KEY_ALLERGY, on);
      });
    }
  }

  function initNavCaret() {
    var nav = document.getElementById('vbs-dash-nav');
    var btn = document.getElementById('vbs-nav-caret');
    if (!nav || !btn) return;
    var KEY = 'vbs-nav-collapsed';
    function setIcon(collapsed) {
      btn.innerHTML = collapsed
        ? '<i class="fa fa-caret-down" aria-hidden="true"></i>'
        : '<i class="fa fa-caret-up" aria-hidden="true"></i>';
      btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      btn.setAttribute('title', collapsed ? 'Show menu' : 'Collapse menu');
      btn.setAttribute('aria-label', collapsed ? 'Show menu' : 'Collapse menu');
    }
    function apply(collapsed) {
      if (collapsed) addClass(nav, 'is-collapsed');
      else removeClass(nav, 'is-collapsed');
      setIcon(collapsed);
    }
    var stored = null;
    try { stored = window.localStorage ? localStorage.getItem(KEY) : null; } catch (e) {}
    var collapsed;
    if (stored === '1') collapsed = true;
    else if (stored === '0') collapsed = false;
    else collapsed = (nav.getAttribute('data-view') || '') !== 'home';
    apply(collapsed);
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      var next = !hasClass(nav, 'is-collapsed');
      apply(next);
      try {
        if (window.localStorage) localStorage.setItem(KEY, next ? '1' : '0');
      } catch (err) {}
    });
  }

  function initLegendCaret() {
    var wrap = document.getElementById('vbs-cover-legend');
    var btn = document.getElementById('vbs-legend-caret');
    if (!wrap || !btn) return;
    var KEY = 'vbs-legend-collapsed';
    function setIcon(collapsed) {
      btn.innerHTML = collapsed
        ? '<i class="fa fa-caret-down" aria-hidden="true"></i>'
        : '<i class="fa fa-caret-up" aria-hidden="true"></i>';
      btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      btn.setAttribute('title', collapsed ? 'Show legend' : 'Collapse legend');
      btn.setAttribute('aria-label', collapsed ? 'Show legend' : 'Collapse legend');
    }
    function apply(collapsed) {
      if (collapsed) addClass(wrap, 'is-collapsed');
      else removeClass(wrap, 'is-collapsed');
      setIcon(collapsed);
    }
    var stored = null;
    try { stored = window.localStorage ? localStorage.getItem(KEY) : null; } catch (e) {}
    // Default collapsed; only expand if user previously chose Show.
    var collapsed = (stored !== '0');
    apply(collapsed);
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      var next = !hasClass(wrap, 'is-collapsed');
      apply(next);
      try {
        if (window.localStorage) localStorage.setItem(KEY, next ? '1' : '0');
      } catch (err) {}
    });
  }

  function initShepherdBlocks() {
    var blocks = document.querySelectorAll('.shepherd-block[data-shepherd-key]');
    for (var i = 0; i < blocks.length; i++) {
      (function (block) {
        var key = block.getAttribute('data-shepherd-key') || 'x';
        var btn = block.querySelector('.shepherd-block-caret');
        var header = block.querySelector('.shepherd-block-header');
        if (!btn || !header) return;
        var KEY = 'vbs-shepherd-' + key + '-collapsed';
        function setIcon(collapsed) {
          btn.innerHTML = collapsed
            ? '<i class="fa fa-caret-down" aria-hidden="true"></i>'
            : '<i class="fa fa-caret-up" aria-hidden="true"></i>';
          btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
          btn.setAttribute('title', collapsed ? 'Show list' : 'Collapse list');
        }
        function apply(collapsed) {
          if (collapsed) addClass(block, 'is-collapsed');
          else removeClass(block, 'is-collapsed');
          setIcon(collapsed);
        }
        var stored = null;
        try { stored = window.localStorage ? localStorage.getItem(KEY) : null; } catch (e) {}
        // Default collapsed
        var collapsed = (stored !== '0');
        apply(collapsed);
        function toggle(e) {
          e.preventDefault();
          var next = !hasClass(block, 'is-collapsed');
          apply(next);
          try {
            if (window.localStorage) localStorage.setItem(KEY, next ? '1' : '0');
          } catch (err) {}
        }
        btn.addEventListener('click', toggle);
        header.addEventListener('click', function (e) {
          if (e.target === btn || (btn.contains && btn.contains(e.target))) return;
          toggle(e);
        });
      })(blocks[i]);
    }
  }

  function init() {
    initSort();
    initTag();
    initPrintFooter();
    initBlocksColToggles();
    initNavCaret();
    initLegendCaret();
    initShepherdBlocks();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
"""


def _settings_panel():
    """Admin-only: map each pool to an involvement OrganizationId."""
    fields = [
        ('org_leaders', 'Volunteers pool', ORG_LEADERS),
        ('org_k5', 'K-5 pool', ORG_K5),
        ('org_prek', 'Pre-K pool', ORG_PREK),
        ('org_nursery', 'Nursery pool', ORG_NURSERY),
    ]
    html = ''
    html += '<div class="vbs-card">'
    html += '<div class="vbs-card-title">Pool involvements</div>'
    html += '<p class="meta-line">Set the OrganizationId for each VBS pool. Defaults are for the current year; change these when you recreate involvements next year. Stored in JsonDocumentRecords section <strong>' + _html(JSON_SECTION) + '</strong> / id <strong>' + _html(SETTINGS_ID1) + '</strong>.</p>'
    html += '<form method="post" action="' + _script_path() + '">'
    html += '<input type="hidden" name="action" value="save_settings" />'
    html += '<input type="hidden" name="view" value="settings" />'
    html += '<input type="hidden" name="week_start" value="' + _html(_s(VBS_WEEK_START)) + '" />'
    for name, label, oid in fields:
        oname = _org_name(oid)
        html += '<div class="field">'
        html += '<label for="' + name + '">' + _html(label) + '</label>'
        html += '<input type="number" min="1" step="1" required name="' + name + '" id="' + name + '" value="' + str(oid) + '" />'
        if oname:
            html += '<p class="meta-line" style="margin:6px 0 0 0">Current: <a href="/Org/' + str(oid) + '" target="_blank">' + _html(oname) + '</a> (#' + str(oid) + ')</p>'
        else:
            html += '<p class="meta-line" style="margin:6px 0 0 0">OrganizationId ' + str(oid) + ' — name not found</p>'
        html += '</div>'
    html += '<button type="submit" class="btn-primary">Save pool involvements</button>'
    html += '</form></div>'
    html += '<div class="vbs-card">'
    html += '<div class="vbs-card-title">VBS week (Counts attendance)</div>'
    html += '<p class="meta-line">Monday date for Mon–Fri attendance toggles on Counts. Leave blank to use the current week’s Monday. Meetings must exist on each pool involvement for those calendar days.</p>'
    html += '<form method="post" action="' + _script_path() + '">'
    html += '<input type="hidden" name="action" value="save_settings" />'
    html += '<input type="hidden" name="view" value="settings" />'
    # Preserve org ids when saving week only — include hidden/current org fields
    html += '<input type="hidden" name="org_leaders" value="' + str(ORG_LEADERS) + '" />'
    html += '<input type="hidden" name="org_k5" value="' + str(ORG_K5) + '" />'
    html += '<input type="hidden" name="org_prek" value="' + str(ORG_PREK) + '" />'
    html += '<input type="hidden" name="org_nursery" value="' + str(ORG_NURSERY) + '" />'
    html += '<div class="field">'
    html += '<label for="week_start">Week start (Monday, YYYY-MM-DD)</label>'
    html += '<input type="text" name="week_start" id="week_start" placeholder="e.g. 2026-07-27" value="' + _html(_s(VBS_WEEK_START)) + '" maxlength="10" />'
    html += '</div>'
    html += '<button type="submit" class="btn-primary">Save VBS week</button>'
    html += '</form></div>'
    return html


def _assign_panel(pools, group_names):
    leaders_people = pools['leaders']['people']

    # Leader Group dropdown: show who is already assigned to each Group N.
    leader_group_opts = '<option value="Unassigned">Unassigned</option>'
    for g in group_names:
        members = []
        for p in leaders_people:
            if p.get('group_raw') != g:
                continue
            members.append(p)

        def _rank(person):
            roles = person.get('roles') or []
            if ROLE_LEADER in roles:
                return 0
            if ROLE_COLEADER in roles:
                return 1
            if ROLE_ASSISTANT in roles:
                return 2
            return 3

        try:
            members.sort(key=lambda person: (_rank(person), _s(person.get('name', '')).lower()))
        except:
            pass
        bits = []
        for p in members:
            role = _s(p.get('role_display'))
            if role:
                bits.append(_s(p.get('name')) + ' (' + role + ')')
            else:
                bits.append(_s(p.get('name')))
        if bits:
            label = g + ' - ' + ', '.join(bits)
        else:
            label = g + ' - (none)'
        leader_group_opts += '<option value="' + _html(g) + '">' + _html(label) + '</option>'

    # Participant Group dropdown: group name only (kids list shows assignment on the person)
    opts = '<option value="Unassigned">Unassigned</option>'
    for g in group_names:
        opts += '<option value="' + _html(g) + '">' + _html(g) + '</option>'

    role_opts = '<option value="">-- Select role --</option>'
    for r in ROLE_NAMES:
        role_opts += '<option value="' + _html(r) + '">' + _html(r) + '</option>'

    service_opts = '<option value="Unassigned">Unassigned</option>'
    for s in SERVICE_AREAS:
        service_opts += '<option value="' + _html(s) + '">' + _html(s) + '</option>'

    # Dropdown label shows primary + role (+ group for SGL) + Also serves.
    # Unassigned leaders (no service area) first, then alphabetical by name.
    leader_opts = '<option value="">-- Select --</option>'
    leaders_sorted = []
    try:
        leaders_sorted = list(leaders_people)
    except:
        leaders_sorted = []

    def _leader_sort_key(person):
        unassigned = 0 if not _s(person.get('service_area')) else 1
        return (
            unassigned,
            _s(person.get('last', '')).lower(),
            _s(person.get('first', '')).lower(),
            _s(person.get('name', '')).lower(),
        )

    try:
        leaders_sorted.sort(key=_leader_sort_key)
    except:
        pass
    for p in leaders_sorted:
        area = _s(p.get('service_area')) or 'Unassigned'
        role = _s(p.get('role_display')) or 'no role'
        also = p.get('also_serves') or []
        also_bit = ''
        if also:
            also_bit = ' (+ ' + ', '.join(also) + ')'
        if area == SERVICE_SMALL_GROUP:
            label = p['name'] + ' - ' + area + ' - ' + role + ' - ' + p['group'] + also_bit
        elif area == 'Unassigned':
            label = p['name'] + ' - Unassigned'
        else:
            label = p['name'] + ' - ' + area + ' - ' + role + also_bit
        leader_opts += '<option value="' + str(p['people_id']) + '">' + _html(label) + '</option>'

    kid_opts = '<option value="">-- Select --</option>'
    # Only K-5 gets Group N; Pre-K / Nursery are pool-only (no group assign).
    # Unassigned students always appear first in the pick list.
    for key in ('k5',):
        kid_opts += '<optgroup label="' + _html(pools[key]['label']) + '">'
        kids = []
        try:
            kids = list(pools[key]['people'])
        except:
            kids = []

        def _kid_sort_key(person):
            unassigned = 0 if not person.get('group_raw') else 1
            return (
                unassigned,
                _s(person.get('last', '')).lower(),
                _s(person.get('first', '')).lower(),
                _s(person.get('name', '')).lower(),
            )

        try:
            kids.sort(key=_kid_sort_key)
        except:
            pass
        for p in kids:
            kid_opts += '<option value="' + str(pools[key]['org_id']) + ':' + str(p['people_id']) + '">' + \
                        _html(p['name'] + ' - ' + p['group']) + '</option>'
        kid_opts += '</optgroup>'

    also_checks = ''
    for area in SECONDARY_AREAS:
        also_checks += (
            '<label class="also-check" data-also-area="' + _html(area) + '">'
            '<input type="checkbox" class="leader-also-cb" value="' + _html(area) + '" />'
            '<span>' + _html(area) + '</span></label>'
        )

    html = ''
    html += '<div class="vbs-card">'
    html += '<div class="vbs-card-title">Create group</div>'
    html += '<form method="post" action="' + _script_path() + '" class="vbs-inline-form">'
    html += '<input type="hidden" name="action" value="create_group" />'
    html += '<input type="hidden" name="view" value="assign" />'
    html += '<button type="submit" class="btn-primary">Add next Group N</button>'
    html += '<span class="meta-line vbs-form-hint">Creates <strong>' + _html(_next_group_name()) + '</strong> in the registry (SubGroup syncs on first assign).</span>'
    html += '</form></div>'

    html += '<div class="assign-grid">'
    html += '<div class="vbs-card">'
    html += '<div class="vbs-card-title">Assign leader</div>'
    html += '<p class="meta-line">Choose person, <strong>service area</strong>, and <strong>role</strong>. '
    html += 'Only <strong>Small Group Leader</strong> also gets a Group N. '
    html += '<strong>Also serves</strong> adds Skits / Choreography on top of any primary (including when those are primary themselves). '
    html += 'Choose <strong>Unassigned</strong> service area to clear.</p>'
    html += '<form method="post" action="' + _script_path() + '" id="leader-assign-form">'
    html += '<input type="hidden" name="action" value="assign_role" />'
    html += '<input type="hidden" name="view" value="assign" />'
    html += '<input type="hidden" name="also_serves" id="leader-also-serves" value="" />'
    html += '<div class="field"><label>Leader</label>'
    html += '<select name="people_id" required>' + leader_opts + '</select></div>'
    html += '<div class="field"><label>Service area</label>'
    html += '<select name="service_area" id="leader-service-area" required>' + service_opts + '</select></div>'
    html += '<div class="field" id="leader-role-wrap"><label>Role</label>'
    html += '<select name="role" id="leader-role">' + role_opts + '</select></div>'
    html += '<div class="field" id="leader-group-wrap"><label>Group</label>'
    html += '<select name="group" id="leader-group">' + leader_group_opts + '</select></div>'
    html += '<div class="field" id="leader-also-wrap"><label>Also serves <span class="meta-line">(optional)</span></label>'
    html += '<div id="leader-also-checks">' + also_checks + '</div>'
    html += '<p class="meta-line" style="margin:4px 0 0 0">Hidden when it matches the primary service area.</p></div>'
    html += '<button type="submit" class="btn-primary">Assign leader</button></form>'
    html += '''<script>
(function () {
  function syncAlsoHidden() {
    var hidden = document.getElementById('leader-also-serves');
    var boxes = document.querySelectorAll('.leader-also-cb');
    var vals = [];
    for (var i = 0; i < boxes.length; i++) {
      var lab = boxes[i].parentNode;
      if (lab && lab.style.display === 'none') continue;
      if (boxes[i].checked) vals.push(boxes[i].value);
    }
    if (hidden) hidden.value = vals.join(',');
  }
  function syncLeaderAssignFields() {
    var area = document.getElementById('leader-service-area');
    var roleWrap = document.getElementById('leader-role-wrap');
    var groupWrap = document.getElementById('leader-group-wrap');
    var alsoWrap = document.getElementById('leader-also-wrap');
    var roleSel = document.getElementById('leader-role');
    var groupSel = document.getElementById('leader-group');
    if (!area) return;
    var v = area.value;
    var isClear = !v || v === 'Unassigned';
    var isSgl = v === 'Small Group Leader';
    if (roleWrap) roleWrap.style.display = isClear ? 'none' : '';
    if (groupWrap) groupWrap.style.display = isSgl ? '' : 'none';
    if (alsoWrap) alsoWrap.style.display = isClear ? 'none' : '';
    if (roleSel) {
      roleSel.required = !isClear;
      if (isClear) roleSel.value = '';
    }
    if (groupSel) {
      groupSel.required = !!isSgl;
      if (!isSgl) groupSel.value = 'Unassigned';
    }
    var labels = document.querySelectorAll('.also-check');
    for (var i = 0; i < labels.length; i++) {
      var a = labels[i].getAttribute('data-also-area') || '';
      var hide = isClear || a === v;
      labels[i].style.display = hide ? 'none' : 'flex';
      if (hide) {
        var cb = labels[i].querySelector('.leader-also-cb');
        if (cb) cb.checked = false;
      }
    }
    syncAlsoHidden();
  }
  var area = document.getElementById('leader-service-area');
  var form = document.getElementById('leader-assign-form');
  if (area) {
    if (area.addEventListener) area.addEventListener('change', syncLeaderAssignFields);
    else if (area.attachEvent) area.attachEvent('onchange', syncLeaderAssignFields);
    syncLeaderAssignFields();
  }
  var boxes = document.querySelectorAll('.leader-also-cb');
  for (var j = 0; j < boxes.length; j++) {
    if (boxes[j].addEventListener) boxes[j].addEventListener('change', syncAlsoHidden);
    else if (boxes[j].attachEvent) boxes[j].attachEvent('onchange', syncAlsoHidden);
  }
  if (form) {
    if (form.addEventListener) form.addEventListener('submit', syncAlsoHidden);
    else if (form.attachEvent) form.attachEvent('onsubmit', syncAlsoHidden);
  }
})();
</script>'''
    html += '</div>'

    html += '<div class="vbs-card">'
    html += '<div class="vbs-card-title">Assign participant</div>'
    html += '<p class="meta-line">K-5 only — choose person and group. <strong>Unassigned</strong> clears their Group N. '
    html += 'Pre-K and Nursery do not use Group N.</p>'
    html += '<form method="post" action="' + _script_path() + '">'
    html += '<input type="hidden" name="action" value="assign_group" />'
    html += '<input type="hidden" name="view" value="assign" />'
    html += '<div class="field"><label>Participant</label>'
    html += '<select name="org_pid" required>' + kid_opts + '</select></div>'
    html += '<div class="field"><label>Group</label>'
    html += '<select name="group" required>' + opts + '</select></div>'
    html += '<button type="submit" class="btn-primary">Assign group</button></form>'
    html += '</div></div>'
    return html


def _render_group_blocks(bundles):
    """One printable card per Group. Shirt / Allergy columns toggled via .show-shirt / .show-allergy."""
    html = ''
    for b in bundles:
        html += '<div class="vbs-group-block vbs-card">'
        block_title = _group_block_title(b)
        html += '<div class="list-actions vbs-screen-only" style="margin-bottom:10px">'
        html += '<h2 class="vbs-group-heading" style="margin:0">' + _html(block_title) + '</h2>'
        html += _tag_add_button(_bundle_people(b), 'VBS ' + VBS_YEAR + ' ' + _s(b['group']))
        html += '</div>'
        html += '<h2 class="vbs-group-heading vbs-print-only">' + _html(block_title) + '</h2>'
        html += '<div class="stats-grid compact vbs-block-stats">'
        html += '<div class="stat-card"><div class="stat-value">' + str(b['team_count']) + '</div><div class="stat-label">Team</div></div>'
        html += '<div class="stat-card"><div class="stat-value">' + str(b['student_count']) + '</div><div class="stat-label">Students</div></div>'
        html += '<div class="stat-card"><div class="stat-value">' + str(b['boys']) + '</div><div class="stat-label">Boys</div></div>'
        html += '<div class="stat-card"><div class="stat-value">' + str(b['girls']) + '</div><div class="stat-label">Girls</div></div>'
        html += '</div>'
        html += '<ul class="subgroup-list">'
        html += '<li class="subgroup-item"><span class="subgroup-name">Leader</span><span>' + (', '.join([_person_link(x, first_last=True) for x in b['leaders']]) or '<em>Unassigned</em>') + '</span></li>'
        if b.get('coleaders'):
            html += '<li class="subgroup-item"><span class="subgroup-name">Co-leader</span><span>' + ', '.join([_person_link(x, first_last=True) for x in b['coleaders']]) + '</span></li>'
        html += '<li class="subgroup-item"><span class="subgroup-name">Assistant Leader(s)</span><span>' + (', '.join([_person_link(x, first_last=True) for x in b['assistants']]) or '<em>None</em>') + '</span></li>'
        html += '</ul>'
        html += '<div class="table-scroll"><table class="people-table"><thead><tr>'
        html += '<th>First</th><th>Last</th><th>Gender</th><th>Age</th><th>Grade</th><th>Emergency contact</th>'
        html += '<th class="col-shirt">T-Shirt</th>'
        html += '<th class="col-allergy">Allergies</th>'
        html += '</tr></thead><tbody>'
        for k in b['kids']:
            has_all = _allergy_text_meaningful(k.get('allergy', ''))
            html += '<tr>'
            html += '<td>' + _html(k['first']) + '</td>'
            html += '<td>' + _html(k['last']) + '</td>'
            html += '<td>' + _html(k['gender']) + '</td>'
            html += '<td>' + _html(k['age']) + '</td>'
            html += '<td>' + _html(k['grade']) + '</td>'
            html += '<td>' + _html(k['emergency']) + '</td>'
            shirt = _s(k.get('shirt_size')) or ''
            html += '<td class="col-shirt">' + _html(shirt) + '</td>'
            note = _html(k['allergy']) if has_all else ''
            html += '<td class="col-allergy">' + note + '</td>'
            html += '</tr>'
        if not b['kids']:
            html += '<tr><td colspan="8"><div class="empty-state">No students</div></td></tr>'
        html += '</tbody></table></div></div>'
    if not bundles:
        html += '<div class="empty-state">No groups yet. Create a group from Assign.</div>'
    return html


def _css():
    # Match InvolvementDashboard: styles live in model.Form only (not model.Styles).
    # Avoid CSS property name "content" (and prefer not relying on @media print hide).
    # Force paint inside TouchPoint .box-content -- blank viewport with HTML in DOM
    # usually means visibility/display was collapsed by theme or print rules.
    return '''
.vbs-root {
    display: block !important;
    visibility: visible !important;
    opacity: 1 !important;
    color: #1e293b !important;
    position: relative !important;
    z-index: 1 !important;
    max-width: 1400px;
    margin: 0 auto;
    padding: 20px;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f5f5f5 !important;
    min-height: 240px;
}
.dashboard-header {
    background: #19283B;
    color: white !important;
    padding: 14px 20px 16px;
    border-radius: 12px;
    margin: 0 auto 12px auto;
    box-shadow: 0 4px 15px rgba(1, 43, 88, 0.35);
    display: block !important;
    visibility: visible !important;
    text-align: center;
    width: 100%;
    max-width: 640px;
    box-sizing: border-box;
}
.vbs-header-hero {
    text-align: center;
    margin: 0 0 8px 0;
}
.vbs-header-hero a {
    display: inline-block;
    text-decoration: none !important;
    line-height: 0;
}
.vbs-header-hero img {
    display: block;
    margin: 0 auto;
    max-height: 106px;
    max-width: 330px;
    width: auto;
    height: auto;
    object-fit: contain;
    border-radius: 8px;
    background: rgba(255,255,255,0.95);
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}
.dashboard-header h1 {
    margin: 0 0 4px 0;
    font-size: 24px;
    font-weight: 700;
    color: white !important;
}
.role-pill {
    display: inline-block;
    margin-top: 8px;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 600;
    background: rgba(255,255,255,0.2);
    border: 1px solid rgba(255,255,255,0.35);
}
.dash-nav {
    display: block !important;
    visibility: visible !important;
    text-align: center;
    margin: 0 0 14px 0;
    background: white;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 8px 28px 8px 10px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
    position: relative;
}
.dash-nav-caret {
    position: absolute;
    top: 4px;
    right: 6px;
    z-index: 2;
    width: 22px;
    height: 22px;
    padding: 0;
    margin: 0;
    border: none;
    border-radius: 4px;
    background: transparent;
    color: #64748b !important;
    cursor: pointer;
    line-height: 22px;
    font-size: 16px;
    text-align: center;
}
.dash-nav-caret:hover {
    color: #19283B !important;
    background: #f1f5f9;
}
.dash-nav.is-collapsed {
    padding: 2px 8px !important;
    min-height: 26px;
    margin-bottom: 8px;
    border-color: #b5cfd9 !important;
    box-shadow: 0 0 0 1px rgba(147, 197, 253, 0.45);
}
.dash-nav.is-collapsed .dash-nav-body {
    display: none !important;
}
.dash-nav.is-collapsed .dash-nav-caret {
    position: static;
    display: inline-block;
    vertical-align: middle;
    color: #6699ea !important;
}
.dash-nav-segment {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: 4px 6px;
    margin: 0 0 4px 0;
}
.dash-nav-segment:last-child {
    margin-bottom: 0;
}
.dash-nav-label {
    display: inline-block;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.4px;
    text-transform: uppercase;
    color: #64748b !important;
    margin: 0;
    white-space: nowrap;
}
.dash-tabs {
    display: inline !important;
    visibility: visible !important;
    margin: 0;
}
.dash-tab {
    display: inline-block !important;
    visibility: visible !important;
    border: 1px solid #e2e8f0;
    background: white;
    color: #475569 !important;
    padding: 4px 10px;
    border-radius: 6px;
    font-weight: 600;
    font-size: 12px;
    line-height: 1.25;
    text-decoration: none !important;
    margin: 1px 2px;
}
.dash-tab:hover {
    border-color: #6699ea;
    color: #19283B !important;
}
.dash-tab.active {
    border-color: #19283B;
    background: #19283B;
    color: white !important;
}
/* Segment highlights: Master Lists / VBS Ops / Admin */
.dash-nav-segment.seg-master .dash-tab:hover {
    border-color: #6699ea;
    color: #19283B !important;
}
.dash-nav-segment.seg-master .dash-tab.active {
    border-color: #6699ea;
    background: #6699ea;
    color: white !important;
}
.dash-nav-segment.seg-ops .dash-tab:hover {
    border-color: #87d091;
    color: #19283B !important;
}
.dash-nav-segment.seg-ops .dash-tab.active {
    border-color: #87d091;
    background: #87d091;
    color: #19283B !important;
}
.dash-nav-segment.seg-admin .dash-tab:hover {
    border-color: #d2836a;
    color: #19283B !important;
}
.dash-nav-segment.seg-admin .dash-tab.active {
    border-color: #d2836a;
    background: #d2836a;
    color: white !important;
}
.dash-nav-segment.seg-master .dash-nav-label { color: #6699ea !important; }
.dash-nav-segment.seg-ops .dash-nav-label { color: #3d8f4a !important; }
.dash-nav-segment.seg-admin .dash-nav-label { color: #d2836a !important; }
.dash-tab.dash-tab-allergy {
    border-color: #d2836a;
    color: #19283B !important;
}
.dash-tab.dash-tab-allergy:hover {
    border-color: #d2836a;
    color: #19283B !important;
    background: #f8ebe6;
}
.dash-tab.dash-tab-allergy.active {
    border-color: #d2836a;
    background: #d2836a;
    color: white !important;
}
/* All Allergies uses tertiary tangerine (not Master Lists blue) */
.dash-nav-segment.seg-master .dash-tab.dash-tab-allergy.active {
    border-color: #d2836a;
    background: #d2836a;
    color: white !important;
}
.vbs-card {
    display: block !important;
    visibility: visible !important;
    background: white !important;
    padding: 25px;
    border-radius: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    margin-bottom: 20px;
    color: #1e293b !important;
    font-style: normal !important;
    border-bottom: none !important;
    font-size: 14px !important;
}
.vbs-card-title {
    font-size: 20px;
    font-weight: 600;
    margin: 0 0 16px 0;
    color: #1e293b !important;
    font-style: normal !important;
}
.vbs-group-heading {
    font-size: 28px;
    font-weight: 700;
    margin: 0 0 16px 0;
    color: #19283B !important;
    font-style: normal !important;
    line-height: 1.2;
}
.stats-grid {
    display: flex !important;
    flex-wrap: wrap;
    justify-content: center;
    align-items: stretch;
    gap: 12px;
    margin-bottom: 20px;
    text-align: center;
}
.stats-grid .stat-card {
    display: flex !important;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    vertical-align: top;
    width: 148px;
    min-height: 128px;
    margin: 0;
    padding: 14px 12px;
    box-sizing: border-box;
}
.stats-grid.compact { margin-bottom: 16px; }
.stats-grid .stat-label {
    line-height: 1.25;
}
.stats-grid .stat-sub {
    margin-top: 6px;
}
.stat-card {
    background: white !important;
    padding: 18px 16px;
    border-radius: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    text-align: center;
    border: 1px solid #e2e8f0;
    color: #1e293b !important;
}
.stat-card.stat-card-total {
    background: #b5cfd9 !important;
    border-color: #7dd3fc;
    box-shadow: 0 2px 8px rgba(14, 165, 233, 0.18);
}
.stat-card.stat-card-total .stat-value {
    color: #6699ea !important;
}
.stat-card.stat-card-total .stat-label {
    color: #0c4a6e !important;
    font-weight: 700;
}
a.stat-card-link {
    text-decoration: none !important;
    color: inherit !important;
    cursor: pointer;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
a.stat-card-link:hover {
    border-color: #6699ea !important;
    box-shadow: 0 4px 12px rgba(1, 156, 255, 0.18);
}
.stat-sub {
    margin-top: 6px;
    font-size: 11px;
    line-height: 1.25;
    color: #64748b !important;
    text-transform: none;
    letter-spacing: 0;
    word-break: break-word;
}
/* Group Blocks / Allergy by Group: keep count strip compact */
.vbs-block-stats {
    display: flex !important;
    flex-wrap: wrap;
    justify-content: center;
    gap: 8px;
    margin-bottom: 12px !important;
}
.vbs-block-stats .stat-card {
    display: block !important;
    flex: 1 1 100px;
    width: auto !important;
    min-width: 0;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 8px 10px !important;
    border-radius: 8px !important;
    box-sizing: border-box;
}
.vbs-block-stats .stat-value {
    font-size: 22px !important;
    margin: 0 0 2px 0 !important;
    line-height: 1.15;
}
.vbs-block-stats .stat-label {
    font-size: 10px !important;
    letter-spacing: 0.3px;
    line-height: 1.2;
}
.stat-value {
    font-size: 28px;
    font-weight: bold;
    color: #19283B !important;
    margin: 6px 0;
}
.stat-label {
    color: #64748b !important;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.people-table {
    width: 100%;
    border-collapse: collapse;
    display: table !important;
    visibility: visible !important;
    color: #1e293b !important;
    background: white !important;
}
.people-table th, .people-table td {
    text-align: left;
    padding: 10px 12px;
    border-bottom: 1px solid #e2e8f0;
    vertical-align: top;
    color: #1e293b !important;
}
.people-table th {
    color: #64748b !important;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.4px;
}
.people-table a {
    color: #19283B !important;
    font-weight: 600;
    text-decoration: none;
}
.people-table a:hover { text-decoration: underline; color: #6699ea !important; }
.counts-day-toggles {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
}
.counts-day-toggles .btn-col-toggle {
    display: inline-block;
}
.counts-drill-link {
    color: #19283B !important;
    font-weight: 700;
    text-decoration: none !important;
    border-bottom: 1px dashed #b5cfd9;
}
.counts-drill-link:hover {
    color: #6699ea !important;
    border-bottom-color: #6699ea;
}
.counts-drill-link.active {
    color: #6699ea !important;
    border-bottom-style: solid;
}
.counts-row-active {
    background: #eef6ff !important;
}
.counts-drill-panel {
    border: 2px solid #b5cfd9 !important;
    margin-bottom: 16px !important;
}
.counts-drill-panel .btn-tag-add {
    margin: 0;
}
.people-table th.vbs-sort {
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
}
.people-table th.vbs-sort:hover {
    color: #19283B !important;
    background: #f1f5f9;
}
.people-table th.vbs-sort-asc {
    color: #19283B !important;
    box-shadow: inset 0 -3px 0 #6699ea;
}
.people-table th.vbs-sort-desc {
    color: #19283B !important;
    box-shadow: inset 0 3px 0 #6699ea;
}
.subgroup-list { list-style: none; padding: 0; margin: 0 0 16px 0; }
.subgroup-item {
    display: block !important;
    padding: 12px 15px;
    background: #f8fafc !important;
    margin-bottom: 8px;
    border-radius: 6px;
    border-left: 3px solid #6699ea;
    color: #1e293b !important;
}
.subgroup-name { font-weight: 600; color: #1e293b !important; margin-right: 12px; }
.empty-state {
    background: #f8fafc !important;
    border: 1px dashed #cbd5e1;
    color: #64748b !important;
    padding: 18px;
    border-radius: 8px;
    text-align: center;
}
.info-banner {
    background: #eef6ff !important;
    border-left: 4px solid #6699ea;
    color: #19283B !important;
    padding: 12px 14px;
    border-radius: 8px;
    margin-bottom: 16px;
    display: block !important;
}
.info-banner.danger {
    background: #fef2f2 !important;
    border-left-color: #dc2626;
    color: #991b1b !important;
}
.meta-line {
    color: #64748b !important;
    font-size: 14px;
    margin: 0 0 12px 0;
}
.assign-grid {
    display: block !important;
}
.assign-grid .vbs-card {
    display: inline-block;
    vertical-align: top;
    width: 46%;
    min-width: 280px;
    margin-right: 2%;
}
.field { margin-bottom: 14px; }
.field label {
    display: block;
    font-weight: 600;
    color: #475569 !important;
    margin-bottom: 6px;
    font-size: 13px;
}
.field select, .field input {
    width: 100%;
    padding: 12px 14px;
    font-size: 15px;
    border: 2px solid #e2e8f0;
    border-radius: 8px;
    box-sizing: border-box;
    background: white;
    color: #1e293b !important;
}
.field select:focus, .field input:focus {
    outline: none;
    border-color: #6699ea;
}
#leader-also-checks {
    text-align: left;
}
.also-check {
    display: flex !important;
    justify-content: flex-start !important;
    align-items: center !important;
    gap: 8px;
    width: auto !important;
    max-width: 100%;
    margin: 0 0 8px 0 !important;
    font-weight: 500 !important;
    cursor: pointer;
    color: #1e293b !important;
}
.field input.leader-also-cb,
.also-check input[type="checkbox"] {
    width: auto !important;
    min-width: 18px;
    max-width: 18px;
    height: 18px;
    margin: 0 !important;
    padding: 0 !important;
    flex: 0 0 auto;
    border: none;
    border-radius: 0;
    background: transparent;
}
.also-check span {
    flex: 0 0 auto;
    text-align: left;
}
.btn-primary {
    background: #19283B;
    color: #fff !important;
    border: none;
    border-radius: 8px;
    padding: 12px 20px;
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
}
.btn-primary:hover { opacity: 0.92; }
.btn-secondary {
    background: white;
    color: #19283B !important;
    border: 2px solid #e2e8f0;
    border-radius: 8px;
    padding: 10px 18px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
}
.btn-secondary:hover {
    border-color: #6699ea;
    color: #6699ea !important;
}
.list-actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 12px;
}
.btn-tag-add {
    background: #19283B;
    color: #fff !important;
    border: none;
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 600;
    cursor: pointer;
    white-space: nowrap;
}
.btn-tag-add:hover { background: #6699ea; color: #fff !important; }
.tag-modal-overlay {
    display: none;
    position: fixed;
    inset: 0;
    z-index: 10050;
    background: rgba(15, 23, 42, 0.45);
    align-items: center;
    justify-content: center;
    padding: 20px;
}
.tag-modal-overlay.visible { display: flex; }
.tag-modal {
    background: #fff;
    border-radius: 14px;
    width: 100%;
    max-width: 440px;
    box-shadow: 0 20px 50px rgba(0, 0, 0, 0.25);
    overflow: hidden;
}
.tag-modal-header {
    padding: 16px 20px;
    background: #19283B;
    color: #fff;
    font-size: 18px;
    font-weight: 600;
}
.tag-modal-body { padding: 20px; }
.tag-modal-body label {
    display: block;
    font-weight: 600;
    color: #334155;
    margin-bottom: 6px;
    font-size: 13px;
}
.tag-modal-body input[type="text"] {
    width: 100%;
    padding: 10px 12px;
    border: 2px solid #e2e8f0;
    border-radius: 8px;
    font-size: 15px;
    box-sizing: border-box;
    margin-bottom: 16px;
}
.tag-modal-body input[type="text"]:focus {
    outline: none;
    border-color: #6699ea;
}
.tag-modal-meta {
    font-size: 13px;
    color: #64748b;
    margin: 0 0 14px 0;
}
.tag-modal-options {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin-bottom: 8px;
}
.tag-modal-options label.option-row {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    font-weight: 500;
    cursor: pointer;
    margin: 0;
}
.tag-modal-options input { margin-top: 3px; }
.tag-modal-footer {
    padding: 14px 20px 20px;
    display: flex;
    justify-content: flex-end;
    gap: 8px;
}
.btn-tag-confirm {
    background: #19283B;
    color: #fff !important;
    border: none;
    border-radius: 8px;
    padding: 10px 16px;
    font-weight: 600;
    cursor: pointer;
}
.btn-tag-confirm:hover { background: #6699ea; }
.vbs-leader-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: stretch;
}
.vbs-leader-grid .vbs-leader-card {
    flex: 1 1 calc(33.333% - 10px);
    max-width: calc(33.333% - 10px);
    min-width: 220px;
    margin: 0 !important;
    box-sizing: border-box;
}
.vbs-leader-grid .subgroup-item {
    padding: 6px 8px;
    margin-bottom: 4px;
    font-size: 13px;
}
.vbs-leader-grid .subgroup-name {
    display: inline-block;
    min-width: 4.5em;
}
.vbs-print-only { display: none !important; }
.vbs-print-sheet-title { display: none !important; }
.vbs-print-header { display: none !important; }
.vbs-print-footer { display: none !important; }
.btn-print {
    background: #eeeeee !important;
    color: #19283B !important;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    padding: 10px 18px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    margin-bottom: 12px;
    box-shadow: none;
    text-decoration: none !important;
}
.btn-print:hover {
    background: #e5e5e5 !important;
    border-color: #9ca3af;
    color: #19283B !important;
}
.btn-print:active {
    background: #d4d4d4 !important;
}
hr.soft {
    border: none;
    border-top: 1px solid #e2e8f0;
    margin: 18px 0;
}
.vbs-group-block { page-break-inside: avoid; }
.toolbar {
    display: block !important;
    margin-bottom: 12px;
}
.toolbar h2 {
    margin: 0;
    font-size: 20px;
    color: #1e293b !important;
}
.vbs-main {
    display: block !important;
    visibility: visible !important;
    color: #1e293b !important;
}
.cover-card { padding: 28px 30px; }
.cover-metrics {
    margin: 0 0 22px 0;
}
.cover-metrics .stats-grid {
    margin-bottom: 0;
}
.cover-metrics .stat-card {
    min-height: 140px;
    box-sizing: border-box;
}
.cover-metrics .stat-label {
    font-weight: 700 !important;
    color: #334155 !important;
}
/* Home tiles: outline only */
.cover-metrics .cover-tile {
    background: #fff !important;
    box-shadow: none !important;
    border-style: solid;
    border-width: 2px;
}
.cover-metrics .cover-tile-primary {
    border-color: #19283B !important;
}
.cover-metrics .cover-tile-secondary {
    border-color: #6699ea !important;
}
.cover-metrics .cover-tile-green {
    border-color: #87d091 !important;
}
.cover-metrics a.cover-tile-secondary:hover {
    box-shadow: 0 0 0 1px #6699ea !important;
}
.cover-metrics a.cover-tile-green:hover {
    box-shadow: 0 0 0 1px #87d091 !important;
}
.cover-metrics a.cover-tile-primary:hover {
    box-shadow: 0 0 0 1px #19283B !important;
}
.cover-attendance {
    margin: 0 0 24px 0;
    padding: 16px 14px 18px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
}
.cover-attendance-head {
    text-align: center;
    margin: 0 0 14px 0;
}
.cover-attendance-title {
    margin: 0 0 4px 0 !important;
    font-size: 18px;
    font-weight: 700;
    color: #19283B !important;
}
.cover-attendance-range {
    margin: 0 !important;
    font-size: 12px;
}
.att-day-grid {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 10px;
    margin: 0 0 18px 0;
}
.att-day-tile {
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 12px 10px 14px;
    text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.att-day-name {
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.02em;
    color: #64748b !important;
    text-transform: uppercase;
    margin-bottom: 4px;
}
.att-day-total-label {
    font-size: 11px;
    font-weight: 600;
    color: #475569 !important;
    margin: 0 0 2px 0;
}
.att-day-total {
    font-size: 36px;
    font-weight: 800;
    line-height: 1.05;
    color: #19283B !important;
    margin: 0 0 10px 0;
}
.att-day-breakdown {
    list-style: none;
    margin: 0;
    padding: 0;
    text-align: left;
    font-size: 12px;
    color: #334155 !important;
    line-height: 1.55;
}
.att-day-breakdown li {
    display: flex;
    align-items: center;
    gap: 6px;
}
.att-day-breakdown strong {
    margin-left: auto;
    font-weight: 700;
    color: #0f172a !important;
}
.att-swatch {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 2px;
    flex: 0 0 auto;
}
.att-chart-wrap {
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 12px 10px 8px;
}
.att-chart-block {
    margin-top: 4px;
}
.att-chart-block .att-chart-wrap {
    border: none;
    border-radius: 0;
    padding: 4px 0 0 0;
    background: transparent;
}
.att-chart-legend {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 12px 18px;
    margin: 0 0 8px 0;
    font-size: 12px;
    color: #334155 !important;
}
.att-legend-item {
    display: inline-flex;
    align-items: center;
    gap: 6px;
}
.att-chart {
    display: block;
    width: 100%;
    max-width: 720px;
    height: auto;
    margin: 0 auto;
}
.att-grid {
    stroke: #e2e8f0;
    stroke-width: 1;
}
.att-y-label,
.att-x-label {
    fill: #64748b;
    font-size: 11px;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}
.att-bar-total {
    fill: #19283B;
    font-size: 11px;
    font-weight: 700;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}
@media (max-width: 900px) {
    .att-day-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}
@media (max-width: 520px) {
    .att-day-grid {
        grid-template-columns: 1fr;
    }
    .att-day-total { font-size: 30px; }
}
.cover-offerings {
    margin: 0 0 24px 0;
    padding: 16px 14px 18px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
}
.cover-offerings-head {
    text-align: center;
    margin: 0 0 12px 0;
}
.cover-offerings-title {
    margin: 0 0 4px 0 !important;
    font-size: 18px;
    font-weight: 700;
    color: #19283B !important;
}
.cover-offerings-range {
    margin: 0 !important;
    font-size: 12px;
}
.offering-week-total {
    text-align: center;
    margin: 0 0 14px 0;
    padding: 12px 14px;
    background: #fff;
    border: 2px solid #87d091;
    border-radius: 10px;
}
.offering-week-total-label {
    font-size: 12px;
    font-weight: 700;
    color: #64748b !important;
    text-transform: uppercase;
    letter-spacing: 0.03em;
}
.offering-week-total-value {
    font-size: 32px;
    font-weight: 800;
    color: #19283B !important;
    line-height: 1.15;
    margin-top: 2px;
}
.offering-day-grid {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 10px;
    margin: 0 0 12px 0;
}
.offering-day-tile {
    background: #fff;
    border: 2px solid #6699ea;
    border-radius: 10px;
    padding: 12px 10px 14px;
    text-align: center;
    box-sizing: border-box;
}
.offering-day-name {
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.02em;
    color: #64748b !important;
    text-transform: uppercase;
    margin-bottom: 2px;
}
.offering-day-date {
    font-size: 11px;
    color: #94a3b8 !important;
    margin-bottom: 8px;
}
.offering-day-amount {
    font-size: 20px;
    font-weight: 800;
    color: #19283B !important;
}
.offering-input-wrap {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 2px;
    margin-top: 6px;
}
.offering-dollar {
    font-size: 16px;
    font-weight: 700;
    color: #64748b !important;
}
.offering-input-wrap input {
    width: 100%;
    max-width: 96px;
    padding: 6px 8px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    font-size: 15px;
    font-weight: 700;
    text-align: right;
    color: #19283B !important;
    background: #fff;
}
.offering-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px 14px;
    margin-top: 4px;
}
.offering-actions .btn-primary {
    padding: 10px 16px;
    font-size: 14px;
}
@media (max-width: 900px) {
    .offering-day-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}
@media (max-width: 520px) {
    .offering-day-grid {
        grid-template-columns: 1fr;
    }
}
.cover-shepherding {
    margin: 0 0 24px 0;
    padding: 16px 14px 18px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
}
.cover-shepherding-head {
    text-align: center;
    margin: 0 0 14px 0;
}
.cover-shepherding-title {
    margin: 0 0 4px 0 !important;
    font-size: 18px;
    font-weight: 700;
    color: #19283B !important;
}
.shepherd-block {
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    margin: 0 0 10px 0;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    overflow: hidden;
}
.shepherd-block:last-child { margin-bottom: 0; }
.shepherd-block-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 10px 12px;
    cursor: pointer;
}
.shepherd-block-heading {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    flex: 1;
    min-width: 0;
}
.shepherd-block-name {
    font-size: 15px;
    font-weight: 700;
    color: #1e293b !important;
}
.shepherd-count {
    display: inline-block;
    min-width: 1.6em;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
    background: #b5cfd9;
    color: #6699ea !important;
    text-align: center;
}
.shepherd-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
    background: #87d091;
    color: #19283B !important;
}
.shepherd-block-caret {
    width: 28px;
    height: 28px;
    padding: 0;
    margin: 0;
    border: none;
    border-radius: 6px;
    background: transparent;
    color: #64748b !important;
    cursor: pointer;
    line-height: 28px;
    font-size: 16px;
    text-align: center;
    flex: 0 0 auto;
}
.shepherd-block-caret:hover {
    color: #19283B !important;
    background: #f1f5f9;
}
.shepherd-block-body {
    padding: 0 12px 12px 12px;
    border-top: 1px solid #f1f5f9;
}
.shepherd-block.is-collapsed .shepherd-block-body {
    display: none !important;
}
.shepherd-block.is-collapsed .shepherd-block-header {
    border-bottom: none;
}
.shepherd-block.shepherd-placeholder .shepherd-block-body .info-banner {
    background: #f8fafc;
    border-color: #e2e8f0;
    color: #475569 !important;
}
.cover-welcome {
    margin: 0;
}
.cover-lead {
    font-size: 16px;
    line-height: 1.5;
    color: #475569 !important;
    margin: 0;
    max-width: 820px;
}
.cover-legend-wrap {
    margin-top: 20px;
}
.cover-legend-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin: 0 0 8px 0;
}
.cover-legend-heading {
    margin: 0 !important;
    font-size: 18px;
    color: #1e293b !important;
    flex: 1;
}
.cover-legend-caret {
    width: 28px;
    height: 28px;
    padding: 0;
    margin: 0;
    border: none;
    border-radius: 6px;
    background: transparent;
    color: #64748b !important;
    cursor: pointer;
    line-height: 28px;
    font-size: 18px;
    text-align: center;
    flex-shrink: 0;
}
.cover-legend-caret:hover {
    color: #19283B !important;
    background: #f1f5f9;
}
.cover-legend-wrap.is-collapsed .cover-legend-body {
    display: none !important;
}
.cover-legend-wrap.is-collapsed .cover-legend-header {
    margin-bottom: 0;
    padding: 8px 10px;
    border: 1px solid #b5cfd9;
    border-radius: 8px;
    background: #f0f9ff;
    box-shadow: 0 0 0 1px rgba(147, 197, 253, 0.35);
}
.cover-legend-wrap.is-collapsed .cover-legend-caret {
    color: #6699ea !important;
}
.cover-legend {
    display: block !important;
    margin-top: 12px;
}
.cover-legend-row {
    display: block !important;
    padding: 12px 14px;
    background: #f8fafc !important;
    border-radius: 10px;
    border: 1px solid #e2e8f0;
    margin-bottom: 12px;
    color: #1e293b !important;
}
.cover-pill {
    display: inline-block !important;
    min-width: 120px;
    text-align: center;
    margin-right: 12px;
}
.cover-legend-desc {
    display: inline;
    color: #475569 !important;
    font-size: 14px;
    line-height: 1.4;
}
.cover-cta {
    margin-top: 24px;
    padding-top: 18px;
    border-top: 1px solid #e2e8f0;
}
.vbs-find-title {
    margin: 0 0 16px 0;
    font-size: 28px;
    font-weight: 700;
    color: #19283B !important;
    text-align: center;
}
.vbs-find-table th, .vbs-find-table td {
    font-size: 18px !important;
    padding: 12px 14px !important;
}
.vbs-find-table td:last-child {
    font-weight: 700;
    color: #19283B !important;
    white-space: nowrap;
}
.vbs-blocks-view:not(.show-shirt) .col-shirt {
    display: none !important;
}
.vbs-blocks-view:not(.show-allergy) .col-allergy {
    display: none !important;
}
.vbs-blocks-view.show-allergy th.col-allergy,
.vbs-blocks-view.show-allergy td.col-allergy {
    background: #fee2e2 !important;
    color: #7f1d1d !important;
}
.blocks-col-actions {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
    margin-top: 8px;
}
.blocks-group-filter {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px 10px;
    margin: 0 0 4px 0;
}
.blocks-group-filter label {
    font-size: 13px;
    font-weight: 700;
    color: #334155 !important;
    margin: 0;
}
.blocks-group-filter select {
    min-width: 180px;
    max-width: 100%;
    padding: 6px 10px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: #fff;
    color: #1e293b !important;
    font-size: 14px;
    font-weight: 600;
}
.blocks-col-toggles {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
}
.blocks-col-actions .btn-print {
    margin-bottom: 0;
}
.btn-col-toggle {
    background: white;
    color: #475569 !important;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
}
.btn-col-toggle:hover {
    border-color: #6699ea;
    color: #19283B !important;
}
.btn-col-toggle.is-on {
    border-color: #19283B;
    background: #19283B;
    color: white !important;
}
.btn-col-toggle-allergy.is-on {
    border-color: #991b1b;
    background: #dc2626;
    color: white !important;
}
.table-scroll {
    width: 100%;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
}
.vbs-inline-form .vbs-form-hint {
    display: inline;
    margin-left: 12px;
}
.vbs-inline-form .btn-primary {
    margin-bottom: 8px;
}
@media (max-width: 768px) {
    .vbs-root {
        padding: 10px !important;
        max-width: 100% !important;
    }
    .dashboard-header {
        padding: 12px 14px !important;
        border-radius: 10px !important;
        margin: 0 0 10px 0 !important;
        max-width: 100% !important;
        width: 100% !important;
    }
    .vbs-header-hero {
        margin-bottom: 6px !important;
    }
    .vbs-header-hero img {
        max-height: 79px !important;
        max-width: 264px !important;
    }
    .dashboard-header h1 {
        font-size: 20px !important;
    }
    .dash-nav {
        margin-bottom: 10px !important;
        padding: 6px 8px !important;
        text-align: center;
    }
    .dash-nav-segment {
        margin-bottom: 4px !important;
        gap: 3px 4px !important;
    }
    .dash-nav-label {
        font-size: 9px !important;
        width: 100%;
        text-align: center;
    }
    .vbs-leader-grid .vbs-leader-card {
        flex: 1 1 100% !important;
        max-width: 100% !important;
        min-width: 0 !important;
    }
    .dash-tabs {
        margin-bottom: 0 !important;
    }
    .dash-tab {
        padding: 5px 9px !important;
        font-size: 12px !important;
        margin: 1px 2px !important;
    }
    .vbs-card {
        padding: 16px !important;
        margin-bottom: 14px !important;
        border-radius: 10px !important;
    }
    .vbs-card-title {
        font-size: 18px !important;
    }
    .vbs-group-heading {
        font-size: 24px !important;
    }
    .assign-grid .vbs-card {
        display: block !important;
        width: 100% !important;
        min-width: 0 !important;
        margin-right: 0 !important;
    }
    .stats-grid {
        display: flex !important;
        flex-wrap: wrap;
        justify-content: center;
        align-items: stretch;
        gap: 8px;
        margin-bottom: 12px !important;
        text-align: center;
    }
    .stats-grid .stat-card {
        display: flex !important;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        flex: 1 1 calc(50% - 8px);
        width: auto !important;
        min-width: 0;
        min-height: 110px;
        margin: 0 !important;
        padding: 10px 8px !important;
        border-radius: 8px !important;
        box-sizing: border-box;
    }
    .stats-grid .stat-value {
        font-size: 20px !important;
        margin: 0 0 2px 0 !important;
        line-height: 1.15;
    }
    .stats-grid .stat-label {
        font-size: 10px !important;
        letter-spacing: 0.3px;
        line-height: 1.2;
    }
    .stats-grid.compact {
        margin-bottom: 10px !important;
    }
    .vbs-group-block .vbs-block-stats,
    .vbs-block-stats {
        display: flex !important;
        flex-wrap: wrap;
        justify-content: center;
        gap: 8px;
        margin-bottom: 10px !important;
    }
    .vbs-group-block .vbs-block-stats .stat-card,
    .vbs-block-stats .stat-card {
        flex: 1 1 calc(50% - 8px);
        padding: 6px 8px !important;
    }
    .vbs-group-block .vbs-block-stats .stat-value,
    .vbs-block-stats .stat-value {
        font-size: 18px !important;
    }
    .field select, .field input, .btn-primary, .btn-secondary, .btn-print, .btn-tag-add {
        font-size: 16px !important;
        min-height: 44px;
        width: 100%;
        box-sizing: border-box;
    }
    .field input.leader-also-cb,
    .also-check input[type="checkbox"] {
        width: auto !important;
        min-width: 22px !important;
        max-width: 22px !important;
        min-height: 22px !important;
        height: 22px !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    .also-check {
        justify-content: flex-start !important;
        min-height: 44px;
    }
    .btn-print, .btn-secondary, .btn-tag-add {
        display: block;
        text-align: center;
        margin: 0 0 10px 0 !important;
    }
    .list-actions {
        display: block !important;
    }
    .list-actions .meta-line,
    .list-actions .vbs-card-title,
    .list-actions .vbs-group-heading {
        margin-bottom: 10px !important;
    }
    .toolbar .btn-print,
    .toolbar a.btn-print,
    .toolbar a.btn-secondary {
        width: 100%;
    }
    .vbs-inline-form .vbs-form-hint {
        display: block;
        margin: 10px 0 0 0;
    }
    .cover-card {
        padding: 18px 14px !important;
    }
    .cover-legend-row {
        padding: 10px !important;
    }
    .cover-pill {
        display: block !important;
        width: 100%;
        margin: 0 0 8px 0 !important;
        box-sizing: border-box;
    }
    .cover-cta a {
        display: block !important;
        width: 100%;
        margin: 0 0 10px 0 !important;
        text-align: center;
        box-sizing: border-box;
    }
    .subgroup-item {
        padding: 10px 12px !important;
    }
    .subgroup-name {
        display: block;
        margin: 0 0 4px 0 !important;
    }
    .people-table th, .people-table td {
        padding: 8px 10px !important;
        font-size: 13px !important;
    }
    .vbs-find-title {
        font-size: 20px !important;
    }
    .vbs-find-table th, .vbs-find-table td {
        font-size: 15px !important;
    }
}
@media print {
    /* Default-like margins (avoid Chrome "Minimal" / zero-margin look) */
    @page {
        margin: 0.75in;
    }
    /* Hide TouchPoint chrome that can leave a blank first printed page */
    .navbar,
    .navbar-fixed-top,
    .breadcrumb,
    .page-header,
    .box-header,
    #header,
    header.main-header,
    .main-header,
    .sidebar,
    .main-sidebar,
    .control-sidebar,
    footer,
    .footer {
        display: none !important;
    }
    .vbs-screen-only,
    .vbs-root .dashboard-header,
    .vbs-root .dash-nav,
    .vbs-root .dash-tabs,
    .vbs-root .toolbar,
    .vbs-root .role-pill,
    .vbs-find-sheet > .meta-line,
    .tag-modal-overlay {
        display: none !important;
    }
    .vbs-print-only {
        display: block !important;
    }
    /* One-time in-body titles are redundant — running header repeats on every page */
    .vbs-print-sheet-title {
        display: none !important;
    }
    .vbs-print-header {
        display: block !important;
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        z-index: 9999;
        font-size: 11pt !important;
        font-weight: 700 !important;
        line-height: 1.25;
        color: #000 !important;
        border-bottom: 1px solid #999;
        padding: 0 0 8px 0;
        margin: 0;
        background: #fff !important;
        text-align: left;
        height: 22pt;
        box-sizing: border-box;
    }
    .vbs-print-footer {
        display: block !important;
        position: fixed;
        left: 0;
        right: 0;
        bottom: 0;
        z-index: 9999;
        font-size: 8pt !important;
        line-height: 1.2;
        color: #444 !important;
        border-top: 1px solid #999;
        padding: 4px 0 0 0;
        margin: 0;
        background: #fff !important;
        text-align: left;
        height: 18pt;
        box-sizing: border-box;
    }
    .vbs-root {
        padding-top: 36pt !important;
        padding-bottom: 28pt !important;
        background: #fff !important;
    }
    .vbs-find-sheet {
        box-shadow: none !important;
        padding: 0 !important;
        background: #fff !important;
        margin: 0 !important;
    }
    .vbs-find-title {
        font-size: 18pt !important;
        margin: 0 0 10px 0 !important;
        color: #000 !important;
    }
    .vbs-find-table th, .vbs-find-table td {
        font-size: 14pt !important;
        padding: 6px 10px !important;
        color: #000 !important;
    }
    .vbs-group-block {
        page-break-after: always;
        page-break-inside: avoid;
        box-shadow: none !important;
        /* Clear running print header on every page (page 2+ ignores .vbs-root padding) */
        padding-top: 36pt !important;
        padding-bottom: 12pt !important;
        margin-top: 0 !important;
        box-sizing: border-box !important;
    }
    .vbs-group-heading {
        font-size: 22pt !important;
        color: #000 !important;
        margin: 0 0 10px 0 !important;
        padding-top: 0 !important;
    }
    .vbs-tshirt-table th, .vbs-tshirt-table td {
        font-size: 12pt !important;
        padding: 6px 10px !important;
        color: #000 !important;
    }
    .vbs-group-block:last-child {
        page-break-after: auto;
    }
    /* Counts + Group Leaders: compact letter (8.5x11) layout */
    .vbs-print-letter .vbs-card {
        box-shadow: none !important;
        border: 1px solid #cbd5e1;
        page-break-inside: avoid;
        margin-bottom: 10px !important;
        padding: 10px 12px !important;
        background: #fff !important;
    }
    /* Allergies list is long — allow card/table to flow across pages (avoid blank page 1) */
    .vbs-allergy-sheet .vbs-card {
        page-break-inside: auto !important;
        break-inside: auto !important;
        border: none !important;
        padding: 0 !important;
        margin: 0 !important;
    }
    .vbs-allergy-sheet .vbs-print-sheet-title {
        page-break-after: avoid !important;
        break-after: avoid !important;
        margin: 0 0 8px 0 !important;
    }
    .vbs-allergy-sheet .people-table {
        page-break-inside: auto !important;
        break-inside: auto !important;
    }
    .vbs-allergy-sheet .people-table tr {
        page-break-inside: avoid;
        break-inside: avoid;
    }
    .vbs-allergy-sheet .table-scroll {
        overflow: visible !important;
    }
    .vbs-allergy-sheet .list-actions {
        display: none !important;
    }
    .vbs-print-letter .vbs-card-title {
        font-size: 12pt !important;
        margin: 0 0 6px 0 !important;
        color: #000 !important;
    }
    .vbs-print-letter .stats-grid {
        margin-bottom: 10px !important;
        text-align: center !important;
    }
    .vbs-print-letter .stat-card {
        box-shadow: none !important;
        border: 1px solid #cbd5e1;
        padding: 8px 10px !important;
        width: 110px !important;
        margin: 0 8px 8px 0 !important;
    }
    .vbs-print-letter .stat-card-total {
        background: #b5cfd9 !important;
        border-color: #7dd3fc !important;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
    }
    .vbs-print-letter .stat-value {
        font-size: 16pt !important;
        margin: 2px 0 !important;
        color: #000 !important;
    }
    .vbs-print-letter .stat-label {
        font-size: 8pt !important;
        color: #333 !important;
    }
    .vbs-print-letter .people-table th,
    .vbs-print-letter .people-table td {
        font-size: 9pt !important;
        padding: 3px 5px !important;
        color: #000 !important;
    }
    .vbs-print-letter .people-table th {
        font-size: 8pt !important;
    }
    .vbs-print-letter .table-scroll {
        overflow: visible !important;
    }
    .vbs-print-letter .subgroup-list {
        margin: 0 !important;
    }
    .vbs-print-letter .subgroup-item {
        padding: 4px 8px !important;
        margin-bottom: 3px !important;
        background: #f8fafc !important;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
        font-size: 10pt !important;
        color: #000 !important;
    }
    .vbs-print-letter .vbs-leader-card {
        margin-bottom: 8px !important;
    }
    /* Group Leaders: 3-column letter sheet (roomier vertical spacing) */
    .vbs-leader-sheet .vbs-print-sheet-title {
        font-size: 14pt !important;
        margin: 0 0 10px 0 !important;
    }
    .vbs-leader-sheet .vbs-leader-grid {
        display: block !important;
        column-count: 3;
        column-gap: 12px;
    }
    .vbs-leader-sheet .vbs-leader-card {
        display: block;
        width: 100% !important;
        max-width: none !important;
        break-inside: avoid;
        page-break-inside: avoid;
        -webkit-column-break-inside: avoid;
        margin: 0 0 10px 0 !important;
        padding: 8px 8px !important;
        border: 1px solid #94a3b8 !important;
        box-shadow: none !important;
    }
    .vbs-leader-sheet .vbs-leader-card .vbs-card-title {
        font-size: 10pt !important;
        margin: 0 0 5px 0 !important;
        line-height: 1.2 !important;
    }
    .vbs-leader-sheet .subgroup-list {
        margin: 0 !important;
    }
    .vbs-leader-sheet .subgroup-item {
        padding: 4px 6px !important;
        margin-bottom: 3px !important;
        font-size: 8.5pt !important;
        line-height: 1.3 !important;
        border-radius: 3px !important;
        border-left-width: 2px !important;
    }
    .vbs-leader-sheet .subgroup-name {
        min-width: 0 !important;
        margin-right: 5px !important;
        font-size: 8.5pt !important;
    }
    .vbs-leader-sheet .subgroup-item a {
        color: #000 !important;
        font-weight: 600 !important;
        text-decoration: none !important;
    }
    .vbs-print-letter .meta-line {
        font-size: 9pt !important;
        color: #000 !important;
    }
    .vbs-blocks-view:not(.show-shirt) .col-shirt {
        display: none !important;
    }
    .vbs-blocks-view:not(.show-allergy) .col-allergy {
        display: none !important;
    }
    .vbs-blocks-view.show-allergy th.col-allergy,
    .vbs-blocks-view.show-allergy td.col-allergy {
        background: #fee2e2 !important;
        color: #7f1d1d !important;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
    }
}
'''


def _view_body(view, pools, group_names, can_assign, can_admin=False):
    if view == 'home':
        return _cover_page(can_assign, pools, group_names, can_admin=can_admin)

    if view == 'assign':
        if can_assign:
            return _assign_panel(pools, group_names)
        return '<div class="info-banner">View only. Requires Admin or VBSAdmin to assign.</div>'

    if view == 'settings':
        if can_admin:
            return _settings_panel()
        return '<div class="info-banner danger">Settings require the Admin role.</div>'

    if view == 'leaders':
        return '<div class="vbs-card">' + _roster_table(
            pools['leaders']['people'],
            include_role=True,
            include_service=True,
            include_grade=False,
            include_age_band=True,
            blank_group_unless_sgl=True,
            tag_suggest='VBS ' + VBS_YEAR + ' Volunteers',
        ) + '</div>'

    if view == 'participants':
        html = '<div class="vbs-card">'
        html += '<div class="toolbar">'
        html += '<p class="meta-line" style="margin:0">Member member-type only. Use landscape <strong>11x17</strong> in the print dialog.</p>'
        html += '<div>'
        html += '<button type="button" class="btn-print" onclick="window.print()">Print full roster 11x17</button> '
        html += '<a class="btn-print" href="' + _script_path() + '?view=findgroup" style="display:inline-block;text-decoration:none;margin-left:8px">Print &quot;Find Your Group&quot; 11x17</a>'
        html += '</div></div>'
        html += _roster_table(
            pools['k5']['people'],
            tag_suggest='VBS ' + VBS_YEAR + ' K-5',
        )
        html += '</div>'
        return html

    if view == 'findgroup':
        html = '<div class="vbs-card vbs-find-sheet">'
        html += '<div class="toolbar">'
        html += '<p class="meta-line" style="margin:0">Name + Group only. Print landscape <strong>11x17</strong>. Sorted by last name. '
        html += 'In the print dialog use <strong>Default</strong> margins (not Minimal).</p>'
        html += '<div>'
        html += '<a class="btn-secondary" href="' + _script_path() + '?view=participants" style="display:inline-block;text-decoration:none;margin-right:8px">Back to K-5 roster</a>'
        html += '<button type="button" class="btn-print" onclick="window.print()">Print &quot;Find Your Group&quot; 11x17</button>'
        html += '</div></div>'
        html += '<h2 class="vbs-find-title">Find Your Group — K-5</h2>'
        html += _find_group_table(pools['k5']['people'])
        html += '</div>'
        return html

    if view == 'prek':
        return '<div class="vbs-card">' + _roster_table(
            pools['prek']['people'],
            include_group=False,
            include_grade=False,
            tag_suggest='VBS ' + VBS_YEAR + ' Pre-K',
        ) + '</div>'

    if view == 'nursery':
        return '<div class="vbs-card">' + _roster_table(
            pools['nursery']['people'],
            include_group=False,
            include_grade=False,
            tag_suggest='VBS ' + VBS_YEAR + ' Nursery',
        ) + '</div>'

    if view == 'counts':
        rows = _count_rows(pools, group_names)
        total_groups = len(rows)
        total_students = 0
        total_people = 0
        for r in rows:
            total_students += r['students']
            total_people += r['total']
        prek_line = _pool_count_line(pools['prek']['people'])
        nur_line = _pool_count_line(pools['nursery']['people'])
        prek_students = prek_line['total']
        nur_students = nur_line['total']
        prek_leaders = _count_service_area(pools['leaders']['people'], SERVICE_PREK)
        nur_leaders = _count_service_area(pools['leaders']['people'], SERVICE_NURSERY)
        prek_nur_kids = prek_students + nur_students
        prek_nur_total = prek_nur_kids + prek_leaders + nur_leaders
        try:
            total_enrolled = (
                len(pools['leaders']['people'])
                + len(pools['k5']['people'])
                + len(pools['prek']['people'])
                + len(pools['nursery']['people'])
            )
        except:
            total_enrolled = 0
        drill = _form_val('drill', '')
        day_mode = _counts_day_mode()
        meet_day = _counts_day_ymd(day_mode)
        html = '<div class="vbs-print-letter">'
        html += '<div class="vbs-screen-only toolbar" style="margin-bottom:12px">'
        html += '<p class="meta-line" style="margin:0">Use portrait <strong>8.5×11</strong> (Letter). Click an Area or Group name to drill down. '
        html += 'Pre-K/Nursery and Groups use <strong>Enrolled</strong> or a weekday for Meeting attendance.</p>'
        html += '<div><button type="button" class="btn-print" onclick="window.print()">Print 8.5x11</button></div>'
        html += '</div>'
        html += '<h2 class="vbs-print-sheet-title">' + _html(APP_TITLE) + ' — Counts</h2>'
        if drill:
            html += _counts_drill_panel(pools, drill)
        html += '<div class="stats-grid">'
        html += '<div class="stat-card"><div class="stat-value">' + str(total_groups) + '</div><div class="stat-label">Groups</div></div>'
        html += '<div class="stat-card"><div class="stat-value">' + str(total_students) + '</div><div class="stat-label">K-5 placed</div></div>'
        html += '<div class="stat-card"><div class="stat-value">' + str(total_people) + '</div><div class="stat-label">Leaders + K-5</div></div>'
        html += '<div class="stat-card"><div class="stat-value">' + str(prek_nur_kids) + '</div><div class="stat-label">Pre-K + Nursery kids</div></div>'
        html += '<div class="stat-card"><div class="stat-value">' + str(prek_nur_total) + '</div><div class="stat-label">Leaders + Pre-K/Nursery</div></div>'
        html += '<div class="stat-card stat-card-total"><div class="stat-value">' + str(total_enrolled) + '</div><div class="stat-label">Total Enrolled</div></div>'
        html += '</div>'

        # Volunteers first
        html += '<div class="vbs-card">'
        html += '<div class="vbs-card-title">Volunteer Counts</div>'
        html += '<p class="meta-line vbs-screen-only">Primary service-area headcounts. Skits / Choreography count unique people with that area as primary <em>or</em> Also serves. Click an area to list people.</p>'
        html += '<div class="table-scroll"><table class="people-table"><thead><tr>'
        html += '<th>Area</th><th>Total</th>'
        html += '</tr></thead><tbody>'
        for area_name, area_label in SERVICE_COUNT_ROWS:
            if area_name in SECONDARY_AREAS:
                n_vol = _count_area_involved(pools['leaders']['people'], area_name)
            else:
                n_vol = _count_service_area(pools['leaders']['people'], area_name)
            dkey = 'area:' + area_name
            row_cls = 'counts-row-active' if drill == dkey else ''
            html += '<tr class="' + row_cls + '"><td><strong>' + _counts_drill_link(area_label, dkey, drill, day_mode) + '</strong></td>'
            html += '<td>' + str(n_vol) + '</td></tr>'
        html += '</tbody></table></div></div>'

        # Shared day toggles for Pre-K/Nursery + Groups
        html += '<div class="vbs-card vbs-screen-only" style="padding:14px 16px">'
        html += '<div class="vbs-card-title" style="margin-bottom:8px">Attendance view</div>'
        html += _counts_day_toggles(day_mode, meet_day)
        html += '</div>'

        # Pre-K / Nursery
        html += '<div class="vbs-card">'
        html += '<div class="vbs-card-title">Pre-K &amp; Nursery</div>'
        if day_mode == 'enrolled':
            html += '<p class="meta-line vbs-screen-only">Students from the Pre-K / Nursery pools. Leaders are volunteers with that service area. Click an area to list people.</p>'
            html += '<div class="table-scroll"><table class="people-table"><thead><tr>'
            html += '<th>Area</th><th>Students</th><th>Leaders</th><th>Total</th>'
            html += '</tr></thead><tbody>'
            prek_cls = ' counts-row-active' if drill == 'prek' else ''
            nur_cls = ' counts-row-active' if drill == 'nursery' else ''
            html += '<tr class="' + prek_cls.strip() + '"><td><strong>' + _counts_drill_link('Pre-K', 'prek', drill, day_mode) + '</strong></td>'
            html += '<td>' + str(prek_students) + '</td>'
            html += '<td>' + str(prek_leaders) + '</td>'
            html += '<td>' + str(prek_students + prek_leaders) + '</td></tr>'
            html += '<tr class="' + nur_cls.strip() + '"><td><strong>' + _counts_drill_link('Nursery', 'nursery', drill, day_mode) + '</strong></td>'
            html += '<td>' + str(nur_students) + '</td>'
            html += '<td>' + str(nur_leaders) + '</td>'
            html += '<td>' + str(nur_students + nur_leaders) + '</td></tr>'
            html += '</tbody></table></div>'
        else:
            prek_ids = _attend_present_ids(ORG_PREK, meet_day)
            nur_ids = _attend_present_ids(ORG_NURSERY, meet_day)
            lead_ids = _attend_present_ids(ORG_LEADERS, meet_day)
            prek_stu_p = len(prek_ids)
            nur_stu_p = len(nur_ids)
            prek_lead_p = _count_people_present(
                _people_with_service(pools['leaders']['people'], SERVICE_PREK), lead_ids)
            nur_lead_p = _count_people_present(
                _people_with_service(pools['leaders']['people'], SERVICE_NURSERY), lead_ids)
            html += '<p class="meta-line vbs-screen-only">Present = marked attending on that involvement’s Meeting for <strong>' + _html(meet_day or '—') + '</strong>. '
            html += 'Leaders = Volunteers involvement attendance that day with that service area.</p>'
            html += '<div class="table-scroll"><table class="people-table"><thead><tr>'
            html += '<th>Area</th><th>Students present</th><th>Leaders present</th><th>Total</th>'
            html += '</tr></thead><tbody>'
            html += '<tr><td><strong>Pre-K</strong></td><td>' + str(prek_stu_p) + '</td><td>' + str(prek_lead_p) + '</td><td>' + str(prek_stu_p + prek_lead_p) + '</td></tr>'
            html += '<tr><td><strong>Nursery</strong></td><td>' + str(nur_stu_p) + '</td><td>' + str(nur_lead_p) + '</td><td>' + str(nur_stu_p + nur_lead_p) + '</td></tr>'
            html += '</tbody></table></div>'
        html += '</div>'

        # Groups
        html += '<div class="vbs-card">'
        html += '<div class="vbs-card-title">Groups (Small Group Leaders + K-5)</div>'
        if day_mode == 'enrolled':
            html += '<p class="meta-line vbs-screen-only">Click a Group name to list its leaders and students. Click a column header to sort.</p>'
            html += '<div class="table-scroll"><table class="people-table vbs-sortable"><thead><tr>'
            html += _sort_th('Group', 'group')
            html += _sort_th('Students', 'num')
            html += _sort_th('Leaders', 'num')
            html += _sort_th('Total', 'num')
            html += _sort_th('Grade', 'text')
            html += '</tr></thead><tbody>'
            for r in rows:
                dkey = 'group:' + _s(r['group'])
                row_cls = 'counts-row-active' if drill == dkey else ''
                html += '<tr class="' + row_cls + '"><td><strong>' + _counts_drill_link(r['group'], dkey, drill, day_mode) + '</strong></td>'
                html += '<td>' + str(r['students']) + '</td>'
                html += '<td>' + str(r['leaders']) + '</td>'
                html += '<td>' + str(r['total']) + '</td>'
                html += '<td>' + _html(r.get('grades', '')) + '</td></tr>'
            if not rows:
                html += '<tr><td colspan="5"><div class="empty-state">No groups</div></td></tr>'
            html += '</tbody></table></div>'
            ua_lead = 0
            ua_k5 = 0
            for p in pools['leaders']['people']:
                if not p.get('service_area'):
                    ua_lead += 1
            for p in pools['k5']['people']:
                if not p['group_raw']:
                    ua_k5 += 1
            html += '<p class="meta-line" style="margin-top:16px"><strong>Unassigned:</strong> '
            html += _counts_drill_link('Volunteers (no service area): ' + str(ua_lead), 'ua:vol', drill, day_mode)
            html += ' | '
            html += _counts_drill_link('K-5: ' + str(ua_k5), 'ua:k5', drill, day_mode)
            html += '</p>'
        else:
            html += '<p class="meta-line vbs-screen-only">Students present = K-5 Meeting attendance that day for people currently tagged with that Group N. '
            html += 'Leaders present = Volunteers Meeting attendance that day for Small Group Leaders tagged with that Group.</p>'
            html += '<div class="table-scroll"><table class="people-table vbs-sortable"><thead><tr>'
            html += _sort_th('Group', 'group')
            html += _sort_th('Students present', 'num')
            html += _sort_th('Leaders present', 'num')
            html += _sort_th('Total', 'num')
            html += '</tr></thead><tbody>'
            for r in rows:
                gname = _s(r['group'])
                stu_p = _attend_present_in_group_count(ORG_K5, gname, meet_day)
                lead_p = _attend_present_in_group_count(ORG_LEADERS, gname, meet_day)
                html += '<tr><td><strong>' + _html(gname) + '</strong></td>'
                html += '<td>' + str(stu_p) + '</td>'
                html += '<td>' + str(lead_p) + '</td>'
                html += '<td>' + str(stu_p + lead_p) + '</td></tr>'
            if not rows:
                html += '<tr><td colspan="4"><div class="empty-state">No groups</div></td></tr>'
            html += '</tbody></table></div>'
        html += '</div></div>'
        return html

    if view == 'byleader':
        selected = _blocks_selected_group(group_names)
        bundles = _filter_group_bundles(
            _build_group_bundles(pools, group_names, allergy_only=False),
            selected,
        )
        html = '<div class="vbs-print-letter vbs-leader-sheet">'
        html += '<div class="vbs-screen-only toolbar" style="margin-bottom:12px">'
        html += '<form method="get" action="' + _script_path() + '" class="blocks-group-filter">'
        html += '<input type="hidden" name="view" value="byleader" />'
        html += '<label for="leaders-group-select">Group</label>'
        html += '<select id="leaders-group-select" name="group" onchange="this.form.submit()">'
        html += '<option value="all"' + (' selected' if selected == 'all' else '') + '>All groups</option>'
        for g in group_names:
            sel = ' selected' if selected == g else ''
            html += '<option value="' + _html(g) + '"' + sel + '>' + _html(g) + '</option>'
        html += '</select></form>'
        html += '<p class="meta-line" style="margin:8px 0 0 0">Use portrait <strong>8.5×11</strong> (Letter). Print layout is 3 columns to fit one page'
        if selected != 'all':
            html += ' · showing <strong>' + _html(selected) + '</strong>'
        html += '.</p>'
        html += '<div><button type="button" class="btn-print" onclick="window.print()">Print 8.5x11</button></div>'
        html += '</div>'
        html += '<h2 class="vbs-print-sheet-title">' + _html(APP_TITLE) + ' — Group Leaders</h2>'
        html += '<div class="vbs-leader-grid">'
        for b in bundles:
            team = []
            for key in ('leaders', 'coleaders', 'assistants'):
                for p in b.get(key) or []:
                    team.append(p)
            html += '<div class="vbs-card vbs-leader-card">'
            html += '<div class="list-actions vbs-screen-only" style="margin-bottom:8px">'
            html += '<div class="vbs-card-title" style="margin:0">' + _html(b['group']) + '</div>'
            html += _tag_add_button(team, 'VBS ' + VBS_YEAR + ' ' + _s(b['group']) + ' Leaders')
            html += '</div>'
            html += '<div class="vbs-card-title vbs-print-only">' + _html(b['group']) + '</div>'
            html += '<ul class="subgroup-list">'
            html += '<li class="subgroup-item"><span class="subgroup-name">Leader</span><span>' + (', '.join([_person_link_with_age_band(x) for x in b['leaders']]) or '<em>Unassigned</em>') + '</span></li>'
            if b.get('coleaders'):
                html += '<li class="subgroup-item"><span class="subgroup-name">Co-leader</span><span>' + ', '.join([_person_link_with_age_band(x) for x in b['coleaders']]) + '</span></li>'
            html += '<li class="subgroup-item"><span class="subgroup-name">Assistants</span><span>' + (', '.join([_person_link_with_age_band(x) for x in b['assistants']]) or '<em>None</em>') + '</span></li>'
            html += '</ul></div>'
        html += '</div>'
        if not bundles:
            html += '<div class="empty-state">No groups</div>'
        html += '</div>'
        return html

    if view == 'blocks':
        selected = _blocks_selected_group(group_names)
        bundles = _filter_group_bundles(
            _build_group_bundles(pools, group_names, allergy_only=False),
            selected,
        )
        html = '<div class="vbs-blocks-view" id="vbs-blocks-view">'
        html += '<div class="vbs-screen-only toolbar blocks-col-toolbar" style="margin-bottom:12px">'
        html += '<form method="get" action="' + _script_path() + '" class="blocks-group-filter">'
        html += '<input type="hidden" name="view" value="blocks" />'
        html += '<label for="blocks-group-select">Group</label>'
        html += '<select id="blocks-group-select" name="group" onchange="this.form.submit()">'
        html += '<option value="all"' + (' selected' if selected == 'all' else '') + '>All groups</option>'
        for g in group_names:
            sel = ' selected' if selected == g else ''
            html += '<option value="' + _html(g) + '"' + sel + '>' + _html(g) + '</option>'
        html += '</select></form>'
        html += '<p class="meta-line" style="margin:8px 0 0 0">Toggle extra columns, then print. Print uses one group per page'
        if selected != 'all':
            html += ' · showing <strong>' + _html(selected) + '</strong>'
        html += '.</p>'
        html += '<div class="blocks-col-actions">'
        html += '<button type="button" class="btn-print" onclick="window.print()">Print 8.5x11 (one group / page)</button>'
        html += '<div class="blocks-col-toggles">'
        html += '<button type="button" class="btn-col-toggle" data-col="shirt" aria-pressed="false">T-Shirt size</button>'
        html += '<button type="button" class="btn-col-toggle btn-col-toggle-allergy" data-col="allergy" aria-pressed="false">Allergies</button>'
        html += '</div></div></div>'
        html += _render_group_blocks(bundles)
        html += '</div>'
        return html

    if view == 'allergies':
        people = _allergy_people(pools)
        html = '<div class="vbs-print-letter vbs-allergy-sheet">'
        html += '<div class="vbs-screen-only toolbar" style="margin-bottom:12px">'
        html += '<p class="meta-line" style="margin:0">Use portrait <strong>8.5×11</strong> (Letter). '
        html += 'Unassigned group shows blank so the list stays clean.</p>'
        html += '<div><button type="button" class="btn-print" onclick="window.print()">Print 8.5x11</button></div>'
        html += '</div>'
        html += '<h2 class="vbs-print-sheet-title">VBS All Allergies Master</h2>'
        html += '<div class="vbs-card">'
        html += _list_toolbar(
            people,
            '<strong>' + str(len(people)) + '</strong> with allergies on file · click a column header to sort',
            'VBS ' + VBS_YEAR + ' Allergies',
        )
        html += '<div class="table-scroll"><table class="people-table vbs-sortable"><thead><tr>'
        html += _sort_th('Name', 'text')
        html += _sort_th('Pool', 'text')
        html += _sort_th('Group', 'group')
        html += _sort_th('Allergies', 'text')
        html += _sort_th('Emergency', 'text')
        html += '</tr></thead><tbody>'
        for p in people:
            g = _s(p.get('group'))
            if g.lower() == 'unassigned':
                g = ''
            html += '<tr>'
            html += '<td>' + _person_link(p) + '</td>'
            html += '<td>' + _html(p.get('pool', '')) + '</td>'
            html += '<td>' + _html(g) + '</td>'
            html += '<td>' + _html(p['allergy']) + '</td>'
            html += '<td>' + _html(p['emergency']) + '</td>'
            html += '</tr>'
        if not people:
            html += '<tr><td colspan="5"><div class="empty-state">No allergies on file (RecReg)</div></td></tr>'
        html += '</tbody></table></div></div></div>'
        return html

    if view == 'tshirts':
        who = _form_val('who', 'all')
        people, who, who_label = _tshirt_people(pools, who)
        tiles = _tshirt_size_tiles(people)
        base = _script_path() + '?view=tshirts'
        html = '<div class="vbs-screen-only toolbar" style="margin-bottom:12px">'
        html += '<div class="tshirt-filters">'
        for key, lab in (
            ('all', 'All'),
            ('volunteers', 'Volunteers'),
            ('participants', 'Participants'),
        ):
            cls = 'dash-tab'
            if key == who:
                cls += ' active'
            href = base + '&who=' + key
            html += '<a class="' + cls + '" href="' + href + '" style="margin:0 8px 8px 0">' + _html(lab) + '</a>'
        html += '</div>'
        html += '<button type="button" class="btn-print" onclick="window.print()">Print 8.5x11</button>'
        html += '</div>'
        html += '<div class="stats-grid compact vbs-block-stats">'
        html += '<div class="stat-card"><div class="stat-value">' + str(len(people)) + '</div><div class="stat-label">People</div></div>'
        for size, n in tiles:
            html += '<div class="stat-card"><div class="stat-value">' + str(n) + '</div><div class="stat-label">' + _html(size) + '</div></div>'
        html += '</div>'
        html += '<div class="vbs-card">'
        tag_suggest = 'VBS ' + VBS_YEAR + ' T-Shirts'
        if who == 'volunteers':
            tag_suggest = 'VBS ' + VBS_YEAR + ' Volunteer T-Shirts'
        elif who == 'participants':
            tag_suggest = 'VBS ' + VBS_YEAR + ' Participant T-Shirts'
        html += _list_toolbar(
            people,
            '<strong>' + str(len(people)) + '</strong> · ' + _html(who_label) + ' · click a column header to sort',
            tag_suggest,
        )
        html += '<div class="table-scroll"><table class="people-table vbs-sortable vbs-tshirt-table"><thead><tr>'
        html += _sort_th('Name', 'text')
        html += _sort_th('T-Shirt Size', 'text')
        html += '</tr></thead><tbody>'
        for p in people:
            size = _s(p.get('shirt_size')) or 'Unknown'
            html += '<tr>'
            html += '<td>' + _person_link(p) + '</td>'
            html += '<td>' + _html(size) + '</td>'
            html += '</tr>'
        if not people:
            html += '<tr><td colspan="2"><div class="empty-state">No people found</div></td></tr>'
        html += '</tbody></table></div></div>'
        return html

    return '<div class="info-banner danger">Unknown view: ' + _html(view) + '</div>'


def _page(view, pools, group_names, msg, can_assign, can_admin=False):
    try:
        body = _view_body(view, pools, group_names, can_assign, can_admin=can_admin)
    except Exception, ex:
        body = (
            '<div style="background:#fef2f2;border:2px solid #dc2626;color:#991b1b;padding:14px;margin:12px 0;">'
            '<strong>View error (' + _html(view) + ')</strong>'
            '<pre style="white-space:pre-wrap">' + _html(_ex_msg(ex)) + '</pre></div>'
        )

    if not body:
        body = '<div style="padding:14px;border:1px dashed #64748b;color:#000;background:#fff;">No content generated for view <strong>' + _html(view) + '</strong>.</div>'

    alert = ''
    if msg:
        alert = '<div class="info-banner">' + _html(msg) + '</div>'
    if _LOAD_WARNINGS:
        alert += '<div class="info-banner danger"><strong>Data load warning</strong><ul style="margin:8px 0 0 18px">'
        for w in _LOAD_WARNINGS:
            alert += '<li>' + _html(w) + '</li>'
        alert += '</ul></div>'

    if can_admin:
        role_label = 'Admin'
    elif can_assign:
        role_label = 'Can assign'
    else:
        role_label = 'View only'

    # Styles only in Form (same pattern as InvolvementDashboard). Do not set model.Styles.
    html = ''
    html += '<style type="text/css">' + _css() + '</style>'
    html += '<div class="vbs-root vbs-view-' + _html(view) + '">'
    html += '<div class="tag-modal-overlay" id="tag-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="tag-modal-title">'
    html += '<div class="tag-modal">'
    html += '<div class="tag-modal-header" id="tag-modal-title">Add to Tag</div>'
    html += '<div class="tag-modal-body">'
    html += '<p class="tag-modal-meta" id="tag-modal-count"></p>'
    html += '<label for="tag-name-input">Tag name</label>'
    html += '<input type="text" id="tag-name-input" maxlength="50" placeholder="e.g. VBS 2026 Group 1" autocomplete="off" />'
    html += '<div class="tag-modal-options">'
    html += '<label class="option-row"><input type="radio" name="tag-mode" value="append" checked />'
    html += '<span>Append — add these people; keep anyone already on the tag</span></label>'
    html += '<label class="option-row"><input type="radio" name="tag-mode" value="clear" />'
    html += '<span>Clear first — empty the tag, then add only this list</span></label>'
    html += '<label class="option-row"><input type="checkbox" id="tag-open-when-done" checked />'
    html += '<span>Open the tag in a new tab when done</span></label>'
    html += '</div></div>'
    html += '<div class="tag-modal-footer">'
    html += '<button type="button" class="btn-secondary" id="btn-tag-cancel">Cancel</button>'
    html += '<button type="button" class="btn-tag-confirm" id="btn-tag-confirm">Add to Tag</button>'
    html += '</div></div></div>'
    html += '<div class="dashboard-header">'
    html += _header_hero_html()
    html += '<h1>' + _html(APP_TITLE) + '</h1>'
    html += '<div class="role-pill">' + role_label + '</div>'
    html += '</div>'
    html += _nav(view, can_assign, can_admin=can_admin)
    html += alert
    html += '<div class="vbs-main">' + body + '</div>'
    # Print-only running header/footer (position:fixed → repeats on every printed page).
    print_title = _print_doc_title(view)
    html += '<div class="vbs-print-header" id="vbs-print-header">' + _html(print_title) + '</div>'
    html += '<div class="vbs-print-footer" id="vbs-print-footer" '
    html += 'data-app="" data-view="" '
    html += 'data-print-title="' + _html(print_title) + '">Printed</div>'
    html += '</div>'
    try:
        model.Script = _table_sort_script()
    except:
        pass
    return html


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    model.Title = APP_TITLE
    model.Header = APP_TITLE
    model.Styles = ''
    _clear_warnings()
    _apply_org_config(_load_settings())

    try:
        can_assign = _can_assign()
        can_admin = _can_admin()
        view = _resolve_view(can_assign, can_admin=can_admin)
        # Browser tab / Save-as PDF name matches this view's print document
        print_title = _print_doc_title(view)
        if view not in ('home', 'assign', 'settings'):
            model.Title = print_title
            model.Header = print_title
        msg = _form_val('msg', '')

        is_ajax = _s(_form_val('ajax')).lower() == 'true'
        if is_ajax:
            action = _form_val('action')
            if action == 'add_to_tag':
                try:
                    _json_out(_add_people_to_tag(
                        _form_val('people_ids'),
                        _form_val('tag_name'),
                        _form_val('clear_first'),
                    ))
                except Exception, ex:
                    _json_out({'error': _ex_msg(ex)})
            else:
                _json_out({'error': 'Unknown action'})
            return

        if model.HttpMethod == 'post':
            action = _form_val('action')
            view = _resolve_view(can_assign, can_admin=can_admin)
            message = 'Unknown action.'

            if action == 'create_group':
                ok, message = _create_group()
            elif action == 'assign_group':
                org_pid = _form_val('org_pid')
                parts = org_pid.split(':')
                if len(parts) != 2:
                    ok, message = False, 'Invalid participant selection.'
                else:
                    org_id = _i(parts[0])
                    pid = _i(parts[1])
                    if org_id == ORG_K5:
                        ok, message = _assign_group(pid, org_id, _form_val('group'))
                    else:
                        ok, message = False, 'Only K-5 participants get Group N assignments.'
            elif action == 'assign_role':
                ok, message = _assign_role(
                    _form_val('people_id'),
                    _form_val('role'),
                    _form_val('group'),
                    _form_val('service_area'),
                    _form_val('also_serves'),
                )
            elif action == 'clear_leader':
                ok, message = _clear_leader_assignment(_form_val('people_id'))
            elif action == 'save_settings':
                ok, message = _save_pool_settings()
                view = 'settings'
            elif action == 'save_offerings':
                ok, message = _save_offerings_from_form()
                view = 'home'
            elif action == 'add_to_tag':
                result = _add_people_to_tag(
                    _form_val('people_ids'),
                    _form_val('tag_name'),
                    _form_val('clear_first'),
                )
                if result.get('error'):
                    message = result['error']
                else:
                    message = str(result.get('count', 0)) + ' people added to tag "' + _s(result.get('tag_name')) + '".'
            else:
                message = 'Unknown action.'

            _redirect(message, view)
            return

        pools = _load_all_pools()
        group_names = _all_group_names()
        _show(_page(view, pools, group_names, msg, can_assign, can_admin=can_admin))
    except Exception, ex:
        err = _html(_ex_msg(ex))
        _show(
            '<div style="display:block!important;background:#fef2f2;border:2px solid #dc2626;'
            'color:#991b1b;padding:16px;margin:12px;border-radius:8px;font-family:sans-serif;">'
            '<strong>' + _html(APP_TITLE) + ' error</strong>'
            '<pre style="white-space:pre-wrap;margin-top:8px">' + err + '</pre></div>'
        )


main()
