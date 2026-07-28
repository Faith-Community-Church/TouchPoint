#Roles=Access
# Script: BalanceDueFollowUp.py
# Purpose: List current involvement members with a remaining balance due (IndDue > 0)
#   and email follow-ups via an Email Template whose Title starts with BalanceDue.
#   One row per person; family members share the same TranId paylink.
#   Email goes to the user who paid/started (LoginPeopleId) when known, else the
#   member with the balance. From address is the current user or a delegated
#   PeopleCanEmailFor address.
# Author: Jake Pierson
# Date: 2026-07-21
#
# Install: Special Content -> Python Scripts -> name BalanceDueFollowUp
# Run: /PyScriptForm/BalanceDueFollowUp
#
# Prerequisites:
#   - Access (staff) role
#   - Email Template Title starting with BalanceDue
#
# IronPython notes (TouchPoint embeds IronPython 2.7):
#   - Use print without parentheses; except Exception, ex
#   - Put UI in model.Form on GET (PyScriptForm ignores Output)
#   - Prefer model.DynamicData() for SQL params (not bare dict / **kwargs)
#   - Prefer string concat over .format() for large HTML
#   - model.GetPayLink(peopleId, orgId) builds the shared family paylink

TEMPLATE_TITLE_PREFIX = 'BalanceDue'
SCRIPT_PATH = '/PyScriptForm/BalanceDueFollowUp'


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


def _html(val):
    s = _s(val)
    s = s.replace('&', '&amp;')
    s = s.replace('<', '&lt;')
    s = s.replace('>', '&gt;')
    s = s.replace('"', '&quot;')
    return s


def _money(val):
    if _is_null(val):
        return 0.0
    try:
        return float(val)
    except:
        return 0.0


def _money_s(val):
    try:
        n = _money(val)
        # IronPython-safe money formatting
        return '$' + ('%.2f' % n)
    except:
        return '$0.00'


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
        '    var= cb ? (cb.getAttribute("data-sort") || cb.textContent || "") : "";\n'
        '    va = ("" + va).replace(/^\\s+|\\s+$/g, "").toLowerCase();\n'
        '    vb = ("" + vb).replace(/^\\s+|\\s+$/g, "").toLowerCase();\n'
        '    var emptyA = (!va || va === "never" || va === "—" || va === "-");\n'
        '    var emptyB = (!vb || vb === "never" || vb === "—" || vb === "-");\n'
        '    if (emptyA && emptyB) return 0;\n'
        '    if (emptyA) return 1;\n'
        '    if (emptyB) return -1;\n'
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


def _user_id():
    """Users.UserId for LimitToRole checks."""
    uid = model.UserPeopleId
    if not uid:
        return 0
    sql = 'SELECT TOP 1 UserId FROM dbo.Users WHERE PeopleId = @pid ORDER BY UserId'
    p = _dd()
    p.AddValue('pid', str(uid))
    rows = list(q.QuerySql(sql, p))
    if rows and (not _is_null(rows[0].UserId)):
        return _i(rows[0].UserId, 0)
    return 0


def _from_options():
    """
    Current user plus PeopleCanEmailFor delegates (same idea as Mass Emailer).
    Returns list of dicts: PeopleId, Email, Name
    """
    opts = []
    me = model.UserPeopleId
    if not me:
        return opts

    sql_me = """
SELECT TOP 1
    p.PeopleId,
    p.Name,
    CASE WHEN ISNULL(p.SendEmailAddress1, 1) = 1 AND NULLIF(p.EmailAddress, '') IS NOT NULL
         THEN p.EmailAddress ELSE p.EmailAddress2 END AS Email
FROM dbo.People p
WHERE p.PeopleId = @pid
"""
    p = _dd()
    p.AddValue('pid', str(me))
    rows = list(q.QuerySql(sql_me, p))
    if rows and _s(rows[0].Email):
        opts.append({
            'PeopleId': _i(rows[0].PeopleId),
            'Email': _s(rows[0].Email),
            'Name': _s(rows[0].Name),
        })

    sql_del = """
SELECT
    p.PeopleId,
    p.Name,
    CASE WHEN ISNULL(p.SendEmailAddress1, 1) = 1 AND NULLIF(p.EmailAddress, '') IS NOT NULL
         THEN p.EmailAddress ELSE p.EmailAddress2 END AS Email
FROM dbo.PeopleCanEmailFor cf
JOIN dbo.People p ON p.PeopleId = cf.OnBehalfOf
WHERE cf.CanEmail = @pid
  AND (
        (ISNULL(p.SendEmailAddress1, 1) = 1 AND NULLIF(p.EmailAddress, '') IS NOT NULL)
        OR (ISNULL(p.SendEmailAddress2, 0) = 1 AND NULLIF(p.EmailAddress2, '') IS NOT NULL)
      )
ORDER BY p.Name
"""
    for row in list(q.QuerySql(sql_del, p)):
        if _s(row.Email):
            opts.append({
                'PeopleId': _i(row.PeopleId),
                'Email': _s(row.Email),
                'Name': _s(row.Name),
            })
    return opts


def _resolve_from(from_pid, options):
    """Pick from address/name from selected PeopleId; default to first option."""
    if not options:
        return None, None, None
    chosen = options[0]
    want = _i(from_pid)
    if want:
        for o in options:
            if o['PeopleId'] == want:
                chosen = o
                break
    return chosen['PeopleId'], chosen['Email'], chosen['Name']


def _email_templates():
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
    return {
        'OrgId': _i(_form_val('OrgId')),
        'OrgName': _form_val('OrgName'),
        'LastName': _form_val('LastName'),
        'FirstName': _form_val('FirstName'),
        'PeopleId': _i(_form_val('PeopleId')),
    }


def _sql_params(sp):
    p = _dd()
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
    p.AddValue('userId', str(_user_id()))
    p.AddValue('isAdmin', '1' if model.UserIsInRole('Admin') else '0')
    return p


def _run_search(sp):
    """
    One row per current member with IndDue > 0.
    Starter/payer = Transaction.LoginPeopleId on the root TranId when present.
    """
    sql = """
SELECT
    om.PeopleId,
    COALESCE(p.Name2, p.Name) AS PersonName,
    p.PreferredName,
    p.FirstName,
    p.LastName,
    om.OrganizationId,
    o.OrganizationName,
    om.TranId,
    SUM(ts.IndDue) AS AmountDue,
    SUM(ts.IndPaid) AS AmountPaid,
    SUM(ts.IndAmt) AS FeeTotal,
    t.LoginPeopleId AS StarterPeopleId,
    starter.Name AS StarterName,
    (
        SELECT MAX(t2.TransactionDate)
        FROM dbo.[Transaction] t2
        WHERE t2.OriginalId = om.TranId
          AND ISNULL(t2.AdjustFee, 0) = 0
          AND (
                t2.Approved = 1
                OR t2.TransactionId LIKE 'Coupon%'
              )
    ) AS LastPaymentDate
FROM dbo.OrganizationMembers om
JOIN dbo.TransactionSummary ts
  ON ts.RegId = om.TranId
 AND ts.PeopleId = om.PeopleId
JOIN dbo.People p ON p.PeopleId = om.PeopleId
JOIN dbo.Organizations o ON o.OrganizationId = om.OrganizationId
LEFT JOIN dbo.[Transaction] t ON t.Id = om.TranId
LEFT JOIN dbo.People starter ON starter.PeopleId = t.LoginPeopleId
WHERE om.TranId IS NOT NULL
  AND ISNULL(om.Pending, 0) = 0
  AND (@HasOrgId = '0' OR om.OrganizationId = CAST(@OrgId AS int))
  AND (@HasOrgName = '0' OR o.OrganizationName LIKE '%' + @OrgName + '%')
  AND (@HasLastName = '0' OR p.LastName LIKE @LastName + '%')
  AND (@HasFirstName = '0' OR p.FirstName LIKE @FirstName + '%')
  AND (@HasPeopleId = '0' OR om.PeopleId = CAST(@PeopleId AS int))
  AND (
        @isAdmin = '1'
        OR o.LimitToRole IS NULL
        OR EXISTS (
            SELECT 1
            FROM dbo.Roles r
            JOIN dbo.UserRole ur ON ur.RoleId = r.RoleId
            WHERE ur.UserId = CAST(@userId AS int)
              AND r.RoleName = o.LimitToRole
        )
      )
GROUP BY
    om.PeopleId, p.Name2, p.Name, p.PreferredName, p.FirstName, p.LastName,
    om.OrganizationId, o.OrganizationName, om.TranId,
    t.LoginPeopleId, starter.Name
HAVING SUM(ts.IndDue) > 0
ORDER BY o.OrganizationName, p.Name2, p.Name
"""
    rows = list(q.QuerySql(sql, _sql_params(sp)))
    emailed_lookup = _last_emailed_lookup(rows)
    return rows, emailed_lookup


def _last_emailed_lookup(rows):
    """Map 'recipientPid~orgId' -> last emailed datetime for BalanceDue outreach."""
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

    sql = """
SELECT
    eqt.PeopleId AS RecipientPeopleId,
    eqt.OrgId AS OrganizationId,
    MAX(ISNULL(eqt.Sent, ISNULL(eq.Sent, eq.Queued))) AS LastEmailed
FROM dbo.EmailQueue eq
JOIN dbo.EmailQueueTo eqt ON eqt.Id = eq.Id
WHERE eqt.PeopleId IN ({recips})
  AND eqt.OrgId IN ({orgs})
  AND ISNULL(eq.Subject, '') LIKE '%' + @prefix + '%'
GROUP BY eqt.PeopleId, eqt.OrgId
""".format(orgs=org_csv, recips=recip_csv)

    p = _dd()
    p.AddValue('prefix', TEMPLATE_TITLE_PREFIX)
    for e in list(q.QuerySql(sql, p)):
        if _is_null(e.OrganizationId):
            continue
        key = _s(e.RecipientPeopleId) + '~' + _s(e.OrganizationId)
        lookup[key] = e.LastEmailed
    return lookup


def _recipient_for_row(row):
    """Prefer LoginPeopleId (payer/starter); else the member with the balance."""
    if not _is_null(row.StarterPeopleId):
        return row.StarterPeopleId, 'starter'
    if not _is_null(row.PeopleId):
        return row.PeopleId, 'member'
    return None, 'none'


def _paylink(people_id, org_id):
    try:
        link = model.GetPayLink(int(people_id), int(org_id))
        return _s(link)
    except:
        return ''


def _row_token(row):
    """
    recipientPid~orgId~memberPid~memberName~orgName~kind~amountDue~amountPaid
    """
    recip, kind = _recipient_for_row(row)
    if recip is None:
        return None
    member_name = _s(row.PersonName).replace('~', ' ').replace(',', ' ')
    org_name = _s(row.OrganizationName).replace('~', ' ').replace(',', ' ')
    return '~'.join([
        _s(recip),
        _s(row.OrganizationId),
        _s(row.PeopleId),
        member_name,
        org_name,
        kind,
        _s(_money(row.AmountDue)),
        _s(_money(row.AmountPaid)),
    ])


def _parse_row_token(token):
    parts = _s(token).split('~')
    if len(parts) < 8:
        return None
    return {
        'RecipientPeopleId': _i(parts[0]),
        'OrganizationId': _i(parts[1]),
        'MemberPeopleId': _i(parts[2]),
        'MemberName': parts[3],
        'OrganizationName': parts[4],
        'RecipientKind': parts[5],
        'AmountDue': parts[6],
        'AmountPaid': parts[7],
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


def _member_first(row_or_name, preferred=None):
    if preferred and _s(preferred):
        return _s(preferred)
    n = _s(row_or_name)
    if not n:
        return ''
    return _s(n.split(' ')[0])


def _qs(sp, extra_msg=None):
    parts = []
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
    return html


def _options_html(templates, selected):
    parts = []
    parts.append('<option value="">-- select template --</option>')
    for t in templates:
        name = _s(t.Name)
        title = _s(t.Title) or name
        sel = ' selected' if name == selected else ''
        parts.append('<option value="' + _html(name) + '"' + sel + '>' + _html(title) + '</option>')
    return '\n'.join(parts)


def _from_options_html(options, selected_pid):
    parts = []
    for o in options:
        sel = ''
        if selected_pid and o['PeopleId'] == selected_pid:
            sel = ' selected'
        elif (not selected_pid) and len(parts) == 0:
            sel = ' selected'
        label = o['Name'] + ' <' + o['Email'] + '>'
        parts.append('<option value="' + _s(o['PeopleId']) + '"' + sel + '>' + _html(label) + '</option>')
    if not parts:
        parts.append('<option value="">-- no from address available --</option>')
    return '\n'.join(parts)


def _rows_html(rows, emailed_lookup):
    if (not rows) or (len(rows) == 0):
        return '<tr><td colspan="10"><em>No current members with a remaining balance.</em></td></tr>'
    parts = []
    for row in rows:
        token = _row_token(row)
        recip, kind = _recipient_for_row(row)

        if token is not None:
            cb = '<input type="checkbox" name="rowtokens" value="' + _html(token) + '" class="bdf-cb" />'
        else:
            cb = '<input type="checkbox" disabled title="No email recipient" />'

        person = '<a href="/Person2/' + _s(row.PeopleId) + '" target="_blank">' + _html(row.PersonName) + '</a>'
        org = '<a href="/Org/' + _s(row.OrganizationId) + '" target="_blank">' + _html(row.OrganizationName) + '</a>'

        if kind == 'starter':
            email_to = 'Payer/starter'
            if not _is_null(row.StarterName):
                email_to = '<a href="/Person2/' + _s(row.StarterPeopleId) + '" target="_blank">' + \
                           _html(row.StarterName) + '</a> <span class="text-muted">(payer)</span>'
        else:
            email_to = 'Member'

        pay = _paylink(row.PeopleId, row.OrganizationId)
        if pay:
            pay_html = '<a href="' + _html(pay) + '" target="_blank">Pay link</a>'
        else:
            pay_html = '<span class="text-muted">n/a</span>'

        last_html = '<span class="text-muted">Never</span>'
        last_key = ''
        if recip is not None and (not _is_null(row.OrganizationId)):
            key = _s(recip) + '~' + _s(row.OrganizationId)
            if key in emailed_lookup and (not _is_null(emailed_lookup[key])):
                last_html = _html(_fmt_dt(emailed_lookup[key]))
                last_key = _sort_dt_key(emailed_lookup[key])

        last_pay = _fmt_dt(row.LastPaymentDate)
        last_pay_key = _sort_dt_key(row.LastPaymentDate)
        if not last_pay:
            last_pay = '<span class="text-muted">—</span>'
        else:
            last_pay = _html(last_pay)

        name_sort = (_s(row.LastName) + ', ' + _s(row.FirstName)).strip(', ')
        if not name_sort:
            name_sort = _s(row.PersonName)

        email_sort = ''
        if kind == 'starter':
          email_sort = _s(row.StarterName) if not _is_null(row.StarterName) else 'payer'
        else:
            email_sort = 'zzz-member'

        row_html = '<tr>'
        row_html += '<td>' + cb + '</td>'
        row_html += _td(person, name_sort)
        row_html += _td(org, _s(row.OrganizationName))
        row_html += _td(_s(row.OrganizationId), _s(row.OrganizationId))
        row_html += _td(_money_s(row.FeeTotal), _s(row.FeeTotal), 'right')
        row_html += _td(_money_s(row.AmountPaid), _s(row.AmountPaid), 'right')
        row_html += _td('<strong>' + _money_s(row.AmountDue) + '</strong>', _s(row.AmountDue), 'right')
        row_html += _td(last_pay, last_pay_key)
        row_html += _td(pay_html, '1' if pay else '0')
        row_html += _td(email_to, email_sort)
        row_html += _td(last_html, last_key)
        row_html += '</tr>'
        parts.append(row_html)
    return ''.join(parts)


def _confirm_page(sp, tokens, template_name, templates, from_pid):
    title = template_name
    for t in templates:
        if _s(t.Name) == template_name:
            title = _s(t.Title) or template_name
            break
    options = _from_options()
    fp, femail, fname = _resolve_from(from_pid, options)
    from_label = (fname or '') + ' <' + (femail or '') + '>'

    html = '<div style="max-width:640px;margin:40px auto;font-family:sans-serif">'
    html += '<h2>Confirm email</h2>'
    html += '<p>Send <strong>' + str(len(tokens)) + '</strong> balance-due email(s) using template '
    html += '<strong>' + _html(title) + '</strong>?</p>'
    html += '<p>From: <strong>' + _html(from_label) + '</strong></p>'
    html += '<p style="color:#666;font-size:13px">Each selected row emails the payer/starter when known, '
    html += 'otherwise the member. Family members share the same paylink.</p>'
    html += '<form method="post" action="' + SCRIPT_PATH + '" style="display:inline">'
    html += _hidden_filters(sp)
    html += '<input type="hidden" name="action" value="email" />'
    html += '<input type="hidden" name="confirm" value="1" />'
    html += '<input type="hidden" name="TemplateName" value="' + _html(template_name) + '" />'
    html += '<input type="hidden" name="FromPeopleId" value="' + _s(fp or '') + '" />'
    for tok in tokens:
        html += '<input type="hidden" name="rowtokens" value="' + _html(tok) + '" />'
    html += '<button type="submit" class="btn btn-primary">Yes, send email</button>'
    html += '</form> '
    html += '<a href="' + SCRIPT_PATH + '?' + _qs(sp) + '">Cancel</a>'
    html += '</div>'
    return html


def _page(sp, rows, templates, message, emailed_lookup, from_options):
    selected_template = _form_val('TemplateName', '')
    selected_from = _i(_form_val('FromPeopleId'))
    msg_html = ''
    if message:
        msg_html = '<div class="alert alert-info">' + message + '</div>'
    if emailed_lookup is None:
        emailed_lookup = {}

    sort_css, sort_js = _sortable_table_assets('bdf-table')

    html = ''
    html += '<style>'
    html += '.bdf-wrap{max-width:1280px;}'
    html += '.bdf-wrap .filters .form-group{margin-right:12px;margin-bottom:10px;display:inline-block;vertical-align:top;}'
    html += '.bdf-wrap table{margin-top:12px;}'
    html += '.bdf-wrap .text-muted{color:#888;font-size:12px;}'
    html += '.bdf-actions{margin:12px 0;padding:12px;background:#f7f7f7;border:1px solid #ddd;}'
    html += sort_css
    html += '</style>'
    html += '<div class="bdf-wrap">'
    html += '<p>Current involvement members with a <strong>remaining balance greater than $0</strong>. '
    html += 'One row per person; family registrations share one paylink. '
    html += 'Filter by involvement to focus the list.</p>'
    html += msg_html

    html += '<form method="get" action="' + SCRIPT_PATH + '" class="filters form-inline">'
    html += '<div class="form-group"><label>Involvement ID</label><br/>'
    html += '<input class="form-control" name="OrgId" value="' + _html(sp['OrgId'] or '') + '" style="width:100px" /></div>'
    html += '<div class="form-group"><label>Involvement name</label><br/>'
    html += '<input class="form-control" name="OrgName" value="' + _html(sp['OrgName']) + '" style="width:200px" /></div>'
    html += '<div class="form-group"><label>Last name</label><br/>'
    html += '<input class="form-control" name="LastName" value="' + _html(sp['LastName']) + '" style="width:140px" /></div>'
    html += '<div class="form-group"><label>First name</label><br/>'
    html += '<input class="form-control" name="FirstName" value="' + _html(sp['FirstName']) + '" style="width:140px" /></div>'
    html += '<div class="form-group"><label>People ID</label><br/>'
    html += '<input class="form-control" name="PeopleId" value="' + _html(sp['PeopleId'] or '') + '" style="width:100px" /></div>'
    html += '<div class="form-group"><label>&nbsp;</label><br/>'
    html += '<button type="submit" class="btn btn-primary">Search</button></div>'
    html += '</form>'

    html += '<form method="post" action="' + SCRIPT_PATH + '" id="bdf-email-form" onsubmit="return bdfPrepare();">'
    html += _hidden_filters(sp)
    html += '<input type="hidden" name="action" value="email" />'
    html += '<div class="bdf-actions">'
    html += '<div class="form-group" style="display:inline-block;margin-right:12px">'
    html += '<label>From</label><br/>'
    html += '<select name="FromPeopleId" id="FromPeopleId" class="form-control" style="width:280px">'
    html += _from_options_html(from_options, selected_from)
    html += '</select></div> '
    html += '<div class="form-group" style="display:inline-block;margin-right:12px">'
    html += '<label>Email template (Title contains ' + _html(TEMPLATE_TITLE_PREFIX) + ')</label><br/>'
    html += '<select name="TemplateName" id="TemplateName" class="form-control" style="width:320px">'
    html += _options_html(templates, selected_template)
    html += '</select></div> '
    html += '<div class="form-group" style="display:inline-block">'
    html += '<label>&nbsp;</label><br/>'
    html += '<button type="submit" class="btn btn-success">Email selected</button> '
    html += '<button type="button" class="btn btn-default" onclick="bdfToggle(true)">Select all</button> '
    html += '<button type="button" class="btn btn-default" onclick="bdfToggle(false)">Clear</button>'
    html += '</div></div>'

    html += '<p><strong>' + str(len(rows)) + '</strong> member(s) with balance due</p>'
    html += '<p class="text-muted">Email goes to the payer/starter when known, otherwise the member. '
    html += 'Handlebars fields: {{PersonName}}, {{PersonFirst}}, {{InvolvementName}}, '
    html += '{{AmountPaid}}, {{AmountDue}}, {{PayUrl}}, {{{PayLink}}}. '
    html += '<strong>Last emailed</strong> tracks prior BalanceDue outreach for that recipient + involvement. '
    html += 'Click a column header to sort.</p>'
    html += '<table id="bdf-table" class="table table-striped table-condensed"><thead><tr>'
    html += '<th></th>'
    html += _sortable_th('Person', 1, 'text')
    html += _sortable_th('Involvement', 2, 'text')
    html += _sortable_th('ID', 3, 'num')
    html += _sortable_th('Fee', 4, 'num', 'right')
    html += _sortable_th('Paid', 5, 'num', 'right')
    html += _sortable_th('Due', 6, 'num', 'right')
    html += _sortable_th('Last payment', 7, 'text')
    html += _sortable_th('Pay link', 8, 'text')
    html += _sortable_th('Email to', 9, 'text')
    html += _sortable_th('Last emailed', 10, 'text')
    html += '</tr></thead><tbody>'
    html += _rows_html(rows, emailed_lookup)
    html += '</tbody></table></form></div>'

    html += '<script>\n'
    html += sort_js
    html += 'function bdfToggle(on) {\n'
    html += '  var boxes = document.querySelectorAll(".bdf-cb");\n'
    html += '  for (var i = 0; i < boxes.length; i++) boxes[i].checked = on;\n'
    html += '}\n'
    html += 'function bdfPrepare() {\n'
    html += '  var boxes = document.querySelectorAll(".bdf-cb:checked");\n'
    html += '  if (!boxes.length) { alert("Select at least one row."); return false; }\n'
    html += '  var sel = document.getElementById("TemplateName");\n'
    html += '  if (!sel || !sel.value) { alert("Select an email template."); return false; }\n'
    html += '  var fr = document.getElementById("FromPeopleId");\n'
    html += '  if (!fr || !fr.value) { alert("Select a From address."); return false; }\n'
    html += '  return true;\n'
    html += '}\n'
    html += '</script>'
    return html


def _send_email(tokens, template_name, from_pid):
    if not tokens:
        return False, 'No rows selected.'
    if not template_name:
        return False, 'No email template selected.'

    templates = _email_templates()
    names = [_s(t.Name) for t in templates]
    if template_name not in names:
        return False, 'Template does not match BalanceDue filter (or Name mismatch).'

    options = _from_options()
    fp, femail, fname = _resolve_from(from_pid, options)
    if not femail:
        return False, 'No valid From email address available for your account.'

    queued_by = model.UserPeopleId
    if not queued_by:
        return False, 'Cannot determine current user PeopleId for email queue.'

    sent = 0
    skipped = 0

    for token in tokens:
        info = _parse_row_token(token)
        if info is None or not info['RecipientPeopleId'] or not info['OrganizationId'] or not info['MemberPeopleId']:
            skipped += 1
            continue

        recip = info['RecipientPeopleId']
        org_id = info['OrganizationId']
        member_pid = info['MemberPeopleId']

        person_name = info['MemberName']
        person_first = _member_first(person_name)
        psql = """
SELECT TOP 1 PreferredName, Name
FROM dbo.People WHERE PeopleId = @pid
"""
        pp = _dd()
        pp.AddValue('pid', str(member_pid))
        prows = list(q.QuerySql(psql, pp))
        if prows:
            if not _is_null(prows[0].PreferredName):
                person_first = _s(prows[0].PreferredName)
            if not _is_null(prows[0].Name):
                person_name = _s(prows[0].Name)

        pay_url = _paylink(member_pid, org_id)
        pay_link = ''
        if pay_url:
            pay_link = '<a href="' + pay_url + '">Pay remaining balance for ' + _html(info['OrganizationName']) + '</a>'

        amount_due = _money_s(info['AmountDue'])
        amount_paid = _money_s(info['AmountPaid'])

        dd = model.DynamicData()
        dd.AddValue('PeopleId', recip)
        dd.AddValue('PersonName', person_name)
        dd.AddValue('PersonFirst', person_first)
        dd.AddValue('InvolvementName', info['OrganizationName'])
        dd.AddValue('InvolvementId', str(org_id))
        dd.AddValue('AmountDue', amount_due)
        dd.AddValue('AmountPaid', amount_paid)
        dd.AddValue('PayUrl', pay_url)
        dd.AddValue('PayLink', pay_link)
        dd.AddValue('RecipientKind', info['RecipientKind'])

        model.CurrentOrgId = org_id
        query = 'peopleids=(' + str(recip) + ')'
        model.EmailContentWithPythonData(query, queued_by, femail, fname, template_name, [dd])
        sent += 1

    if sent == 0:
        return False, 'No valid recipients after parsing selection.' + (' Skipped ' + str(skipped) + '.' if skipped else '')

    msg = 'Queued ' + str(sent) + ' email(s) using template "' + template_name + '" from ' + femail + '.'
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
    return '<div class="alert alert-danger"><strong>Balance Due Follow-Up error</strong>' + \
           '<pre style="white-space:pre-wrap;margin-top:8px">' + msg + '</pre></div>'


def main():
    model.Title = 'Balance Due Follow-Up'
    model.Header = 'Balance Due Follow-Up'

    try:
        if not model.UserIsInRole('Access'):
            _show('<div class="alert alert-danger">Not authorized. Requires Access (staff).</div>')
            return

        sp = _search_params()
        templates = _email_templates()
        from_options = _from_options()
        action = _form_val('action', '')
        msg = _form_val('msg')

        if model.HttpMethod == 'post' and action == 'email':
            tokens = _selected_row_tokens()
            template_name = _form_val('TemplateName')
            from_pid = _form_val('FromPeopleId')
            if _form_val('confirm') != '1':
                if (not tokens) or (not template_name):
                    print 'REDIRECT=' + SCRIPT_PATH + '?' + _qs(sp, 'Select rows and a template before emailing.')
                    return
                print _confirm_page(sp, tokens, template_name, templates, from_pid)
                return
            ok, message = _send_email(tokens, template_name, from_pid)
            print 'REDIRECT=' + SCRIPT_PATH + '?' + _qs(sp, message)
            return

        # Default: show all currently owing (optionally filtered). Emphasize OrgId/OrgName.
        rows, emailed_lookup = _run_search(sp)

        message = _html(msg) if msg else ''
        if not templates:
            note = 'No email templates found whose Title/Name contains <strong>' + \
                   _html(TEMPLATE_TITLE_PREFIX) + '</strong>. ' + \
                   'Create a template with Title starting with BalanceDue.'
            message = (message + '<br/>' + note) if message else note
        if not from_options:
            note = 'No From email address found for your user (or delegates).'
            message = (message + '<br/>' + note) if message else note

        _show(_page(sp, rows, templates, message, emailed_lookup, from_options))
    except Exception, ex:
        _show(_error_page(ex))


main()

