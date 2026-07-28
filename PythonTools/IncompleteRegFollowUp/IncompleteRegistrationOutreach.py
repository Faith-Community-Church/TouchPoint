#Roles=Admin,ManageRegistrations
# Script: IncompleteRegistrationOutreach.py
# Purpose: List incomplete registration attempts for people who are not active
#   members of the involvement and have no later successful registration for
#   that same involvement. Defaults to the past 30 days; filters refine results.
#   Email selected people via an Email Template whose Title starts with IncompleteReg.
# Author: Jake Pierson
# Date: 2026-07-09
#
# Install: Special Content -> Python Scripts -> name IncompleteRegistrationOutreach
# Run: /PyScriptForm/IncompleteRegistrationOutreach
#
# IronPython notes (TouchPoint embeds IronPython 2.7):
#   - Use print without parentheses; except Exception, ex
#   - Put UI in model.Form on GET (PyScriptForm ignores Output)
#   - Prefer model.DynamicData() for SQL params (not bare dict / **kwargs)
#   - Prefer token replace over .format() for large HTML (braces in names break format)
#   - People DOB column is BDate; RegPeople uses BirthDate

FROM_ADDR = 'jpierson@fcchudson.com'
FROM_NAME_DEFAULT = 'Jake Pierson'
TEMPLATE_TITLE_PREFIX = 'IncompleteReg'
DEFAULT_LOOKBACK_DAYS = 30
SCRIPT_PATH = '/PyScriptForm/IncompleteRegistrationOutreach'

MEMBER_TYPE_INACTIVE = 230
MEMBER_TYPE_PROSPECT = 311


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


def _dt(val, default=None):
    s = _s(val)
    if not s:
        return default
    try:
        from System import DateTime
        return DateTime.Parse(s).Date
    except:
        return default


def _html(val):
    s = _s(val)
    s = s.replace('&', '&amp;')
    s = s.replace('<', '&lt;')
    s = s.replace('>', '&gt;')
    s = s.replace('"', '&quot;')
    return s


def _get(name, default=''):
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


def _default_dates():
    from System import DateTime
    end = DateTime.Today
    start = end.AddDays(-DEFAULT_LOOKBACK_DAYS)
    return start, end


def _from_name():
    sql = """
SELECT TOP 1 Name
FROM dbo.People
WHERE EmailAddress = @email OR EmailAddress2 = @email
ORDER BY PeopleId
"""
    p = _dd()
    p.AddValue('email', FROM_ADDR)
    rows = q.QuerySql(sql, p)
    for row in rows:
        if not _is_null(row.Name):
            return _s(row.Name, FROM_NAME_DEFAULT)
    return FROM_NAME_DEFAULT


def _email_templates():
    # TypeID: 0=HTML, 2=EmailTemplate, 7=UnlayerTemplate
    # Match Title OR Name so either field can carry the IncompleteReg convention.
    sql = """
SELECT c.Name, c.Title, c.TypeID
FROM dbo.Content c
WHERE c.TypeID IN (0, 2, 7)
  AND (
        LTRIM(RTRIM(ISNULL(c.Title, ''))) LIKE @prefix + '%'
        OR LTRIM(RTRIM(ISNULL(c.Name, ''))) LIKE @prefix + '%'
        OR LTRIM(RTRIM(ISNULL(c.Title, ''))) LIKE '%' + @prefix + '%'
        OR LTRIM(RTRIM(ISNULL(c.Name, ''))) LIKE '%' + @prefix + '%'
      )
ORDER BY ISNULL(c.Title, c.Name)
"""
    p = _dd()
    p.AddValue('prefix', TEMPLATE_TITLE_PREFIX)
    return list(q.QuerySql(sql, p))


def _search_params():
    start_default, end_default = _default_dates()
    start = _dt(_form_val('StartDate'), start_default)
    end = _dt(_form_val('EndDate'), end_default)
    return {
        'OrgId': _i(_form_val('OrgId')),
        'OrgName': _form_val('OrgName'),
        'LastName': _form_val('LastName'),
        'FirstName': _form_val('FirstName'),
        'PeopleId': _i(_form_val('PeopleId')),
        'StartDate': start,
        'EndDate': end,
    }


def _sql_params(sp):
    p = _dd()
    p.AddValue('StartDate', sp['StartDate'].ToString('yyyy-MM-dd'))
    p.AddValue('EndDate', sp['EndDate'].ToString('yyyy-MM-dd'))
    p.AddValue('OrgName', sp['OrgName'] or '')
    p.AddValue('LastName', sp['LastName'] or '')
    p.AddValue('FirstName', sp['FirstName'] or '')
    p.AddValue('OrgId', str(sp['OrgId']) if sp['OrgId'] else '0')
    p.AddValue('PeopleId', str(sp['PeopleId']) if sp['PeopleId'] else '0')
    p.AddValue('HasOrgId', '1' if sp['OrgId'] else '0')
    p.AddValue('HasPeopleId', '1' if sp['PeopleId'] else '0')
    p.AddValue('HasOrgName', '1' if sp['OrgName'] else '0')
    p.AddValue('HasLastName', '1' if sp['LastName'] else '0')
    p.AddValue('HasFirstName', '1' if sp['FirstName'] else '0')
    p.AddValue('InactiveType', str(MEMBER_TYPE_INACTIVE))
    p.AddValue('ProspectType', str(MEMBER_TYPE_PROSPECT))
    return p


def _run_search(sp):
    sql = """
;WITH raw AS (
    SELECT
        r.Id AS DatumId,
        CAST(NULL AS uniqueidentifier) AS RegistrationId,
        r.Stamp AS AttemptDate,
        r.OrganizationId,
        r.OrganizationName,
        r.UserPeopleId,
        r.Name AS UserName,
        v.Slot,
        v.PeopleId AS ListedPeopleId,
        CASE WHEN v.Slot = 1 THEN r.first ELSE NULL END AS FirstName,
        CASE WHEN v.Slot = 1 THEN r.last ELSE NULL END AS LastName,
        CASE WHEN v.Slot = 1 THEN r.dob ELSE NULL END AS DobText
    FROM dbo.RegistrationList r
    CROSS APPLY (VALUES
        (1, r.PeopleId1),
        (2, r.PeopleId2),
        (3, r.PeopleId3),
        (4, r.PeopleId4)
    ) v(Slot, PeopleId)
    WHERE r.Id IS NOT NULL
      AND ISNULL(r.completed, 0) = 0
      AND r.OrganizationId IS NOT NULL
      AND r.Stamp >= CAST(@StartDate AS datetime)
      AND r.Stamp < DATEADD(day, 1, CAST(@EndDate AS datetime))
      AND (
            v.PeopleId IS NOT NULL
            OR (v.Slot = 1 AND (r.first IS NOT NULL OR r.last IS NOT NULL))
          )
      AND (@HasOrgId = '0' OR r.OrganizationId = CAST(@OrgId AS int))
      AND (@HasOrgName = '0' OR r.OrganizationName LIKE '%' + @OrgName + '%')

    UNION ALL

    SELECT
        CAST(NULL AS int) AS DatumId,
        r.RegistrationId,
        r.CreatedDate AS AttemptDate,
        r.OrganizationId,
        o.OrganizationName,
        r.PeopleId AS UserPeopleId,
        pu.Name AS UserName,
        1 AS Slot,
        p.PeopleId AS ListedPeopleId,
        p.FirstName,
        p.LastName,
        CONVERT(varchar(50), p.BirthDate) AS DobText
    FROM dbo.Registration r
    JOIN dbo.RegPeople p ON p.RegistrationId = r.RegistrationId
    LEFT JOIN dbo.Organizations o ON o.OrganizationId = r.OrganizationId
    LEFT JOIN dbo.People pu ON pu.PeopleId = r.PeopleId
    WHERE p.CompletedDate IS NULL
      AND r.OrganizationId IS NOT NULL
      AND r.CreatedDate >= CAST(@StartDate AS datetime)
      AND r.CreatedDate < DATEADD(day, 1, CAST(@EndDate AS datetime))
      AND (@HasOrgId = '0' OR r.OrganizationId = CAST(@OrgId AS int))
      AND (@HasOrgName = '0' OR o.OrganizationName LIKE '%' + @OrgName + '%')
),
resolved AS (
    SELECT
        raw.DatumId,
        raw.RegistrationId,
        raw.AttemptDate,
        raw.OrganizationId,
        raw.OrganizationName,
        raw.UserPeopleId,
        raw.UserName,
        raw.FirstName,
        raw.LastName,
        raw.DobText,
        COALESCE(
            raw.ListedPeopleId,
            (
                SELECT TOP 1 pe.PeopleId
                FROM dbo.People pe
                WHERE raw.FirstName IS NOT NULL
                  AND raw.LastName IS NOT NULL
                  AND raw.DobText IS NOT NULL
                  AND LTRIM(RTRIM(raw.DobText)) <> ''
                  AND TRY_CONVERT(date, raw.DobText) IS NOT NULL
                  AND pe.FirstName = raw.FirstName
                  AND pe.LastName = raw.LastName
                  AND pe.BDate = TRY_CONVERT(date, raw.DobText)
                ORDER BY pe.PeopleId
            )
        ) AS PeopleId
    FROM raw
),
named AS (
    SELECT
        r.DatumId,
        r.RegistrationId,
        r.AttemptDate,
        r.OrganizationId,
        r.OrganizationName,
        r.UserPeopleId,
        r.UserName,
        r.PeopleId,
        COALESCE(p.Name2, p.Name,
            NULLIF(LTRIM(RTRIM(ISNULL(r.FirstName, '') + ' ' + ISNULL(r.LastName, ''))), ''),
            '(unknown)') AS RegistrantName,
        COALESCE(p.LastName, r.LastName) AS MatchLastName,
        COALESCE(p.FirstName, r.FirstName) AS MatchFirstName
    FROM resolved r
    LEFT JOIN dbo.People p ON p.PeopleId = r.PeopleId
)
SELECT
    n.DatumId,
    n.RegistrationId,
    n.AttemptDate,
    n.OrganizationId,
    n.OrganizationName,
    n.UserPeopleId,
    n.UserName,
    n.PeopleId,
    n.RegistrantName,
    n.MatchLastName,
    n.MatchFirstName
FROM named n
WHERE (@HasLastName = '0' OR n.MatchLastName LIKE @LastName + '%')
  AND (@HasFirstName = '0' OR n.MatchFirstName LIKE @FirstName + '%')
  AND (@HasPeopleId = '0' OR n.PeopleId = CAST(@PeopleId AS int))
  AND (
        n.PeopleId IS NULL
        OR NOT EXISTS (
            SELECT 1
            FROM dbo.OrganizationMembers om
            WHERE om.PeopleId = n.PeopleId
              AND om.OrganizationId = n.OrganizationId
              AND ISNULL(om.Pending, 0) = 0
              AND om.InactiveDate IS NULL
              AND om.MemberTypeId NOT IN (
                    CAST(@InactiveType AS int),
                    CAST(@ProspectType AS int)
                  )
        )
      )
  AND (
        n.PeopleId IS NULL
        OR NOT EXISTS (
            SELECT 1
            FROM dbo.RegistrationList c
            WHERE c.OrganizationId = n.OrganizationId
              AND ISNULL(c.completed, 0) = 1
              AND c.Stamp IS NOT NULL
              AND c.Stamp > n.AttemptDate
              AND (
                    c.PeopleId1 = n.PeopleId
                    OR c.PeopleId2 = n.PeopleId
                    OR c.PeopleId3 = n.PeopleId
                    OR c.PeopleId4 = n.PeopleId
                  )
        )
      )
ORDER BY n.AttemptDate DESC, n.OrganizationName, n.RegistrantName
"""
    rows = list(q.QuerySql(sql, _sql_params(sp)))
    emailed_lookup = _last_emailed_lookup(rows)
    return rows, emailed_lookup


def _last_emailed_lookup(rows):
    """
    Map 'recipientPid~orgId' -> last emailed datetime for IncompleteReg outreach.
    Matched by Subject containing IncompleteReg and EmailQueueTo.OrgId
    (stamped at send time via model.CurrentOrgId).
    """
    lookup = {}
    if (not rows) or (len(rows) == 0):
        return lookup

    recip_ids = {}
    org_ids = {}
    for row in rows:
        recip, kind = _recipient_for_row(row)
        if recip is not None:
            recip_ids[_s(recip)] = 1
        if not _is_null(row.OrganizationId):
            org_ids[_s(row.OrganizationId)] = 1

    if len(recip_ids) == 0 or len(org_ids) == 0:
        return lookup

    recip_csv = ','.join(recip_ids.keys())
    org_csv = ','.join(org_ids.keys())

    # Primary: OrgId stamped on EmailQueueTo when we set model.CurrentOrgId before send
    sql = """
SELECT
    eqt.PeopleId AS RecipientPeopleId,
    eqt.OrgId AS OrganizationId,
    MAX(ISNULL(eqt.Sent, ISNULL(eq.Sent, eq.Queued))) AS LastEmailed
FROM dbo.EmailQueue eq
JOIN dbo.EmailQueueTo eqt ON eqt.Id = eq.Id
WHERE eqt.PeopleId IN ({recips})
  AND eqt.OrgId IN ({orgs})
  AND (
        ISNULL(eq.Subject, '') LIKE '%' + @prefix + '%'
        OR ISNULL(eq.FromAddr, '') = @fromaddr
      )
GROUP BY eqt.PeopleId, eqt.OrgId
""".format(orgs=org_csv, recips=recip_csv)

    p = _dd()
    p.AddValue('prefix', TEMPLATE_TITLE_PREFIX)
    p.AddValue('fromaddr', FROM_ADDR)
    emailed = list(q.QuerySql(sql, p))

    for e in emailed:
        if _is_null(e.OrganizationId):
            continue
        key = _s(e.RecipientPeopleId) + '~' + _s(e.OrganizationId)
        lookup[key] = e.LastEmailed

    # Fallback for older sends (before OrgId stamping): subject match + body has org id
    # after Handlebars merge, or literal InvolvementId value in body.
    sql2 = """
SELECT
    eqt.PeopleId AS RecipientPeopleId,
    o.OrganizationId,
    MAX(ISNULL(eqt.Sent, ISNULL(eq.Sent, eq.Queued))) AS LastEmailed
FROM dbo.EmailQueue eq
JOIN dbo.EmailQueueTo eqt ON eqt.Id = eq.Id
JOIN dbo.Organizations o ON o.OrganizationId IN ({orgs})
WHERE eqt.PeopleId IN ({recips})
  AND ISNULL(eqt.OrgId, 0) = 0
  AND ISNULL(eq.Subject, '') LIKE '%' + @prefix + '%'
  AND (
        eq.Body LIKE '%/OnlineReg/' + CAST(o.OrganizationId AS varchar(20)) + '%'
        OR eq.Body LIKE '%' + CAST(o.OrganizationId AS varchar(20)) + '%'
      )
GROUP BY eqt.PeopleId, o.OrganizationId
""".format(orgs=org_csv, recips=recip_csv)

    emailed2 = list(q.QuerySql(sql2, p))
    for e in emailed2:
        key = _s(e.RecipientPeopleId) + '~' + _s(e.OrganizationId)
        if key not in lookup:
            lookup[key] = e.LastEmailed

    return lookup


def _detail_url(row):
    if not _is_null(row.DatumId):
        return '/OnlineReg/RegPeople/' + _s(row.DatumId)
    if not _is_null(row.RegistrationId):
        return '/OnlineReg/Registration/' + _s(row.RegistrationId)
    return '#'


def _fmt_dt(val):
    if _is_null(val):
        return ''
    try:
        return _s(val.ToString('M/d/yyyy h:mm tt'))
    except:
        return _html(val)


def _sort_dt_key(val):
    """ISO-ish key for client-side date sorting."""
    if _is_null(val):
        return ''
    try:
        return _s(val.ToString('yyyy-MM-dd HH:mm:ss'))
    except:
        return ''


def _td(content, sort_key=None, align=None):
    attrs = ''
    if sort_key is not None:
        attrs += ' data-sort="' + _html(sort_key) + '"'
    if align:
        attrs += ' style="text-align:' + align + '"'
    return '<td' + attrs + '>' + content + '</td>'


def _sortable_th(label, col_index, sort_type='text', align=None):
    style = 'cursor:pointer;user-select:none;white-space:nowrap;'
    if align:
        style += 'text-align:' + align + ';'
    return ('<th class="tps-sort" data-col="' + str(col_index) + '" data-type="' + sort_type + '" '
            'style="' + style + '" title="Click to sort">' + label + ' <span class="tps-sort-ind"></span></th>')


def _sortable_table_assets(table_id):
    """CSS + JS for clickable column sorting (client-side)."""
    css = (
        '.tps-sort{color:#337ab7;}'
        '.tps-sort:hover{text-decoration:underline;}'
        '.tps-sort-ind{font-size:10px;color:#999;}'
    )
    js = (
        'function tpsSortTable(tableId, colIndex, type, th) {\n'
        '  var table = document.getElementById(tableId);\n'
        '  if (!table) return;\n'
        '  var tbody = table.tBodies[0];\n'
        '  if (!tbody) return;\n'
        '  var rows = Array.prototype.slice.call(tbody.rows);\n'
        '  var asc = !(th.getAttribute("data-asc") === "1");\n'
        '  var headers = table.tHead ? table.tHead.rows[0].cells : [];\n'
        '  for (var h = 0; h < headers.length; h++) {\n'
        '    headers[h].removeAttribute("data-asc");\n'
        '    var ind = headers[h].querySelector(".tps-sort-ind");\n'
        '    if (ind) ind.textContent = "";\n'
        '  }\n'
        '  th.setAttribute("data-asc", asc ? "1" : "0");\n'
        '  var ind2 = th.querySelector(".tps-sort-ind");\n'
        '  if (ind2) ind2.textContent = asc ? "▲" : "▼";\n'
        '  rows.sort(function(a, b) {\n'
        '    var ca = a.cells[colIndex], cb = b.cells[colIndex];\n'
        '    var va = ca ? (ca.getAttribute("data-sort") || ca.textContent || "") : "";\n'
        '    var vb = cb ? (cb.getAttribute("data-sort") || cb.textContent || "") : "";\n'
        '    va = ("" + va).replace(/^\\s+|\\s+$/g, "").toLowerCase();\n'
        '    vb = ("" + vb).replace(/^\\s+|\\s+$/g, "").toLowerCase();\n'
        '    var emptyA = (!va || va === "never" || va === "—" || va === "-");\n'
        '    var emptyB = (!vb || vb === "never" || vb === "—" || vb === "-");\n'
        '    if (emptyA && emptyB) return 0;\n'
        '    if (emptyA) return       '    if (emptyB) return -1;\n'
        '    var cmp = 0;\n'
        '    if (type === "num") {\n'
        '      cmp = (parseFloat(va) || 0) - (parseFloat(vb) || 0);\n'
        '    } else {\n'
        '      if (va < vb) cmp = -1; else if (va > vb) cmp = 1;\n'
        '    }\n'
        '    return asc ? cmp : -cmp;\n'
        '  });\n'
        '  for (var i = 0; i < rows.length; i++) tbody.appendChild(rows[i]);\n'
        '}\n'
        'function tpsBindSort(tableId) {\n'
        '  var table = document.getElementById(tableId);\n'
        '  if (!table || !table.tHead) return;\n'
        '  var headers = table.tHead.rows[0].cells;\n'
        '  for (var i = 0; i < headers.length; i++) {\n'
        '    (function(th) {\n'
        '      if (!th.className || th.className.indexOf("tps-sort") < 0) return;\n'
        '      th.onclick = function() {\n'
        '        tpsSortTable(tableId, parseInt(th.getAttribute("data-col"), 10),\n'
        '                     th.getAttribute("data-type") || "text", th);\n'
        '      };\n'
        '    })(headers[i]);\n'
        '  }\n'
        '}\n'
        'tpsBindSort("' + table_id + '");\n'
    )
    return css, js


def _url_encode(s):
    from System import Uri
    return Uri.EscapeDataString(_s(s))


def _qs(sp, extra_msg=None):
    parts = []
    parts.append('StartDate=' + _url_encode(sp['StartDate'].ToString('yyyy-MM-dd')))
    parts.append('EndDate=' + _url_encode(sp['EndDate'].ToString('yyyy-MM-dd')))
    if sp['OrgId']:
        parts.append('OrgId=' + str(sp['OrgId']))
    if sp['OrgName']:
        parts.append('OrgName=' + _url_encode(sp['OrgName']))
    if sp['LastName']:
        parts.append('LastName=' + _url_encode(sp['LastName']))
    if sp['FirstName']:
        parts.append('FirstName=' + _url_encode(sp['FirstName']))
    if sp['PeopleId']:
        parts.append('PeopleId=' + str(sp['PeopleId']))
    if extra_msg:
        parts.append('msg=' + _url_encode(extra_msg))
    return '&'.join(parts)


def _hidden_filters(sp):
    html = ''
    html += '<input type="hidden" name="OrgId" value="' + _html(sp['OrgId'] or '') + '" />'
    html += '<input type="hidden" name="OrgName" value="' + _html(sp['OrgName']) + '" />'
    html += '<input type="hidden" name="LastName" value="' + _html(sp['LastName']) + '" />'
    html += '<input type="hidden" name="FirstName" value="' + _html(sp['FirstName']) + '" />'
    html += '<input type="hidden" name="PeopleId" value="' + _html(sp['PeopleId'] or '') + '" />'
    html += '<input type="hidden" name="StartDate" value="' + _html(sp['StartDate'].ToString('yyyy-MM-dd')) + '" />'
    html += '<input type="hidden" name="EndDate" value="' + _html(sp['EndDate'].ToString('yyyy-MM-dd')) + '" />'
    return html


def _options_html(templates, selected):
    parts = []
    parts.append('<option value="">-- select template --</option>')
    for t in templates:
        name = _s(t.Name)
        title = _s(t.Title)
        if not title:
            title = name
        sel = ''
        if name == selected:
            sel = ' selected'
        parts.append('<option value="' + _html(name) + '"' + sel + '>' + _html(title) + '</option>')
    return '\n'.join(parts)


def _recipient_for_row(row):
    """
    Option C: prefer the user who started the registration (often a parent),
    otherwise the registrant.
    Returns (recipientPeopleId, recipientLabel) or (None, reason).
    """
    if not _is_null(row.UserPeopleId):
        return row.UserPeopleId, 'starter'
    if not _is_null(row.PeopleId):
        return row.PeopleId, 'registrant'
    return None, 'none'


def _register_url(org_id):
    return _s(model.CmsHost).rstrip('/') + '/OnlineReg/' + _s(org_id)


def _row_token(row):
    """
    Encode enough context for email send in the checkbox value.
    Format: recipientPid~orgId~registrantPid~registrantName~orgName~kind
    Uses ~ so ASP.NET comma-joining of multi-checkboxes stays safe.
    """
    recip, kind = _recipient_for_row(row)
    if recip is None:
        return None
    reg_pid = '' if _is_null(row.PeopleId) else _s(row.PeopleId)
    reg_name = _s(row.RegistrantName).replace('~', ' ').replace(',', ' ')
    org_name = _s(row.OrganizationName).replace('~', ' ').replace(',', ' ')
    return '~'.join([
        _s(recip),
        _s(row.OrganizationId),
        reg_pid,
        reg_name,
        org_name,
        kind,
    ])


def _parse_row_token(token):
    parts = _s(token).split('~')
    if len(parts) < 6:
        return None
    return {
        'RecipientPeopleId': _i(parts[0]),
        'OrganizationId': _i(parts[1]),
        'RegistrantPeopleId': _i(parts[2]),
        'RegistrantName': parts[3],
        'OrganizationName': parts[4],
        'RecipientKind': parts[5],
    }


def _selected_row_tokens():
    raw = _get('rowtokens', None)
    if raw is None:
        return []
    raw = _s(raw)
    if not raw:
        return []
    tokens = []
    for part in raw.split(','):
        t = _s(part)
        if t and ('~' in t):
            tokens.append(t)
    return tokens


def _registrant_first(name):
    n = _s(name)
    if not n:
        return ''
    return _s(n.split(' ')[0])


def _rows_html(rows, emailed_lookup):
    if (not rows) or (len(rows) == 0):
        return '<tr><td colspan="9"><em>No matching incomplete registrations.</em></td></tr>'
    parts = []
    for row in rows:
        token = _row_token(row)
        recip, kind = _recipient_for_row(row)

        if token is not None:
            cb = '<input type="checkbox" name="rowtokens" value="' + _html(token) + '" class="pid-cb" />'
        else:
            cb = '<input type="checkbox" disabled title="No email recipient PeopleId" />'

        if not _is_null(row.PeopleId):
            registrant = '<a href="/Person2/' + _s(row.PeopleId) + '" target="_blank">' + _html(row.RegistrantName) + '</a>'
        else:
            registrant = _html(row.RegistrantName) + ' <span class="text-muted">(no PeopleId)</span>'

        if _is_null(row.UserName):
            user = '<em>anonymous</em>'
        else:
            user = _html(row.UserName)
            if not _is_null(row.UserPeopleId):
                user = '<a href="/Person2/' + _s(row.UserPeopleId) + '" target="_blank">' + user + '</a>'

        if kind == 'starter':
            email_to = 'Starter/parent'
        elif kind == 'registrant':
            email_to = 'Registrant'
        else:
            email_to = '<span class="text-muted">n/a</span>'

        org = '<a href="/Org/' + _s(row.OrganizationId) + '" target="_blank">' + _html(row.OrganizationName) + '</a>'
        attempt = '<a href="' + _detail_url(row) + '" target="_blank">' + _html(_fmt_dt(row.AttemptDate)) + '</a>'

        last_html = '<span class="text-muted">Never</span>'
        last_key = ''
        if recip is not None and (not _is_null(row.OrganizationId)):
            key = _s(recip) + '~' + _s(row.OrganizationId)
            if key in emailed_lookup and (not _is_null(emailed_lookup[key])):
                last_html = _html(_fmt_dt(emailed_lookup[key]))
                last_key = _sort_dt_key(emailed_lookup[key])

        user_sort = _s(row.UserName) if not _is_null(row.UserName) else 'zzz-anonymous'
        email_sort = 'starter' if kind == 'starter' else ('registrant' if kind == 'registrant' else 'zzz')

        row_html = '<tr>'
        row_html += '<td>' + cb + '</td>'
        row_html += _td(attempt, _sort_dt_key(row.AttemptDate))
        # Sort Registrant by last name, then first (not display "First Last").
        name_sort = (_s(row.MatchLastName) + ', ' + _s(row.MatchFirstName)).strip(', ')
        if not name_sort:
            name_sort = _s(row.RegistrantName)
        row_html += _td(registrant, name_sort)
        row_html += _td(user, user_sort)
        row_html += _td(email_to, email_sort)
        row_html += _td(org, _s(row.OrganizationName))
        row_html += _td(_s(row.OrganizationId), _s(row.OrganizationId), None)
        row_html += _td(last_html, last_key)
        row_html += _td('Incomplete', 'Incomplete')
        row_html += '</tr>'
        parts.append(row_html)
    return ''.join(parts)


def _confirm_page(sp, tokens, template_name, templates):
    title = template_name
    for t in templates:
        if _s(t.Name) == template_name:
            title = _s(t.Title) or template_name
            break
    html = '<div style="max-width:640px;margin:40px auto;font-family:sans-serif">'
    html += '<h2>Confirm email</h2>'
    html += '<p>Send <strong>' + str(len(tokens)) + '</strong> email(s) using template '
    html += '<strong>' + _html(title) + '</strong> from <strong>' + _html(FROM_ADDR) + '</strong>?</p>'
    html += '<p style="color:#666;font-size:13px">Each selected row emails the registration starter/parent when known, '
    html += 'otherwise the registrant. Use Handlebars fields in the template (see notes on the report page).</p>'
    html += '<form method="post" action="' + SCRIPT_PATH + '" style="display:inline">'
    html += _hidden_filters(sp)
    html += '<input type="hidden" name="action" value="email" />'
    html += '<input type="hidden" name="confirm" value="1" />'
    html += '<input type="hidden" name="TemplateName" value="' + _html(template_name) + '" />'
    for tok in tokens:
        html += '<input type="hidden" name="rowtokens" value="' + _html(tok) + '" />'
    html += '<button type="submit" class="btn btn-primary">Yes, send email</button>'
    html += '</form> '
    html += '<a href="' + SCRIPT_PATH + '?' + _qs(sp) + '">Cancel</a>'
    html += '</div>'
    return html


def _page(sp, rows, templates, message, emailed_lookup):
    selected_template = _form_val('TemplateName', '')
    msg_html = ''
    if message:
        msg_html = '<div class="alert alert-info">' + message + '</div>'

    if emailed_lookup is None:
        emailed_lookup = {}

    sort_css, sort_js = _sortable_table_assets('iro-table')

    html = ''
    html += '<style>'
    html += '.iro-wrap{max-width:1200px;}'
    html += '.iro-wrap .filters .form-group{margin-right:12px;margin-bottom:10px;display:inline-block;vertical-align:top;}'
    html += '.iro-wrap table{margin-top:12px;}'
    html += '.iro-wrap .text-muted{color:#888;font-size:12px;}'
    html += '.iro-actions{margin:12px 0;padding:12px;background:#f7f7f7;border:1px solid #ddd;}'
    html += sort_css
    html += '</style>'
    html += '<div class="iro-wrap">'
    html += '<p>Incomplete registration attempts where the person is <strong>not</strong> an active '
    html += 'member of the involvement and has <strong>no later successful</strong> registration '
    html += 'for that involvement. Showing the past <strong>' + str(DEFAULT_LOOKBACK_DAYS) + '</strong> days by default; use filters to refine.</p>'
    html += msg_html

    html += '<form method="get" action="' + SCRIPT_PATH + '" class="filters form-inline">'
    html += '<div class="form-group"><label>Involvement ID</label><br/>'
    html += '<input class="form-control" name="OrgId" value="' + _html(sp['OrgId'] or '') + '" style="width:100px" /></div>'
    html += '<div class="form-group"><label>Involvement name</label><br/>'
    html += '<input class="form-control" name="OrgName" value="' + _html(sp['OrgName']) + '" style="width:180px" /></div>'
    html += '<div class="form-group"><label>Last name</label><br/>'
    html += '<input class="form-control" name="LastName" value="' + _html(sp['LastName']) + '" style="width:140px" /></div>'
    html += '<div class="form-group"><label>First name</label><br/>'
    html += '<input class="form-control" name="FirstName" value="' + _html(sp['FirstName']) + '" style="width:140px" /></div>'
    html += '<div class="form-group"><label>People ID</label><br/>'
    html += '<input class="form-control" name="PeopleId" value="' + _html(sp['PeopleId'] or '') + '" style="width:100px" /></div>'
    html += '<div class="form-group"><label>Start date</label><br/>'
    html += '<input class="form-control" type="date" name="StartDate" value="' + _html(sp['StartDate'].ToString('yyyy-MM-dd')) + '" /></div>'
    html += '<div class="form-group"><label>End date</label><br/>'
    html += '<input class="form-control" type="date" name="EndDate" value="' + _html(sp['EndDate'].ToString('yyyy-MM-dd')) + '" /></div>'
    html += '<div class="form-group"><label>&nbsp;</label><br/>'
    html += '<button type="submit" class="btn btn-primary">Search</button></div>'
    html += '</form>'

    html += '<form method="post" action="' + SCRIPT_PATH + '" id="email-form" onsubmit="return iroPrepare();">'
    html += _hidden_filters(sp)
    html += '<input type="hidden" name="action" value="email" />'
    html += '<div class="iro-actions">'
    html += '<label>Email template (Title/Name contains ' + _html(TEMPLATE_TITLE_PREFIX) + ')</label> '
    html += '<select name="TemplateName" id="TemplateName" class="form-control" style="display:inline-block;width:320px">'
    html += _options_html(templates, selected_template)
    html += '</select> '
    html += '<button type="submit" class="btn btn-success">Email selected</button> '
    html += '<button type="button" class="btn btn-default" onclick="iroToggle(true)">Select all</button> '
    html += '<button type="button" class="btn btn-default" onclick="iroToggle(false)">Clear</button> '
    html += '<span class="text-muted">From: ' + _html(FROM_ADDR) + '</span>'
    html += '</div>'

    html += '<p><strong>' + str(len(rows)) + '</strong> incomplete attempt(s)</p>'
    html += '<p class="text-muted">Email goes to the starter/parent when known, otherwise the registrant. '
    html += 'Attempt date links require Admin, Finance, or ManageTransactions. '
    html += 'Use Handlebars fields in the template: {{RegistrantName}}, {{InvolvementName}}, {{RegisterUrl}}. '
    html += '<strong>Last emailed</strong> is based on prior IncompleteReg outreach for that recipient + involvement. '
    html += 'Click a column header to sort.</p>'
    html += '<table id="iro-table" class="table table-striped table-condensed"><thead><tr>'
    html += '<th></th>'
    html += _sortable_th('Attempt date', 1, 'text')
    html += _sortable_th('Registrant', 2, 'text')
    html += _sortable_th('User who started', 3, 'text')
    html += _sortable_th('Email to', 4, 'text')
    html += _sortable_th('Involvement', 5, 'text')
    html += _sortable_th('Involvement ID', 6, 'num')
    html += _sortable_th('Last emailed', 7, 'text')
    html += _sortable_th('Status', 8, 'text')
    html += '</tr></thead><tbody>'
    html += _rows_html(rows, emailed_lookup)
    html += '</tbody></table></form></div>'

    html += '<script>\n'
    html += sort_js
    html += 'function iroToggle(on) {\n'
    html += '  var boxes = document.querySelectorAll(".pid-cb");\n'
    html += '  for (var i = 0; i < boxes.length; i++) boxes[i].checked = on;\n'
    html += '}\n'
    html += 'function iroUniqueCount() {\n'
    html += '  var boxes = document.querySelectorAll(".pid-cb:checked");\n'
    html += '  return boxes.length;\n'
    html += '}\n'
    html += 'function iroPrepare() {\n'
    html += '  var n = iroUniqueCount();\n'
    html += '  if (!n) { alert("Select at least one row with an email recipient."); return false; }\n'
    html += '  var sel = document.getElementById("TemplateName");\n'
    html += '  if (!sel || !sel.value) { alert("Select an email template."); return false; }\n'
    html += '  return true;\n'
    html += '}\n'
    html += '</script>'
    return html


def _send_email(tokens, template_name):
    if not tokens:
        return False, 'No rows selected.'
    if not template_name:
        return False, 'No email template selected.'

    templates = _email_templates()
    names = []
    for t in templates:
        names.append(_s(t.Name))
    if template_name not in names:
        return False, 'Template does not match IncompleteReg filter (or Name mismatch).'

    queued_by = model.UserPeopleId
    if not queued_by:
        return False, 'Cannot determine current user PeopleId for email queue.'

    recipient_pids = []
    skipped = 0

    for token in tokens:
        info = _parse_row_token(token)
        if info is None or not info['RecipientPeopleId'] or not info['OrganizationId']:
            skipped += 1
            continue
        recip = info['RecipientPeopleId']

        reg_name = info['RegistrantName']
        reg_first = _registrant_first(reg_name)
        # Prefer live People record when we have a registrant PeopleId
        if info['RegistrantPeopleId']:
            psql = """
SELECT TOP 1 PreferredName, Name, Name2
FROM dbo.People WHERE PeopleId = @pid
"""
            pp = _dd()
            pp.AddValue('pid', str(info['RegistrantPeopleId']))
            prows = list(q.QuerySql(psql, pp))
            if prows:
                if not _is_null(prows[0].PreferredName):
                    reg_first = _s(prows[0].PreferredName)
                if not _is_null(prows[0].Name):
                    reg_name = _s(prows[0].Name)

        org_name = info['OrganizationName']
        reg_url = _register_url(info['OrganizationId'])
        # Prebuilt HTML link — use triple braces in template: {{{RegisterLink}}}
        reg_link = '<a href="' + reg_url + '">Complete registration for ' + _html(org_name) + '</a>'

        dd = model.DynamicData()
        dd.AddValue('PeopleId', recip)
        dd.AddValue('RegistrantName', reg_name)
      dd.AddValue('RegistrantFirst', reg_first)
        dd.AddValue('InvolvementName', org_name)
        dd.AddValue('InvolvementId', str(info['OrganizationId']))
        dd.AddValue('RegisterUrl', reg_url)
        dd.AddValue('RegisterLink', reg_link)
        dd.AddValue('RecipientKind', info['RecipientKind'])

        # Stamp involvement on EmailQueueTo so Last emailed can find this send.
        # EmailContentWithPythonData uses model.CurrentOrgId -> Util2.CurrentOrgId.
        model.CurrentOrgId = info['OrganizationId']

        # One email per selected row so sibling registrations keep correct merge data
        query = 'peopleids=(' + str(recip) + ')'
        model.EmailContentWithPythonData(query, queued_by, FROM_ADDR, _from_name(), template_name, [dd])
        recipient_pids.append(recip)

    if len(recipient_pids) == 0:
        return False, 'No valid recipients after parsing selection.' + (' Skipped ' + str(skipped) + '.' if skipped else '')

    msg = 'Queued ' + str(len(recipient_pids)) + ' email(s) using template "' + template_name + '".'
    if skipped:
        msg += ' Skipped ' + str(skipped) + ' invalid row(s).'
    return True, msg


def _show(html):
    if model.HttpMethod == 'get':
        model.Form = html
    else:
        print html


def _error_page(ex):
    try:
        msg = _html(ex.ToString())
    except:
        msg = _html(str(ex))
    return '<div class="alert alert-danger"><strong>Incomplete Registration Outreach error</strong>' + \
           '<pre style="white-space:pre-wrap;margin-top:8px">' + msg + '</pre></div>'


def main():
    model.Title = 'Incomplete Registration Outreach'
    model.Header = 'Incomplete Registration Outreach'

    try:
        if not (model.UserIsInRole('Admin') or model.UserIsInRole('ManageRegistrations')):
            _show('<div class="alert alert-danger">Not authorized. Requires Admin or ManageRegistrations.</div>')
            return

        sp = _search_params()
        templates = _email_templates()
        action = _form_val('action', '')
        msg = _form_val('msg')

        if model.HttpMethod == 'post' and action == 'email':
            tokens = _selected_row_tokens()
            template_name = _form_val('TemplateName')
            if _form_val('confirm') != '1':
                if (not tokens) or (not template_name):
                    print 'REDIRECT=' + SCRIPT_PATH + '?' + _qs(sp, 'Select rows and a template before emailing.')
                    return
                print _confirm_page(sp, tokens, template_name, templates)
                return
            ok, message = _send_email(tokens, template_name)
            print 'REDIRECT=' + SCRIPT_PATH + '?' + _qs(sp, message)
            return

        rows, emailed_lookup = _run_search(sp)

        message = _html(msg) if msg else ''
        if not templates:
            # Diagnostic: show nearby Content rows so we can see TypeID / Title / Name
            diag_sql = """
SELECT TOP 20 c.Name, c.Title, c.TypeID
FROM dbo.Content c
WHERE c.TypeID IN (0, 2, 7)
  AND (
        c.Title LIKE '%' + @needle + '%'
        OR c.Name LIKE '%' + @needle + '%'
        OR c.Title LIKE '%Incomplete%'
        OR c.Name LIKE '%Incomplete%'
      )
ORDER BY c.Name
"""
            dp = _dd()
            dp.AddValue('needle', TEMPLATE_TITLE_PREFIX)
            diag_rows = list(q.QuerySql(diag_sql, dp))
            note = 'No email templates matched prefix <strong>' + _html(TEMPLATE_TITLE_PREFIX) + '</strong>. '
            note += 'Expected Title or Name to contain that text, and TypeID 0/2/7 (HTML / Email / Unlayer).'
            if diag_rows:
                note += '<br/><br/><strong>Nearby templates found:</strong><ul>'
                for r in diag_rows:
                    note += '<li>Name=<code>' + _html(r.Name) + '</code> Title=<code>' + \
                            _html(r.Title) + '</code> TypeID=' + _s(r.TypeID) + '</li>'
                note += '</ul>'
            else:
                note += '<br/>No Content rows with "Incomplete" in Name/Title were found either. ' + \
                        'Confirm the template was saved under Communication → Email Templates.'
            if message:
                message = message + br/>' + note
            else:
                message = note

        _show(_page(sp, rows, templates, message, emailed_lookup))
    except Exception, ex:
        _show(_error_page(ex))


main()

