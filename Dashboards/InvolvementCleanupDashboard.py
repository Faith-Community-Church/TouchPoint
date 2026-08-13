#Roles=Admin
# Script: InvolvementCleanup.py
# Purpose: Admin tool with three tabs:
#   Structure - nested Program > Division > Involvement tree (ministry structure)
#   Clean Up  - problem queues (dormant, past dates, zero members, etc.)
#   Manage    - flat selectable list for bulk actions
# Author: Jake Pierson
# Date: 2026-08-12
#
# Install: Special Content -> Python Scripts -> name InvolvementCleanup
# Run: /PyScriptForm/InvolvementCleanup
#
# Special Content only (no C# deploy). Writes use the signed-in browser session:
#   POST /Org/PostData          status / type
#   POST /OrgSearch/Edit        id=amc-{orgId} mobile category
#   POST /OrgSearch/MainDiv     main division
#   POST /OrgSearch/ToggleTag   add/remove related (non-main) division
#   Python DropOrgMember        drop current members to Previous
#
# Terminology: main division = Organizations.DivisionId.
# Related / non-main divisions = other DivOrg rows for that involvement.
#
# IronPython notes (TouchPoint embeds IronPython 2.7):
#   - Use print without parentheses; except Exception, ex
#   - Put UI in model.Form on GET (PyScriptForm ignores Output)
#   - Heavy SQL via ajax POST after shell paints
#   - Prefer string concat over .format() for large HTML

import traceback

SCRIPT_PATH = '/PyScriptForm/InvolvementCleanup'
INVOLVEMENT_DASHBOARD_BASE = 'https://fcchudson.tpsdb.com/PyScriptForm/InvolvementDashboard'

ORG_STATUS_ACTIVE = 30
ORG_STATUS_INACTIVE = 40
INACTIVE_DAYS = 90
RECENT_ATTEND_DAYS = 30
DORMANT_MEMBER_DAYS = 45

# Queues: (key, label, description)
QUEUES = [
    ('dormant', 'Dormant', 'Active involvements with no meetings or member activity in ~90 days'),
    ('past_meeting', 'Last meeting in the past', 'Active involvements whose last meeting date is before today'),
    ('past_regend', 'Registration end in the past', 'Active involvements with RegEnd before today'),
    ('main_fellowship', 'Main Fellowship - no attendance (30d)', 'Active Bible Fellowship orgs with no qualifying attendance in 30 days'),
    ('zero_members', 'Zero current members', 'Active involvements with MemberCount = 0'),
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
        return unicode(val).strip()
    except:
        try:
            return str(val).strip()
        except:
            return default


def _i(val, default=0):
    s = _s(val)
    if not s:
        return default
    try:
        return int(s)
    except:
        return default


def _b(val):
    s = _s(val).lower()
    return s in ('1', 'true', 'yes', 'on')


def _html(val):
    s = _s(val)
    return (s.replace('&', '&amp;')
             .replace('<', '&lt;')
             .replace('>', '&gt;')
             .replace('"', '&quot;'))


def _get(name, default=None):
    try:
        v = Data.GetValue(name)
    except:
        v = None
    if _is_null(v):
        return default
    return v


def _form_val(name, default=''):
    v = _get(name, None)
    if v is None:
        return default
    return _s(v, default)


def _dd():
    return model.DynamicData()


def _fmt_dt(val):
    if _is_null(val):
        return ''
    try:
        return _s(val.ToString('M/d/yyyy'))
    except:
        return _html(val)


def _json_quote(s):
    s = _s(s, u'')
    parts = ['"']
    for ch in s:
        o = ord(ch)
        if ch == u'"':
            parts.append('\\"')
        elif ch == u'\\':
            parts.append('\\\\')
        elif ch == u'\n':
            parts.append('\\n')
        elif ch == u'\r':
            parts.append('\\r')
        elif ch == u'\t':
            parts.append('\\t')
        elif o < 0x20 or o > 0x7e:
            parts.append('\\u%04x' % o)
        else:
            parts.append(chr(o))
    parts.append('"')
    return ''.join(parts)


def _json_dump(obj):
    if obj is None:
        return 'null'
    if obj is True:
        return 'true'
    if obj is False:
        return 'false'
    if isinstance(obj, (int, long)) and not isinstance(obj, bool):
        return str(int(obj))
    if isinstance(obj, float):
        return repr(float(obj))
    if isinstance(obj, dict):
        items = []
        for k, v in obj.items():
            items.append(_json_quote(_s(k)) + ':' + _json_dump(v))
        return '{' + ','.join(items) + '}'
    if isinstance(obj, (list, tuple)):
        return '[' + ','.join([_json_dump(x) for x in obj]) + ']'
    return _json_quote(_s(obj))


def _json_out(obj):
    print _json_dump(obj)


def _err_out(e):
    try:
        tb = _s(traceback.format_exc())
    except:
        tb = ''
    _json_out({'error': _s(e), 'traceback': tb})


def _parse_org_ids():
    raw = _form_val('org_ids')
    ids = []
    seen = {}
    for part in raw.replace(';', ',').split(','):
        oid = _i(part, 0)
        if oid > 0 and oid not in seen:
            seen[oid] = 1
            ids.append(oid)
    return ids


def _dashboard_url(org_id):
    return INVOLVEMENT_DASHBOARD_BASE + '?org_id=' + str(_i(org_id))


def _org_link(org_id, name):
    return ('<a href="/Org/' + str(_i(org_id)) + '" target="_blank" rel="noopener noreferrer">'
            + _html(name) + '</a>')


def _dash_icon(org_id):
    url = _html(_dashboard_url(org_id))
    return ('<a class="ic-icon-btn" href="' + url + '" target="_blank" rel="noopener noreferrer" '
            'title="Open Involvement Dashboard"><i class="fa fa-dashboard"></i></a>')


def _mobile_badge(allow):
    if _i(allow, 0) == 1 or allow is True or _s(allow).lower() == 'true':
        return '<span class="ic-badge ic-badge-on" title="Allow Mobile View">Mobile</span>'
    return '<span class="ic-badge ic-badge-off" title="Mobile view off">-</span>'


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def _lookup_programs():
    sql = """
SELECT p.Id, p.Name
FROM dbo.Program p
ORDER BY p.Name
"""
    rows = []
    for r in q.QuerySql(sql):
        rows.append({'id': _i(r.Id), 'name': _s(r.Name)})
    return rows


def _lookup_divisions(prog_id=0):
    sql = """
SELECT d.Id, d.Name, pd.ProgId
FROM dbo.Division d
LEFT JOIN dbo.ProgDiv pd ON pd.DivId = d.Id
WHERE (@progId = 0 OR pd.ProgId = @progId)
ORDER BY d.Name
"""
    p = _dd()
    p.AddValue('progId', str(_i(prog_id, 0)))
    rows = []
    for r in q.QuerySql(sql, p):
        rows.append({'id': _i(r.Id), 'name': _s(r.Name), 'prog_id': _i(r.ProgId)})
    return rows


def _lookup_org_types():
    sql = """
SELECT Id, Description
FROM lookup.OrganizationType
ORDER BY Description
"""
    rows = [{'id': 0, 'name': '(none)'}]
    for r in q.QuerySql(sql):
        rows.append({'id': _i(r.Id), 'name': _s(r.Description)})
    return rows


def _lookup_mobile_categories():
    sql = """
SELECT Id, Description
FROM lookup.CategoryMobile
ORDER BY Description
"""
    rows = [{'id': 0, 'name': '(none)'}]
    try:
        for r in q.QuerySql(sql):
            rows.append({'id': _i(r.Id), 'name': _s(r.Description)})
    except:
        pass
    return rows


# ---------------------------------------------------------------------------
# Queue / structure queries
# ---------------------------------------------------------------------------

def _base_select():
    return """
SELECT
    o.OrganizationId AS OrgId,
    o.OrganizationName AS Organization,
    o.OrganizationStatusId AS OrgStatusId,
    CASE WHEN o.OrganizationStatusId = 30 THEN 'Active' ELSE 'Inactive' END AS OrgStatus,
    o.MemberCount AS Members,
    o.DivisionId AS MainDivId,
    d.Name AS Division,
    p.Id AS ProgId,
    p.Name AS Program,
    o.OrganizationTypeId AS OrgTypeId,
    ot.Description AS OrgType,
    ISNULL(o.AllowMobileView, 0) AS AllowMobileView,
    o.CategoryMobileId AS CategoryMobileId,
    cm.Description AS MobileCategory,
    o.LastMeetingDate,
    o.RegEnd,
    o.CreatedDate,
    o.IsBibleFellowshipOrg
"""


def _base_from():
    return """
FROM dbo.Organizations o
LEFT JOIN dbo.Division d ON d.Id = o.DivisionId
OUTER APPLY (
    SELECT TOP 1 p2.Id, p2.Name
    FROM dbo.ProgDiv pd2
    JOIN dbo.Program p2 ON p2.Id = pd2.ProgId
    WHERE pd2.DivId = d.Id
    ORDER BY p2.Name
) p
LEFT JOIN lookup.OrganizationType ot ON ot.Id = o.OrganizationTypeId
LEFT JOIN lookup.CategoryMobile cm ON cm.Id = o.CategoryMobileId
"""


def _row_dict(r):
    return {
        'org_id': _i(r.OrgId),
        'name': _s(r.Organization),
        'status': _s(r.OrgStatus),
        'status_id': _i(r.OrgStatusId),
        'members': _i(r.Members),
        'prog_id': _i(r.ProgId),
        'program': _s(r.Program),
        'div_id': _i(r.MainDivId),
        'division': _s(r.Division),
        'org_type_id': _i(r.OrgTypeId),
        'org_type': _s(r.OrgType),
        'allow_mobile': _i(r.AllowMobileView),
        'category_id': _i(r.CategoryMobileId),
        'mobile_category': _s(r.MobileCategory),
        'last_meeting': _fmt_dt(r.LastMeetingDate),
        'reg_end': _fmt_dt(r.RegEnd),
        'created': _fmt_dt(r.CreatedDate),
    }


def _run_queue(queue_key, prog_id=0, div_id=0, include_inactive=False):
    queue_key = _s(queue_key) or 'dormant'
    p = _dd()
    p.AddValue('progId', str(_i(prog_id, 0)))
    p.AddValue('divId', str(_i(div_id, 0)))
    p.AddValue('inactiveDays', str(INACTIVE_DAYS))
    p.AddValue('attendDays', str(RECENT_ATTEND_DAYS))
    p.AddValue('memberDays', str(DORMANT_MEMBER_DAYS))

    prog_filter = ' AND (@progId = 0 OR p.Id = CAST(@progId AS int)) '
    div_filter = ' AND (@divId = 0 OR o.DivisionId = CAST(@divId AS int)) '

    if queue_key == 'dormant':
        sql = _base_select() + _base_from() + """
WHERE o.OrganizationStatusId = 30
""" + prog_filter + div_filter + """
  AND (
        o.LastMeetingDate IS NULL
        OR o.LastMeetingDate < DATEADD(day, -CAST(@inactiveDays AS int), GETDATE())
      )
  AND NOT EXISTS (
        SELECT 1 FROM dbo.OrganizationMembers om
        WHERE om.OrganizationId = o.OrganizationId
          AND (
                om.EnrollmentDate >= DATEADD(day, -CAST(@memberDays AS int), GETDATE())
                OR (om.InactiveDate IS NOT NULL
                    AND om.InactiveDate >= DATEADD(day, -CAST(@memberDays AS int), GETDATE()))
              )
      )
ORDER BY o.OrganizationName
"""
    elif queue_key == 'past_meeting':
        sql = _base_select() + _base_from() + """
WHERE o.OrganizationStatusId = 30
""" + prog_filter + div_filter + """
  AND o.LastMeetingDate IS NOT NULL
  AND o.LastMeetingDate < CAST(GETDATE() AS date)
ORDER BY o.LastMeetingDate, o.OrganizationName
"""
    elif queue_key == 'past_regend':
        sql = _base_select() + _base_from() + """
WHERE o.OrganizationStatusId = 30
""" + prog_filter + div_filter + """
  AND o.RegEnd IS NOT NULL
  AND o.RegEnd < GETDATE()
ORDER BY o.RegEnd, o.OrganizationName
"""
    elif queue_key == 'main_fellowship':
        sql = _base_select() + _base_from() + """
WHERE o.OrganizationStatusId = 30
  AND ISNULL(o.IsBibleFellowshipOrg, 0) = 1
""" + prog_filter + div_filter + """
  AND NOT EXISTS (
        SELECT 1 FROM dbo.Meetings m
        WHERE m.OrganizationId = o.OrganizationId
          AND m.MeetingDate > DATEADD(day, -CAST(@attendDays AS int), GETDATE())
          AND m.MeetingDate < GETDATE()
          AND m.NumPresent > 3
      )
ORDER BY o.OrganizationName
"""
    elif queue_key == 'zero_members':
        sql = _base_select() + _base_from() + """
WHERE o.OrganizationStatusId = 30
""" + prog_filter + div_filter + """
  AND ISNULL(o.MemberCount, 0) = 0
ORDER BY o.OrganizationName
"""
    elif queue_key == 'manage':
        # flat browse for bulk Manage tab
        inactive_sql = '' if include_inactive else ' AND o.OrganizationStatusId = 30 '
        sql = _base_select() + _base_from() + """
WHERE 1=1
""" + inactive_sql + prog_filter + div_filter + """
ORDER BY p.Name, d.Name, o.OrganizationName
"""
    else:
        inactive_sql = ' AND o.OrganizationStatusId = 30 '
        sql = _base_select() + _base_from() + """
WHERE 1=0
""" + inactive_sql + prog_filter + div_filter + """
ORDER BY o.OrganizationName
"""

    rows = []
    for r in q.QuerySql(sql, p):
        rows.append(_row_dict(r))
    return rows



def _tree_where(include_inactive=False):
    where = ['1=1']
    if not include_inactive:
        where.append("os.OrgStatus = 'Active'")
    where.append('(@progId = 0 OR os.ProgId = CAST(@progId AS int))')
    where.append('(@divId = 0 OR os.DivId = CAST(@divId AS int))')
    where.append("(@createdAfter = '' OR o.CreatedDate >= CAST(@createdAfter AS datetime))")
    return ' AND '.join(where)


def _tree_params(prog_id=0, div_id=0, created_after=''):
    p = _dd()
    p.AddValue('progId', str(_i(prog_id, 0)))
    p.AddValue('divId', str(_i(div_id, 0)))
    p.AddValue('createdAfter', _s(created_after))
    return p


def _tree_row_dict(r, related_divs=''):
    return {
        'prog_id': _i(r.ProgId),
        'program': _s(r.Program),
        'div_id': _i(r.DivId),
        'division': _s(r.Division),
        'org_id': _i(r.OrgId),
        'name': _s(r.Organization),
        'status': _s(r.OrgStatus),
        'members': _i(r.Members),
        'previous': _i(r.Previous),
        'visitors': _i(r.Visitors),
        'meetings': _i(r.Meetings),
        'org_type': _s(r.OrgType),
        'created': _fmt_dt(r.CreatedDate),
        'related_divs': _s(related_divs),
    }


def _run_tree(prog_id=0, div_id=0, include_inactive=False, created_after=''):
    """Nested ministry structure rows from OrganizationStructure (+ related divs)."""
    p = _tree_params(prog_id, div_id, created_after)
    where_sql = _tree_where(include_inactive)
    # Prefer related-div aggregation; fall back if STUFF/FOR XML fails on this SQL host.
    sql_related = (
        "SELECT "
        "os.ProgId, os.Program, os.DivId, os.Division, os.OrgId, os.Organization, "
        "os.OrgStatus, os.Members, os.Previous, os.Vistors AS Visitors, os.Meetings, "
        "ot.Description AS OrgType, o.CreatedDate, "
        "STUFF(( "
        "  SELECT '|' + CAST(d2.Id AS varchar(20)) + ':' + REPLACE(d2.Name, '|', '/') "
        "  FROM dbo.DivOrg do2 "
        "  JOIN dbo.Division d2 ON d2.Id = do2.DivId "
        "  WHERE do2.OrgId = os.OrgId AND d2.Id <> os.DivId "
        "  FOR XML PATH(''), TYPE "
        ").value('.', 'nvarchar(max)'), 1, 1, '') AS RelatedDivs "
        "FROM dbo.OrganizationStructure os "
        "INNER JOIN dbo.Organizations o ON o.OrganizationId = os.OrgId "
        "LEFT JOIN lookup.OrganizationType ot ON ot.Id = o.OrganizationTypeId "
        "WHERE " + where_sql + " "
        "ORDER BY os.Program, os.Division, os.Organization"
    )
    sql_basic = (
        "SELECT "
        "os.ProgId, os.Program, os.DivId, os.Division, os.OrgId, os.Organization, "
        "os.OrgStatus, os.Members, os.Previous, os.Vistors AS Visitors, os.Meetings, "
        "ot.Description AS OrgType, o.CreatedDate "
        "FROM dbo.OrganizationStructure os "
        "INNER JOIN dbo.Organizations o ON o.OrganizationId = os.OrgId "
        "LEFT JOIN lookup.OrganizationType ot ON ot.Id = o.OrganizationTypeId "
        "WHERE " + where_sql + " "
        "ORDER BY os.Program, os.Division, os.Organization"
    )
    rows = []
    try:
        for r in q.QuerySql(sql_related, p):
            rows.append(_tree_row_dict(r, _s(r.RelatedDivs)))
    except:
        rows = []
        for r in q.QuerySql(sql_basic, p):
            rows.append(_tree_row_dict(r, ''))
    return rows


def _summary_from_tree_rows(rows):
    """
    Build Structure tile totals from the same rows used for the tree.
    Counts programs/divisions/involvements distinctly; member metrics are
    summed once per OrgId (OrganizationStructure can repeat an org under
    multiple divisions).
    """
    progs = {}
    divs = {}
    orgs = {}
    for r in rows or []:
        pid = _i(r.get('prog_id'))
        did = _i(r.get('div_id'))
        oid = _i(r.get('org_id'))
        if pid > 0:
            progs[pid] = 1
        if did > 0:
            divs[did] = 1
        if oid > 0 and oid not in orgs:
            orgs[oid] = r
    members = 0
    previous = 0
    visitors = 0
    meetings = 0
    active = 0
    for oid, r in orgs.items():
        members += _i(r.get('members'))
        previous += _i(r.get('previous'))
        visitors += _i(r.get('visitors'))
        meetings += _i(r.get('meetings'))
        if _s(r.get('status')) == 'Active':
            active += 1
    return {
        'programs': len(progs),
        'divisions': len(divs),
        'involvements': len(orgs),
        'active': active,
        'members': members,
        'previous': previous,
        'visitors': visitors,
        'meetings': meetings,
    }


def _org_warnings(org_ids):
    """Warn-but-allow signals for selected orgs."""
    if not org_ids:
        return []
    # Build safe IN list from ints only
    in_list = ','.join([str(_i(x)) for x in org_ids if _i(x) > 0])
    if not in_list:
        return []
    sql = """
SELECT
    o.OrganizationId AS OrgId,
    o.OrganizationName AS Organization,
    ISNULL(o.MemberCount, 0) AS Members,
    CASE WHEN EXISTS (
        SELECT 1 FROM dbo.Meetings m
        WHERE m.OrganizationId = o.OrganizationId AND m.MeetingDate > GETDATE()
    ) THEN 1 ELSE 0 END AS HasFutureMeetings,
    CASE WHEN ISNULL(o.RegistrationTypeId, 0) > 0
              AND (o.RegEnd IS NULL OR o.RegEnd > GETDATE())
              AND ISNULL(o.RegistrationClosed, 0) = 0
         THEN 1 ELSE 0 END AS OpenRegistration
FROM dbo.Organizations o
WHERE o.OrganizationId IN (""" + in_list + """)
"""
    out = []
    for r in q.QuerySql(sql):
        notes = []
        if _i(r.Members) > 0:
            notes.append(str(_i(r.Members)) + ' current members')
        if _i(r.HasFutureMeetings) == 1:
            notes.append('future meetings')
        if _i(r.OpenRegistration) == 1:
            notes.append('open registration')
        out.append({
            'org_id': _i(r.OrgId),
            'name': _s(r.Organization),
            'warnings': notes,
        })
    return out


# ---------------------------------------------------------------------------
# Server-side helpers for writes (Special Content only)
# Status/type/category/divisions are applied in the browser via existing
# TouchPoint endpoints. Python only drops members and reports DivOrg membership.
# ---------------------------------------------------------------------------

def _action_drop_members(org_ids):
    """Drop current members to Previous via model.DropOrgMember (built-in)."""
    results = []
    for oid in org_ids:
        item = {'org_id': oid, 'ok': False, 'message': '', 'dropped': 0}
        try:
            p = _dd()
            p.AddValue('orgid', str(oid))
            sql = '''
SELECT om.PeopleId
FROM dbo.OrganizationMembers om
WHERE om.OrganizationId = @orgid
  AND om.InactiveDate IS NULL
'''
            rows = list(q.QuerySql(sql, p))
            n = 0
            for r in rows:
                pid = _i(r.PeopleId)
                if pid <= 0:
                    continue
                model.DropOrgMember(pid, oid)
                n += 1
            item['ok'] = True
            item['dropped'] = n
            item['message'] = 'Dropped ' + str(n) + ' to Previous'
        except Exception, ex:
            item['message'] = _s(ex)
        results.append(item)
    return results


def _div_membership(org_ids, div_id):
    """Return which orgs already have DivOrg for div_id (for ToggleTag add/remove)."""
    out = []
    if not org_ids or div_id <= 0:
        return out
    safe_ids = []
    for i in org_ids:
        n = _i(i)
        if n > 0:
            safe_ids.append(str(n))
    if not safe_ids:
        return out
    id_list = ','.join(safe_ids)
    p = _dd()
    p.AddValue('divid', str(div_id))
    sql = '''
SELECT o.OrganizationId AS OrgId,
       CASE WHEN EXISTS (
           SELECT 1 FROM dbo.DivOrg d
           WHERE d.OrgId = o.OrganizationId AND d.DivId = @divid
       ) THEN 1 ELSE 0 END AS HasDiv
FROM dbo.Organizations o
WHERE o.OrganizationId IN ({0})
'''.format(id_list)
    for r in q.QuerySql(sql, p):
        out.append({
            'org_id': _i(r.OrgId),
            'has': _i(r.HasDiv) == 1,
        })
    return out


def _related_divisions(org_ids):
    """
    For each org, list DivOrg rows that are not the main division
    (Organizations.DivisionId). Used to strip related/non-main divisions.
    """
    by_org = {}
    safe_ids = []
    for i in org_ids:
        n = _i(i)
        if n > 0 and n not in by_org:
            by_org[n] = {'org_id': n, 'main_div_id': 0, 'related': []}
            safe_ids.append(str(n))
    if not safe_ids:
        return []
    id_list = ','.join(safe_ids)
    sql = '''
SELECT
    o.OrganizationId AS OrgId,
    ISNULL(o.DivisionId, 0) AS MainDivId,
    d.DivId AS RelatedDivId
FROM dbo.Organizations o
LEFT JOIN dbo.DivOrg d
    ON d.OrgId = o.OrganizationId
   AND ISNULL(o.DivisionId, 0) > 0
   AND d.DivId <> o.DivisionId
WHERE o.OrganizationId IN ({0})
ORDER BY o.OrganizationId, d.DivId
'''.format(id_list)
    for r in q.QuerySql(sql):
        oid = _i(r.OrgId)
        if oid not in by_org:
            continue
        by_org[oid]['main_div_id'] = _i(r.MainDivId)
        rid = _i(r.RelatedDivId)
        if rid > 0 and rid not in by_org[oid]['related']:
            by_org[oid]['related'].append(rid)
    out = []
    for oid in sorted(by_org.keys()):
        out.append(by_org[oid])
    return out


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def _css():
    return '''
.ic-root {
    display: block !important;
    color: #1e293b !important;
    max-width: 1280px;
    margin: 0 auto;
    padding: 20px;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f5f5f5 !important;
    box-sizing: border-box;
}
.ic-root .dashboard-header {
    background: #19283B;
    color: white !important;
    padding: 18px 24px 20px;
    border-radius: 12px;
    margin: 0 auto 16px auto;
    box-shadow: 0 4px 15px rgba(1, 43, 88, 0.35);
    text-align: center;
    max-width: 720px;
}
.ic-root .dashboard-header h1 {
    margin: 0 0 6px 0;
    font-size: 26px;
    font-weight: 700;
    color: white !important;
}
.ic-root .dashboard-header .header-sub {
    margin: 0;
    font-size: 13px;
    opacity: 0.9;
    color: white !important;
}
.ic-card {
    background: white !important;
    padding: 18px 20px;
    border-radius: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    margin-bottom: 14px;
    color: #1e293b !important;
}
.ic-card-title {
    font-size: 18px;
    font-weight: 600;
    margin: 0 0 8px 0;
}
.ic-meta { font-size: 13px; color: #64748b !important; margin: 0 0 12px 0; }
.ic-tabs { text-align: center; margin: 0 0 14px 0; }
.ic-tab {
    display: inline-block;
    border: 1px solid #e2e8f0;
    background: white;
    color: #475569 !important;
    padding: 6px 12px;
    border-radius: 6px;
    font-weight: 600;
    font-size: 13px;
    text-decoration: none !important;
    margin: 2px;
    cursor: pointer;
}
.ic-tab.active {
    border-color: #19283B;
    background: #19283B;
    color: white !important;
}
.ic-filters .form-group {
    display: inline-block;
    vertical-align: top;
    margin: 0 10px 10px 0;
}
.ic-filters label {
    display: block;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    color: #64748b;
    margin-bottom: 4px;
}
.ic-filters select, .ic-filters input {
    min-width: 160px;
    padding: 6px 8px;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
}
.ic-actions {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 12px;
    margin: 0 0 12px 0;
}
.ic-actions .btn-primary, .ic-actions .btn-secondary {
    display: inline-block;
    margin: 0 6px 6px 0;
    text-decoration: none !important;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    border: none;
}
.ic-actions .btn-primary { background: #19283B; color: #fff !important; }
.ic-actions .btn-secondary {
    background: white;
    color: #19283B !important;
    border: 2px solid #e2e8f0;
}
.ic-actions .btn-secondary:hover { border-color: #6699ea; color: #6699ea !important; }
.ic-root .people-table {
    width: 100%;
    border-collapse: collapse;
    background: white !important;
}
.ic-root .people-table th, .ic-root .people-table td {
    text-align: left;
    padding: 8px 10px;
    border-bottom: 1px solid #e2e8f0;
    vertical-align: middle;
    font-size: 13px;
}
.ic-root .people-table th {
    color: #64748b !important;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.4px;
}
.ic-root .people-table a {
    color: #19283B !important;
    font-weight: 600;
    text-decoration: none;
}
.ic-root .people-table a:hover { color: #6699ea !important; text-decoration: underline; }
.ic-root .people-table tbody tr:hover { background: #f8fafc; }
.ic-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 700;
}
.ic-badge-on { background: #dcfce7; color: #166534; }
.ic-badge-off { background: #f1f5f9; color: #94a3b8; }
.ic-icon-btn {
    display: inline-block;
    width: 28px;
    height: 28px;
    line-height: 28px;
    text-align: center;
    border-radius: 6px;
    border: 1px solid #e2e8f0;
    color: #19283B !important;
    text-decoration: none !important;
}
.ic-icon-btn:hover { border-color: #6699ea; color: #6699ea !important; }
.ic-modal-overlay {
    display: none;
    position: fixed;
    z-index: 10000;
    left: 0; top: 0; right: 0; bottom: 0;
    background: rgba(15, 23, 42, 0.45);
}
.ic-modal-overlay.visible { display: block; }
.ic-modal {
    background: white;
    max-width: 560px;
    margin: 60px auto;
    padding: 22px 24px;
    border-radius: 12px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.25);
}
.ic-modal h3 { margin: 0 0 10px 0; }
.ic-warn {
    background: #fff7ed;
    border: 1px solid #fdba74;
    color: #9a3412;
    padding: 10px 12px;
    border-radius: 8px;
    font-size: 13px;
    margin: 10px 0;
}
.ic-empty { color: #64748b; padding: 20px; text-align: center; }

.ic-stats {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin: 0 0 14px 0;
}
.ic-stat {
    flex: 1;
    min-width: 90px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 12px 10px;
    text-align: center;
}
.ic-stat .n {
    font-size: 22px;
    font-weight: 700;
    color: #19283B;
    line-height: 1.1;
}
.ic-stat .l {
    margin-top: 4px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    color: #64748b;
}
.ic-tree-wrap { overflow: auto; }
.ic-tree-table { width: 100%; border-collapse: collapse; background: white !important; }
.ic-tree-table th, .ic-tree-table td {
    padding: 8px 10px;
    border-bottom: 1px solid #e2e8f0;
    font-size: 13px;
    vertical-align: middle;
}
.ic-tree-table th {
    text-align: left;
    color: #64748b !important;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    background: #f8fafc;
}
.ic-tree-table .num { text-align: center; }
.ic-prog-row { background: #e8eef7; font-weight: 700; cursor: pointer; }
.ic-div-row { background: #f0f5fa; cursor: pointer; display: none; }
.ic-org-row { display: none; }
.ic-org-row.inactive { background: #fff1f2; color: #94a3b8; }
.ic-toggle {
    display: inline-block;
    width: 18px;
    text-align: center;
    font-weight: 700;
    margin-right: 4px;
    color: #19283B;
}
.ic-related { font-size: 12px; color: #64748b; }
.ic-related a { color: #6699ea !important; text-decoration: none; }
.ic-related a:hover { text-decoration: underline; }
.ic-highlight { animation: ic-hl 2s ease-in-out; }
@keyframes ic-hl {
    0% { background-color: #fef9c3; }
    100% { background-color: transparent; }
}
.ic-pad-div { padding-left: 28px !important; }
.ic-pad-org { padding-left: 56px !important; }
'''


def _options_html(items, selected=0):
    html = ''
    for it in items:
        sel = ' selected="selected"' if _i(it.get('id')) == _i(selected) else ''
        html += '<option value="' + str(_i(it.get('id'))) + '"' + sel + '>'
        html += _html(it.get('name')) + '</option>'
    return html


def _queue_options_html():
    html = ''
    for key, label, desc in QUEUES:
        html += '<option value="' + _html(key) + '">' + _html(label) + '</option>'
    return html


def _page():
    programs = _lookup_programs()
    divisions = _lookup_divisions(0)
    org_types = _lookup_org_types()
    categories = _lookup_mobile_categories()

    html = '<style>' + _css() + '</style>'
    html += '<div class="ic-root">'
    html += '<div class="dashboard-header">'
    html += '<h1>Involvement Cleanup</h1>'
    html += '<p class="header-sub">Browse ministry structure, work cleanup lists, and manage '
    html += 'involvements in bulk. Admin only. Writes use your TouchPoint session.</p>'
    html += '</div>'

    html += '<div class="ic-tabs">'
    html += '<a class="ic-tab active" data-tab="structure" href="#">Structure</a>'
    html += '<a class="ic-tab" data-tab="cleanup" href="#">Clean Up</a>'
    html += '<a class="ic-tab" data-tab="manage" href="#">Manage</a>'
    html += '</div>'

    html += '<div class="ic-card" id="ic-filters-card">'
    html += '<div class="ic-card-title">Filters</div>'
    html += '<div class="ic-filters form-inline">'
    html += '<div class="form-group" id="ic-queue-wrap" style="display:none"><label>Queue</label>'
    html += '<select id="ic-queue">' + _queue_options_html() + '</select></div>'
    html += '<div class="form-group"><label>Program</label>'
    html += '<select id="ic-prog"><option value="0">All programs</option>'
    html += _options_html(programs) + '</select></div>'
    html += '<div class="form-group"><label>Division</label>'
    html += '<select id="ic-div"><option value="0">All divisions</option>'
    html += _options_html(divisions) + '</select></div>'
    html += '<div class="form-group" id="ic-created-wrap"><label>Created after</label>'
    html += '<input type="date" id="ic-created-after" /></div>'
    html += '<div class="form-group" id="ic-inactive-wrap"><label>Include inactive</label>'
    html += '<select id="ic-include-inactive"><option value="0">Active only</option>'
    html += '<option value="1">Active + inactive</option></select></div>'
    html += '<div class="form-group"><label>&nbsp;</label>'
    html += '<button type="button" class="btn-primary" id="ic-load" style="background:#19283B;color:#fff;'
    html += 'border:none;border-radius:8px;padding:8px 14px;font-weight:600;cursor:pointer">Load</button></div>'
    html += '</div></div>'

    html += '<div id="ic-stats" class="ic-stats" style="display:none"></div>'

    html += '<div class="ic-card" id="ic-actions-card" style="display:none">'
    html += '<div class="ic-card-title">Actions</div>'
    html += '<p class="ic-meta">Select rows, then choose an action. Every write asks for confirmation. '
    html += 'Writes use your TouchPoint session (Org / OrgSearch endpoints); drops use DropOrgMember. '
    html += 'Warnings are shown but do not block.</p>'
    html += '<div class="ic-actions">'
    html += '<button type="button" class="btn-primary" data-action="mark_inactive">Mark inactive</button>'
    html += '<button type="button" class="btn-secondary" data-action="set_main_division">Set main division</button>'
    html += '<button type="button" class="btn-secondary" data-action="add_division">Add related division</button>'
    html += '<button type="button" class="btn-secondary" data-action="remove_division">Remove related division</button>'
    html += '<button type="button" class="btn-secondary" data-action="remove_all_related">Remove all related divisions</button>'
    html += '<button type="button" class="btn-secondary" data-action="set_type">Change type</button>'
    html += '<button type="button" class="btn-secondary" data-action="set_category">Set mobile category</button>'
    html += '<button type="button" class="btn-secondary" id="ic-select-all">Select all</button>'
    html += '<button type="button" class="btn-secondary" id="ic-clear">Clear</button>'
    html += '</div>'
    html += '<div id="ic-result" class="ic-meta"></div>'
    html += '</div>'

    html += '<div class="ic-card">'
    html += '<div class="ic-card-title" id="ic-list-title">Structure</div>'
    html += '<p class="ic-meta" id="ic-list-meta">Expand programs and divisions to browse involvements.</p>'
    html += '<div id="ic-table-wrap"><div class="ic-empty">Loading...</div></div>'
    html += '</div>'
    html += '</div>'

    # Modal
    html += '<div class="ic-modal-overlay" id="ic-modal">'
    html += '<div class="ic-modal">'
    html += '<h3 id="ic-modal-title">Confirm</h3>'
    html += '<div id="ic-modal-body"></div>'
    html += '<div style="margin-top:16px;text-align:right">'
    html += '<button type="button" class="btn-secondary" id="ic-modal-cancel" '
    html += 'style="margin-right:8px;background:#fff;border:2px solid #e2e8f0;border-radius:8px;'
    html += 'padding:8px 14px;font-weight:600;cursor:pointer">Cancel</button>'
    html += '<button type="button" class="btn-primary" id="ic-modal-ok" '
    html += 'style="background:#19283B;color:#fff;border:none;border-radius:8px;'
    html += 'padding:8px 14px;font-weight:600;cursor:pointer">Confirm</button>'
    html += '</div></div></div>'

    look = {
        'divisions': divisions,
        'org_types': org_types,
        'categories': categories,
    }
    look_json = _json_dump(look)

    html += '<script>\n'
    html += '(function() {\n'
    html += '  var scriptUrl = window.location.pathname;\n'
    html += '  var lookups = ' + look_json + ';\n'
    html += '  var currentTab = "structure";\n'
    html += '  var pendingAction = null;\n'
    html += '  function esc(s) {\n'
    html += '    return String(s == null ? "" : s)\n'
    html += '      .replace(/&/g, "&amp;").replace(/</g, "&lt;")\n'
    html += '      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");\n'
    html += '  }\n'
    html += '  function selectedIds() {\n'
    html += '    var ids = [];\n'
    html += '    var boxes = document.querySelectorAll(".ic-cb:checked");\n'
    html += '    for (var i = 0; i < boxes.length; i++) ids.push(boxes[i].value);\n'
    html += '    return ids;\n'
    html += '  }\n'
    html += '  function setResult(msg) {\n'
    html += '    var el = document.getElementById("ic-result");\n'
    html += '    if (el) el.innerHTML = msg || "";\n'
    html += '  }\n'
    html += '  function refreshDivOptions() {\n'
    html += '    var prog = document.getElementById("ic-prog").value || "0";\n'
    html += '    var sel = document.getElementById("ic-div");\n'
    html += '    var cur = sel.value;\n'
    html += '    var h = "<option value=\\"0\\">All divisions</option>";\n'
    html += '    for (var i = 0; i < lookups.divisions.length; i++) {\n'
    html += '      var d = lookups.divisions[i];\n'
    html += '      if (prog !== "0" && String(d.prog_id) !== String(prog)) continue;\n'
    html += '      h += "<option value=\\"" + d.id + "\\">" + esc(d.name) + "</option>";\n'
    html += '    }\n'
    html += '    sel.innerHTML = h;\n'
    html += '    var found = false;\n'
    html += '    for (var j = 0; j < sel.options.length; j++) {\n'
    html += '      if (sel.options[j].value === cur) { found = true; break; }\n'
    html += '    }\n'
    html += '    sel.value = found ? cur : "0";\n'
    html += '  }\n'
    html += '  function renderRows(rows) {\n'
    html += '    var wrap = document.getElementById("ic-table-wrap");\n'
    html += '    var meta = document.getElementById("ic-list-meta");\n'
    html += '    if (!rows || !rows.length) {\n'
    html += '      wrap.innerHTML = "<div class=\\"ic-empty\\">No matching involvements.</div>";\n'
    html += '      if (meta) meta.textContent = "0 involvements";\n'
    html += '      return;\n'
    html += '    }\n'
    html += '    if (meta) meta.textContent = rows.length + " involvement(s)";\n'
    html += '    var h = "<table class=\\"people-table\\"><thead><tr>";\n'
    html += '    h += "<th></th><th></th><th>Involvement</th><th>Program</th><th>Division</th>";\n'
    html += '    h += "<th>Type</th><th>Mobile</th><th>Category</th><th>Members</th>";\n'
    html += '    h += "<th>Last meeting</th><th>Reg end</th><th>Status</th></tr></thead><tbody>";\n'
    html += '    for (var i = 0; i < rows.length; i++) {\n'
    html += '      var r = rows[i];\n'
    html += '      var dash = "' + _html(INVOLVEMENT_DASHBOARD_BASE) + '?org_id=" + r.org_id;\n'
    html += '      h += "<tr>";\n'
    html += '      h += "<td><input type=\\"checkbox\\" class=\\"ic-cb\\" value=\\"" + r.org_id + "\\" /></td>";\n'
    html += '      h += "<td><a class=\\"ic-icon-btn\\" href=\\"" + esc(dash) + "\\" target=\\"_blank\\" rel=\\"noopener noreferrer\\" title=\\"Involvement Dashboard\\"><i class=\\"fa fa-dashboard\\"></i></a></td>";\n'
    html += '      h += "<td><a href=\\"/Org/" + r.org_id + "\\" target=\\"_blank\\" rel=\\"noopener noreferrer\\">" + esc(r.name) + "</a>";\n'
    html += '      h += " <span class=\\"ic-meta\\">(" + r.org_id + ")</span></td>";\n'
    html += '      h += "<td>" + esc(r.program || "") + "</td>";\n'
    html += '      h += "<td>" + esc(r.division || "") + "</td>";\n'
    html += '      h += "<td>" + esc(r.org_type || "") + "</td>";\n'
    html += '      h += "<td>" + (r.allow_mobile ? "<span class=\\"ic-badge ic-badge-on\\">Mobile</span>" : "<span class=\\"ic-badge ic-badge-off\\">-</span>") + "</td>";\n'
    html += '      h += "<td>" + esc(r.mobile_category || "") + "</td>";\n'
    html += '      h += "<td>" + esc(r.members) + "</td>";\n'
    html += '      h += "<td>" + esc(r.last_meeting || "") + "</td>";\n'
    html += '      h += "<td>" + esc(r.reg_end || "") + "</td>";\n'
    html += '      h += "<td>" + esc(r.status || "") + "</td>";\n'
    html += '      h += "</tr>";\n'
    html += '    }\n'
    html += '    h += "</tbody></table>";\n'
    html += '    wrap.innerHTML = h;\n'
    html += '  }\n'
    html += '  function renderStats(s) {\n'
    html += '    var el = document.getElementById("ic-stats");\n'
    html += '    if (!el || !s) { if (el) el.style.display = "none"; return; }\n'
    html += '    var items = [\n'
    html += '      ["Programs", s.programs], ["Divisions", s.divisions], ["Total Inv", s.involvements],\n'
    html += '      ["Active Inv", s.active], ["Members", s.members], ["Previous", s.previous],\n'
    html += '      ["Visitors", s.visitors], ["Meetings", s.meetings]\n'
    html += '    ];\n'
    html += '    var h = "";\n'
    html += '    for (var i = 0; i < items.length; i++) {\n'
    html += '      h += "<div class=\\"ic-stat\\"><div class=\\"n\\">" + esc(items[i][1]) + "</div>";\n'
    html += '      h += "<div class=\\"l\\">" + esc(items[i][0]) + "</div></div>";\n'
    html += '    }\n'
    html += '    el.innerHTML = h;\n'
    html += '    el.style.display = "flex";\n'
    html += '  }\n'
    html += '  function parseRelated(related, currentDivId) {\n'
    html += '    if (!related) return "";\n'
    html += '    var parts = String(related).split("|");\n'
    html += '    var links = [];\n'
    html += '    for (var i = 0; i < parts.length; i++) {\n'
    html += '      if (!parts[i]) continue;\n'
    html += '      var idx = parts[i].indexOf(":");\n'
    html += '      if (idx < 0) continue;\n'
    html += '      var did = parts[i].substring(0, idx);\n'
    html += '      var dname = parts[i].substring(idx + 1);\n'
    html += '      if (String(did) === String(currentDivId)) continue;\n'
    html += '      links.push("<a href=\\"#\\" data-hl-div=\\"" + esc(did) + "\\">" + esc(dname) + "</a>");\n'
    html += '    }\n'
    html += '    if (!links.length) return "";\n'
    html += '    return "<span class=\\"ic-related\\">Also in: " + links.join(", ") + "</span>";\n'
    html += '  }\n'
    html += '  function toggleChildren(elementId, type) {\n'
    html += '    var element = document.getElementById(elementId);\n'
    html += '    if (!element) return;\n'
    html += '    var icon = element.querySelector(".ic-toggle");\n'
    html += '    var children = document.getElementsByClassName(elementId);\n'
    html += '    var isExpanded = icon && icon.getAttribute("data-open") === "1";\n'
    html += '    if (isExpanded) {\n'
    html += '      if (icon) { icon.innerHTML = "+"; icon.setAttribute("data-open", "0"); }\n'
    html += '      for (var i = 0; i < children.length; i++) {\n'
    html += '        children[i].style.display = "none";\n'
    html += '        if (type === "program") {\n'
    html += '          var divId = children[i].id;\n'
    html += '          var divChildren = document.getElementsByClassName(divId);\n'
    html += '          var divIcon = children[i].querySelector(".ic-toggle");\n'
    html += '          if (divIcon) { divIcon.innerHTML = "+"; divIcon.setAttribute("data-open", "0"); }\n'
    html += '          for (var j = 0; j < divChildren.length; j++) divChildren[j].style.display = "none";\n'
    html += '        }\n'
    html += '      }\n'
    html += '    } else {\n'
    html += '      if (icon) { icon.innerHTML = "-"; icon.setAttribute("data-open", "1"); }\n'
    html += '      for (var k = 0; k < children.length; k++) children[k].style.display = "table-row";\n'
    html += '    }\n'
    html += '  }\n'
    html += '  function highlightDivision(divId) {\n'
    html += '    var divisionElement = document.getElementById("div_" + divId);\n'
    html += '    if (!divisionElement) return false;\n'
    html += '    var classes = divisionElement.className.split(" ");\n'
    html += '    var programClass = null;\n'
    html += '    for (var i = 0; i < classes.length; i++) {\n'
    html += '      if (classes[i].indexOf("prog_") === 0) { programClass = classes[i]; break; }\n'
    html += '    }\n'
    html += '    if (programClass) {\n'
    html += '      var programElement = document.getElementById(programClass);\n'
    html += '      if (programElement) {\n'
    html += '        var programIcon = programElement.querySelector(".ic-toggle");\n'
    html += '        if (programIcon && programIcon.getAttribute("data-open") !== "1") toggleChildren(programClass, "program");\n'
    html += '      }\n'
    html += '    }\n'
    html += '    var divisionIcon = divisionElement.querySelector(".ic-toggle");\n'
    html += '    if (divisionIcon && divisionIcon.getAttribute("data-open") !== "1") toggleChildren("div_" + divId, "division");\n'
    html += '    if (divisionElement.scrollIntoView) divisionElement.scrollIntoView({ behavior: "smooth", block: "center" });\n'
    html += '    divisionElement.classList.add("ic-highlight");\n'
    html += '    setTimeout(function() { divisionElement.classList.remove("ic-highlight"); }, 2000);\n'
    html += '    return false;\n'
    html += '  }\n'
    html += '  function renderTree(rows, summary) {\n'
    html += '    var wrap = document.getElementById("ic-table-wrap");\n'
    html += '    var meta = document.getElementById("ic-list-meta");\n'
    html += '    renderStats(summary);\n'
    html += '    if (!rows || !rows.length) {\n'
    html += '      wrap.innerHTML = "<div class=\\"ic-empty\\">No matching structure rows.</div>";\n'
    html += '      if (meta) meta.textContent = "0 involvements";\n'
    html += '      return;\n'
    html += '    }\n'
    html += '    if (meta) meta.textContent = rows.length + " involvement row(s) in tree";\n'
    html += '    var progTotals = {}, divTotals = {};\n'
    html += '    for (var i = 0; i < rows.length; i++) {\n'
    html += '      var r0 = rows[i];\n'
    html += '      if (!progTotals[r0.prog_id]) progTotals[r0.prog_id] = {m:0,p:0,v:0,mt:0};\n'
    html += '      if (!divTotals[r0.div_id]) divTotals[r0.div_id] = {m:0,p:0,v:0,mt:0};\n'
    html += '      progTotals[r0.prog_id].m += (r0.members||0); progTotals[r0.prog_id].p += (r0.previous||0);\n'
    html += '      progTotals[r0.prog_id].v += (r0.visitors||0); progTotals[r0.prog_id].mt += (r0.meetings||0);\n'
    html += '      divTotals[r0.div_id].m += (r0.members||0); divTotals[r0.div_id].p += (r0.previous||0);\n'
    html += '      divTotals[r0.div_id].v += (r0.visitors||0); divTotals[r0.div_id].mt += (r0.meetings||0);\n'
    html += '    }\n'
    html += '    var h = "<div class=\\"ic-tree-wrap\\"><table class=\\"ic-tree-table\\"><thead><tr>";\n'
    html += '    h += "<th>Name</th><th>Status</th><th>Type</th><th class=\\"num\\">Members</th>";\n'
    html += '    h += "<th class=\\"num\\">Previous</th><th class=\\"num\\">Visitors</th><th class=\\"num\\">Meetings</th>";\n'
    html += '    h += "<th>Related divisions</th><th>Created</th></tr></thead><tbody>";\n'
    html += '    var curProg = null, curDiv = null;\n'
    html += '    for (var x = 0; x < rows.length; x++) {\n'
    html += '      var r = rows[x];\n'
    html += '      if (curProg !== r.prog_id) {\n'
    html += '        curProg = r.prog_id; curDiv = null;\n'
    html += '        var pt = progTotals[r.prog_id] || {m:0,p:0,v:0,mt:0};\n'
    html += '        var pid = "prog_" + r.prog_id;\n'
    html += '        h += "<tr id=\\"" + pid + "\\" class=\\"ic-prog-row\\" data-toggle=\\"" + pid + "\\" data-ttype=\\"program\\">";\n'
    html += '        h += "<td><span class=\\"ic-toggle\\" data-open=\\"0\\">+</span>" + esc(r.program) + "</td>";\n'
    html += '        h += "<td>-</td><td>-</td>";\n'
    html += '        h += "<td class=\\"num\\">" + pt.m + "</td><td class=\\"num\\">" + pt.p + "</td>";\n'
    html += '        h += "<td class=\\"num\\">" + pt.v + "</td><td class=\\"num\\">" + pt.mt + "</td>";\n'
    html += '        h += "<td></td><td></td></tr>";\n'
    html += '      }\n'
    html += '      if (curDiv !== r.div_id) {\n'
    html += '        curDiv = r.div_id;\n'
    html += '        var dt = divTotals[r.div_id] || {m:0,p:0,v:0,mt:0};\n'
    html += '        var did = "div_" + r.div_id;\n'
    html += '        h += "<tr id=\\"" + did + "\\" class=\\"ic-div-row prog_" + r.prog_id + "\\" data-toggle=\\"" + did + "\\" data-ttype=\\"division\\">";\n'
    html += '        h += "<td class=\\"ic-pad-div\\"><span class=\\"ic-toggle\\" data-open=\\"0\\">+</span>" + esc(r.division) + "</td>";\n'
    html += '        h += "<td>-</td><td>-</td>";\n'
    html += '        h += "<td class=\\"num\\">" + dt.m + "</td><td class=\\"num\\">" + dt.p + "</td>";\n'
    html += '        h += "<td class=\\"num\\">" + dt.v + "</td><td class=\\"num\\">" + dt.mt + "</td>";\n'
    html += '        h += "<td></td><td></td></tr>";\n'
    html += '      }\n'
    html += '      var inactive = (r.status === "Inactive") ? " inactive" : "";\n'
    html += '      h += "<tr class=\\"ic-org-row div_" + r.div_id + inactive + "\\">";\n'
    html += '      h += "<td class=\\"ic-pad-org\\"><a href=\\"/Org/" + r.org_id + "\\" target=\\"_blank\\" rel=\\"noopener noreferrer\\">" + esc(r.name) + "</a></td>";\n'
    html += '      h += "<td>" + esc(r.status || "") + "</td>";\n'
    html += '      h += "<td>" + esc(r.org_type || "") + "</td>";\n'
    html += '      h += "<td class=\\"num\\">" + esc(r.members) + "</td>";\n'
    html += '      h += "<td class=\\"num\\">" + esc(r.previous) + "</td>";\n'
    html += '      h += "<td class=\\"num\\">" + esc(r.visitors) + "</td>";\n'
    html += '      h += "<td class=\\"num\\">" + esc(r.meetings) + "</td>";\n'
    html += '      h += "<td>" + parseRelated(r.related_divs, r.div_id) + "</td>";\n'
    html += '      h += "<td>" + esc(r.created || "") + "</td>";\n'
    html += '      h += "</tr>";\n'
    html += '    }\n'
    html += '    h += "</tbody></table></div>";\n'
    html += '    wrap.innerHTML = h;\n'
    html += '    var toggles = wrap.querySelectorAll("[data-toggle]");\n'
    html += '    for (var t = 0; t < toggles.length; t++) {\n'
    html += '      toggles[t].onclick = function() {\n'
    html += '        toggleChildren(this.getAttribute("data-toggle"), this.getAttribute("data-ttype"));\n'
    html += '      };\n'
    html += '    }\n'
    html += '    var links = wrap.querySelectorAll("[data-hl-div]");\n'
    html += '    for (var L = 0; L < links.length; L++) {\n'
    html += '      links[L].onclick = function(e) {\n'
    html += '        if (e && e.preventDefault) e.preventDefault();\n'
    html += '        highlightDivision(this.getAttribute("data-hl-div"));\n'
    html += '        return false;\n'
    html += '      };\n'
    html += '    }\n'
    html += '    var programRows = wrap.querySelectorAll(".ic-prog-row");\n'
    html += '    for (var p = 0; p < programRows.length; p++) {\n'
    html += '      toggleChildren(programRows[p].id, "program");\n'
    html += '    }\n'
    html += '  }\n'
    html += '  function setListStatus(msg) {\n'
    html += '    var meta = document.getElementById("ic-list-meta");\n'
    html += '    if (meta) meta.textContent = msg || "";\n'
    html += '    setResult(msg || "");\n'
    html += '  }\n'
    html += '  function loadList() {\n'
    html += '    if (!window.jQuery) return;\n'
    html += '    var prog = document.getElementById("ic-prog").value || "0";\n'
    html += '    var div = document.getElementById("ic-div").value || "0";\n'
    html += '    var inc = document.getElementById("ic-include-inactive").value || "0";\n'
    html += '    var created = document.getElementById("ic-created-after").value || "";\n'
    html += '    var wrap = document.getElementById("ic-table-wrap");\n'
    html += '    if (wrap) wrap.innerHTML = "<div class=\\"ic-empty\\">Loading...</div>";\n'
    html += '    setListStatus("Loading...");\n'
    html += '    if (currentTab === "structure") {\n'
    html += '      jQuery.ajax({\n'
    html += '        url: scriptUrl, type: "POST", dataType: "text",\n'
    html += '        data: { ajax: "true", action: "get_tree", prog_id: prog, div_id: div, include_inactive: inc, created_after: created }\n'
    html += '      }).done(function(response) {\n'
    html += '        var text = String(response || "").replace(/^\\uFEFF/, "").trim();\n'
    html += '        var data = null;\n'
    html += '        try { data = JSON.parse(text); } catch (e) {\n'
    html += '          setListStatus("Bad tree response (not JSON). Re-upload InvolvementCleanup.py?");\n'
    html += '          if (wrap) wrap.innerHTML = "<div class=\\"ic-empty\\">Could not load structure tree.</div>";\n'
    html += '          return;\n'
    html += '        }\n'
    html += '        if (data.error) {\n'
    html += '          setListStatus("Tree error: " + (data.error || "unknown"));\n'
    html += '          if (wrap) wrap.innerHTML = "<div class=\\"ic-empty\\">" + esc(data.error) + "</div>";\n'
    html += '          return;\n'
    html += '        }\n'
    html += '        try {\n'
    html += '          renderTree(data.rows || [], data.summary || null);\n'
    html += '          setResult("");\n'
    html += '        } catch (err) {\n'
    html += '          setListStatus("Tree render failed: " + err);\n'
    html += '          if (wrap) wrap.innerHTML = "<div class=\\"ic-empty\\">Tree render failed.</div>";\n'
    html += '        }\n'
    html += '      }).fail(function() {\n'
    html += '        setListStatus("Tree load failed");\n'
    html += '        if (wrap) wrap.innerHTML = "<div class=\\"ic-empty\\">Tree load failed.</div>";\n'
    html += '      });\n'
    html += '      return;\n'
    html += '    }\n'
    html += '    document.getElementById("ic-stats").style.display = "none";\n'
    html += '    var queue = currentTab === "manage" ? "manage" : (document.getElementById("ic-queue").value || "dormant");\n'
    html += '    jQuery.ajax({\n'
    html += '      url: scriptUrl, type: "POST", dataType: "text",\n'
    html += '      data: { ajax: "true", action: "get_queue", queue: queue, prog_id: prog, div_id: div, include_inactive: inc }\n'
    html += '    }).done(function(response) {\n'
    html += '      var text = String(response || "").replace(/^\\uFEFF/, "").trim();\n'
    html += '      var data = null;\n'
    html += '      try { data = JSON.parse(text); } catch (e) { setResult("Bad response"); return; }\n'
    html += '      if (data.error) { setResult(esc(data.error)); return; }\n'
    html += '      renderRows(data.rows || []);\n'
    html += '      setResult("");\n'
    html += '    }).fail(function() { setResult("Load failed"); });\n'
    html += '  }\n'
    html += '  function optionList(items) {\n'
    html += '    var h = "";\n'
    html += '    for (var i = 0; i < items.length; i++) {\n'
    html += '      h += "<option value=\\"" + items[i].id + "\\">" + esc(items[i].name) + "</option>";\n'
    html += '    }\n'
    html += '    return h;\n'
    html += '  }\n'
    html += '  function openModal(action) {\n'
    html += '    var ids = selectedIds();\n'
    html += '    if (!ids.length) { alert("Select at least one involvement."); return; }\n'
    html += '    pendingAction = { action: action, ids: ids };\n'
    html += '    var title = document.getElementById("ic-modal-title");\n'
    html += '    var body = document.getElementById("ic-modal-body");\n'
    html += '    var html = "<p>Apply to <strong>" + ids.length + "</strong> involvement(s).</p>";\n'
    html += '    if (action === "mark_inactive") {\n'
    html += '      title.textContent = "Mark inactive";\n'
    html += '      html += "<label><input type=\\"checkbox\\" id=\\"ic-drop-members\\" /> Also drop current members to Previous (keeps history)</label>";\n'
    html += '      html += "<div class=\\"ic-warn\\" id=\\"ic-warn-box\\">Checking warnings...</div>";\n'
    html += '    } else if (action === "set_type") {\n'
    html += '      title.textContent = "Change involvement type";\n'
    html += '      html += "<label>Type</label><br/><select id=\\"ic-modal-type\\">" + optionList(lookups.org_types) + "</select>";\n'
    html += '    } else if (action === "set_category") {\n'
    html += '      title.textContent = "Set mobile category";\n'
    html += '      html += "<label>Mobile category</label><br/><select id=\\"ic-modal-cat\\">" + optionList(lookups.categories) + "</select>";\n'
    html += '    } else if (action === "set_main_division" || action === "add_division" || action === "remove_division") {\n'
    html += '      title.textContent = action === "set_main_division" ? "Set main division" : (action === "add_division" ? "Add related division" : "Remove related division");\n'
    html += '      html += "<label>Division</label><br/><select id=\\"ic-modal-div\\">" + optionList(lookups.divisions) + "</select>";\n'
    html += '      html += "<p class=\\"ic-meta\\">Program follows the selected division. Related = non-main DivOrg links.</p>";\n'
    html += '    } else if (action === "remove_all_related") {\n'
    html += '      title.textContent = "Remove all related divisions";\n'
    html += '      html += "<p>Keeps the <strong>main</strong> division on each involvement and removes every other (related / non-main) division link.</p>";\n'
    html += '      html += "<p class=\\"ic-meta\\">Involvements with no main division set are skipped.</p>";\n'
    html += '    }\n'
    html += '    body.innerHTML = html;\n'
    html += '    document.getElementById("ic-modal").className = "ic-modal-overlay visible";\n'
    html += '    if (action === "mark_inactive") loadWarnings(ids);\n'
    html += '  }\n'
    html += '  function loadWarnings(ids) {\n'
    html += '    jQuery.ajax({\n'
    html += '      url: scriptUrl, type: "POST", dataType: "text",\n'
    html += '      data: { ajax: "true", action: "get_warnings", org_ids: ids.join(",") }\n'
    html += '    }).done(function(response) {\n'
    html += '      var data = null;\n'
    html += '      try { data = JSON.parse(String(response || "").trim()); } catch (e) { return; }\n'
    html += '      var box = document.getElementById("ic-warn-box");\n'
    html += '      if (!box) return;\n'
    html += '      var rows = data.rows || [];\n'
    html += '      var lines = [];\n'
    html += '      for (var i = 0; i < rows.length; i++) {\n'
    html += '        if (rows[i].warnings && rows[i].warnings.length)\n'
    html += '          lines.push(esc(rows[i].name) + ": " + esc(rows[i].warnings.join(", ")));\n'
    html += '      }\n'
    html += '      box.innerHTML = lines.length ? ("Warnings (allowed):<br/>" + lines.join("<br/>")) : "No special warnings.";\n'
    html += '    });\n'
    html += '  }\n'
    html += '  function closeModal() {\n'
    html += '    document.getElementById("ic-modal").className = "ic-modal-overlay";\n'
    html += '    pendingAction = null;\n'
    html += '  }\n'
    html += '  function showActionResults(results) {\n'
    html += '    var ok = 0, fail = 0, msgs = [];\n'
    html += '    for (var i = 0; i < results.length; i++) {\n'
    html += '      if (results[i].ok) ok++; else { fail++; msgs.push(results[i].org_id + ": " + results[i].message); }\n'
    html += '    }\n'
    html += '    setResult("Done. OK=" + ok + (fail ? (", failed=" + fail + " (" + esc(msgs.join("; ")) + ")") : ""));\n'
    html += '    loadList();\n'
    html += '  }\n'
    html += '  function runEach(ids, fnEach, done) {\n'
    html += '    var i = 0, results = [];\n'
    html += '    function next() {\n'
    html += '      if (i >= ids.length) { done(results); return; }\n'
    html += '      var oid = ids[i++];\n'
    html += '      fnEach(oid, function(item) { results.push(item); next(); });\n'
    html += '    }\n'
    html += '    next();\n'
    html += '  }\n'
    html += '  function postOrgField(oid, name, value, okMsg, cb) {\n'
    html += '    jQuery.ajax({\n'
    html += '      url: "/Org/PostData", type: "POST", dataType: "text",\n'
    html += '      data: { pk: oid, name: name, value: String(value) }\n'
    html += '    }).done(function() { cb({ org_id: oid, ok: true, message: okMsg }); })\n'
    html += '     .fail(function(xhr) {\n'
    html += '       cb({ org_id: oid, ok: false, message: "Org/PostData failed (" + (xhr.status || "?") + ")" });\n'
    html += '     });\n'
    html += '  }\n'
    html += '  function confirmModal() {\n'
    html += '    if (!pendingAction || !window.jQuery) return;\n'
    html += '    var a = pendingAction.action;\n'
    html += '    var ids = pendingAction.ids.slice(0);\n'
    html += '    var dropMembers = false;\n'
    html += '    var typeId = "0";\n'
    html += '    var catId = "0";\n'
    html += '    var divId = "0";\n'
    html += '    if (a === "mark_inactive") {\n'
    html += '      var cbDrop = document.getElementById("ic-drop-members");\n'
    html += '      dropMembers = !!(cbDrop && cbDrop.checked);\n'
    html += '    } else if (a === "set_type") {\n'
    html += '      typeId = document.getElementById("ic-modal-type").value;\n'
    html += '    } else if (a === "set_category") {\n'
    html += '      catId = document.getElementById("ic-modal-cat").value;\n'
    html += '    } else if (a === "set_main_division" || a === "add_division" || a === "remove_division") {\n'
    html += '      divId = document.getElementById("ic-modal-div").value;\n'
    html += '      if (!divId || divId === "0") { alert("Select a division."); return; }\n'
    html += '    }\n'
    html += '    setResult("Working...");\n'
    html += '    closeModal();\n'
    html += '    if (a === "mark_inactive") {\n'
    html += '      var markAll = function() {\n'
    html += '        runEach(ids, function(oid, cb) {\n'
    html += '          postOrgField(oid, "status", "40", "Marked inactive", cb);\n'
    html += '        }, showActionResults);\n'
    html += '      };\n'
    html += '      if (!dropMembers) { markAll(); return; }\n'
    html += '      jQuery.ajax({\n'
    html += '        url: scriptUrl, type: "POST", dataType: "text",\n'
    html += '        data: { ajax: "true", action: "drop_members", org_ids: ids.join(","), confirm: "1" }\n'
    html += '      }).done(function(response) {\n'
    html += '        var data2 = null;\n'
    html += '        try { data2 = JSON.parse(String(response || "").trim()); } catch (e) { setResult("Drop failed: bad response"); return; }\n'
    html += '        if (data2.error) { setResult(esc(data2.error)); return; }\n'
    html += '        markAll();\n'
    html += '      }).fail(function() { setResult("Drop members failed"); });\n'
    html += '      return;\n'
    html += '    }\n'
    html += '    if (a === "set_type") {\n'
    html += '      runEach(ids, function(oid, cb) {\n'
    html += '        postOrgField(oid, "type", typeId, "Type updated", cb);\n'
    html += '      }, showActionResults);\n'
    html += '      return;\n'
    html += '    }\n'
    html += '    if (a === "set_category") {\n'
    html += '      runEach(ids, function(oid, cb) {\n'
    html += '        jQuery.ajax({\n'
    html += '          url: "/OrgSearch/Edit", type: "POST", dataType: "text",\n'
    html += '          data: { id: "amc-" + oid, value: String(catId) }\n'
    html += '        }).done(function() { cb({ org_id: oid, ok: true, message: "Mobile category updated" }); })\n'
    html += '         .fail(function(xhr) {\n'
    html += '           cb({ org_id: oid, ok: false, message: "OrgSearch/Edit failed (" + (xhr.status || "?") + ")" });\n'
    html += '         });\n'
    html += '      }, showActionResults);\n'
    html += '      return;\n'
    html += '    }\n'
    html += '    if (a === "set_main_division") {\n'
    html += '      runEach(ids, function(oid, cb) {\n'
    html += '        jQuery.ajax({\n'
    html += '          url: "/OrgSearch/MainDiv", type: "POST", dataType: "text",\n'
    html += '          data: { id: oid, tagdiv: divId }\n'
    html += '        }).done(function(ret) {\n'
    html += '          if (String(ret || "").trim() === "error")\n'
    html += '            cb({ org_id: oid, ok: false, message: "MainDiv error" });\n'
    html += '          else\n'
    html += '            cb({ org_id: oid, ok: true, message: "Main division updated" });\n'
    html += '        }).fail(function(xhr) {\n'
    html += '          cb({ org_id: oid, ok: false, message: "MainDiv failed (" + (xhr.status || "?") + ")" });\n'
    html += '        });\n'
    html += '      }, showActionResults);\n'
    html += '      return;\n'
    html += '    }\n'
    html += '    if (a === "add_division" || a === "remove_division") {\n'
    html += '      jQuery.ajax({\n'
    html += '        url: scriptUrl, type: "POST", dataType: "text",\n'
    html += '        data: { ajax: "true", action: "div_membership", org_ids: ids.join(","), div_id: divId }\n'
    html += '      }).done(function(response) {\n'
    html += '        var data2 = null;\n'
    html += '        try { data2 = JSON.parse(String(response || "").trim()); } catch (e) { setResult("Bad div membership response"); return; }\n'
    html += '        if (data2.error) { setResult(esc(data2.error)); return; }\n'
    html += '        var hasMap = {};\n'
    html += '        var rows = data2.rows || [];\n'
    html += '        for (var r = 0; r < rows.length; r++) hasMap[rows[r].org_id] = !!rows[r].has;\n'
    html += '        runEach(ids, function(oid, cb) {\n'
    html += '          var has = !!hasMap[oid];\n'
    html += '          if (a === "add_division" && has) {\n'
    html += '            cb({ org_id: oid, ok: true, message: "Already has division" });\n'
    html += '            return;\n'
    html += '          }\n'
    html += '          if (a === "remove_division" && !has) {\n'
    html += '            cb({ org_id: oid, ok: true, message: "Not in division" });\n'
    html += '            return;\n'
    html += '          }\n'
    html += '          postToggleTag(oid, divId, function(ok, msg) {\n'
    html += '            cb({ org_id: oid, ok: ok, message: msg || (a === "add_division" ? "Related division added" : "Related division removed") });\n'
    html += '          }, a === "add_division" ? "Related division added" : "Related division removed");\n'
    html += '        }, showActionResults);\n'
    html += '      }).fail(function() { setResult("div_membership failed"); });\n'
    html += '      return;\n'
    html += '    }\n'
    html += '    if (a === "remove_all_related") {\n'
    html += '      jQuery.ajax({\n'
    html += '        url: scriptUrl, type: "POST", dataType: "text",\n'
    html += '        data: { ajax: "true", action: "list_related_divisions", org_ids: ids.join(",") }\n'
    html += '      }).done(function(response) {\n'
    html += '        var data2 = null;\n'
    html += '        try { data2 = JSON.parse(String(response || "").trim()); } catch (e) { setResult("Bad related-divisions response"); return; }\n'
    html += '        if (data2.error) { setResult(esc(data2.error)); return; }\n'
    html += '        var map = {};\n'
    html += '        var rows = data2.rows || [];\n'
    html += '        for (var r = 0; r < rows.length; r++) map[rows[r].org_id] = rows[r];\n'
    html += '        runEach(ids, function(oid, cb) {\n'
    html += '          var info = map[oid] || { main_div_id: 0, related: [] };\n'
    html += '          if (!info.main_div_id) {\n'
    html += '            cb({ org_id: oid, ok: false, message: "No main division set" });\n'
    html += '            return;\n'
    html += '          }\n'
    html += '          var related = info.related || [];\n'
    html += '          if (!related.length) {\n'
    html += '            cb({ org_id: oid, ok: true, message: "No related divisions" });\n'
    html += '            return;\n'
    html += '          }\n'
    html += '          var ri = 0, removed = 0, failMsg = "";\n'
    html += '          function nextRelated() {\n'
    html += '            if (ri >= related.length) {\n'
    html += '              if (failMsg) cb({ org_id: oid, ok: false, message: failMsg });\n'
    html += '              else cb({ org_id: oid, ok: true, message: "Removed " + removed + " related division(s)" });\n'
    html += '              return;\n'
    html += '            }\n'
    html += '            var rid = related[ri++];\n'
    html += '            postToggleTag(oid, rid, function(ok, msg) {\n'
    html += '              if (ok) removed++;\n'
    html += '              else if (!failMsg) failMsg = msg || ("Failed on div " + rid);\n'
    html += '              nextRelated();\n'
    html += '            }, "ok");\n'
    html += '          }\n'
    html += '          nextRelated();\n'
    html += '        }, showActionResults);\n'
    html += '      }).fail(function() { setResult("list_related_divisions failed"); });\n'
    html += '      return;\n'
    html += '    }\n'
    html += '    setResult("Unknown action");\n'
    html += '  }\n'
    html += '  function postToggleTag(oid, tagdiv, cb, okMsg) {\n'
    html += '    jQuery.ajax({\n'
    html += '      url: "/OrgSearch/ToggleTag", type: "POST", dataType: "text",\n'
    html += '      data: { id: oid, tagdiv: tagdiv }\n'
    html += '    }).done(function(ret) {\n'
    html += '      var s = String(ret || "").trim();\n'
    html += '      var parsed = null;\n'
    html += '      if (s.charAt(0) === "{") { try { parsed = JSON.parse(s); } catch (e2) { parsed = null; } }\n'
    html += '      if (parsed && parsed.warning === "lastDivision")\n'
    html += '        cb(false, "Cannot remove last division");\n'
    html += '      else if (parsed && parsed.error)\n'
    html += '        cb(false, String(parsed.error));\n'
    html += '      else if (s === "error")\n'
    html += '        cb(false, "ToggleTag error");\n'
    html += '      else\n'
    html += '        cb(true, okMsg || "ok");\n'
    html += '    }).fail(function(xhr) {\n'
    html += '      cb(false, "ToggleTag failed (" + (xhr.status || "?") + ")");\n'
    html += '    });\n'
    html += '  }\n'
    html += '  function setTab(tab) {\n'
    html += '    currentTab = tab;\n'
    html += '    var tabs = document.querySelectorAll(".ic-tab");\n'
    html += '    for (var i = 0; i < tabs.length; i++) {\n'
    html += '      tabs[i].className = "ic-tab" + (tabs[i].getAttribute("data-tab") === tab ? " active" : "");\n'
    html += '    }\n'
    html += '    var isStructure = tab === "structure";\n'
    html += '    var isCleanup = tab === "cleanup";\n'
    html += '    var isManage = tab === "manage";\n'
    html += '    document.getElementById("ic-queue-wrap").style.display = isCleanup ? "inline-block" : "none";\n'
    html += '    document.getElementById("ic-created-wrap").style.display = isStructure ? "inline-block" : "none";\n'
    html += '    document.getElementById("ic-inactive-wrap").style.display = (isStructure || isManage) ? "inline-block" : "none";\n'
    html += '    document.getElementById("ic-actions-card").style.display = (isCleanup || isManage) ? "block" : "none";\n'
    html += '    if (!isStructure) document.getElementById("ic-stats").style.display = "none";\n'
    html += '    var title = "Structure";\n'
    html += '    var meta = "Expand programs and divisions to browse involvements.";\n'
    html += '    if (isCleanup) { title = "Clean Up"; meta = "Pick a queue, then select rows for actions."; }\n'
    html += '    if (isManage) { title = "Manage"; meta = "Browse all involvements and take bulk actions."; }\n'
    html += '    document.getElementById("ic-list-title").textContent = title;\n'
    html += '    document.getElementById("ic-list-meta").textContent = meta;\n'
    html += '    loadList();\n'
    html += '  }\n'
    html += '  function init() {\n'
    html += '    document.getElementById("ic-load").onclick = function() { loadList(); };\n'
    html += '    document.getElementById("ic-prog").onchange = function() { refreshDivOptions(); };\n'
    html += '    document.getElementById("ic-select-all").onclick = function() {\n'
    html += '      var boxes = document.querySelectorAll(".ic-cb");\n'
    html += '      for (var i = 0; i < boxes.length; i++) boxes[i].checked = true;\n'
    html += '    };\n'
    html += '    document.getElementById("ic-clear").onclick = function() {\n'
    html += '      var boxes = document.querySelectorAll(".ic-cb");\n'
    html += '      for (var i = 0; i < boxes.length; i++) boxes[i].checked = false;\n'
    html += '    };\n'
    html += '    document.getElementById("ic-modal-cancel").onclick = closeModal;\n'
    html += '    document.getElementById("ic-modal-ok").onclick = confirmModal;\n'
    html += '    var tabs = document.querySelectorAll(".ic-tab");\n'
    html += '    for (var t = 0; t < tabs.length; t++) {\n'
    html += '      tabs[t].onclick = function(e) {\n'
    html += '        if (e && e.preventDefault) e.preventDefault();\n'
    html += '        setTab(this.getAttribute("data-tab"));\n'
    html += '        return false;\n'
    html += '      };\n'
    html += '    }\n'
    html += '    var btns = document.querySelectorAll("[data-action]");\n'
    html += '    for (var b = 0; b < btns.length; b++) {\n'
    html += '      btns[b].onclick = function() { openModal(this.getAttribute("data-action")); };\n'
    html += '    }\n'
    html += '    refreshDivOptions();\n'
    html += '    setTab("structure");\n'
    html += '  }\n'
    html += '  if (window.jQuery) init();\n'
    html += '  else window.addEventListener("load", function() { if (window.jQuery) init(); });\n'
    html += '})();\n'
    html += '</script>\n'
    return html

def _error_page(ex):
    html = '<style>' + _css() + '</style><div class="ic-root">'
    html += '<div class="dashboard-header"><h1>Involvement Cleanup</h1>'
    html += '<p class="header-sub">Error loading tool.</p></div>'
    html += '<div class="ic-card"><pre style="white-space:pre-wrap;font-size:12px">'
    html += _html(traceback.format_exc()) + '</pre></div></div>'
    return html


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

model.Header = 'Involvement Cleanup'
is_ajax = _form_val('ajax') == 'true'

if is_ajax:
    action = _form_val('action')
    try:
        if action == 'get_queue':
            rows = _run_queue(
                _form_val('queue', 'dormant'),
                _i(_form_val('prog_id'), 0),
                _i(_form_val('div_id'), 0),
                _b(_form_val('include_inactive')),
            )
            _json_out({'rows': rows, 'count': len(rows)})
        elif action == 'get_tree':
            prog = _i(_form_val('prog_id'), 0)
            div = _i(_form_val('div_id'), 0)
            inc = _b(_form_val('include_inactive'))
            created = _form_val('created_after', '')
            rows = _run_tree(prog, div, inc, created)
            summary = _summary_from_tree_rows(rows)
            _json_out({'rows': rows, 'count': len(rows), 'summary': summary})
        elif action == 'get_warnings':
            _json_out({'rows': _org_warnings(_parse_org_ids())})
        elif action == 'drop_members':
            if _form_val('confirm') != '1':
                _json_out({'error': 'Confirmation required'})
            else:
                _json_out({'results': _action_drop_members(_parse_org_ids())})
        elif action == 'div_membership':
            _json_out({
                'rows': _div_membership(_parse_org_ids(), _i(_form_val('div_id')))
            })
        elif action == 'list_related_divisions':
            _json_out({'rows': _related_divisions(_parse_org_ids())})
        else:
            _json_out({'error': 'Unknown action'})
    except Exception, e:
        _err_out(e)
else:
    try:
        model.Form = _page()
    except Exception, ex:
        model.Form = _error_page(ex)
