#Roles=Access
# Script: AwanaRegistrationDashboard.py
# Purpose: Awana dashboard for Clubbers (Inv 1916) and Volunteers (Inv 1929).
#   Overview of both involvements, a Volunteers tab (org 1929: Overview, club
#   filters, Volunteer Management for Admin or Staff+Next Gen), then one tab
#   per club. Club tabs: Overview roster, Registration, Allergies, Contacts.
# Author: Jake Pierson (Awana shell); Ben Swaby (base dashboard);
#   Jake Pierson (Registration / Allergies / Contacts)
# Date: 2026-08-28
#
# Install: Special Content -> Python Scripts -> name AwanaRegistrationDashboard
# Run: /PyScriptForm/AwanaRegistrationDashboard
#
# Scope (edit IDs / AWANA_CLUBS below):
#   Clubbers org 1916 ("Awana Registration")
#   Volunteers org 1929
#   Club tabs match subgroup names on those involvements.
#
# IronPython notes (TouchPoint embeds IronPython 2.7):
#   - Use print without parentheses; except Exception, ex
#   - Put UI in model.Form on GET (PyScriptForm ignores Output)
#   - Prefer model.DynamicData() for SQL params
#   - Prefer token replace over .format() for large HTML (JS braces break format)
#   - Never unicode(byte_string) with default encoding ('unknown' codec);
#     use _s() / _json_out() for safe text + ASCII JSON (handles ö / 0xF6)

import json
import traceback

# Soft-set default encoding so implicit str<->unicode coercions don't use 'unknown'
try:
    import sys
    reload(sys)
    sys.setdefaultencoding('latin-1')
except:
    pass

REGISTRATION_FORM_TYPE = 26
STATUS_COMPLETED = 2

# Overview question types: choice + text. Emergency/Parents only on person drill-down.
# Money skipped for v1 (refine later). Other structural types skipped.
QTYPE_TEXT = 1
QTYPE_SINGLE = 2
QTYPE_MULTI = 3
QTYPE_DROPDOWN = 6
QTYPE_EMERGENCY = 8
QTYPE_PARENTS = 12
QTYPE_MONEY = 11

OVERVIEW_CHOICE_TYPES = (QTYPE_SINGLE, QTYPE_MULTI, QTYPE_DROPDOWN)
OVERVIEW_TEXT_TYPES = (QTYPE_TEXT,)
PERSON_EXTRA_TYPES = (QTYPE_EMERGENCY, QTYPE_PARENTS)

SUBTYPE_MENU = 1

BRAND = {
    'black-pearl': '#001429',
    'downriver': '#012B58',
    'azure': '#019CFF',
    'hawkes': '#CCEBFF',
    'linen': '#F5F4E8',
    'forest': '#005C3B',
    'deep-copper': '#801D13',
    'vermillion': '#E52300',
    'crusta': '#FF7941',
}

# ---------------------------------------------------------------------------
# Awana scope — Clubbers + Volunteers involvements; clubs = subgroups
# ---------------------------------------------------------------------------
CLUBBERS_ORG_ID = 1916
VOLUNTEERS_ORG_ID = 1929
# Application involvements (IsMemberOf any of these = application on file)
APP_ORG_IDS = (502, 529, 1742, 1780)
EV_AWANA_HANDBOOK = 'Awana Handbook Signed'
EV_AWANA_INPERSON = 'Awana In Person Training'
EV_MINOR_INPERSON = 'Minor_Child_Protection_Training_Date'
BG_REPORT_PMM = 1
BG_REPORT_MS_TRAINING = 3
BG_STATUS_COMPLETE = 3
MINOR_MAX_AGE = 17
# First matching substring in MemberTag.Name (lowercased) wins.
# Exact match on label is preferred. Put TnT Girls/Boys before any generic TnT.
AWANA_CLUBS = [
    {'key': 'puggles', 'label': 'Puggles', 'match': ['puggles']},
    {'key': 'cubbies', 'label': 'Cubbies', 'match': ['cubbies']},
    {'key': 'sparks', 'label': 'Sparks', 'match': ['sparks']},
    {
        'key': 'tnt-girls',
        'label': 'TnT Girls',
        'match': ['tnt girls', 't&t girls', 't and t girls', 'tnt-girls', 't&t-girls'],
    },
    {
        'key': 'tnt-boys',
        'label': 'TnT Boys',
        'match': ['tnt boys', 't&t boys', 't and t boys', 'tnt-boys', 't&t-boys'],
    },
]


def _is_hear_about_question(label):
    """True when free-text Other answers should collapse into one Other group."""
    lab = _s(label).lower()
    return 'how did you hear' in lab


def _allergy_text_meaningful(text):
    """True only when MedicalDescription looks like a real allergy note."""
    t = _s(text).lower()
    if not t:
        return False
    t = ' '.join(t.split())
    if not t:
        return False
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


# Age brackets for Overview demographics (label -> inclusive min/max; None max = no upper bound)
AGE_BRACKETS = [
    ('0-5', 0, 5),
    ('6-10', 6, 10),
    ('11-13', 11, 13),
    ('14-17', 14, 17),
    ('18-24', 18, 24),
    ('25-29', 25, 29),
    ('30-39', 30, 39),
    ('40-49', 40, 49),
    ('50-64', 50, 64),
    ('65+', 65, None),
]
AGE_BRACKET_LABELS = [b[0] for b in AGE_BRACKETS] + ['Unknown']


def _age_bracket_label(age):
    """Map a numeric age to a bracket label."""
    if age is None:
        return 'Unknown'
    try:
        age = int(age)
    except:
        return 'Unknown'
    for label, lo, hi in AGE_BRACKETS:
        if hi is None:
            if age >= lo:
                return label
        elif lo <= age <= hi:
            return label
    return 'Unknown'


def _empty_age_groups():
    groups = {}
    for label in AGE_BRACKET_LABELS:
        groups[label] = 0
    return groups

# ---------------------------------------------------------------------------
# Program-specific Overview profiles
# Edit this block to customize demographics by Program Id.
# Anything not listed here uses DEFAULT_OVERVIEW_PROFILE.
# ---------------------------------------------------------------------------
DEFAULT_OVERVIEW_PROFILE = {
    'show_age': True,
    'show_grade': False,
    'show_marital': True,
    'show_enrollment_timeline': True,
    # Next Gen Contacts tab (parents + emergency from RecReg stock fields)
    'show_contacts': False,
    # Future knobs (not wired yet — safe to set for later):
    # 'show_gender_stats': True,
    # 'show_finance': True,
    # 'show_subgroups': True,
}

PROGRAM_OVERVIEW_PROFILES = {
    # Next Generation
    1112: {
        'name': 'Next Generation',
        'show_age': False,
        'show_grade': True,
        'show_marital': False,
        'show_enrollment_timeline': True,
        'show_contacts': True,
    },
    # Example for a future program:
    # 9999: {
    #     'name': 'Example Program',
    #     'show_age': True,
    #     'show_grade': False,
    #     'show_marital': True,
    #     'show_enrollment_timeline': True,
    # },
}


def _overview_profile(program_id):
    """Merge program overrides onto the default overview profile."""
    profile = {}
    for k, v in DEFAULT_OVERVIEW_PROFILE.items():
        profile[k] = v
    overrides = PROGRAM_OVERVIEW_PROFILES.get(_i(program_id), None)
    if overrides:
        for k, v in overrides.items():
            if k != 'name':
                profile[k] = v
        profile['profile_name'] = _s(overrides.get('name'), '')
    else:
        profile['profile_name'] = ''
    profile['program_id'] = _i(program_id)
    return profile


def _awana_club_for_name(name):
    """Return club dict for a subgroup/org name. Exact label match first, then substring."""
    n = _s(name).strip()
    nlow = n.lower()
    if not nlow:
        return None
    for club in AWANA_CLUBS:
        if _s(club.get('label')).lower() == nlow:
            return club
    for club in AWANA_CLUBS:
        for m in club.get('match') or []:
            if _s(m).lower() and _s(m).lower() in nlow:
                return club
    return None


def _club_shell():
    """Empty club buckets in display order (so tabs always exist)."""
    clubs = []
    for c in AWANA_CLUBS:
        clubs.append({
            'key': c['key'],
            'label': c['label'],
            'clubbers_tag_id': 0,
            'volunteer_tag_id': 0,
            'clubbers_count': 0,
            'volunteer_count': 0,
        })
    return clubs


def _org_brief(org_id):
    """Id + name for a known involvement, or None."""
    org_id = _i(org_id, 0)
    if org_id <= 0:
        return None
    sql = """
SELECT o.OrganizationId, o.OrganizationName, o.RegistrationTypeId,
       ISNULL(d.Name, '') AS DivisionName, ISNULL(p.Id, 0) AS ProgramId,
       ISNULL(p.Name, '') AS ProgramName, ISNULL(o.MemberCount, 0) AS MemberCount,
       o.ImageUrl, o.BadgeUrl,
       COALESCE(
           NULLIF(LTRIM(RTRIM(oe.Data)), ''),
           NULLIF(LTRIM(RTRIM(oe.StrValue)), ''),
           NULLIF(LTRIM(RTRIM(o.ImageUrl)), '')
       ) AS TitleGraphicUrl
FROM Organizations o
LEFT JOIN Division d ON o.DivisionId = d.Id
LEFT JOIN Program p ON d.ProgId = p.Id
LEFT JOIN dbo.Setting s ON s.Id = 'SitesDataHeroImageEv'
LEFT JOIN dbo.OrganizationExtra oe
    ON oe.OrganizationId = o.OrganizationId
   AND s.Setting IS NOT NULL
   AND LTRIM(RTRIM(s.Setting)) <> ''
   AND oe.Field = s.Setting
WHERE o.OrganizationId = @orgId
"""
    p = _dd()
    p.AddValue('orgId', org_id)
    rows = list(q.QuerySql(sql, p))
    if not rows:
        return None
    r = rows[0]
    return {
        'id': _i(r.OrganizationId, 0),
        'name': _s(r.OrganizationName),
        'division': _s(r.DivisionName),
        'program': _s(r.ProgramName),
        'program_id': _i(r.ProgramId, 0),
        'member_count': _i(r.MemberCount, 0),
        'registration_type_id': _i(r.RegistrationTypeId, 0),
        'is_registration_form': _i(r.RegistrationTypeId, 0) == REGISTRATION_FORM_TYPE,
        'title_graphic_url': _s(r.TitleGraphicUrl) if hasattr(r, 'TitleGraphicUrl') else '',
        'badge_url': _s(r.BadgeUrl) if hasattr(r, 'BadgeUrl') else '',
    }


def _org_subgroups(org_id):
    """MemberTags on an involvement, with current member counts."""
    org_id = _i(org_id, 0)
    if org_id <= 0:
        return []
    sql = """
SELECT
    mt.Id AS SubgroupId,
    mt.Name AS SubgroupName,
    COUNT(DISTINCT CASE WHEN pe.PeopleId IS NOT NULL THEN omt.PeopleId END) AS MemberCount
FROM MemberTags mt
LEFT JOIN OrgMemMemTags omt ON omt.MemberTagId = mt.Id AND omt.OrgId = @orgId
LEFT JOIN People pe ON pe.PeopleId = omt.PeopleId AND pe.IsDeceased = 0
WHERE mt.OrgId = @orgId
GROUP BY mt.Id, mt.Name
ORDER BY mt.Name
"""
    p = _dd()
    p.AddValue('orgId', org_id)
    rows = list(q.QuerySql(sql, p))
    out = []
    for r in rows:
        sid = _i(r.SubgroupId, 0)
        if sid <= 0:
            continue
        out.append({
            'id': sid,
            'name': _s(r.SubgroupName),
            'count': _i(r.MemberCount, 0),
        })
    return out


def _map_subgroups_to_clubs(subgroups):
    """Match subgroups onto club keys. Prefer exact label match if two tags collide."""
    mapped = {}
    unmatched = []
    for sg in subgroups:
        club = _awana_club_for_name(sg.get('name'))
        if not club:
            unmatched.append(sg)
            continue
        key = club['key']
        existing = mapped.get(key)
        if not existing:
            mapped[key] = sg
        elif _s(sg.get('name')).lower() == _s(club.get('label')).lower():
            mapped[key] = sg
    return mapped, unmatched


def _awana_overview_payload():
    """Club cards from subgroups on Clubbers 1916 + Volunteers 1929."""
    denied = _require_org_access(CLUBBERS_ORG_ID)
    if denied:
        return denied

    clubbers = _org_brief(CLUBBERS_ORG_ID)
    volunteers = None
    if _user_can_access_org(VOLUNTEERS_ORG_ID):
        volunteers = _org_brief(VOLUNTEERS_ORG_ID)

    program_id = _i(clubbers.get('program_id'), 0) if clubbers else 0
    profile = _overview_profile(program_id or 1112)
    clubs = _club_shell()
    by_key = {}
    for c in clubs:
        by_key[c['key']] = c

    if clubbers:
        mapped, unmatched = _map_subgroups_to_clubs(_org_subgroups(CLUBBERS_ORG_ID))
        for key, sg in mapped.items():
            if key in by_key:
                by_key[key]['clubbers_tag_id'] = _i(sg.get('id'), 0)
                by_key[key]['clubbers_count'] = _i(sg.get('count'), 0)
    if volunteers:
        mapped_v, unmatched_v = _map_subgroups_to_clubs(_org_subgroups(VOLUNTEERS_ORG_ID))
        for key, sg in mapped_v.items():
            if key in by_key:
                by_key[key]['volunteer_tag_id'] = _i(sg.get('id'), 0)
                by_key[key]['volunteer_count'] = _i(sg.get('count'), 0)

    result = {
        'clubbers_org': clubbers,
        'volunteers_org': volunteers,
        'profile_name': profile.get('profile_name') or 'Next Generation',
        'overview_profile': profile,
        'clubs': clubs,
        'total_members': 0,
        'volunteer_members': _i(volunteers.get('member_count'), 0) if volunteers else 0,
        'show_staff_tab': _user_can_see_staff_tab(),
        'male_count': 0,
        'female_count': 0,
        'grades': [],
        'enrollment_timeline': {},
        'transactions': {
            'total': 0,
            'paid_in_full': 0,
            'remaining_balance': 0,
            'total_paid': 0.0,
            'total_due': 0.0,
        },
    }

    demo_sql = """
        SELECT
            pe.GenderId,
            COALESCE(
                NULLIF(LTRIM(RTRIM(gl_om.Description)), ''),
                NULLIF(LTRIM(RTRIM(gl_pe.Description)), ''),
                'Unknown'
            ) as GradeLabel,
            COALESCE(gl_om.Id, gl_pe.Id, 99999) as GradeSort,
            om.EnrollmentDate
        FROM OrganizationMembers om
        JOIN People pe ON om.PeopleId = pe.PeopleId
        LEFT JOIN lookup.GradeLevel gl_pe ON pe.GradeLevelId = gl_pe.Id
        LEFT JOIN lookup.GradeLevel gl_om ON om.GradeLevelId = gl_om.Id
        WHERE om.OrganizationId = @orgId
            AND pe.IsDeceased = 0
    """
    p = _dd()
    p.AddValue('orgId', CLUBBERS_ORG_ID)
    members = list(q.QuerySql(demo_sql, p))
    result['total_members'] = len(members)
    result['male_count'] = len([m for m in members if m.GenderId == 1])
    result['female_count'] = len([m for m in members if m.GenderId == 2])

    grade_counts = {}
    grade_sort = {}
    for member in members:
        label = _s(member.GradeLabel, 'Unknown') if hasattr(member, 'GradeLabel') else 'Unknown'
        if not label or label.lower() == 'unknown':
            label = 'Unknown'
        grade_counts[label] = grade_counts.get(label, 0) + 1
        if label not in grade_sort:
            grade_sort[label] = _i(member.GradeSort, 99999) if hasattr(member, 'GradeSort') else 99999

    def _grade_key(item):
        label = item[0]
        if label == 'Unknown':
            return (1, 99999, label)
        return (0, grade_sort.get(label, 99999), label)

    grades = []
    for label, count in sorted(grade_counts.items(), key=_grade_key):
        grades.append({'label': label, 'count': count})
    result['grades'] = grades

    enrollment_timeline = {}
    for member in members:
        if hasattr(member, 'EnrollmentDate') and member.EnrollmentDate:
            date_key = "{0:04d}-{1:02d}".format(member.EnrollmentDate.Year, member.EnrollmentDate.Month)
            enrollment_timeline[date_key] = enrollment_timeline.get(date_key, 0) + 1
    sorted_timeline = sorted(enrollment_timeline.items(), key=lambda x: x[0], reverse=True)[:12]
    sorted_timeline.reverse()
    result['enrollment_timeline'] = dict(sorted_timeline)

    transaction_sql = """
    ;WITH Raw AS (
        SELECT
            ISNULL(t.OriginalId, t.Id) AS GroupId,
            t.Id,
            t.Amt,
            t.Amtdue,
            t.TransactionDate
        FROM [Transaction] t
        WHERE t.OrgId = @orgId
    ),
    Grouped AS (
        SELECT
            GroupId,
            SUM(ISNULL(Amt, 0)) AS GroupPaid
        FROM Raw
        GROUP BY GroupId
        HAVING SUM(ISNULL(Amt, 0)) > 0
    ),
    Latest AS (
        SELECT
            r.GroupId,
            ISNULL(r.Amtdue, 0) AS BalanceDue,
            ROW_NUMBER() OVER (
                PARTITION BY r.GroupId
                ORDER BY r.TransactionDate DESC, r.Id DESC
            ) AS rn
        FROM Raw r
        INNER JOIN Grouped g ON g.GroupId = r.GroupId
    )
    SELECT
        COUNT(*) AS TotalTransactions,
        SUM(CASE WHEN l.BalanceDue <= 0 THEN 1 ELSE 0 END) AS PaidInFullCount,
        SUM(CASE WHEN l.BalanceDue > 0 THEN 1 ELSE 0 END) AS RemainingBalanceCount,
        SUM(g.GroupPaid) AS TotalPaid,
        SUM(CASE WHEN l.BalanceDue > 0 THEN l.BalanceDue ELSE 0 END) AS TotalDue
    FROM Grouped g
    INNER JOIN Latest l ON l.GroupId = g.GroupId AND l.rn = 1
    """
    p4 = _dd()
    p4.AddValue('orgId', CLUBBERS_ORG_ID)
    transaction_result = list(q.QuerySql(transaction_sql, p4))
    transactions = transaction_result[0] if transaction_result else None
    if transactions:
        result['transactions'] = {
            'total': int(transactions.TotalTransactions) if transactions.TotalTransactions else 0,
            'paid_in_full': int(transactions.PaidInFullCount) if transactions.PaidInFullCount else 0,
            'remaining_balance': int(transactions.RemainingBalanceCount) if transactions.RemainingBalanceCount else 0,
            'total_paid': float(transactions.TotalPaid) if transactions.TotalPaid else 0,
            'total_due': float(transactions.TotalDue) if transactions.TotalDue else 0,
        }
    return result


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
    """
    Convert any DB/CLR/byte value to a pure Python unicode string.
    Avoids IronPython's default 'unknown' codec (byte 0xF6 = ö in cp1252/latin-1).
    Never call bare unicode(bytes) or .decode() on a unicode string.
    """
    if _is_null(val):
        return default
    try:
        from System import String as NetString
        from System.Text import Encoding

        net = None

        # True Python 2 byte string (not unicode / System.String)
        try:
            is_py_bytes = isinstance(val, str) and not isinstance(val, unicode)
        except:
            is_py_bytes = False

        if is_py_bytes:
            # latin-1 accepts every byte (0xF6 -> ö)
            s = val.decode('latin-1').strip()
        else:
            # System.String / unicode / numbers / other CLR objects
            try:
                if isinstance(val, NetString):
                    net = val
                else:
                    net = NetString.Format('{0}', val)
            except:
                try:
                    net = NetString(val.ToString())
                except:
                    return default

            if net is None:
                return default

            # Round-trip via UTF-8 bytes -> Python unicode (detaches from CLR quirks)
            utf8 = Encoding.UTF8.GetBytes(net)
            buf = []
            i = 0
            while i < utf8.Length:
                buf.append(chr(utf8[i] & 0xFF))
                i += 1
            s = ''.join(buf).decode('utf-8').strip()

        if s == '' or s == 'None' or s == 'null':
            return default
        return s
    except:
        # Last resort: keep only ASCII
        try:
            raw = repr(val)
            out = []
            for ch in raw:
                try:
                    o = ord(ch)
                    if 32 <= o <= 126:
                        out.append(chr(o))
                except:
                    pass
            s = ''.join(out).strip()
            return s if s else default
        except:
            return default


def _i(val, default=0):
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


def _fmt_date(val):
    """M/d/yyyy from a DateTime / SQL date, or empty."""
    if val is None or _is_null(val):
        return ''
    try:
        return val.ToString('M/d/yyyy')
    except:
        s = _s(val)
        if not s:
            return ''
        if ' ' in s:
            s = s.split(' ')[0]
        return s


def _fmt_date_or_str(date_val, str_val):
    d = _fmt_date(date_val)
    if d:
        return d
    raw = _s(str_val)
    if not raw or raw.lower().startswith('unknown type'):
        return ''
    try:
        from System import DateTime
        return DateTime.Parse(raw).ToString('M/d/yyyy')
    except:
        if '/' in raw or '-' in raw:
            return raw
        return ''


def _fmt_iso(date_val, str_val):
    """yyyy-MM-dd for HTML date inputs."""
    if date_val is not None and not _is_null(date_val):
        try:
            return date_val.ToString('yyyy-MM-dd')
        except:
            pass
    raw = _fmt_date_or_str(date_val, str_val)
    if not raw:
        return ''
    try:
        from System import DateTime
        return DateTime.Parse(raw).ToString('yyyy-MM-dd')
    except:
        return ''


def _join_labels(parts, sep='; '):
    out = []
    for p in parts:
        s = _s(p)
        if s:
            out.append(s)
    return sep.join(out)


def _user_can_see_staff_tab():
    """Admins see Staff. Everyone else needs both Staff and Next Gen."""
    try:
        if model.UserIsInRole('Admin'):
            return True
        return bool(model.UserIsInRole('Staff')) and bool(model.UserIsInRole('Next Gen'))
    except:
        return False


def _is_volunteer_member(people_id):
    people_id = _i(people_id, 0)
    if people_id <= 0:
        return False
    sql = """
SELECT TOP 1 om.PeopleId, pe.Age
FROM dbo.OrganizationMembers om
INNER JOIN dbo.People pe ON pe.PeopleId = om.PeopleId
WHERE om.OrganizationId = @orgId
  AND om.PeopleId = @pid
  AND pe.IsDeceased = 0
"""
    p = _dd()
    p.AddValue('orgId', VOLUNTEERS_ORG_ID)
    p.AddValue('pid', people_id)
    try:
        rows = list(q.QuerySql(sql, p))
        return len(rows) > 0
    except:
        return False


def _volunteer_is_minor(people_id):
    """True when volunteer Age is known and <= 17."""
    people_id = _i(people_id, 0)
    if people_id <= 0:
        return False
    sql = """
SELECT TOP 1 pe.Age
FROM dbo.OrganizationMembers om
INNER JOIN dbo.People pe ON pe.PeopleId = om.PeopleId
WHERE om.OrganizationId = @orgId
  AND om.PeopleId = @pid
  AND pe.IsDeceased = 0
"""
    p = _dd()
    p.AddValue('orgId', VOLUNTEERS_ORG_ID)
    p.AddValue('pid', people_id)
    try:
        rows = list(q.QuerySql(sql, p))
    except:
        return False
    if not rows:
        return False
    age_val = rows[0].Age if hasattr(rows[0], 'Age') else None
    if age_val is None or _is_null(age_val):
        return False
    age = _i(age_val, -1)
    return age >= 0 and age <= MINOR_MAX_AGE


def _set_awana_ev_date(people_id, field_key, date_str):
    """Write training Extra Values. Minors use Child Protection EV; handbook is N/A."""
    if not _user_can_see_staff_tab():
        return {'error': 'Not authorized'}
    denied = _require_org_access(VOLUNTEERS_ORG_ID)
    if denied:
        return denied
    people_id = _i(people_id, 0)
    if people_id <= 0:
        return {'error': 'Invalid person'}
    if not _is_volunteer_member(people_id):
        return {'error': 'Person is not an Awana volunteer'}
    field_key = _s(field_key)
    is_minor = _volunteer_is_minor(people_id)
    if field_key == 'handbook':
        if is_minor:
            return {'error': 'Handbook is not applicable for minors'}
        field = EV_AWANA_HANDBOOK
    elif field_key == 'inperson':
        field = EV_MINOR_INPERSON if is_minor else EV_AWANA_INPERSON
    else:
        return {'error': 'Invalid field'}
    date_str = _s(date_str).strip()
    if not date_str:
        try:
            model.DeleteExtraValue(people_id, field)
        except:
            pass
        return {'ok': True, 'field': field_key, 'date': '', 'iso': ''}
    try:
        from System import DateTime
        dt = DateTime.Parse(date_str)
        model.AddExtraValueDate(people_id, field, dt)
        return {
            'ok': True,
            'field': field_key,
            'date': dt.ToString('M/d/yyyy'),
            'iso': dt.ToString('yyyy-MM-dd'),
        }
    except:
        return {'error': 'Could not save date'}


def _dd():
    return model.DynamicData()


def _data(name, default=None):
    if hasattr(model.Data, name):
        return getattr(model.Data, name)
    return default


# ---------------------------------------------------------------------------
# Org visibility (mirrors dbo.OrgSearch: LimitToRole + OrgLeadersOnly)
# ---------------------------------------------------------------------------

# Applied to queries that alias Organizations as o. Params: @userId, @pid, @olo
_ORG_ACCESS_SQL = """
  AND (
        o.LimitToRole IS NULL
        OR EXISTS (
            SELECT NULL
            FROM dbo.Roles r
            INNER JOIN dbo.UserRole ur ON ur.RoleId = r.RoleId
            WHERE ur.UserId = @userId
              AND r.RoleName = o.LimitToRole
        )
      )
  AND (
        @olo = 0
        OR EXISTS (
            SELECT NULL
            FROM (
                SELECT om.OrganizationId AS OrgId
                FROM dbo.OrganizationMembers om
                WHERE om.PeopleId = @pid
                UNION
                SELECT o2.OrganizationId
                FROM dbo.Organizations o2
                WHERE o2.ParentOrgId IN (
                    SELECT om.OrganizationId
                    FROM dbo.OrganizationMembers om
                    WHERE om.PeopleId = @pid
                )
                UNION
                SELECT o3.OrganizationId
                FROM dbo.Organizations o3
                WHERE o3.ParentOrgId IN (
                    SELECT o2.OrganizationId
                    FROM dbo.Organizations o2
                    WHERE o2.ParentOrgId IN (
                        SELECT om.OrganizationId
                        FROM dbo.OrganizationMembers om
                        WHERE om.PeopleId = @pid
                    )
                )
            ) allowed
            WHERE allowed.OrgId = o.OrganizationId
        )
      )
"""


def _auth_context():
    """Current user PeopleId / UserId and OrgLeadersOnly flag."""
    pid = 0
    try:
        if model.UserPeopleId:
            pid = int(model.UserPeopleId)
    except:
        pid = 0
    olo = False
    try:
        olo = bool(model.UserIsInRole('OrgLeadersOnly'))
    except:
        olo = False
    uid = 0
    if pid > 0:
        try:
            p = _dd()
            p.AddValue('pid', pid)
            rows = list(q.QuerySql(
                "SELECT TOP 1 UserId FROM dbo.Users WHERE PeopleId = @pid ORDER BY UserId",
                p
            ))
            if rows:
                uid = _i(rows[0].UserId, 0)
        except:
            uid = 0
    return {
        'people_id': pid,
        'user_id': uid,
        'olo': 1 if olo else 0,
    }


def _bind_org_access(params):
    """Add @userId, @pid, @olo to a DynamicData param bag."""
    auth = _auth_context()
    params.AddValue('userId', auth['user_id'])
    params.AddValue('pid', auth['people_id'])
    params.AddValue('olo', auth['olo'])
    return auth


def _user_can_access_org(org_id):
    """True if current user may see this involvement (OrgSearch rules)."""
    org_id = _i(org_id, 0)
    if org_id <= 0:
        return False
    auth = _auth_context()
    if auth['people_id'] <= 0:
        return False
    sql = """
SELECT TOP 1 o.OrganizationId
FROM dbo.Organizations o
WHERE o.OrganizationId = @orgId
""" + _ORG_ACCESS_SQL
    p = _dd()
    p.AddValue('orgId', org_id)
    _bind_org_access(p)
    try:
        rows = list(q.QuerySql(sql, p))
        return len(rows) > 0
    except:
        return False


def _require_org_access(org_id):
    """Return an error dict if access is denied; otherwise None."""
    if _i(org_id, 0) <= 0:
        return {'error': 'Invalid involvement'}
    if not _user_can_access_org(org_id):
        return {'error': 'You do not have access to this involvement.'}
    return None


def _json_safe(obj):
    """Recursively coerce values to JSON-friendly Python types."""
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    try:
        if isinstance(obj, (int, long)) and not isinstance(obj, bool):
            return int(obj)
        if isinstance(obj, float):
            return float(obj)
    except:
        try:
            if isinstance(obj, int) and not isinstance(obj, bool):
                return int(obj)
            if isinstance(obj, float):
                return float(obj)
        except:
            pass
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            out[_s(k, u'')] = _json_safe(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    # CLR Decimal / numeric
    try:
        from System import Decimal as NetDecimal
        if isinstance(obj, NetDecimal):
            return float(obj)
    except:
        pass
    try:
        if not isinstance(obj, (str, unicode)):
            return float(obj)
    except:
        pass
    return _s(obj, u'')


def _json_quote(s):
    """Quote a string as ASCII-only JSON (\\uXXXX for non-ASCII)."""
    s = _s(s, u'')
    parts = ['"']
    for ch in s:
        o = ord(ch)
        if ch == u'"':
            parts.append('\\"')
        elif ch == u'\\':
            parts.append('\\\\')
        elif ch == u'\b':
            parts.append('\\b')
        elif ch == u'\f':
            parts.append('\\f')
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
    """Manual JSON serializer — avoids IronPython json.dumps codec issues."""
    obj = _json_safe(obj)
    return _json_dump_raw(obj)


def _json_dump_raw(obj):
    if obj is None:
        return 'null'
    if obj is True:
        return 'true'
    if obj is False:
        return 'false'
    try:
        if isinstance(obj, (int, long)) and not isinstance(obj, bool):
            return str(int(obj))
    except:
        if isinstance(obj, int) and not isinstance(obj, bool):
            return str(int(obj))
    if isinstance(obj, float):
        # Ensure JSON-legal number formatting
        try:
            if obj != obj:  # NaN
                return 'null'
            if obj == float('inf') or obj == float('-inf'):
                return 'null'
        except:
            pass
        return repr(float(obj))
    if isinstance(obj, dict):
        items = []
        for k, v in obj.items():
            items.append(_json_quote(_s(k)) + ':' + _json_dump_raw(v))
        return '{' + ','.join(items) + '}'
    if isinstance(obj, (list, tuple)):
        return '[' + ','.join([_json_dump_raw(x) for x in obj]) + ']'
    return _json_quote(_s(obj))


def _json_out(obj):
    print _json_dump(obj)


def _err_out(e):
    """Safe AJAX error payload (exception text can also contain non-ASCII)."""
    try:
        tb = _s(traceback.format_exc())
    except:
        tb = ''
    _json_out({'error': _s(e), 'traceback': tb})


def _parse_answer(raw):
    """Parse RegAnswer.AnswerValue (usually JSON string / array)."""
    s = _s(raw)
    if not s:
        return None
    try:
        return json.loads(s)
    except:
        return s


def _answer_display(val, question_type_id, sub_type_id, options):
    """Human-readable answer for text/export/person view."""
    if val is None:
        return ''
    if question_type_id == QTYPE_EMERGENCY:
        parts = _s(val).split('\n')
        name = _s(parts[0] if parts else '')
        phone = _s(parts[1] if len(parts) > 1 else '')
        if name and phone:
            return name + ' / ' + phone
        return name or phone
    if question_type_id == QTYPE_PARENTS:
        parts = _s(val).split('\n')
        mother = _s(parts[0] if parts else '')
        father = _s(parts[1] if len(parts) > 1 else '')
        bits = []
        if mother:
            bits.append('Mother: ' + mother)
        if father:
            bits.append('Father: ' + father)
        return '; '.join(bits)
    if sub_type_id == SUBTYPE_MENU and isinstance(val, list) and options:
        bits = []
        i = 0
        while i < len(options) and i < len(val):
            qty = _s(val[i])
            if qty and qty != '0':
                bits.append(_s(options[i].get('text'), 'Option') + ': ' + qty)
            i += 1
        return '; '.join(bits)
    if isinstance(val, list):
        return ', '.join([_s(x) for x in val if _s(x)])
    return _s(val)


def _is_blank_answer(val):
    if val is None:
        return True
    if isinstance(val, list):
        for x in val:
            if _s(x) and _s(x) != '0':
                return False
        return True
    s = _s(val)
    if not s:
        return True
    # Emergency/Parents often store "null\nnull"
    if s.replace('\n', '').replace('null', '').strip() == '':
        return True
    return False


def _parse_options(options_json):
    raw = _s(options_json)
    if not raw:
        return []
    try:
        opts = json.loads(raw)
    except:
        return []
    result = []
    if not isinstance(opts, list):
        return result
    for o in opts:
        if not isinstance(o, dict):
            continue
        text = _s(o.get('text') or o.get('Text'))
        value = _s(o.get('value') or o.get('Value') or text)
        lookup = _s(o.get('lookup') or o.get('Lookup'))
        result.append({
            'text': text or value or lookup,
            'value': value or text or lookup,
            'lookup': lookup,
            'other': bool(o.get('other') or o.get('Other')),
        })
    return result


def _option_key(o):
    """Unique option identity for counting.

    When Save as SubGroup is on, option.value is the SubGroup name and can be
    shared (e.g. 6th/7th/8th all value=Middle School). Prefer text, then lookup.
    """
    return _s(o.get('text')) or _s(o.get('lookup')) or _s(o.get('value'))


def _choice_selected_values(parsed, options, sub_type_id):
    """Return list of option keys this answer selected (for counting)."""
    selected = []
    if parsed is None:
        return selected
    if sub_type_id == SUBTYPE_MENU and isinstance(parsed, list):
        i = 0
        while i < len(options) and i < len(parsed):
            qty = _s(parsed[i])
            if qty and qty != '0':
                selected.append(_option_key(options[i]))
            i += 1
        return selected

    # Shared SubGroup values must not match every grade that uses that SubGroup
    value_uses = {}
    for o in options:
        v = _s(o.get('value'))
        if v:
            value_uses[v] = value_uses.get(v, 0) + 1

    opt_by_text = {}
    opt_by_lookup = {}
    opt_by_value = {}
    for o in options:
        key = _option_key(o)
        t = _s(o.get('text'))
        lk = _s(o.get('lookup'))
        v = _s(o.get('value'))
        if t:
            opt_by_text[t] = key
        if lk:
            opt_by_lookup[lk] = key
        # Only match on value when it uniquely identifies one option
        if v and value_uses.get(v, 0) == 1:
            opt_by_value[v] = key

    values = parsed if isinstance(parsed, list) else [parsed]
    for v in values:
        sv = _s(v)
        if not sv:
            continue
        if sv in opt_by_text:
            selected.append(opt_by_text[sv])
        elif sv in opt_by_lookup:
            selected.append(opt_by_lookup[sv])
        elif sv in opt_by_value:
            selected.append(opt_by_value[sv])
        else:
            # Free-text "Other" or unmatched — count under raw value
            selected.append(sv)
    return selected


def _org_meta(org_id):
    sql = """
SELECT o.OrganizationId, o.OrganizationName, o.RegistrationTypeId,
       d.Name AS DivisionName, p.Name AS ProgramName
FROM Organizations o
LEFT JOIN Division d ON o.DivisionId = d.Id
LEFT JOIN Program p ON d.ProgId = p.Id
WHERE o.OrganizationId = @orgId
"""
    p = _dd()
    p.AddValue('orgId', org_id)
    rows = list(q.QuerySql(sql, p))
    if not rows:
        return None
    return rows[0]


def _completed_registrants(org_id, subgroup_id=0):
    """Most recent completed RegPeople per PeopleId for the involvement."""
    tag_id = _i(subgroup_id, 0)
    sql = """
;WITH Ranked AS (
    SELECT
        rp.RegPeopleId,
        rp.PeopleId,
        rp.CompletedDate,
        ISNULL(pe.Name2, LTRIM(RTRIM(ISNULL(rp.FirstName,'') + ' ' + ISNULL(rp.LastName,'')))) AS PersonName,
        ROW_NUMBER() OVER (
            PARTITION BY rp.PeopleId
            ORDER BY rp.CompletedDate DESC, rp.RegPeopleId
        ) AS rn
    FROM dbo.RegPeople rp
    INNER JOIN dbo.Registration r ON r.RegistrationId = rp.RegistrationId
    LEFT JOIN dbo.People pe ON pe.PeopleId = rp.PeopleId
    WHERE r.OrganizationId = @orgId
      AND rp.Status = @status
      AND rp.CompletedDate IS NOT NULL
      AND rp.PeopleId IS NOT NULL
      AND (
            @tagId = 0
            OR EXISTS (
                SELECT 1
                FROM dbo.OrgMemMemTags omt
                WHERE omt.OrgId = @orgId
                  AND omt.MemberTagId = @tagId
                  AND omt.PeopleId = rp.PeopleId
            )
          )
)
SELECT RegPeopleId, PeopleId, CompletedDate, PersonName
FROM Ranked
WHERE rn = 1
ORDER BY PersonName
"""
    p = _dd()
    p.AddValue('orgId', org_id)
    p.AddValue('status', STATUS_COMPLETED)
    p.AddValue('tagId', tag_id)
    return list(q.QuerySql(sql, p))


def _questions_for_org(org_id):
    sql = """
SELECT RegQuestionId, [Order], Label, QuestionTypeId, QuestionSubTypeId,
       IsRequired, IsDisabled, Options
FROM dbo.RegQuestion
WHERE OrganizationId = @orgId
  AND ISNULL(IsDisabled, 0) = 0
ORDER BY [Order], Label
"""
    p = _dd()
    p.AddValue('orgId', org_id)
    return list(q.QuerySql(sql, p))


def _answers_for_registrants(org_id, question_ids, subgroup_id=0):
    """All answers for completed registrants (most recent per person) for given questions."""
    if not question_ids:
        return []
    tag_id = _i(subgroup_id, 0)
    # Build IN list of quoted guids (safe: from our own query)
    id_list = ','.join(["'" + _s(qid).replace("'", "") + "'" for qid in question_ids])
    sql = """
;WITH Ranked AS (
    SELECT
        rp.RegPeopleId,
        rp.PeopleId,
        ROW_NUMBER() OVER (
            PARTITION BY rp.PeopleId
            ORDER BY rp.CompletedDate DESC, rp.RegPeopleId
        ) AS rn
    FROM dbo.RegPeople rp
    INNER JOIN dbo.Registration r ON r.RegistrationId = rp.RegistrationId
    WHERE r.OrganizationId = @orgId
      AND rp.Status = @status
      AND rp.CompletedDate IS NOT NULL
      AND rp.PeopleId IS NOT NULL
      AND (
            @tagId = 0
            OR EXISTS (
                SELECT 1
                FROM dbo.OrgMemMemTags omt
                WHERE omt.OrgId = @orgId
                  AND omt.MemberTagId = @tagId
                  AND omt.PeopleId = rp.PeopleId
            )
          )
)
SELECT ra.RegQuestionId, ra.RegPeopleId, ra.AnswerValue,
       rk.PeopleId,
       ISNULL(pe.Name2, '') AS PersonName
FROM Ranked rk
INNER JOIN dbo.RegAnswer ra ON ra.RegPeopleId = rk.RegPeopleId
LEFT JOIN dbo.People pe ON pe.PeopleId = rk.PeopleId
WHERE rk.rn = 1
  AND ra.RegQuestionId IN ({0})
""".format(id_list)
    p = _dd()
    p.AddValue('orgId', org_id)
    p.AddValue('status', STATUS_COMPLETED)
    p.AddValue('tagId', tag_id)
    return list(q.QuerySql(sql, p))


def _build_registration_summary(org_id, subgroup_id=0):
    org = _org_meta(org_id)
    if not org:
        return {'error': 'Organization not found'}

    reg_type = _i(org.RegistrationTypeId, 0)
    if reg_type != REGISTRATION_FORM_TYPE:
        return {
            'is_registration_form': False,
            'org_name': _s(org.OrganizationName),
            'message': 'This involvement is not using the new Registration Form architecture. Registration question summaries are only available for Registration Form involvements.',
            'questions': [],
            'completed_count': 0,
            'empty': True,
        }

    registrants = _completed_registrants(org_id, subgroup_id)
    completed_count = len(registrants)
    questions = _questions_for_org(org_id)

    overview_qs = []
    for qrow in questions:
        qt = _i(qrow.QuestionTypeId, 0)
        if qt in OVERVIEW_CHOICE_TYPES or qt in OVERVIEW_TEXT_TYPES:
            overview_qs.append(qrow)
        # Money and structural types intentionally skipped

    if not overview_qs:
        return {
            'is_registration_form': True,
            'org_name': _s(org.OrganizationName),
            'completed_count': completed_count,
            'questions': [],
            'empty': True,
            'message': 'No registration questions are configured for this involvement yet.',
        }

    qids = [_s(qrow.RegQuestionId) for qrow in overview_qs]
    answers = _answers_for_registrants(org_id, qids, subgroup_id)

    # Index answers by question
    by_q = {}
    for a in answers:
        qid = _s(a.RegQuestionId)
        if qid not in by_q:
            by_q[qid] = []
        by_q[qid].append(a)

    result_questions = []

    for qrow in overview_qs:
        qid = _s(qrow.RegQuestionId)
        qt = _i(qrow.QuestionTypeId, 0)
        st = _i(qrow.QuestionSubTypeId, 0) if not _is_null(qrow.QuestionSubTypeId) else 0
        label = _s(qrow.Label, '(Untitled question)')
        options = _parse_options(qrow.Options)
        q_answers = by_q.get(qid, [])

        answered_people = set()
        blank_count = 0
        parsed_by_person = []

        # Map RegPeopleId -> answer for this question
        ans_by_rp = {}
        for a in q_answers:
            ans_by_rp[_s(a.RegPeopleId)] = a

        for reg in registrants:
            rp_id = _s(reg.RegPeopleId)
            a = ans_by_rp.get(rp_id)
            parsed = _parse_answer(a.AnswerValue) if a else None
            if _is_blank_answer(parsed):
                blank_count += 1
            else:
                answered_people.add(_i(reg.PeopleId))
                parsed_by_person.append({
                    'people_id': _i(reg.PeopleId),
                    'name': _s(reg.PersonName),
                    'parsed': parsed,
                    'raw_display': _answer_display(parsed, qt, st, options),
                })

        answered_count = len(answered_people)
        # blank_count already counts registrants with no/blank answer
        item = {
            'id': qid,
            'label': label,
            'type_id': qt,
            'sub_type_id': st,
            'answered': answered_count,
            'blank': blank_count,
        }

        if qt in OVERVIEW_CHOICE_TYPES:
            item['kind'] = 'choice'
            counts = {}
            for o in options:
                counts[_option_key(o)] = 0
            other_counts = {}
            for row in parsed_by_person:
                for sel in _choice_selected_values(row['parsed'], options, st):
                    if sel in counts:
                        counts[sel] += 1
                    else:
                        other_counts[sel] = other_counts.get(sel, 0) + 1
            opt_out = []
            # Only "How did you hear..." collapses free-text / Other into one group.
            # Grade and similar dropdowns list each answer as its own bar.
            collapse_other = _is_hear_about_question(label)
            other_variants = []
            other_total = 0
            for o in options:
                key = _option_key(o)
                c = counts.get(key, 0)
                pct = int(round((100.0 * c / answered_count), 0)) if answered_count else 0
                if collapse_other and o.get('other'):
                    if c > 0:
                        other_variants.append({
                            'value': key,
                            'text': o['text'],
                            'count': c,
                            'pct': pct,
                        })
                        other_total += c
                    continue
                opt_out.append({
                    'value': key,
                    'text': o['text'],
                    'count': c,
                    'pct': pct,
                })
            for ov, c in sorted(other_counts.items(), key=lambda x: (-x[1], x[0])):
                pct = int(round((100.0 * c / answered_count), 0)) if answered_count else 0
                if collapse_other:
                    other_variants.append({
                        'value': ov,
                        'text': ov + ' (other)',
                        'count': c,
                        'pct': pct,
                    })
                    other_total += c
                else:
                    opt_out.append({
                        'value': ov,
                        'text': ov,
                        'count': c,
                        'pct': pct,
                    })
            if collapse_other and other_variants:
                other_pct = int(round((100.0 * other_total / answered_count), 0)) if answered_count else 0
                opt_out.append({
                    'value': '__other__',
                    'text': 'Other',
                    'count': other_total,
                    'pct': other_pct,
                    'is_other_group': True,
                    'variant_count': len(other_variants),
                    'variants': other_variants,
                })
            item['options'] = [o for o in opt_out if _i(o.get('count'), 0) > 0]
        else:
            item['kind'] = 'text'
            previews = []
            for row in parsed_by_person[:5]:
                disp = row['raw_display']
                if len(disp) > 80:
                    disp = disp[:77] + '...'
                previews.append(disp)
            item['preview'] = previews

        if answered_count <= 0:
            continue
        result_questions.append(item)

    empty = completed_count == 0 or (
        sum([qitem['answered'] for qitem in result_questions]) == 0
        and len(result_questions) > 0
        and all(qitem['answered'] == 0 for qitem in result_questions)
    )

    return {
        'is_registration_form': True,
        'org_name': _s(org.OrganizationName),
        'completed_count': completed_count,
        'questions': result_questions,
        'empty': empty and len(result_questions) == 0,
        'message': (
            'No completed registration answers yet.'
            if completed_count == 0
            else (
                'No questions with answers for this club.'
                if len(result_questions) == 0
                else ''
            )
        ),
    }


def _get_option_people(org_id, question_id, option_value, subgroup_id=0):
    questions = _questions_for_org(org_id)
    qrow = None
    for q in questions:
        if _s(q.RegQuestionId) == _s(question_id):
            qrow = q
            break
    if not qrow:
        return {'error': 'Question not found'}

    qt = _i(qrow.QuestionTypeId, 0)
    st = _i(qrow.QuestionSubTypeId, 0) if not _is_null(qrow.QuestionSubTypeId) else 0
    options = _parse_options(qrow.Options)
    registrants = _completed_registrants(org_id, subgroup_id)
    answers = _answers_for_registrants(org_id, [_s(question_id)], subgroup_id)
    ans_by_rp = {}
    for a in answers:
        ans_by_rp[_s(a.RegPeopleId)] = a

    target = _s(option_value)
    configured_other = {}
    known_keys = {}
    for o in options:
        key = _option_key(o)
        known_keys[key] = True
        if o.get('other'):
            configured_other[key] = True

    people = []
    for reg in registrants:
        a = ans_by_rp.get(_s(reg.RegPeopleId))
        parsed = _parse_answer(a.AnswerValue) if a else None
        if _is_blank_answer(parsed):
            continue
        selected = _choice_selected_values(parsed, options, st)
        match = False
        if target == '__other__':
            for sel in selected:
                if sel in configured_other or sel not in known_keys:
                    match = True
                    break
        elif target in selected:
            match = True
        if match:
            people.append({
                'people_id': _i(reg.PeopleId),
                'name': _s(reg.PersonName),
                'answer': _answer_display(parsed, qt, st, options),
            })
    return {
        'question_id': _s(question_id),
        'question_label': _s(qrow.Label),
        'option_value': target,
        'people': people,
    }


def _get_allergy_people(org_id, subgroup_id=0):
    """Org members with a real allergy note on RecReg (default allergies list)."""
    tag_id = _i(subgroup_id, 0)
    sql = """
SELECT
    pe.PeopleId,
    ISNULL(pe.Name2, LTRIM(RTRIM(ISNULL(pe.FirstName,'') + ' ' + ISNULL(pe.LastName,'')))) AS PersonName,
    ISNULL(rr.MedicalDescription, '') AS AllergyText
FROM OrganizationMembers om
INNER JOIN People pe ON pe.PeopleId = om.PeopleId
LEFT JOIN RecReg rr ON rr.PeopleId = pe.PeopleId
WHERE om.OrganizationId = @orgId
  AND (
        @tagId = 0
        OR EXISTS (
            SELECT 1
            FROM dbo.OrgMemMemTags omt
            WHERE omt.OrgId = @orgId
              AND omt.MemberTagId = @tagId
              AND omt.PeopleId = om.PeopleId
        )
      )
ORDER BY PersonName
"""
    p = _dd()
    p.AddValue('orgId', org_id)
    p.AddValue('tagId', tag_id)
    rows = list(q.QuerySql(sql, p))
    people = []
    for r in rows:
        allergy = _s(r.AllergyText)
        if not _allergy_text_meaningful(allergy):
            continue
        people.append({
            'people_id': _i(r.PeopleId),
            'name': _s(r.PersonName),
            'allergy': allergy,
        })
    return {
        'count': len(people),
        'people': people,
    }


def _get_contact_people(org_id, subgroup_id=0):
    """Org members with parent and/or emergency contact data from RecReg stock fields."""
    tag_id = _i(subgroup_id, 0)
    sql = """
SELECT
    pe.PeopleId,
    ISNULL(pe.Name2, LTRIM(RTRIM(ISNULL(pe.FirstName,'') + ' ' + ISNULL(pe.LastName,'')))) AS PersonName,
    ISNULL(rr.mname, '') AS MotherName,
    ISNULL(rr.fname, '') AS FatherName,
    ISNULL(rr.emcontact, '') AS EmContact,
    ISNULL(rr.emphone, '') AS EmPhone
FROM OrganizationMembers om
INNER JOIN People pe ON pe.PeopleId = om.PeopleId
LEFT JOIN RecReg rr ON rr.PeopleId = pe.PeopleId
WHERE om.OrganizationId = @orgId
  AND (
        @tagId = 0
        OR EXISTS (
            SELECT 1
            FROM dbo.OrgMemMemTags omt
            WHERE omt.OrgId = @orgId
              AND omt.MemberTagId = @tagId
              AND omt.PeopleId = om.PeopleId
        )
      )
ORDER BY PersonName
"""
    p = _dd()
    p.AddValue('orgId', org_id)
    p.AddValue('tagId', tag_id)
    rows = list(q.QuerySql(sql, p))
    people = []
    for r in rows:
        mother = _s(r.MotherName)
        father = _s(r.FatherName)
        em_contact = _s(r.EmContact)
        em_phone = _s(r.EmPhone)
        if not (mother or father or em_contact or em_phone):
            continue
        people.append({
            'people_id': _i(r.PeopleId),
            'name': _s(r.PersonName),
            'mother': mother,
            'father': father,
            'em_contact': em_contact,
            'em_phone': em_phone,
        })
    return {
        'count': len(people),
        'people': people,
    }


def _app_org_in_sql():
    """Safe IN-list of application org ids (ints only)."""
    ids = []
    for oid in APP_ORG_IDS:
        n = _i(oid, 0)
        if n > 0:
            ids.append(str(n))
    return ','.join(ids) if ids else '0'


def _volunteer_clubs_by_people(org_id):
    """PeopleId -> Awana club labels (display order) for volunteer org tags."""
    org_id = _i(org_id, 0)
    out = {}
    if org_id <= 0:
        return out
    sql = """
SELECT omt.PeopleId, mt.Name AS TagName
FROM dbo.OrgMemMemTags omt
INNER JOIN dbo.MemberTags mt ON mt.Id = omt.MemberTagId
WHERE omt.OrgId = @orgId
"""
    p = _dd()
    p.AddValue('orgId', org_id)
    order = [c['label'] for c in AWANA_CLUBS]
    for r in list(q.QuerySql(sql, p)):
        club = _awana_club_for_name(_s(r.TagName) if hasattr(r, 'TagName') else '')
        if not club:
            continue
        pid = _i(r.PeopleId)
        labels = out.setdefault(pid, [])
        lab = club['label']
        if lab not in labels:
            labels.append(lab)
    for pid in out:
        out[pid] = sorted(out[pid], key=lambda x: order.index(x) if x in order else 99)
    return out


def _get_club_roster(org_id, subgroup_id=0, include_staff=False):
    """Org members (optionally one subgroup) for clubber/volunteer lists and CSV."""
    tag_id = _i(subgroup_id, 0)
    staff_select = ''
    staff_join = ''
    if include_staff:
        staff_select = """,
    pmm.CompletedDate AS BgDate,
    mst.CompletedDate AS VideoDate,
    app.AppDate AS AppDate,
    app.AppOrgId AS AppOrgId,
    ev_tr.DateValue AS InPersonDate,
    ev_tr.StrValue AS InPersonStr,
    ev_tr_min.DateValue AS MinorInPersonDate,
    ev_tr_min.StrValue AS MinorInPersonStr,
    ev_hb.DateValue AS HandbookDate,
    ev_hb.StrValue AS HandbookStr
"""
        staff_join = """
OUTER APPLY (
    SELECT TOP 1 COALESCE(bg.Updated, bg.Created) AS CompletedDate
    FROM dbo.BackgroundChecks bg
    WHERE bg.PeopleID = pe.PeopleId
      AND bg.ReportTypeID = @pmmType
      AND bg.StatusID = @bgComplete
    ORDER BY COALESCE(bg.Updated, bg.Created) DESC, bg.ID DESC
) pmm
OUTER APPLY (
    SELECT TOP 1 COALESCE(bg.Updated, bg.Created) AS CompletedDate
    FROM dbo.BackgroundChecks bg
    WHERE bg.PeopleID = pe.PeopleId
      AND bg.ReportTypeID = @msTrainType
      AND bg.StatusID = @bgComplete
    ORDER BY COALESCE(bg.Updated, bg.Created) DESC, bg.ID DESC
) mst
OUTER APPLY (
    SELECT TOP 1 omapp.EnrollmentDate AS AppDate, omapp.OrganizationId AS AppOrgId
    FROM dbo.OrganizationMembers omapp
    WHERE omapp.PeopleId = pe.PeopleId
      AND omapp.OrganizationId IN (""" + _app_org_in_sql() + """)
    ORDER BY omapp.EnrollmentDate DESC
) app
LEFT JOIN dbo.PeopleExtra ev_tr
    ON ev_tr.PeopleId = pe.PeopleId AND ev_tr.Field = @inPersonField
LEFT JOIN dbo.PeopleExtra ev_tr_min
    ON ev_tr_min.PeopleId = pe.PeopleId AND ev_tr_min.Field = @minorInPersonField
LEFT JOIN dbo.PeopleExtra ev_hb
    ON ev_hb.PeopleId = pe.PeopleId AND ev_hb.Field = @handbookField
"""
    sql = """
SELECT
    pe.PeopleId,
    ISNULL(pe.Name2, LTRIM(RTRIM(ISNULL(pe.FirstName,'') + ' ' + ISNULL(pe.LastName,'')))) AS PersonName,
    ISNULL(pe.FirstName, '') AS FirstName,
    ISNULL(pe.LastName, '') AS LastName,
    ISNULL(pe.EmailAddress, '') AS Email,
    pe.Age,
    COALESCE(
        NULLIF(LTRIM(RTRIM(gl_om.Description)), ''),
        NULLIF(LTRIM(RTRIM(gl_pe.Description)), ''),
        ''
    ) AS GradeLabel,
    CASE pe.GenderId WHEN 1 THEN 'Male' WHEN 2 THEN 'Female' ELSE '' END AS Gender,
    ISNULL(rr.MedicalDescription, '') AS AllergyText,
    ISNULL(rr.mname, '') AS MotherName,
    ISNULL(rr.fname, '') AS FatherName,
    ISNULL(rr.emcontact, '') AS EmContact,
    ISNULL(rr.emphone, '') AS EmPhone
""" + staff_select + """
FROM OrganizationMembers om
INNER JOIN People pe ON pe.PeopleId = om.PeopleId
LEFT JOIN lookup.GradeLevel gl_pe ON pe.GradeLevelId = gl_pe.Id
LEFT JOIN lookup.GradeLevel gl_om ON om.GradeLevelId = gl_om.Id
LEFT JOIN RecReg rr ON rr.PeopleId = pe.PeopleId
""" + staff_join + """
WHERE om.OrganizationId = @orgId
  AND pe.IsDeceased = 0
  AND (
        @tagId = 0
        OR EXISTS (
            SELECT 1
            FROM dbo.OrgMemMemTags omt
            WHERE omt.OrgId = @orgId
              AND omt.MemberTagId = @tagId
              AND omt.PeopleId = om.PeopleId
        )
      )
ORDER BY PersonName
"""
    p = _dd()
    p.AddValue('orgId', org_id)
    p.AddValue('tagId', tag_id)
    if include_staff:
        p.AddValue('pmmType', BG_REPORT_PMM)
        p.AddValue('msTrainType', BG_REPORT_MS_TRAINING)
        p.AddValue('bgComplete', BG_STATUS_COMPLETE)
        p.AddValue('inPersonField', EV_AWANA_INPERSON)
        p.AddValue('minorInPersonField', EV_MINOR_INPERSON)
        p.AddValue('handbookField', EV_AWANA_HANDBOOK)
    rows = list(q.QuerySql(sql, p))
    people = []
    for r in rows:
        age_val = r.Age if hasattr(r, 'Age') else None
        if age_val is None or _is_null(age_val):
            age = None
            is_minor = False
        else:
            age = _i(age_val, -1)
            if age < 0:
                age = None
                is_minor = False
            else:
                is_minor = age <= MINOR_MAX_AGE
        allergy = _s(r.AllergyText) if hasattr(r, 'AllergyText') else ''
        mother = _s(r.MotherName) if hasattr(r, 'MotherName') else ''
        father = _s(r.FatherName) if hasattr(r, 'FatherName') else ''
        em_contact = _s(r.EmContact) if hasattr(r, 'EmContact') else ''
        em_phone = _s(r.EmPhone) if hasattr(r, 'EmPhone') else ''
        emergency = em_contact
        if em_phone:
            emergency = (emergency + ' (' + em_phone + ')') if emergency else em_phone
        item = {
            'people_id': _i(r.PeopleId),
            'name': _s(r.PersonName, '(Unknown)'),
            'first': _s(r.FirstName),
            'last': _s(r.LastName),
            'email': _s(r.Email),
            'age': age if age is not None else '',
            'is_minor': is_minor,
            'grade': _s(r.GradeLabel),
            'gender': _s(r.Gender),
            'has_allergy': _allergy_text_meaningful(allergy),
            'emergency': emergency,
            'parents': _join_labels([mother, father], ' / '),
        }
        if include_staff:
            bg_date = _fmt_date(r.BgDate) if hasattr(r, 'BgDate') else ''
            video_date = _fmt_date(r.VideoDate) if hasattr(r, 'VideoDate') else ''
            if is_minor:
                bg_date = ''
                video_date = ''
            item['bg_date'] = bg_date
            item['video_date'] = video_date
            item['app_date'] = _fmt_date(r.AppDate) if hasattr(r, 'AppDate') else ''
            item['has_application'] = _i(r.AppOrgId, 0) > 0 if hasattr(r, 'AppOrgId') else bool(item['app_date'])
            if is_minor:
                item['inperson_date'] = _fmt_date_or_str(
                    r.MinorInPersonDate if hasattr(r, 'MinorInPersonDate') else None,
                    r.MinorInPersonStr if hasattr(r, 'MinorInPersonStr') else '')
                item['inperson_iso'] = _fmt_iso(
                    r.MinorInPersonDate if hasattr(r, 'MinorInPersonDate') else None,
                    r.MinorInPersonStr if hasattr(r, 'MinorInPersonStr') else '')
                item['handbook_date'] = ''
                item['handbook_iso'] = ''
            else:
                item['inperson_date'] = _fmt_date_or_str(
                    r.InPersonDate if hasattr(r, 'InPersonDate') else None,
                    r.InPersonStr if hasattr(r, 'InPersonStr') else '')
                item['inperson_iso'] = _fmt_iso(
                    r.InPersonDate if hasattr(r, 'InPersonDate') else None,
                    r.InPersonStr if hasattr(r, 'InPersonStr') else '')
                item['handbook_date'] = _fmt_date_or_str(
                    r.HandbookDate if hasattr(r, 'HandbookDate') else None,
                    r.HandbookStr if hasattr(r, 'HandbookStr') else '')
                item['handbook_iso'] = _fmt_iso(
                    r.HandbookDate if hasattr(r, 'HandbookDate') else None,
                    r.HandbookStr if hasattr(r, 'HandbookStr') else '')
        people.append(item)
    return {
        'org_id': _i(org_id, 0),
        'subgroup_id': tag_id,
        'people': people,
        'count': len(people),
    }


def _get_registration_excel_url(org_id):
    """
    Build the standard Involvement Registration Report (Excel) URL.
    Uses OrgMembersQuery (same people set as the org toolbar export).
    """
    org = _org_meta(org_id)
    if not org:
        return {'error': 'Organization not found'}
    if _i(org.RegistrationTypeId, 0) != REGISTRATION_FORM_TYPE:
        return {'error': 'Registration Excel export is only for Registration Form involvements.'}

    # Prog/Div for MemberTypeCodes clause
    meta_sql = """
SELECT o.OrganizationId, ISNULL(o.DivisionId, 0) AS DivisionId, ISNULL(d.ProgId, 0) AS ProgId
FROM Organizations o
LEFT JOIN Division d ON d.Id = o.DivisionId
WHERE o.OrganizationId = @orgId
"""
    p = _dd()
    p.AddValue('orgId', org_id)
    meta_rows = list(q.QuerySql(meta_sql, p))
    if not meta_rows:
        return {'error': 'Organization not found'}
    prog_id = _i(meta_rows[0].ProgId, 0)
    div_id = _i(meta_rows[0].DivisionId, 0)

    mt_rows = list(q.QuerySql("SELECT Description FROM lookup.MemberType WHERE Description IS NOT NULL AND LTRIM(RTRIM(Description)) <> ''"))
    mt_names = []
    for r in mt_rows:
        name = _s(r.Description)
        if name:
            mt_names.append(name)
    if not mt_names:
        return {'error': 'No member types found to build the registration export.'}
    member_types = ','.join(mt_names)

    try:
        qid = model.OrgMembersQuery(prog_id, div_id, org_id, member_types)
    except Exception, e:
        return {'error': 'Could not build registration export query: ' + _s(e)}

    qid_s = _s(qid)
    if not qid_s:
        return {'error': 'Could not build registration export query.'}

    return {
        'ok': True,
        'url': '/Reports/RegistrationExcel/' + qid_s + '?oid=' + str(org_id),
        'filename': 'Registrations.xlsx',
    }


def _get_text_answers(org_id, question_id, subgroup_id=0):
    questions = _questions_for_org(org_id)
    qrow = None
    for q in questions:
        if _s(q.RegQuestionId) == _s(question_id):
            qrow = q
            break
    if not qrow:
        return {'error': 'Question not found'}

    qt = _i(qrow.QuestionTypeId, 0)
    st = _i(qrow.QuestionSubTypeId, 0) if not _is_null(qrow.QuestionSubTypeId) else 0
    options = _parse_options(qrow.Options)
    registrants = _completed_registrants(org_id, subgroup_id)
    answers = _answers_for_registrants(org_id, [_s(question_id)], subgroup_id)
    ans_by_rp = {}
    for a in answers:
        ans_by_rp[_s(a.RegPeopleId)] = a

    rows = []
    for reg in registrants:
        a = ans_by_rp.get(_s(reg.RegPeopleId))
        parsed = _parse_answer(a.AnswerValue) if a else None
        if _is_blank_answer(parsed):
            continue
        rows.append({
            'people_id': _i(reg.PeopleId),
            'name': _s(reg.PersonName),
            'answer': _answer_display(parsed, qt, st, options),
        })
    return {
        'question_id': _s(question_id),
        'question_label': _s(qrow.Label),
        'kind': 'text',
        'answered_people': rows,
    }


def _get_person_answers(org_id, people_id, subgroup_id=0):
    org = _org_meta(org_id)
    if not org:
        return {'error': 'Organization not found'}

    registrants = _completed_registrants(org_id, subgroup_id)
    reg = None
    for r in registrants:
        if _i(r.PeopleId) == people_id:
            reg = r
            break
    if not reg:
        return {'error': 'No completed registration found for this person'}

    questions = _questions_for_org(org_id)
    # Include overview types + emergency/parents for person view; skip other structural
    show_types = OVERVIEW_CHOICE_TYPES + OVERVIEW_TEXT_TYPES + PERSON_EXTRA_TYPES
    visible = [q for q in questions if _i(q.QuestionTypeId, 0) in show_types]
    qids = [_s(q.RegQuestionId) for q in visible]
    answers = _answers_for_registrants(org_id, qids, subgroup_id)
    ans_by_q = {}
    for a in answers:
        if _s(a.RegPeopleId) == _s(reg.RegPeopleId):
            ans_by_q[_s(a.RegQuestionId)] = a

    items = []
    for qrow in visible:
        qid = _s(qrow.RegQuestionId)
        qt = _i(qrow.QuestionTypeId, 0)
        st = _i(qrow.QuestionSubTypeId, 0) if not _is_null(qrow.QuestionSubTypeId) else 0
        options = _parse_options(qrow.Options)
        a = ans_by_q.get(qid)
        parsed = _parse_answer(a.AnswerValue) if a else None
        if _is_blank_answer(parsed):
            continue
        items.append({
            'question_id': qid,
            'label': _s(qrow.Label, '(Untitled)'),
            'type_id': qt,
            'answer': _answer_display(parsed, qt, st, options),
            'blank': False,
        })

    return {
        'people_id': people_id,
        'name': _s(reg.PersonName),
        'profile_url': '/Person2/' + str(people_id),
        'answers': items,
    }


def _get_age_people(org_id, bracket):
    """People in an involvement whose age falls in the given bracket label."""
    bracket = _s(bracket)
    if bracket not in AGE_BRACKET_LABELS:
        return {'error': 'Invalid age bracket'}

    sql = """
SELECT
    pe.PeopleId,
    ISNULL(pe.Name2, LTRIM(RTRIM(ISNULL(pe.FirstName,'') + ' ' + ISNULL(pe.LastName,'')))) AS PersonName,
    CASE
        WHEN pe.BirthYear IS NOT NULL AND pe.BirthMonth IS NOT NULL AND pe.BirthDay IS NOT NULL
        THEN DATEDIFF(year, DATEFROMPARTS(pe.BirthYear, pe.BirthMonth, pe.BirthDay), GETDATE())
        ELSE NULL
    END AS Age
FROM OrganizationMembers om
INNER JOIN People pe ON om.PeopleId = pe.PeopleId
WHERE om.OrganizationId = @orgId
  AND pe.IsDeceased = 0
ORDER BY PersonName
"""
    p = _dd()
    p.AddValue('orgId', org_id)
    rows = list(q.QuerySql(sql, p))
    people = []
    for r in rows:
        age = r.Age if hasattr(r, 'Age') and not _is_null(r.Age) else None
        try:
            age_i = int(age) if age is not None else None
        except:
            age_i = None
        if _age_bracket_label(age_i) != bracket:
            continue
        people.append({
            'people_id': _i(r.PeopleId),
            'name': _s(r.PersonName, '(Unknown)'),
            'age': age_i,
        })
    return {
        'bracket': bracket,
        'label': bracket,
        'people': people,
        'count': len(people),
    }


def _member_grade_label(row):
    """Same grade label logic as Overview grade distribution."""
    label = _s(row.GradeLabel, 'Unknown') if hasattr(row, 'GradeLabel') else 'Unknown'
    if not label or label.lower() == 'unknown':
        return 'Unknown'
    return label


def _get_grade_people(org_id, grade):
    """People in an involvement whose grade label matches (org grade, else person grade).
    Includes gender so the Next Gen UI can filter grade + gender together.
    """
    grade = _s(grade, 'Unknown') or 'Unknown'

    sql = """
SELECT
    pe.PeopleId,
    pe.GenderId,
    ISNULL(pe.Name2, LTRIM(RTRIM(ISNULL(pe.FirstName,'') + ' ' + ISNULL(pe.LastName,'')))) AS PersonName,
    COALESCE(
        NULLIF(LTRIM(RTRIM(gl_om.Description)), ''),
        NULLIF(LTRIM(RTRIM(gl_pe.Description)), ''),
        'Unknown'
    ) AS GradeLabel
FROM OrganizationMembers om
INNER JOIN People pe ON om.PeopleId = pe.PeopleId
LEFT JOIN lookup.GradeLevel gl_pe ON pe.GradeLevelId = gl_pe.Id
LEFT JOIN lookup.GradeLevel gl_om ON om.GradeLevelId = gl_om.Id
WHERE om.OrganizationId = @orgId
  AND pe.IsDeceased = 0
ORDER BY PersonName
"""
    p = _dd()
    p.AddValue('orgId', org_id)
    rows = list(q.QuerySql(sql, p))
    people = []
    male_count = 0
    female_count = 0
    for r in rows:
        label = _member_grade_label(r)
        if label != grade:
            continue
        gid = _i(r.GenderId, 0) if hasattr(r, 'GenderId') and not _is_null(r.GenderId) else 0
        if gid == 1:
            gender = 'male'
            male_count += 1
        elif gid == 2:
            gender = 'female'
            female_count += 1
        else:
            gender = 'unknown'
        people.append({
            'people_id': _i(r.PeopleId),
            'name': _s(r.PersonName, '(Unknown)'),
            'grade': label,
            'gender': gender,
        })
    return {
        'grade': grade,
        'label': grade,
        'people': people,
        'count': len(people),
        'male_count': male_count,
        'female_count': female_count,
    }


def _get_gender_people(org_id, gender):
    """People in an involvement by gender: male (1) or female (2)."""
    gender = _s(gender).lower()
    if gender == 'male':
        gender_id = 1
        label = 'Male'
    elif gender == 'female':
        gender_id = 2
        label = 'Female'
    else:
        return {'error': 'Invalid gender'}

    sql = """
SELECT
    pe.PeopleId,
    ISNULL(pe.Name2, LTRIM(RTRIM(ISNULL(pe.FirstName,'') + ' ' + ISNULL(pe.LastName,'')))) AS PersonName
FROM OrganizationMembers om
INNER JOIN People pe ON om.PeopleId = pe.PeopleId
WHERE om.OrganizationId = @orgId
  AND pe.IsDeceased = 0
  AND pe.GenderId = @genderId
ORDER BY PersonName
"""
    p = _dd()
    p.AddValue('orgId', org_id)
    p.AddValue('genderId', gender_id)
    rows = list(q.QuerySql(sql, p))
    people = [{
        'people_id': _i(r.PeopleId),
        'name': _s(r.PersonName, '(Unknown)'),
    } for r in rows]
    return {
        'gender': gender,
        'label': label,
        'people': people,
        'count': len(people),
    }


def _get_marital_people(org_id, status):
    """People in an involvement with the given marital status label."""
    status = _s(status, 'Unknown')
    if not status:
        status = 'Unknown'

    sql = """
SELECT
    pe.PeopleId,
    ISNULL(pe.Name2, LTRIM(RTRIM(ISNULL(pe.FirstName,'') + ' ' + ISNULL(pe.LastName,'')))) AS PersonName,
    ISNULL(NULLIF(LTRIM(RTRIM(ms.Description)), ''), 'Unknown') AS MaritalStatus
FROM OrganizationMembers om
INNER JOIN People pe ON om.PeopleId = pe.PeopleId
LEFT JOIN lookup.MaritalStatus ms ON pe.MaritalStatusId = ms.Id
WHERE om.OrganizationId = @orgId
  AND pe.IsDeceased = 0
ORDER BY PersonName
"""
    p = _dd()
    p.AddValue('orgId', org_id)
    rows = list(q.QuerySql(sql, p))
    people = []
    for r in rows:
        row_status = _s(r.MaritalStatus, 'Unknown') if hasattr(r, 'MaritalStatus') else 'Unknown'
        if not row_status:
            row_status = 'Unknown'
        if row_status != status:
            continue
        people.append({
            'people_id': _i(r.PeopleId),
            'name': _s(r.PersonName, '(Unknown)'),
            'marital_status': row_status,
        })
    return {
        'status': status,
        'label': status,
        'people': people,
        'count': len(people),
    }


def _get_subgroup_people(org_id, subgroup_id):
    """People tagged into a specific involvement subgroup (MemberTag)."""
    subgroup_id = _i(subgroup_id, 0)
    if subgroup_id <= 0:
        return {'error': 'Invalid subgroup'}

    name_sql = """
SELECT TOP 1 mt.Name AS SubgroupName
FROM MemberTags mt
WHERE mt.Id = @tagId
  AND mt.OrgId = @orgId
"""
    p0 = _dd()
    p0.AddValue('tagId', subgroup_id)
    p0.AddValue('orgId', org_id)
    name_rows = list(q.QuerySql(name_sql, p0))
    if not name_rows:
        return {'error': 'Subgroup not found'}
    subgroup_name = _s(name_rows[0].SubgroupName, 'Subgroup')

    sql = """
SELECT
    pe.PeopleId,
    ISNULL(pe.Name2, LTRIM(RTRIM(ISNULL(pe.FirstName,'') + ' ' + ISNULL(pe.LastName,'')))) AS PersonName
FROM OrgMemMemTags omt
INNER JOIN People pe ON omt.PeopleId = pe.PeopleId
WHERE omt.OrgId = @orgId
  AND omt.MemberTagId = @tagId
  AND pe.IsDeceased = 0
ORDER BY PersonName
"""
    p = _dd()
    p.AddValue('orgId', org_id)
    p.AddValue('tagId', subgroup_id)
    rows = list(q.QuerySql(sql, p))
    people = []
    for r in rows:
        people.append({
            'people_id': _i(r.PeopleId),
            'name': _s(r.PersonName, '(Unknown)'),
        })
    return {
        'subgroup_id': subgroup_id,
        'label': subgroup_name,
        'people': people,
        'count': len(people),
    }


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
    clear_first: empty the tag before adding (vs append).
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

    # peopleids='1,2,3' is accepted by PeopleQuery2 / AddTag
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


def _get_finance_people(org_id, status):
    """
    People linked to payment groups (Amt>0) for an involvement.
    status: 'paid_in_full' (balance <= 0) or 'remaining_balance' (balance > 0)

    Performance notes:
    - Filters to OrgId first, then only groups with Amt>0 and matching balance.
    - Prefers TransactionPeople; LoginPeopleId only when a group has no TP rows.
    - No role checks here — speed is SQL shape / data volume, not roles.
    """
    status = _s(status)
    if status not in ('paid_in_full', 'remaining_balance'):
        return {'error': 'Invalid finance status'}

    # Leaner query: one OrgId scan, early group filter, avoid triple UNION + CTE self-refs
    sql = """
;WITH TranBase AS (
    SELECT
        t.Id,
        ISNULL(t.OriginalId, t.Id) AS GroupId,
        ISNULL(t.Amt, 0) AS Amt,
        ISNULL(t.Amtdue, 0) AS Amtdue,
        t.TransactionDate,
        t.LoginPeopleId
    FROM dbo.[Transaction] t WITH (NOLOCK)
    WHERE t.OrgId = @orgId
),
GroupTotals AS (
    SELECT GroupId, SUM(Amt) AS GroupPaid
    FROM TranBase
    GROUP BY GroupId
    HAVING SUM(Amt) > 0
),
GroupBalance AS (
    SELECT
        g.GroupId,
        g.GroupPaid,
        b.BalanceDue
    FROM GroupTotals g
    CROSS APPLY (
        SELECT TOP (1) tb.Amtdue AS BalanceDue
        FROM TranBase tb
        WHERE tb.GroupId = g.GroupId
        ORDER BY tb.TransactionDate DESC, tb.Id DESC
    ) b
    WHERE (
        (@status = 'paid_in_full' AND b.BalanceDue <= 0)
        OR (@status = 'remaining_balance' AND b.BalanceDue > 0)
    )
),
LinkedPeople AS (
    SELECT
        gb.GroupId,
        gb.GroupPaid,
        gb.BalanceDue,
        tp.PeopleId
    FROM GroupBalance gb
    INNER JOIN TranBase tb ON tb.GroupId = gb.GroupId
    INNER JOIN dbo.TransactionPeople tp WITH (NOLOCK) ON tp.Id = tb.Id

    UNION

    SELECT
        gb.GroupId,
        gb.GroupPaid,
        gb.BalanceDue,
        tb.LoginPeopleId AS PeopleId
    FROM GroupBalance gb
    INNER JOIN TranBase tb ON tb.GroupId = gb.GroupId
    WHERE tb.LoginPeopleId IS NOT NULL
      AND NOT EXISTS (
            SELECT 1
            FROM TranBase tb2
            INNER JOIN dbo.TransactionPeople tp2 WITH (NOLOCK) ON tp2.Id = tb2.Id
            WHERE tb2.GroupId = gb.GroupId
        )
)
SELECT
    lp.PeopleId,
    ISNULL(pe.Name2, LTRIM(RTRIM(ISNULL(pe.FirstName, '') + ' ' + ISNULL(pe.LastName, '')))) AS PersonName,
    MAX(lp.GroupPaid) AS TotalPaid,
    MAX(lp.BalanceDue) AS BalanceDue
FROM LinkedPeople lp
INNER JOIN dbo.People pe WITH (NOLOCK) ON pe.PeopleId = lp.PeopleId
GROUP BY
    lp.PeopleId,
    ISNULL(pe.Name2, LTRIM(RTRIM(ISNULL(pe.FirstName, '') + ' ' + ISNULL(pe.LastName, ''))))
ORDER BY PersonName
"""
    p = _dd()
    p.AddValue('orgId', org_id)
    p.AddValue('status', status)
    rows = list(q.QuerySql(sql, p))
    people = []
    for r in rows:
        pid = _i(r.PeopleId, 0) if hasattr(r, 'PeopleId') and not _is_null(r.PeopleId) else 0
        if pid <= 0:
            continue
        people.append({
            'people_id': pid,
            'name': _s(r.PersonName, '(Unknown)'),
            'total_paid': float(r.TotalPaid) if hasattr(r, 'TotalPaid') and r.TotalPaid else 0,
            'balance_due': float(r.BalanceDue) if hasattr(r, 'BalanceDue') and r.BalanceDue else 0,
        })
    label = 'Paid in Full' if status == 'paid_in_full' else 'Remaining Balance'
    return {
        'status': status,
        'label': label,
        'people': people,
        'count': len(people),
    }


# ---------------------------------------------------------------------------
# AJAX / page entry
# ---------------------------------------------------------------------------

model.Header = 'Awana Registration'

is_ajax = hasattr(model.Data, 'ajax') and model.Data.ajax == 'true'

if is_ajax:
    action = _s(_data('action'))

    if action == 'list_awana':
        try:
            _json_out(_awana_overview_payload())
        except Exception, e:
            _err_out(e)

    elif action == 'get_dashboard':
        try:
            org_id = _i(_data('org_id'), 0)
            denied = _require_org_access(org_id)
            if denied:
                _json_out(denied)
            else:
                org_sql = """
                SELECT o.OrganizationId, o.OrganizationName, o.RegistrationTypeId,
                       o.ImageUrl, o.BadgeUrl,
                       d.Name as DivisionName, p.Id as ProgramId, p.Name as ProgramName,
                       COALESCE(
                           NULLIF(LTRIM(RTRIM(oe.Data)), ''),
                           NULLIF(LTRIM(RTRIM(oe.StrValue)), ''),
                           NULLIF(LTRIM(RTRIM(o.ImageUrl)), '')
                       ) AS TitleGraphicUrl
                FROM Organizations o
                LEFT JOIN Division d ON o.DivisionId = d.Id
                LEFT JOIN Program p ON d.ProgId = p.Id
                LEFT JOIN dbo.Setting s ON s.Id = 'SitesDataHeroImageEv'
                LEFT JOIN dbo.OrganizationExtra oe
                    ON oe.OrganizationId = o.OrganizationId
                   AND s.Setting IS NOT NULL
                   AND LTRIM(RTRIM(s.Setting)) <> ''
                   AND oe.Field = s.Setting
                WHERE o.OrganizationId = @orgId
            """
                p = _dd()
                p.AddValue('orgId', org_id)
                org_info = list(q.QuerySql(org_sql, p))

                if not org_info:
                    _json_out({'error': 'Organization not found'})
                else:
                    org = org_info[0]
                    program_id = _i(org.ProgramId, 0) if hasattr(org, 'ProgramId') else 0
                    profile = _overview_profile(program_id)

                    demo_sql = """
                        SELECT
                            pe.GenderId,
                            CASE
                                WHEN pe.BirthYear IS NOT NULL AND pe.BirthMonth IS NOT NULL AND pe.BirthDay IS NOT NULL
                                THEN DATEDIFF(year, DATEFROMPARTS(pe.BirthYear, pe.BirthMonth, pe.BirthDay), GETDATE())
                                ELSE NULL
                            END as Age,
                            ms.Description as MaritalStatus,
                            om.EnrollmentDate,
                            DATEDIFF(day, om.EnrollmentDate, GETDATE()) as DaysSinceEnrollment,
                            COALESCE(
                                NULLIF(LTRIM(RTRIM(gl_om.Description)), ''),
                                NULLIF(LTRIM(RTRIM(gl_pe.Description)), ''),
                                'Unknown'
                            ) as GradeLabel,
                            COALESCE(gl_om.Id, gl_pe.Id, 99999) as GradeSort
                        FROM OrganizationMembers om
                        JOIN People pe ON om.PeopleId = pe.PeopleId
                        LEFT JOIN lookup.MaritalStatus ms ON pe.MaritalStatusId = ms.Id
                        LEFT JOIN lookup.GradeLevel gl_pe ON pe.GradeLevelId = gl_pe.Id
                        LEFT JOIN lookup.GradeLevel gl_om ON om.GradeLevelId = gl_om.Id
                        WHERE om.OrganizationId = @orgId
                            AND pe.IsDeceased = 0
                    """
                    p2 = _dd()
                    p2.AddValue('orgId', org_id)
                    members = list(q.QuerySql(demo_sql, p2))

                    total_members = len(members)
                    male_count = len([m for m in members if m.GenderId == 1])
                    female_count = len([m for m in members if m.GenderId == 2])

                    age_groups = _empty_age_groups()
                    if profile.get('show_age'):
                        for member in members:
                            age = member.Age if hasattr(member, 'Age') and not _is_null(member.Age) else None
                            try:
                                age_i = int(age) if age is not None else None
                            except:
                                age_i = None
                            label = _age_bracket_label(age_i)
                            age_groups[label] = age_groups.get(label, 0) + 1

                    grades = []
                    if profile.get('show_grade'):
                        grade_counts = {}
                        grade_sort = {}
                        for member in members:
                            label = _s(member.GradeLabel, 'Unknown') if hasattr(member, 'GradeLabel') else 'Unknown'
                            if not label or label.lower() == 'unknown':
                                label = 'Unknown'
                            grade_counts[label] = grade_counts.get(label, 0) + 1
                            if label not in grade_sort:
                                grade_sort[label] = _i(member.GradeSort, 99999) if hasattr(member, 'GradeSort') else 99999
                        # Unknown last; otherwise by GradeLevel Id
                        def _grade_key(item):
                            label = item[0]
                            if label == 'Unknown':
                                return (1, 99999, label)
                            return (0, grade_sort.get(label, 99999), label)
                        for label, count in sorted(grade_counts.items(), key=_grade_key):
                            grades.append({'label': label, 'count': count})

                    marital_status = {}
                    if profile.get('show_marital'):
                        for member in members:
                            raw = member.MaritalStatus if hasattr(member, 'MaritalStatus') and not _is_null(member.MaritalStatus) else None
                            status = _s(raw, 'Unknown') or 'Unknown'
                            marital_status[status] = marital_status.get(status, 0) + 1

                    enrollment_timeline = {}
                    if profile.get('show_enrollment_timeline'):
                        for member in members:
                            if hasattr(member, 'EnrollmentDate') and member.EnrollmentDate:
                                date_key = "{0:04d}-{1:02d}".format(member.EnrollmentDate.Year, member.EnrollmentDate.Month)
                                enrollment_timeline[date_key] = enrollment_timeline.get(date_key, 0) + 1

                    sorted_timeline = sorted(enrollment_timeline.items(), key=lambda x: x[0], reverse=True)[:12]
                    sorted_timeline.reverse()

                    subgroup_sql = """
                        SELECT mt.Id as SubgroupId, mt.Name as SubgroupName, COUNT(DISTINCT omt.PeopleId) as MemberCount
                        FROM MemberTags mt
                        INNER JOIN OrgMemMemTags omt ON mt.Id = omt.MemberTagId AND omt.OrgId = @orgId
                        WHERE mt.OrgId = @orgId
                        GROUP BY mt.Id, mt.Name
                        HAVING COUNT(DISTINCT omt.PeopleId) > 0
                        ORDER BY mt.Name
                    """
                    p3 = _dd()
                    p3.AddValue('orgId', org_id)
                    subgroups = list(q.QuerySql(subgroup_sql, p3))

                    # Payment groups (OriginalId chain) with Amt > 0 only.
                    # Balance = Amtdue on the latest transaction in the group.
                    transaction_sql = """
    ;WITH Raw AS (
        SELECT
            ISNULL(t.OriginalId, t.Id) AS GroupId,
            t.Id,
            t.Amt,
            t.Amtdue,
            t.TransactionDate
        FROM [Transaction] t
        WHERE t.OrgId = @orgId
    ),
    Grouped AS (
        SELECT
            GroupId,
            SUM(ISNULL(Amt, 0)) AS GroupPaid
        FROM Raw
        GROUP BY GroupId
        HAVING SUM(ISNULL(Amt, 0)) > 0
    ),
    Latest AS (
        SELECT
            r.GroupId,
            ISNULL(r.Amtdue, 0) AS BalanceDue,
            ROW_NUMBER() OVER (
                PARTITION BY r.GroupId
                ORDER BY r.TransactionDate DESC, r.Id DESC
            ) AS rn
        FROM Raw r
        INNER JOIN Grouped g ON g.GroupId = r.GroupId
    )
    SELECT
        COUNT(*) AS TotalTransactions,
        SUM(CASE WHEN l.BalanceDue <= 0 THEN 1 ELSE 0 END) AS PaidInFullCount,
        SUM(CASE WHEN l.BalanceDue > 0 THEN 1 ELSE 0 END) AS RemainingBalanceCount,
        SUM(g.GroupPaid) AS TotalPaid,
        SUM(CASE WHEN l.BalanceDue > 0 THEN l.BalanceDue ELSE 0 END) AS TotalDue
    FROM Grouped g
    INNER JOIN Latest l ON l.GroupId = g.GroupId AND l.rn = 1
    """
                    p4 = _dd()
                    p4.AddValue('orgId', org_id)
                    transaction_result = list(q.QuerySql(transaction_sql, p4))
                    transactions = transaction_result[0] if transaction_result else None

                    result = {
                        'org_name': org.OrganizationName,
                        'program_id': program_id,
                        'program_name': org.ProgramName if hasattr(org, 'ProgramName') and org.ProgramName else 'None',
                        'division_name': org.DivisionName if hasattr(org, 'DivisionName') and org.DivisionName else 'None',
                        'title_graphic_url': _s(org.TitleGraphicUrl) if hasattr(org, 'TitleGraphicUrl') else '',
                        'badge_url': _s(org.BadgeUrl) if hasattr(org, 'BadgeUrl') else '',
                        'registration_type_id': _i(org.RegistrationTypeId, 0),
                        'is_registration_form': _i(org.RegistrationTypeId, 0) == REGISTRATION_FORM_TYPE,
                        'overview_profile': profile,
                        'total_members': total_members,
                        'male_count': male_count,
                        'female_count': female_count,
                        'age_groups': age_groups if profile.get('show_age') else {},
                        'grades': grades,
                        'marital_status': marital_status if profile.get('show_marital') else {},
                        'enrollment_timeline': dict(sorted_timeline) if profile.get('show_enrollment_timeline') else {},
                        'subgroups': [{'id': _i(s.SubgroupId), 'name': _s(s.SubgroupName), 'count': _i(s.MemberCount)} for s in subgroups],
                        'transactions': {
                            'total': int(transactions.TotalTransactions) if transactions and transactions.TotalTransactions else 0,
                            'paid_in_full': int(transactions.PaidInFullCount) if transactions and transactions.PaidInFullCount else 0,
                            'remaining_balance': int(transactions.RemainingBalanceCount) if transactions and transactions.RemainingBalanceCount else 0,
                            'total_paid': float(transactions.TotalPaid) if transactions and transactions.TotalPaid else 0,
                            'total_due': float(transactions.TotalDue) if transactions and transactions.TotalDue else 0,
                        }
                    }
                    _json_out(result)
        except Exception, e:
            _err_out(e)

    elif action == 'get_registration_summary':
        try:
            org_id = _i(_data('org_id'), 0)
            denied = _require_org_access(org_id)
            if denied:
                _json_out(denied)
            else:
                _json_out(_build_registration_summary(org_id, _i(_data('subgroup_id'), 0)))
        except Exception, e:
            _err_out(e)

    elif action == 'get_allergy_people':
        try:
            org_id = _i(_data('org_id'), 0)
            denied = _require_org_access(org_id)
            if denied:
                _json_out(denied)
            else:
                _json_out(_get_allergy_people(org_id, _i(_data('subgroup_id'), 0)))
        except Exception, e:
            _err_out(e)

    elif action == 'get_contact_people':
        try:
            org_id = _i(_data('org_id'), 0)
            denied = _require_org_access(org_id)
            if denied:
                _json_out(denied)
            else:
                _json_out(_get_contact_people(org_id, _i(_data('subgroup_id'), 0)))
        except Exception, e:
            _err_out(e)

    elif action == 'get_option_people':
        try:
            org_id = _i(_data('org_id'), 0)
            denied = _require_org_access(org_id)
            if denied:
                _json_out(denied)
            else:
                question_id = _s(_data('question_id'))
                option_value = _s(_data('option_value'))
                _json_out(_get_option_people(org_id, question_id, option_value, _i(_data('subgroup_id'), 0)))
        except Exception, e:
            _err_out(e)

    elif action == 'get_text_answers':
        try:
            org_id = _i(_data('org_id'), 0)
            denied = _require_org_access(org_id)
            if denied:
                _json_out(denied)
            else:
                question_id = _s(_data('question_id'))
                _json_out(_get_text_answers(org_id, question_id, _i(_data('subgroup_id'), 0)))
        except Exception, e:
            _err_out(e)

    elif action == 'get_person_answers':
        try:
            org_id = _i(_data('org_id'), 0)
            denied = _require_org_access(org_id)
            if denied:
                _json_out(denied)
            else:
                people_id = _i(_data('people_id'), 0)
                _json_out(_get_person_answers(org_id, people_id, _i(_data('subgroup_id'), 0)))
        except Exception, e:
            _err_out(e)

    elif action == 'get_age_people':
        try:
            org_id = _i(_data('org_id'), 0)
            denied = _require_org_access(org_id)
            if denied:
                _json_out(denied)
            else:
                bracket = _s(_data('bracket'))
                _json_out(_get_age_people(org_id, bracket))
        except Exception, e:
            _err_out(e)

    elif action == 'get_grade_people':
        try:
            org_id = _i(_data('org_id'), 0)
            denied = _require_org_access(org_id)
            if denied:
                _json_out(denied)
            else:
                grade = _s(_data('grade'))
                _json_out(_get_grade_people(org_id, grade))
        except Exception, e:
            _err_out(e)

    elif action == 'get_gender_people':
        try:
            org_id = _i(_data('org_id'), 0)
            denied = _require_org_access(org_id)
            if denied:
                _json_out(denied)
            else:
                gender = _s(_data('gender'))
                _json_out(_get_gender_people(org_id, gender))
        except Exception, e:
            _err_out(e)

    elif action == 'get_marital_people':
        try:
            org_id = _i(_data('org_id'), 0)
            denied = _require_org_access(org_id)
            if denied:
                _json_out(denied)
            else:
                status = _s(_data('status'))
                _json_out(_get_marital_people(org_id, status))
        except Exception, e:
            _err_out(e)

    elif action == 'get_subgroup_people':
        try:
            org_id = _i(_data('org_id'), 0)
            denied = _require_org_access(org_id)
            if denied:
                _json_out(denied)
            else:
                subgroup_id = _i(_data('subgroup_id'), 0)
                _json_out(_get_subgroup_people(org_id, subgroup_id))
        except Exception, e:
            _err_out(e)

    elif action == 'get_finance_people':
        try:
            org_id = _i(_data('org_id'), 0)
            denied = _require_org_access(org_id)
            if denied:
                _json_out(denied)
            else:
                status = _s(_data('status'))
                _json_out(_get_finance_people(org_id, status))
        except Exception, e:
            _err_out(e)

    elif action == 'get_club_roster':
        try:
            org_id = _i(_data('org_id'), 0)
            denied = _require_org_access(org_id)
            if denied:
                _json_out(denied)
            else:
                _json_out(_get_club_roster(org_id, _i(_data('subgroup_id'), 0)))
        except Exception, e:
            _err_out(e)

    elif action == 'get_volunteer_roster':
        try:
            org_id = _i(_data('org_id'), 0)
            denied = _require_org_access(org_id)
            if denied:
                _json_out(denied)
            elif org_id != VOLUNTEERS_ORG_ID:
                _json_out({'error': 'Invalid organization'})
            else:
                mode = _s(_data('mode'), 'club')
                include_staff = (mode == 'staff')
                if include_staff and not _user_can_see_staff_tab():
                    _json_out({'error': 'Not authorized to view Volunteer Management.'})
                else:
                    data = _get_club_roster(org_id, _i(_data('subgroup_id'), 0), include_staff)
                    if mode in ('overview', 'staff'):
                        cmap = _volunteer_clubs_by_people(org_id)
                        for person in data.get('people') or []:
                            labels = cmap.get(person.get('people_id'), [])
                            person['clubs'] = labels
                            person['clubs_label'] = ', '.join(labels)
                    data['mode'] = mode
                    _json_out(data)
        except Exception, e:
            _err_out(e)

    elif action == 'set_ev_date':
        try:
            _json_out(_set_awana_ev_date(_data('people_id'), _data('ev_field'), _data('ev_date')))
        except Exception, e:
            _err_out(e)

    elif action == 'get_registration_excel_url':
        try:
            org_id = _i(_data('org_id'), 0)
            denied = _require_org_access(org_id)
            if denied:
                _json_out(denied)
            else:
                _json_out(_get_registration_excel_url(org_id))
        except Exception, e:
            _err_out(e)

    elif action == 'add_to_tag':
        try:
            people_ids = _s(_data('people_ids'))
            tag_name = _s(_data('tag_name'))
            clear_first = _s(_data('clear_first'))
            _json_out(_add_people_to_tag(people_ids, tag_name, clear_first))
        except Exception, e:
            _err_out(e)

    else:
        _json_out({'error': 'Unknown action'})

else:
    # Main page — optional deep link: /PyScriptForm/AwanaRegistrationDashboard?org_id=123
    _initial_org_id = 0
    _initial_org_name = ''
    _initial_club = ''
    try:
        _initial_org_id = _i(_data('org_id'), 0)
        if _initial_org_id <= 0:
            _initial_org_id = _i(Data.GetValue('org_id'), 0)
    except:
        _initial_org_id = 0
    try:
        _initial_club = _s(_data('club'))
        if not _initial_club:
            _initial_club = _s(Data.GetValue('club'))
    except:
        _initial_club = ''
    if _initial_org_id > 0:
        try:
            _op = _dd()
            _op.AddValue('orgId', str(_initial_org_id))
            _orows = list(q.QuerySql(
                'SELECT TOP 1 OrganizationName FROM dbo.Organizations WHERE OrganizationId = @orgId',
                _op))
            if _orows:
                _initial_org_name = _s(_orows[0].OrganizationName)
                if not _initial_club:
                    _matched = _awana_club_for_name(_initial_org_name)
                    if _matched:
                        _initial_club = _matched['key']
        except:
            pass

    model.Form = r'''
<style>
    .dashboard-container {
        max-width: 1400px;
        margin: 0 auto;
        padding: 20px;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }
    .selector-card {
        background: white;
        padding: 25px;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        margin-bottom: 20px;
    }
    .selector-card h2 {
        margin: 0 0 20px 0;
        color: #1e293b;
        font-size: 24px;
    }
    .selector-card h2.selector-toggleable {
        cursor: pointer;
        user-select: none;
    }
    .selector-card h2.selector-toggleable:hover {
        color: #012b58;
    }
    .selector-card select {
        width: 100%;
        padding: 12px;
        font-size: 16px;
        border: 2px solid #e2e8f0;
        border-radius: 8px;
        margin-bottom: 15px;
    }
    .selector-card input[type="text"] {
        width: 100%;
        padding: 12px 14px;
        font-size: 16px;
        border: 2px solid #e2e8f0;
        border-radius: 8px;
        box-sizing: border-box;
    }
    .selector-card input[type="text"]:focus {
        outline: none;
        border-color: #019cff;
    }
    .search-wrap {
        position: relative;
    }
    .search-row {
        display: flex;
        gap: 10px;
        align-items: stretch;
    }
    .search-row input[type="text"] {
        flex: 1;
        min-width: 0;
        margin: 0;
    }
    .btn-search {
        flex-shrink: 0;
        background: #012b58;
        color: #fff;
        border: none;
        border-radius: 8px;
        padding: 12px 22px;
        font-size: 16px;
        font-weight: 600;
        cursor: pointer;
        white-space: nowrap;
    }
    .btn-search:hover {
        opacity: 0.92;
    }
    .btn-search:disabled {
        opacity: 0.55;
        cursor: not-allowed;
    }
    .search-results {
        display: none;
        position: absolute;
        left: 0;
        right: 0;
        top: 100%;
        z-index: 20;
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.12);
        max-height: 320px;
        overflow-y: auto;
        margin-top: 4px;
    }
    .search-results.visible { display: block; }
    .search-result-item {
        padding: 12px 14px;
        cursor: pointer;
        border-bottom: 1px solid #f1f5f9;
    }
    .search-result-item:last-child { border-bottom: none; }
    .search-result-item:hover,
    .search-result-item.active {
        background: #f8fafc;
    }
    .search-result-name {
        font-weight: 600;
        color: #1e293b;
    }
    .search-result-meta {
        font-size: 12px;
        color: #64748b;
        margin-top: 2px;
    }
    .search-hint {
        font-size: 13px;
        color: #64748b;
        margin-top: 8px;
    }
    .search-empty {
        padding: 14px;
        color: #64748b;
        font-size: 14px;
    }
    .dashboard-header {
        background: linear-gradient(135deg, #012b58 0%, #012b58 25%, #019cff 100%);
        color: white;
        padding: 0;
        border-radius: 12px;
        margin-bottom: 20px;
        box-shadow: 0 4px 15px rgba(1, 43, 88, 0.35);
        display: block;
        overflow: hidden;
    }
    .dashboard-header-graphic {
        display: none;
        background: #ffffff;
        text-align: center;
        padding: 16px 20px;
    }
    .dashboard-header-graphic.visible {
        display: block;
    }
    .dashboard-header-graphic img {
        max-width: 100%;
        max-height: 160px;
        width: auto;
        height: auto;
        object-fit: contain;
        border-radius: 8px;
        box-shadow: 0 2px 10px rgba(0, 0, 0, 0.08);
        background: #ffffff;
    }
    .dashboard-header-body {
        padding: 24px 30px 30px;
        display: flex;
        align-items: center;
        gap: 18px;
    }
    .dashboard-header-badge {
        display: none;
        flex-shrink: 0;
        width: 64px;
        height: 64px;
        border-radius: 12px;
        overflow: hidden;
        background: rgba(255, 255, 255, 0.15);
        border: 2px solid rgba(255, 255, 255, 0.35);
    }
    .dashboard-header-badge.visible {
        display: block;
    }
    .dashboard-header-badge img {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }
    .dashboard-header-text {
        min-width: 0;
        flex: 1;
    }
    .dashboard-header h1 {
        margin: 0 0 10px 0;
        font-size: 32px;
    }
    .dashboard-header h1 a {
        color: inherit;
        text-decoration: none;
    }
    .dashboard-header h1 a:hover {
        text-decoration: underline;
    }
    .stats-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 20px;
        margin-bottom: 30px;
    }
    .stat-card {
        background: white;
        padding: 25px;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        text-align: center;
    }
    .stat-card-clickable {
        cursor: pointer;
        border: 2px solid transparent;
        transition: box-shadow 0.15s ease, transform 0.15s ease, border-color 0.15s ease;
    }
    .stat-card-clickable:hover {
        box-shadow: 0 4px 14px rgba(1, 43, 88, 0.15);
        transform: translateY(-1px);
        border-color: #019cff;
    }
    .stat-card-clickable.active {
        border-color: #012b58;
        background: #eef6ff;
    }
    .stat-card-clickable .stat-drill-hint {
        font-size: 11px;
        color: #64748b;
        margin-top: 4px;
        text-transform: none;
        letter-spacing: 0;
    }
    .stat-value {
        font-size: 36px;
        font-weight: bold;
        color: #012b58;
        margin: 10px 0;
    }
    .stat-label {
        color: #64748b;
        font-size: 14px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .section {
        background: white;
        padding: 25px;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        margin-bottom: 20px;
    }
    .section-title {
        font-size: 20px;
        font-weight: 600;
        margin: 0 0 20px 0;
        color: #1e293b;
    }
    .chart-bar {
        display: flex;
        align-items: center;
        margin-bottom: 15px;
    }
    .chart-label {
        width: 160px;
        font-size: 14px;
        color: #475569;
        word-break: break-word;
    }
    .chart-bar-container {
        flex: 1;
        background: #f1f5f9;
        height: 30px;
        border-radius: 6px;
        overflow: hidden;
        margin: 0 15px;
    }
    .chart-bar-fill {
        height: 100%;
        background: #012b58;
        display: flex;
        align-items: center;
        justify-content: flex-end;
        padding-right: 10px;
        color: white;
        font-size: 12px;
        font-weight: 600;
        min-width: 0;
    }
    .chart-count {
        width: 60px;
        text-align: right;
        font-weight: 600;
        color: #012b58;
    }
    #dashboard-content { display: none; }
    .subgroup-list { list-style: none; padding: 0; margin: 0; }
    .subgroup-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px 15px;
        background: #f8fafc;
        margin-bottom: 8px;
        border-radius: 6px;
        border-left: 3px solid #019cff;
    }
    .subgroup-name { font-weight: 500; color: #1e293b; }
    .subgroup-count {
        background: #012b58;
        color: white;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 600;
    }
    .dash-tabs {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-bottom: 20px;
    }
    .dash-tabs.visible { display: flex; }
    .dash-tab {
        border: 2px solid #e2e8f0;
        background: white;
        color: #475569;
        padding: 10px 18px;
        border-radius: 8px;
        font-weight: 600;
        cursor: pointer;
    }
    .dash-tab.active {
        border-color: #012B58;
        background: #012B58;
        color: #F5F4E8;
    }
    .dash-tab[data-tab="overview"].active {
        border-color: #012B58;
        background: #012B58;
        color: #F5F4E8;
    }
    .dash-tab[data-tab="registration"].active,
    .club-subtab[data-subtab="registration"].active {
        border-color: #012B58;
        background: #012B58;
        color: #F5F4E8;
    }
    .dash-tab[data-tab="allergies"].active,
    .club-subtab[data-subtab="allergies"].active {
        border-color: #012B58;
        background: #012B58;
        color: #F5F4E8;
    }
    .dash-tab[data-tab="contacts"].active,
    .club-subtab[data-subtab="contacts"].active {
        border-color: #012B58;
        background: #012B58;
        color: #F5F4E8;
    }
    .club-subtab[data-subtab="club-overview"].active {
        border-color: #012B58;
        background: #012B58;
        color: #F5F4E8;
    }
    .club-subtab.vol-staff {
        margin-left: auto;
        background: #CCEBFF;
        border-color: #019CFF;
        color: #012B58;
    }
    .club-subtab.vol-staff.active {
        background: #019CFF;
        color: #ffffff;
        border-color: #019CFF;
    }
    .minor-pill {
        display: inline-block;
        margin-left: 8px;
        padding: 2px 8px;
        border-radius: 999px;
        background: #CCEBFF;
        color: #012B58;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.3px;
        vertical-align: middle;
    }
    .people-table a.allergy-flag {
        color: #E52300;
        font-weight: 800;
        font-size: 15px;
        margin-left: 8px;
    }
    .people-table a.allergy-flag:hover {
        color: #801D13;
        text-decoration: underline;
    }
    .na-muted {
        color: #001429;
        opacity: 0.4;
        font-style: italic;
        font-weight: 400;
    }
    .staff-ev-date {
        max-width: 148px;
        padding: 4px 6px;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        font-size: 13px;
        color: #001429;
        background: #ffffff;
    }
    .staff-ev-date:focus {
        outline: none;
        border-color: #019CFF;
    }
    .staff-filters {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin: 0 0 14px 0;
    }
    .staff-filter {
        border: 2px solid #e2e8f0;
        background: #ffffff;
        color: #475569;
        padding: 6px 12px;
        border-radius: 8px;
        font-weight: 600;
        font-size: 13px;
        cursor: pointer;
    }
    .staff-filter.active {
        border-color: #012B58;
        background: #012B58;
        color: #F5F4E8;
    }
    .club-subtabs {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin: 0 0 16px 0;
    }
    .club-subtab {
        border: 2px solid #e2e8f0;
        background: white;
        color: #475569;
        padding: 8px 14px;
        border-radius: 8px;
        font-weight: 600;
        cursor: pointer;
        font-size: 14px;
    }
    .club-cards {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
        gap: 14px;
        margin-bottom: 24px;
    }
    .club-card {
        background: #ffffff;
        border: 2px solid #CCEBFF;
        border-radius: 12px;
        padding: 16px 18px;
        cursor: pointer;
        box-shadow: 0 2px 8px rgba(0,20,41,0.06);
    }
    .club-card:hover {
        border-color: #019CFF;
    }
    .club-card.empty {
        cursor: default;
        opacity: 0.7;
        border-color: #e2e8f0;
    }
    .club-card-label {
        font-size: 18px;
        font-weight: 700;
        color: #012B58;
        margin: 0 0 6px 0;
    }
    .club-card-meta {
        font-size: 13px;
        color: #475569;
        margin: 0;
    }
    .club-card-count {
        font-size: 28px;
        font-weight: 700;
        color: #001429;
        margin: 8px 0 0 0;
    }
    .club-org-picker {
        display: none;
        margin-bottom: 16px;
    }
    .club-org-picker.visible { display: block; }
    .club-org-item {
        background: white;
        border: 2px solid #CCEBFF;
        border-radius: 10px;
        padding: 12px 14px;
        margin-bottom: 8px;
        cursor: pointer;
    }
    .club-org-item:hover,
    .club-org-item.active {
        border-color: #019CFF;
        background: #CCEBFF;
    }
    .club-org-item-name {
        font-weight: 600;
        color: #012B58;
    }
    .club-org-item-meta {
        font-size: 12px;
        color: #64748b;
        margin-top: 2px;
    }
    .club-empty {
        background: white;
        border-radius: 12px;
        padding: 28px;
        text-align: center;
        color: #64748b;
    }
    .dash-tab.dash-tab-nextgen {
        display: none;
    }
    .dash-tabs .dash-tab.dash-tab-nextgen.visible {
        display: block;
    }
    .dash-tab-refresh {
        border: 2px solid #e2e8f0;
        background: white;
        color: #475569;
        padding: 10px 14px;
        border-radius: 8px;
        font-weight: 600;
        cursor: pointer;
        margin-left: auto;
    }
    .dash-tab-refresh:hover {
        border-color: #019cff;
        color: #012b58;
    }
    .dash-tab-refresh:disabled {
        opacity: 0.55;
        cursor: not-allowed;
    }
    .tab-panel { display: none; }
    .tab-panel.active { display: block; }

    /* Registration tab: #ccebff bg, all text #012b58, Export #ff7941 */
    #tab-registration,
    #tab-registration .section-title,
    #tab-registration .reg-breadcrumb,
    #tab-registration .reg-breadcrumb a,
    #tab-registration .reg-question-title,
    #tab-registration .reg-meta,
    #tab-registration .reg-preview,
    #tab-registration .chart-label,
    #tab-registration .chart-count,
    #tab-registration .clickable-option:hover .chart-label,
    #tab-registration .people-table th,
    #tab-registration .people-table td,
    #tab-registration .people-table a,
    #tab-registration .btn-back,
    #tab-registration .empty-state,
    #tab-registration .info-banner {
        color: #012b58;
    }
    #tab-registration .section {
        background: #ccebff;
        border: 1px solid #b3d9f5;
    }
    #tab-registration .reg-question-card {
        background: #fffef8;
        border-color: #b3d9f5;
    }
    #tab-registration .reg-question-card:hover {
        border-color: #019cff;
        box-shadow: 0 2px 10px rgba(1, 156, 255, 0.18);
    }
    #tab-registration .chart-bar-fill {
        background: #019cff;
        color: #fff;
    }
    #tab-registration .btn-back {
        background: #fffef8;
        border-color: #b3d9f5;
    }
    #tab-registration .empty-state {
        background: #fffef8;
        border-color: #b3d9f5;
    }
    #tab-registration .info-banner {
        background: #e8f6ff;
        border-left-color: #012b58;
    }
    .reg-toolbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
        margin-bottom: 16px;
        flex-wrap: wrap;
    }
    .btn-reg-excel {
        background: #ff7941;
        color: #fff;
        border: none;
        border-radius: 8px;
        padding: 10px 16px;
        font-weight: 600;
        cursor: pointer;
    }
    .btn-reg-excel:hover { background: #e56a35; color: #fff; }
    .btn-reg-excel:disabled {
        opacity: 0.55;
        cursor: not-allowed;
    }
    .other-group-bar {
        border-radius: 6px;
        padding: 4px 0;
        margin-bottom: 4px;
    }
    .other-group-toggle {
        cursor: pointer;
        display: flex;
        align-items: center;
        gap: 8px;
        width: 100%;
        border: none;
        background: #f8fafc;
        border-radius: 6px;
        padding: 6px 8px;
        text-align: left;
    }
    .other-group-toggle:hover {
        background: #eef6ff;
    }
    .other-group-toggle .chart-label {
        flex: 0 0 140px;
        color: #012b58;
        font-weight: 600;
    }
    .other-variants {
        display: none;
        margin: 4px 0 12px 12px;
        padding-left: 8px;
        border-left: 3px solid #cbd5e1;
    }
    .other-variants.expanded {
        display: block;
    }
    .other-variant-meta {
        font-size: 12px;
        color: #64748b;
        margin: 0 0 8px 0;
    }
    .reg-breadcrumb {
        font-size: 14px;
        color: #64748b;
        margin-bottom: 16px;
    }
    .reg-breadcrumb a {
        color: #019cff;
        cursor: pointer;
        text-decoration: none;
        font-weight: 600;
    }
    .reg-question-card {
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 16px 18px;
        margin-bottom: 12px;
        cursor: pointer;
        transition: box-shadow 0.15s ease, border-color 0.15s ease;
        background: #fff;
    }
    .reg-question-card:hover {
        border-color: #019cff;
        box-shadow: 0 2px 10px rgba(1, 156, 255, 0.18);
    }
    .reg-question-title {
        font-weight: 600;
        color: #1e293b;
        margin: 0 0 8px 0;
        font-size: 16px;
    }
    .reg-meta {
        color: #64748b;
        font-size: 13px;
        margin-bottom: 10px;
    }
    .reg-preview {
        color: #475569;
        font-size: 13px;
        font-style: italic;
        margin-top: 6px;
    }
    .clickable-option {
        cursor: pointer;
    }
    .clickable-option:hover .chart-label {
        color: #019cff;
        text-decoration: underline;
    }
    .age-bar-clickable {
        cursor: pointer;
        border-radius: 6px;
        padding: 4px 0;
        margin-bottom: 11px;
    }
    .age-bar-clickable:hover {
        background: #f1f5f9;
    }
    .age-bar-clickable:hover .chart-label {
        color: #012b58;
        text-decoration: underline;
    }
    .age-bar-clickable.active {
        background: #eef6ff;
    }
    .grade-bar-clickable {
        cursor: pointer;
        border-radius: 6px;
        padding: 4px 0;
        margin-bottom: 11px;
    }
    .grade-bar-clickable:hover {
        background: #f1f5f9;
    }
    .grade-bar-clickable:hover .chart-label {
        color: #012b58;
        text-decoration: underline;
    }
    .grade-bar-clickable.active {
        background: #eef6ff;
    }
    .grade-gender-filters {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin: 0 0 14px 0;
    }
    .grade-gender-filter {
        border: 2px solid #e2e8f0;
        background: #fff;
        color: #334155;
        border-radius: 999px;
        padding: 6px 14px;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
    }
    .grade-gender-filter:hover {
        border-color: #019cff;
        color: #012b58;
    }
    .grade-gender-filter.active {
        background: #012b58;
        border-color: #012b58;
        color: #fff;
    }
    .marital-bar-clickable {
        cursor: pointer;
        border-radius: 6px;
        padding: 4px 0;
        margin-bottom: 11px;
    }
    .marital-bar-clickable:hover {
        background: #f1f5f9;
    }
    .marital-bar-clickable:hover .chart-label {
        color: #012b58;
        text-decoration: underline;
    }
    .marital-bar-clickable.active {
        background: #eef6ff;
    }
    .subgroup-item-clickable {
        cursor: pointer;
    }
    .subgroup-item-clickable:hover {
        background: #eef6ff;
    }
    .subgroup-item-clickable:hover .subgroup-name {
        color: #012b58;
        text-decoration: underline;
    }
    .subgroup-item-clickable.active {
        background: #eef6ff;
        border-left-color: #012b58;
    }
    .people-table {
        width: 100%;
        border-collapse: collapse;
    }
    .people-table th, .people-table td {
        text-align: left;
        padding: 10px 12px;
        border-bottom: 1px solid #e2e8f0;
        vertical-align: top;
    }
    .people-table th {
        color: #64748b;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.4px;
    }
    .people-table a {
        color: #019cff;
        font-weight: 600;
        text-decoration: none;
    }
    .people-table a:hover { text-decoration: underline; }
    .finance-stat-clickable {
        cursor: pointer;
        transition: box-shadow 0.15s ease, transform 0.15s ease;
        border: 2px solid transparent;
    }
    .finance-stat-clickable:hover {
        box-shadow: 0 4px 14px rgba(1, 43, 88, 0.15);
        transform: translateY(-1px);
    }
    .finance-stat-clickable.active {
        border-color: #012b58;
        background: #eef6ff !important;
    }
    .finance-drill-hint {
        font-size: 12px;
        color: #64748b;
        margin-top: 6px;
    }
    .finance-drill-title {
        font-size: 16px;
        font-weight: 600;
        color: #1e293b;
        margin: 0 0 12px 0;
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
        flex-wrap: wrap;
    }
    .drill-actions {
        display: flex;
        gap: 8px;
        align-items: center;
        flex-wrap: wrap;
    }
    .btn-tag-add {
        background: #012b58;
        color: #fff;
        border: none;
        border-radius: 8px;
        padding: 8px 14px;
        font-weight: 600;
        cursor: pointer;
    }
    .btn-tag-add:hover { background: #019cff; color: #fff; }
    .btn-tag-add:disabled {
        opacity: 0.55;
        cursor: not-allowed;
    }
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
        background: #012b58;
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
        border-color: #019cff;
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
    .tag-modal-options input {
        margin-top: 3px;
    }
    .tag-modal-footer {
        padding: 14px 20px 20px;
        display: flex;
        justify-content: flex-end;
        gap: 8px;
    }
    .btn-tag-confirm {
        background: #012b58;
        color: #fff;
        border: none;
        border-radius: 8px;
        padding: 10px 16px;
        font-weight: 600;
        cursor: pointer;
    }
    .btn-tag-confirm:hover { background: #019cff; }
    .btn-back {
        background: #f1f5f9;
        color: #334155;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 8px 14px;
        font-weight: 600;
        cursor: pointer;
    }
    .empty-state {
        background: #f8fafc;
        border: 1px dashed #cbd5e1;
        border-radius: 10px;
        padding: 28px;
        text-align: center;
        color: #64748b;
    }
    .info-banner {
        background: #eff6ff;
        border-left: 4px solid #3b82f6;
        padding: 16px 18px;
        border-radius: 8px;
        color: #1e3a8a;
    }
    .loading-overlay {
        display: none;
        position: fixed;
        inset: 0;
        z-index: 10100;
        background: rgba(15, 23, 42, 0.35);
        align-items: center;
        justify-content: center;
    }
    .loading-overlay.visible {
        display: flex;
    }
    .loading-card {
        background: #fff;
        border-radius: 14px;
        padding: 28px 36px;
        box-shadow: 0 12px 40px rgba(15, 23, 42, 0.25);
        text-align: center;
        min-width: 220px;
    }
    .loading-spinner {
        width: 48px;
        height: 48px;
        margin: 0 auto 16px;
        border: 4px solid #e2e8f0;
        border-top-color: #019cff;
        border-radius: 50%;
        animation: dash-spin 0.8s linear infinite;
    }
    .loading-overlay.reg-loading .loading-spinner {
        border-top-color: #019cff;
    }
    .loading-text {
        color: #1e293b;
        font-size: 15px;
        font-weight: 600;
        margin: 0;
    }
    .loading-subtext {
        color: #64748b;
        font-size: 13px;
        margin: 8px 0 0;
    }
    .btn-cancel-loading {
        margin-top: 16px;
        background: #f1f5f9;
        color: #334155;
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        padding: 8px 16px;
        font-weight: 600;
        cursor: pointer;
    }
    .btn-cancel-loading:hover {
        background: #e2e8f0;
    }
    @keyframes dash-spin {
        to { transform: rotate(360deg); }
    }
</style>

<div class="dashboard-container">
    <div class="loading-overlay" id="loading-overlay" aria-live="polite" aria-busy="false">
        <div class="loading-card">
            <div class="loading-spinner"></div>
            <p class="loading-text" id="loading-text">Loading...</p>
            <p class="loading-subtext">This may take a minute to go to space and back. 🚀</p>
            <button type="button" class="btn-cancel-loading" id="btn-cancel-loading">Cancel</button>
        </div>
    </div>

    <div class="tag-modal-overlay" id="tag-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="tag-modal-title">
        <div class="tag-modal">
            <div class="tag-modal-header" id="tag-modal-title">Add to Tag</div>
            <div class="tag-modal-body">
                <p class="tag-modal-meta" id="tag-modal-count"></p>
                <label for="tag-name-input">Tag name</label>
                <input type="text" id="tag-name-input" maxlength="50" placeholder="e.g. FW Volunteers 18-24" autocomplete="off" />
                <div class="tag-modal-options">
                    <label class="option-row">
                        <input type="radio" name="tag-mode" value="append" checked />
                        <span>Append — add these people; keep anyone already on the tag</span>
                    </label>
                    <label class="option-row">
                        <input type="radio" name="tag-mode" value="clear" />
                        <span>Clear first — empty the tag, then add only this list</span>
                    </label>
                    <label class="option-row">
                        <input type="checkbox" id="tag-open-when-done" checked />
                        <span>Open the tag in a new tab when done</span>
                    </label>
                </div>
            </div>
            <div class="tag-modal-footer">
                <button type="button" class="btn-back" id="btn-tag-cancel">Cancel</button>
                <button type="button" class="btn-tag-confirm" id="btn-tag-confirm">Add to Tag</button>
            </div>
        </div>
    </div>

    <div class="dashboard-header" id="dashboard-header" style="display:block;">
        <div class="dashboard-header-graphic" id="header-graphic">
            <img id="org-graphic" alt="Involvement title graphic" />
        </div>
        <div class="dashboard-header-body">
            <div class="dashboard-header-badge" id="header-badge">
                <img id="org-badge" alt="Channel logo" />
            </div>
            <div class="dashboard-header-text">
                <h1 id="org-name">Awana Registration</h1>
                <p id="org-info" style="margin: 0; opacity: 0.9;">Next Generation</p>
            </div>
        </div>
    </div>

        <div class="dash-tabs visible" id="dash-tabs">
            <button type="button" class="dash-tab active" data-tab="overview">Overview</button>
            <button type="button" class="dash-tab" data-tab="volunteers">Volunteers</button>
            <button type="button" class="dash-tab" data-tab="puggles">Puggles</button>
            <button type="button" class="dash-tab" data-tab="cubbies">Cubbies</button>
            <button type="button" class="dash-tab" data-tab="sparks">Sparks</button>
            <button type="button" class="dash-tab" data-tab="tnt-girls">TnT Girls</button>
            <button type="button" class="dash-tab" data-tab="tnt-boys">TnT Boys</button>
            <button type="button" class="dash-tab-refresh" id="btn-refresh-dashboard" title="Refresh" aria-label="Refresh">
                <i class="fa fa-refresh"></i>
            </button>
        </div>

        <div class="tab-panel active" id="tab-overview">
            <div class="club-cards" id="club-cards"></div>
            <div class="stats-grid" id="stats-grid"></div>
            <div id="gender-drilldown" style="display:none; margin: 0 0 30px 0;"></div>
            <div class="section" id="age-section" style="display:none;">
                <h2 class="section-title" id="distribution-title"><i class="fa fa-chart-bar"></i> Age Distribution</h2>
                <p class="finance-drill-hint" style="margin-top:-8px;margin-bottom:12px;">Click an age group to view people</p>
                <div id="age-chart"></div>
                <div id="age-drilldown" style="display:none; margin-top: 18px;"></div>
            </div>
            <div class="section" id="grade-section" style="display:none;">
                <h2 class="section-title"><i class="fa fa-graduation-cap"></i> Grade Distribution</h2>
                <p class="finance-drill-hint" style="margin-top:-8px;margin-bottom:12px;">All Clubbers combined. Open a club tab for people lists.</p>
                <div id="grade-chart"></div>
                <div id="grade-drilldown" style="display:none; margin-top: 18px;"></div>
            </div>
            <div class="section" id="marital-section" style="display:none;">
                <h2 class="section-title"><i class="fa fa-heart"></i> Marital Status</h2>
                <p class="finance-drill-hint" style="margin-top:-8px;margin-bottom:12px;">Click a status to view people</p>
                <div id="marital-chart"></div>
                <div id="marital-drilldown" style="display:none; margin-top: 18px;"></div>
            </div>
            <div class="section" id="timeline-section" style="display:none;">
                <h2 class="section-title"><i class="fa fa-calendar-plus"></i> Enrollment Timeline (Last 12 Months)</h2>
                <div id="timeline-chart"></div>
            </div>
            <div class="section" id="transaction-section" style="display:none;">
                <h2 class="section-title"><i class="fa fa-dollar"></i> Financial Transactions</h2>
                <div id="transaction-summary"></div>
                <div id="finance-drilldown" style="display:none; margin-top: 18px;"></div>
            </div>
            <div class="section" id="subgroup-section" style="display:none;">
                <h2 class="section-title"><i class="fa fa-layer-group"></i> Subgroups</h2>
                <p class="finance-drill-hint" style="margin-top:-8px;margin-bottom:12px;">Click a subgroup to view people</p>
                <div id="subgroup-list"></div>
                <div id="subgroup-drilldown" style="display:none; margin-top: 18px;"></div>
            </div>
        </div>

        <div class="tab-panel" id="tab-volunteers">
            <div class="section">
                <div class="reg-toolbar">
                    <h2 class="section-title" style="margin:0;"><i class="fa fa-users"></i> Volunteers</h2>
                    <div>
                        <button type="button" class="btn-reg-excel" id="btn-vol-export" style="display:none;">
                            <i class="fa fa-download"></i> Export Volunteers
                        </button>
                    </div>
                </div>
                <div class="club-subtabs" id="vol-club-subtabs"></div>
                <div id="volunteers-view"></div>
            </div>
        </div>

        <div class="tab-panel" id="tab-club">
            <div class="club-empty" id="club-empty" style="display:none;"></div>
            <div class="club-org-picker" id="club-org-picker"></div>
            <div id="club-detail" style="display:none;">
                <div class="reg-toolbar" style="margin-bottom:12px;">
                    <div class="club-subtabs" id="club-subtabs" style="margin:0;">
                        <button type="button" class="club-subtab active" data-subtab="club-overview">Overview</button>
                        <button type="button" class="club-subtab" data-subtab="registration">Registration</button>
                        <button type="button" class="club-subtab" data-subtab="allergies">Allergies</button>
                        <button type="button" class="club-subtab" data-subtab="contacts">Contacts</button>
                    </div>
                    <div>
                        <button type="button" class="btn-reg-excel" id="btn-reg-excel" style="display:none;">
                            <i class="fa fa-download"></i> Export Clubbers
                        </button>
                    </div>
                </div>
                <div class="tab-panel active" id="tab-club-overview">
                    <div class="section">
                        <div class="reg-toolbar">
                            <h2 class="section-title" style="margin:0;"><i class="fa fa-list"></i> Clubbers</h2>
                        </div>
                        <p class="finance-drill-hint" style="margin-top:0;margin-bottom:12px;">
                            Age and grade for this club. A red A means an allergy is on file — click it to open Allergies.
                        </p>
                        <div id="club-overview-view"></div>
                    </div>
                </div>
                <div class="tab-panel" id="tab-registration">
                    <div class="section">
                        <div class="reg-toolbar">
                            <h2 class="section-title" style="margin:0;"><i class="fa fa-clipboard-list"></i> Registration Questions</h2>
                        </div>
                        <div class="reg-breadcrumb" id="reg-breadcrumb"></div>
                        <div id="reg-view"></div>
                    </div>
                </div>
                <div class="tab-panel" id="tab-allergies">
                    <div class="section">
                        <div class="reg-toolbar">
                            <h2 class="section-title" style="margin:0;"><i class="fa fa-medkit"></i> Allergies</h2>
                        </div>
                        <p class="finance-drill-hint" style="margin-top:0;margin-bottom:12px;">
                            Participants with allergy notes from the default allergies list (RecReg).
                        </p>
                        <div id="allergies-view"></div>
                    </div>
                </div>
                <div class="tab-panel" id="tab-contacts">
                    <div class="section">
                        <div class="reg-toolbar">
                            <h2 class="section-title" style="margin:0;"><i class="fa fa-users"></i> Parents &amp; Emergency Contacts</h2>
                        </div>
                        <p class="finance-drill-hint" style="margin-top:0;margin-bottom:12px;">
                            Next Gen stock fields from RecReg: mother, father, and emergency contact.
                        </p>
                        <div id="contacts-view"></div>
                    </div>
                </div>
            </div>
        </div>
</div>

<script>
(function() {
    function initDashboard() {
        var scriptUrl = window.location.pathname;
        var currentOrgId = null;
        var currentSubgroupId = 0;
        var currentShowContacts = true;
        var currentClubKey = null;
        var currentVolClubKey = null;
        var currentSubtab = 'club-overview';
        var staffRosterState = { people: [], filter: 'all' };
        var awanaData = null;
        var initialOrgId = __INITIAL_ORG_ID__;
        var initialOrgName = __INITIAL_ORG_NAME__;
        var initialClub = __INITIAL_CLUB__;
        var clubKeys = ['puggles', 'cubbies', 'sparks', 'tnt-girls', 'tnt-boys'];
        var regState = { view: 'summary', question: null, option: null, person: null, summary: null };
        var gradeDrillState = { label: '', people: [], filter: 'all' };
        var currentXhr = null;
        var loadGeneration = 0;

        function esc(s) {
            return String(s == null ? '' : s)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        }

        function personLink(peopleId, name) {
            return '<a href="/Person2/' + encodeURIComponent(peopleId) + '" target="_blank" rel="noopener">' + esc(name) + '</a>';
        }

        var pendingTagPeopleIds = [];

        function collectPeopleIds(people) {
            var ids = [];
            var seen = {};
            (people || []).forEach(function(p) {
                var id = p && p.people_id ? parseInt(p.people_id, 10) : 0;
                if (id > 0 && !seen[id]) {
                    seen[id] = true;
                    ids.push(id);
                }
            });
            return ids;
        }

        function drillActionsHtml(options) {
            options = options || {};
            var ids = options.peopleIds || [];
            var html = '<div class="drill-actions">';
            if (ids.length) {
                html += '<button type="button" class="btn-tag-add" data-people-ids="' + esc(ids.join(',')) + '"';
                if (options.tagSuggest) {
                    html += ' data-tag-suggest="' + esc(options.tagSuggest) + '"';
                }
                html += '>';
                html += '<i class="fa fa-tag"></i> Add to Tag</button>';
            }
            if (options.closeBtnId) {
                html += '<button type="button" class="btn-back" id="' + esc(options.closeBtnId) + '">' +
                    esc(options.closeLabel || 'Close') + '</button>';
            }
            if (options.backNav) {
                html += '<button type="button" class="btn-back" data-nav="' + esc(options.backNav) + '">';
                html += '<i class="fa fa-arrow-left"></i> ' + esc(options.backLabel || 'Back') + '</button>';
            }
            html += '</div>';
            return html;
        }

        function openTagModal(peopleIds, suggestedName) {
            pendingTagPeopleIds = peopleIds || [];
            if (!pendingTagPeopleIds.length) {
                alert('No people in this list to tag.');
                return;
            }
            $('#tag-modal-count').text(pendingTagPeopleIds.length + ' people will be added to this tag.');
            $('#tag-name-input').val(suggestedName || '');
            $('input[name="tag-mode"][value="append"]').prop('checked', true);
            $('#tag-open-when-done').prop('checked', true);
            $('#tag-modal-overlay').addClass('visible');
            setTimeout(function() { $('#tag-name-input').focus().select(); }, 50);
        }

        function closeTagModal() {
            $('#tag-modal-overlay').removeClass('visible');
            pendingTagPeopleIds = [];
        }

        function submitAddToTag() {
            var tagName = $.trim($('#tag-name-input').val() || '');
            if (!tagName) {
                alert('Enter a tag name.');
                $('#tag-name-input').focus();
                return;
            }
            if (!pendingTagPeopleIds.length) {
                alert('No people to tag.');
                return;
            }
            var clearFirst = $('input[name="tag-mode"]:checked').val() === 'clear';
            var openWhenDone = $('#tag-open-when-done').is(':checked');
            var idsCsv = pendingTagPeopleIds.join(',');
            $('#tag-modal-overlay').removeClass('visible');
            showLoading('Adding people to tag...', false);
            ajaxPost({
                action: 'add_to_tag',
                people_ids: idsCsv,
                tag_name: tagName,
                clear_first: clearFirst ? '1' : '0'
            }, function(data) {
                pendingTagPeopleIds = [];
                if (data.error) {
                    alert(data.error);
                    $('#tag-modal-overlay').addClass('visible');
                    return;
                }
                var msg = (data.count || 0) + ' people added to tag "' + (data.tag_name || tagName) + '"';
                if (data.cleared) msg += ' (tag cleared first)';
                if (openWhenDone && data.tag_url) {
                    window.open(data.tag_url, '_blank', 'noopener');
                } else {
                    alert(msg + '.');
                }
            }, { showLoading: true });
        }

        $(document).on('click', '.btn-tag-add', function() {
            var ids = String($(this).attr('data-people-ids') || '')
                .split(',')
                .map(function(x) { return parseInt(x, 10); })
                .filter(function(x) { return x > 0; });
            var suggested = String($(this).attr('data-tag-suggest') || '');
            openTagModal(ids, suggested);
        });

        $(document).on('click', '#btn-tag-cancel', function() {
            closeTagModal();
        });

        $(document).on('click', '#btn-tag-confirm', function() {
            submitAddToTag();
        });

        $(document).on('keydown', '#tag-name-input', function(e) {
            if (e.which === 13) {
                e.preventDefault();
                submitAddToTag();
            } else if (e.which === 27) {
                closeTagModal();
            }
        });

        $(document).on('click', '#tag-modal-overlay', function(e) {
            if (e.target === this) closeTagModal();
        });

        function showLoading(message, isReg) {
            $('#loading-text').text(message || 'Loading...');
            $('#loading-overlay')
                .toggleClass('reg-loading', !!isReg)
                .attr('aria-busy', 'true')
                .addClass('visible');
        }

        function hideLoading() {
            $('#loading-overlay')
                .attr('aria-busy', 'false')
                .removeClass('visible reg-loading');
        }

        function cancelLoading() {
            loadGeneration += 1;
            if (currentXhr && typeof currentXhr.abort === 'function') {
                try { currentXhr.abort(); } catch (e) {}
            }
            currentXhr = null;
            hideLoading();
            $('#finance-drilldown').filter(':visible').html(
                '<div class="empty-state">Request cancelled.</div>'
            );
            $('.finance-stat-clickable').removeClass('active');
        }

        $('#btn-cancel-loading').on('click', function() {
            cancelLoading();
        });

        function clubPost(data, success, options) {
            return ajaxPost($.extend({
                org_id: currentOrgId,
                subgroup_id: currentSubgroupId || 0
            }, data || {}), success, options);
        }

        function ajaxPost(data, success, options) {
            options = options || {};
            var gen = loadGeneration;
            currentXhr = $.ajax({
                url: scriptUrl,
                type: 'POST',
                data: $.extend({ ajax: 'true' }, data),
                success: function(response) {
                    if (gen !== loadGeneration) return;
                    var parsed = typeof response === 'string' ? JSON.parse(response) : response;
                    success(parsed);
                },
                error: function(xhr, textStatus) {
                    if (textStatus === 'abort' || gen !== loadGeneration) return;
                    alert('Request failed: ' + (xhr.statusText || 'error'));
                },
                complete: function(xhr) {
                    if (currentXhr === xhr) {
                        currentXhr = null;
                    }
                    if (options.hideLoadingOnComplete !== false && options.showLoading) {
                        if (gen === loadGeneration) {
                            hideLoading();
                        }
                    }
                    if (typeof options.complete === 'function') {
                        options.complete();
                    }
                }
            });
            return currentXhr;
        }

        $(document).on('click', '.dash-tab', function() {
            var tab = String($(this).data('tab') || '');
            if (!tab) return;
            $('.dash-tab').removeClass('active');
            $(this).addClass('active');
            if (tab === 'overview') {
                showOverviewTab();
            } else if (tab === 'volunteers') {
                openVolunteersTab();
            } else if (clubKeys.indexOf(tab) >= 0) {
                openClubTab(tab);
            }
        });

        $(document).on('click', '#club-subtabs .club-subtab', function() {
            var sub = String($(this).data('subtab') || 'registration');
            setClubSubtab(sub, true);
        });

        $(document).on('click', '#btn-refresh-dashboard', function() {
            if ($('#tab-volunteers').hasClass('active')) {
                openVolunteersTab(true);
            } else if (currentClubKey) {
                openClubTab(currentClubKey, true);
            } else {
                loadAwanaOverview();
            }
        });

        function findClub(key) {
            var clubs = (awanaData && awanaData.clubs) || [];
            for (var i = 0; i < clubs.length; i++) {
                if (clubs[i].key === key) return clubs[i];
            }
            return null;
        }

        function setHeader(title, subtitle, orgId) {
            if (orgId) {
                $('#org-name').html(
                    '<a href="/Org/' + esc(String(orgId)) + '" target="_blank" rel="noopener noreferrer">' +
                    esc(title) + '</a>'
                );
            } else {
                $('#org-name').text(title || 'Awana Registration');
            }
            $('#org-info').text(subtitle || 'Next Generation · Awana');
        }

        function applyHero(org) {
            org = org || (awanaData && awanaData.clubbers_org) || {};
            if (org.title_graphic_url) {
                $('#org-graphic')
                    .attr('src', org.title_graphic_url)
                    .attr('alt', (org.name || 'Awana') + ' title graphic')
                    .off('error').on('error', function() {
                        $('#header-graphic').removeClass('visible');
                    });
                $('#header-graphic').addClass('visible');
            } else {
                $('#org-graphic').removeAttr('src');
                $('#header-graphic').removeClass('visible');
            }
            if (org.badge_url) {
                $('#org-badge')
                    .attr('src', org.badge_url)
                    .attr('alt', (org.name || 'Awana') + ' logo')
                    .off('error').on('error', function() {
                        $('#header-badge').removeClass('visible');
                    });
                $('#header-badge').addClass('visible');
            } else {
                $('#org-badge').removeAttr('src');
                $('#header-badge').removeClass('visible');
            }
        }

        function showOverviewTab() {
            currentClubKey = null;
            currentVolClubKey = null;
            currentOrgId = null;
            currentSubgroupId = 0;
            $('#tab-club').removeClass('active');
            $('#tab-volunteers').removeClass('active');
            $('#tab-overview').addClass('active');
            var clubbers = awanaData && awanaData.clubbers_org;
            var subtitle = (awanaData && awanaData.profile_name ? awanaData.profile_name + ' · ' : '');
            subtitle += clubbers ? (clubbers.name + ' #' + clubbers.id) : 'Awana';
            setHeader('Awana Registration', subtitle, clubbers ? clubbers.id : null);
            applyHero(clubbers);
        }

        function setClubSubtab(sub, load) {
            currentSubtab = sub || 'club-overview';
            $('#club-subtabs .club-subtab').removeClass('active');
            $('#club-subtabs .club-subtab[data-subtab="' + currentSubtab + '"]').addClass('active');
            $('#club-detail .tab-panel').removeClass('active');
            $('#tab-' + currentSubtab).addClass('active');
            if (!load || !currentOrgId) return;
            if (currentSubtab === 'club-overview') loadClubOverview();
            else if (currentSubtab === 'registration') loadRegistrationSummary();
            else if (currentSubtab === 'allergies') loadAllergies();
            else if (currentSubtab === 'contacts') loadContacts();
        }

        function selectClub(club, opts) {
            opts = opts || {};
            var clubbers = (awanaData && awanaData.clubbers_org) || {};
            currentOrgId = String(clubbers.id || '');
            currentSubgroupId = club.clubbers_tag_id || 0;
            var parts = [];
            parts.push((club.clubbers_count || 0) + ' clubbers');
            if (clubbers.id) parts.push('Inv #' + clubbers.id);
            setHeader(club.label, parts.join(' · '), clubbers.id);
            applyHero(awanaData && awanaData.clubbers_org);
            $('#club-org-picker').removeClass('visible').empty();
            $('#club-empty').hide();
            $('#club-detail').show();
            if (currentClubKey) $('#btn-reg-excel').show();
            var sub = opts.subtab || currentSubtab || 'club-overview';
            setClubSubtab(sub, true);
        }

        function openClubTab(key, forceReload) {
            currentClubKey = key;
            currentVolClubKey = null;
            $('#tab-overview').removeClass('active');
            $('#tab-volunteers').removeClass('active');
            $('#tab-club').addClass('active');
            $('.dash-tab').removeClass('active');
            $('.dash-tab[data-tab="' + key + '"]').addClass('active');

            var club = findClub(key);
            var label = club ? club.label : key;
            if (!club || !club.clubbers_tag_id) {
                currentOrgId = null;
                currentSubgroupId = 0;
                $('#club-detail').hide();
                $('#btn-reg-excel').hide();
                $('#club-org-picker').removeClass('visible').empty();
                $('#club-empty').show().html(
                    'No subgroup named <strong>' + esc(label) +
                    '</strong> on Clubbers (involvement #' +
                    esc(String((awanaData && awanaData.clubbers_org && awanaData.clubbers_org.id) || '1916')) + ').'
                );
                return;
            }
            if (forceReload) {
                currentOrgId = null;
            }
            selectClub(club);
        }

        function csvEscape(s) {
            s = String(s == null ? '' : s);
            if (/[",\n\r]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
            return s;
        }

        function downloadCsv(filename, header, rows) {
            var lines = [header.map(csvEscape).join(',')];
            (rows || []).forEach(function(row) {
                lines.push(row.map(csvEscape).join(','));
            });
            var blob = new Blob([lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
            var url = (window.URL || window.webkitURL).createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = filename || 'export.csv';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            setTimeout(function() {
                try { (window.URL || window.webkitURL).revokeObjectURL(url); } catch (e) {}
            }, 500);
        }

        function openVolunteersTab(forceReload) {
            currentClubKey = null;
            $('#tab-overview').removeClass('active');
            $('#tab-club').removeClass('active');
            $('#tab-volunteers').addClass('active');
            $('.dash-tab').removeClass('active');
            $('.dash-tab[data-tab="volunteers"]').addClass('active');

            var volunteers = (awanaData && awanaData.volunteers_org) || {};
            setHeader(volunteers.name || 'Volunteers',
                (volunteers.id ? 'Inv #' + volunteers.id : 'Awana volunteers'),
                volunteers.id);
            applyHero(awanaData && awanaData.clubbers_org);

            var total = (awanaData && awanaData.volunteer_members) || 0;
            var html = '<button type="button" class="club-subtab" data-vol-club="overview">Overview (' + total + ')</button>';
            ((awanaData && awanaData.clubs) || []).forEach(function(club) {
                html += '<button type="button" class="club-subtab" data-vol-club="' + esc(club.key) + '">' +
                    esc(club.label) + ' (' + (club.volunteer_count || 0) + ')</button>';
            });
            if (awanaData && awanaData.show_staff_tab) {
                html += '<button type="button" class="club-subtab vol-staff" data-vol-club="staff">Volunteer Management</button>';
            }
            $('#vol-club-subtabs').html(html);

            var key = currentVolClubKey;
            if (!key || forceReload) key = 'overview';
            if (key === 'staff' && !(awanaData && awanaData.show_staff_tab)) key = 'overview';
            selectVolunteerClub(key);
        }

        function selectVolunteerClub(key) {
            currentVolClubKey = key;
            $('.club-subtab[data-vol-club]').removeClass('active');
            $('.club-subtab[data-vol-club="' + key + '"]').addClass('active');
            var volunteers = (awanaData && awanaData.volunteers_org) || {};
            if (!volunteers.id) {
                $('#btn-vol-export').hide();
                $('#volunteers-view').html('<div class="empty-state">No volunteer involvement found.</div>');
                return;
            }
            currentOrgId = String(volunteers.id);
            var mode = 'club';
            currentSubgroupId = 0;
            if (key === 'overview') {
                mode = 'overview';
            } else if (key === 'staff') {
                mode = 'staff';
            } else {
                var club = findClub(key);
                if (!club || !club.volunteer_tag_id) {
                    $('#btn-vol-export').hide();
                    $('#volunteers-view').html('<div class="empty-state">No subgroup named <strong>' +
                        esc(club ? club.label : key) + '</strong> on Volunteers.</div>');
                    return;
                }
                currentSubgroupId = club.volunteer_tag_id;
            }
            showLoading('Loading volunteers...', false);
            $('#volunteers-view').html('<div class="empty-state">Loading...</div>');
            clubPost({ action: 'get_volunteer_roster', mode: mode }, function(data) {
                if (data && data.error) {
                    $('#btn-vol-export').hide();
                    $('#volunteers-view').html('<div class="info-banner">Error: ' + esc(data.error) + '</div>');
                    return;
                }
                renderVolunteerRoster(key, data || {});
            }, { showLoading: true });
        }

        function minorPillHtml(p) {
            return (p && p.is_minor) ? '<span class="minor-pill">Minor</span>' : '';
        }

        function staffDateInput(p, field, iso) {
            var title = '';
            if (field === 'inperson' && p && p.is_minor) {
                title = ' title="Minor Child Protection Training"';
            }
            return '<input type="date" class="staff-ev-date" data-pid="' +
                esc(String(p.people_id || '')) + '" data-field="' + esc(field) +
                '" value="' + esc(iso || '') + '"' + title + ' />';
        }

        function staffFilterPeople(people, filter) {
            people = people || [];
            if (filter === 'missing-bc') {
                return people.filter(function(p) { return !p.is_minor && !p.bg_date; });
            }
            if (filter === 'missing-video') {
                return people.filter(function(p) { return !p.is_minor && !p.video_date; });
            }
            if (filter === 'missing-app') {
                return people.filter(function(p) { return !p.has_application; });
            }
            if (filter === 'missing-inperson-minor') {
                return people.filter(function(p) { return p.is_minor && !p.inperson_date; });
            }
            if (filter === 'missing-inperson-adult') {
                return people.filter(function(p) { return !p.is_minor && !p.inperson_date; });
            }
            if (filter === 'missing-handbook') {
                return people.filter(function(p) { return !p.is_minor && !p.handbook_date; });
            }
            return people;
        }

        function staffFilterBarHtml(filter) {
            var items = [
                { key: 'all', label: 'All' },
                { key: 'missing-app', label: 'Missing application' },
                { key: 'missing-bc', label: 'Missing background check' },
                { key: 'missing-video', label: 'Missing video training' },
                { key: 'missing-inperson-minor', label: 'Minors missing in-person training' },
                { key: 'missing-inperson-adult', label: 'Adults missing in-person training' },
                { key: 'missing-handbook', label: 'Adults missing handbook' }
            ];
            var html = '<div class="staff-filters">';
            items.forEach(function(item) {
                html += '<button type="button" class="staff-filter' + (filter === item.key ? ' active' : '') +
                    '" data-staff-filter="' + item.key + '">' + esc(item.label) + '</button>';
            });
            html += '</div>';
            return html;
        }

        function staffTagSuggest(filter) {
            if (filter === 'missing-app') return 'Awana Missing Application';
            if (filter === 'missing-bc') return 'Awana Missing Background Check';
            if (filter === 'missing-video') return 'Awana Missing Video Training';
            if (filter === 'missing-inperson-minor') return 'Awana Minors Missing Training';
            if (filter === 'missing-inperson-adult') return 'Awana Adults Missing Training';
            if (filter === 'missing-handbook') return 'Awana Missing Handbook';
            return 'Awana Volunteers';
        }

        function renderVolunteerRoster(key, data) {
            var allPeople = data.people || [];
            if (key === 'staff') {
                staffRosterState.people = allPeople;
            }
            var filter = (key === 'staff') ? (staffRosterState.filter || 'all') : 'all';
            var people = (key === 'staff') ? staffFilterPeople(allPeople, filter) : allPeople;
            var title = 'Volunteers';
            if (key === 'overview') title = 'All volunteers';
            else if (key === 'staff') title = 'Volunteer Management';
            else {
                var club = findClub(key);
                title = (club && club.label) ? club.label + ' volunteers' : 'Volunteers';
            }
            if (!allPeople.length) {
                $('#btn-vol-export').hide();
                $('#volunteers-view').html('<div class="empty-state">No volunteers' +
                    (key === 'overview' || key === 'staff' ? '.' : ' in <strong>' + esc(title.replace(' volunteers', '')) + '</strong>.') +
                    '</div>');
                return;
            }
            $('#btn-vol-export').show();
            var ids = collectPeopleIds(people);
            var html = '';
            if (key === 'staff') {
                html += staffFilterBarHtml(filter);
            }
            html += '<div class="reg-meta" style="margin-bottom:14px;">' + esc(title) + ': <strong>' + people.length + '</strong>';
            if (key === 'staff' && filter !== 'all') {
                html += ' of ' + allPeople.length;
            }
            html += '</div>';
            var tagOpts = { peopleIds: ids };
            if (key === 'staff') tagOpts.tagSuggest = staffTagSuggest(filter);
            html += drillActionsHtml(tagOpts);
            if (!people.length) {
                var emptyMsg = 'No volunteers match this filter.';
                if (filter === 'missing-app') emptyMsg = 'No volunteers missing an application.';
                else if (filter === 'missing-bc') emptyMsg = 'No adults missing a background check.';
                else if (filter === 'missing-video') emptyMsg = 'No adults missing video training.';
                else if (filter === 'missing-inperson-minor') emptyMsg = 'No minors missing in-person training.';
                else if (filter === 'missing-inperson-adult') emptyMsg = 'No adults missing in-person training.';
                else if (filter === 'missing-handbook') emptyMsg = 'No adults missing a handbook signature.';
                html += '<div class="empty-state">' + emptyMsg + '</div>';
                $('#volunteers-view').html(html);
                return;
            }
            html += '<table class="people-table"><thead><tr><th>Person</th>';
            if (key === 'overview' || key === 'staff') {
                html += '<th>Age</th><th>Clubs</th>';
            }
            if (key === 'staff') {
                html += '<th>Application</th><th>Background Check</th><th>Video Training</th><th>In-Person Training</th><th>Handbook</th>';
            }
            html += '</tr></thead><tbody>';
            people.forEach(function(p) {
                html += '<tr><td>' + personLink(p.people_id, p.name) + minorPillHtml(p) + '</td>';
                if (key === 'overview' || key === 'staff') {
                    html += '<td>' + esc(p.age === 0 || p.age ? String(p.age) : '') + '</td>';
                    html += '<td>' + esc(p.clubs_label || '') + '</td>';
                }
                if (key === 'staff') {
                    html += '<td>' + esc(p.app_date || (p.has_application ? 'On file' : '')) + '</td>';
                    if (p.is_minor) {
                        html += '<td><span class="na-muted">not applicable</span></td>';
                        html += '<td><span class="na-muted">not applicable</span></td>';
                    } else {
                        html += '<td>' + esc(p.bg_date || '') + '</td>';
                        html += '<td>' + esc(p.video_date || '') + '</td>';
                    }
                    html += '<td>' + staffDateInput(p, 'inperson', p.inperson_iso) + '</td>';
                    if (p.is_minor) {
                        html += '<td><span class="na-muted">not applicable</span></td>';
                    } else {
                        html += '<td>' + staffDateInput(p, 'handbook', p.handbook_iso) + '</td>';
                    }
                }
                html += '</tr>';
            });
            html += '</tbody></table>';
            $('#volunteers-view').html(html);
        }

        $(document).on('change', '.staff-ev-date', function() {
            var $inp = $(this);
            var pid = $inp.attr('data-pid');
            var field = $inp.attr('data-field');
            var dateVal = $inp.val() || '';
            $inp.prop('disabled', true);
            clubPost({
                action: 'set_ev_date',
                people_id: pid,
                ev_field: field,
                ev_date: dateVal
            }, function(data) {
                if (data && data.error) {
                    alert(data.error);
                    return;
                }
                if (data && data.iso) $inp.val(data.iso);
                else if (!dateVal) $inp.val('');
                $inp.addClass('saved');
                setTimeout(function() { $inp.removeClass('saved'); }, 1200);
            }, {
                showLoading: false,
                complete: function() { $inp.prop('disabled', false); }
            });
        });

        $(document).on('click', '.staff-filter', function() {
            staffRosterState.filter = String($(this).attr('data-staff-filter') || 'all');
            renderVolunteerRoster('staff', { people: staffRosterState.people || [] });
        });

        $(document).on('click', '.club-subtab[data-vol-club]', function() {
            selectVolunteerClub(String($(this).attr('data-vol-club') || ''));
        });

        $(document).on('click', '#btn-vol-export', function() {
            var name = 'Volunteers';
            if (currentVolClubKey === 'overview') name = 'All-Volunteers';
            else if (currentVolClubKey === 'staff') name = 'Volunteer-Management';
            else {
                var club = findClub(currentVolClubKey);
                if (club && club.label) name = club.label + '-Volunteers';
            }
            exportRosterCsv(name + '.csv', 'volunteers');
        });

        function exportRosterCsv(filename, kind) {
            kind = kind || 'volunteers';
            if (!currentOrgId) return;
            if (kind === 'clubbers' && !currentSubgroupId) {
                alert('Select a club first.');
                return;
            }
            showLoading('Preparing export...', false);
            clubPost({ action: 'get_club_roster' }, function(data) {
                if (data && data.error) {
                    alert(data.error);
                    return;
                }
                var rows = [];
                var header;
                if (kind === 'clubbers') {
                    header = ['PeopleId', 'Name', 'Grade', 'Gender', 'Email', 'Emergency Contact', 'Parents'];
                    (data.people || []).forEach(function(p) {
                        rows.push([p.people_id, p.name, p.grade, p.gender, p.email, p.emergency, p.parents]);
                    });
                } else {
                    header = ['PeopleId', 'Last', 'First', 'Name', 'Grade', 'Gender', 'Email'];
                    (data.people || []).forEach(function(p) {
                        rows.push([p.people_id, p.last, p.first, p.name, p.grade, p.gender, p.email]);
                    });
                }
                downloadCsv(filename, header, rows);
            }, { showLoading: true });
        }

        $(document).on('click', '.club-card[data-club]', function() {
            var key = String($(this).attr('data-club') || '');
            if (!key || $(this).hasClass('empty')) return;
            openClubTab(key);
        });

        function renderClubCards(data) {
            var html = '';
            (data.clubs || []).forEach(function(club) {
                var empty = !club.clubbers_tag_id;
                html += '<div class="club-card' + (empty ? ' empty' : '') + '" data-club="' + esc(club.key) + '">';
                html += '<div class="club-card-label">' + esc(club.label) + '</div>';
                if (empty) {
                    html += '<p class="club-card-meta">No matching subgroup on Clubbers</p>';
                    html += '<div class="club-card-count">—</div>';
                } else {
                    html += '<div class="club-card-count">' + (club.clubbers_count || 0) + '</div>';
                    html += '<p class="club-card-meta">clubbers</p>';
                }
                html += '</div>';
            });
            $('#club-cards').html(html);
        }

        function renderAwanaOverview(data) {
            awanaData = data;
            renderClubCards(data);
            var clubbers = data.clubbers_org || {};
            var subtitle = (data.profile_name || 'Next Generation');
            if (clubbers.name) subtitle += ' · ' + clubbers.name;
            setHeader('Awana Registration', subtitle, clubbers.id);
            applyHero(clubbers);

            var statsHtml = '';
            statsHtml += '<div class="stat-card"><div class="stat-label">Clubbers</div><div class="stat-value">' + (data.total_members || 0) + '</div></div>';
            statsHtml += '<div class="stat-card"><div class="stat-label">Volunteers</div><div class="stat-value">' + (data.volunteer_members || 0) + '</div></div>';
            statsHtml += '<div class="stat-card"><div class="stat-label">Male clubbers</div><div class="stat-value">' + (data.male_count || 0) + '</div></div>';
            statsHtml += '<div class="stat-card"><div class="stat-label">Female clubbers</div><div class="stat-value">' + (data.female_count || 0) + '</div></div>';
            $('#stats-grid').html(statsHtml);
            $('#gender-drilldown').hide().empty();
            $('#age-section').hide();
            $('#marital-section').hide();
            $('#subgroup-section').hide();

            if (data.grades && data.grades.length) {
                var gradeHtml = '';
                var maxGrade = 0;
                data.grades.forEach(function(g) { if (g.count > maxGrade) maxGrade = g.count; });
                data.grades.forEach(function(g) {
                    if (!g.count) return;
                    var pct = maxGrade > 0 ? Math.round((g.count / maxGrade) * 100) : 0;
                    var totalPct = data.total_members > 0 ? Math.round((g.count / data.total_members) * 100) : 0;
                    gradeHtml += '<div class="chart-bar">';
                    gradeHtml += '<div class="chart-label">' + esc(g.label) + '</div>';
                    gradeHtml += '<div class="chart-bar-container"><div class="chart-bar-fill" style="width:' + pct + '%;">' + totalPct + '%</div></div>';
                    gradeHtml += '<div class="chart-count">' + g.count + '</div></div>';
                });
                $('#grade-chart').html(gradeHtml);
                $('#grade-drilldown').hide().empty();
                $('#grade-section').show();
            } else {
                $('#grade-section').hide();
            }

            if (data.transactions && data.transactions.total > 0) {
                var money = function(n) {
                    return '$' + (n || 0).toFixed(2).replace(/\d(?=(\d{3})+\.)/g, '$&,');
                };
                var transHtml = '<div class="row" style="margin-bottom: 15px;">';
                transHtml += '<div class="col-md-4"><div style="background:#f8f9fa;padding:15px;border-radius:8px;text-align:center;">';
                transHtml += '<div style="font-size:24px;font-weight:bold;color:#012B58;">' + data.transactions.total + '</div>';
                transHtml += '<div style="font-size:12px;color:#666;">Payments (Amt &gt; 0)</div></div></div>';
                transHtml += '<div class="col-md-4"><div style="background:#f8f9fa;padding:15px;border-radius:8px;text-align:center;">';
                transHtml += '<div style="font-size:24px;font-weight:bold;color:#005C3B;">' + money(data.transactions.total_paid) + '</div>';
                transHtml += '<div style="font-size:12px;color:#666;">Total Paid</div></div></div>';
                transHtml += '<div class="col-md-4"><div style="background:#f8f9fa;padding:15px;border-radius:8px;text-align:center;">';
                transHtml += '<div style="font-size:24px;font-weight:bold;color:#E52300;">' + money(data.transactions.total_due) + '</div>';
                transHtml += '<div style="font-size:12px;color:#666;">Total Due</div></div></div></div>';
                transHtml += '<div class="row">';
                transHtml += '<div class="col-md-6"><div style="background:#f8f9fa;padding:15px;border-radius:8px;text-align:center;">';
                transHtml += '<div style="font-size:20px;font-weight:bold;color:#005C3B;">' + data.transactions.paid_in_full + '</div>';
                transHtml += '<div style="font-size:12px;color:#666;">Paid in Full</div></div></div>';
                transHtml += '<div class="col-md-6"><div style="background:#f8f9fa;padding:15px;border-radius:8px;text-align:center;">';
                transHtml += '<div style="font-size:20px;font-weight:bold;color:#FF7941;">' + data.transactions.remaining_balance + '</div>';
                transHtml += '<div style="font-size:12px;color:#666;">Remaining Balance</div></div></div></div>';
                transHtml += '<p class="finance-drill-hint" style="margin-top:12px;">Open a club tab for people lists.</p>';
                $('#transaction-summary').html(transHtml);
                $('#finance-drilldown').hide().empty();
                $('#transaction-section').show();
            } else {
                $('#transaction-section').hide();
            }

            if (data.enrollment_timeline && Object.keys(data.enrollment_timeline).length > 0) {
                var timelineHtml = '';
                var maxTimeline = Math.max.apply(null, Object.values(data.enrollment_timeline));
                var monthNames = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
                for (var month in data.enrollment_timeline) {
                    var count = data.enrollment_timeline[month];
                    var pct = maxTimeline > 0 ? Math.round((count / maxTimeline) * 100) : 0;
                    var parts = month.split('-');
                    var monthLabel = monthNames[parseInt(parts[1], 10) - 1] + ' ' + parts[0];
                    timelineHtml += '<div class="chart-bar"><div class="chart-label">' + esc(monthLabel) + '</div>';
                    timelineHtml += '<div class="chart-bar-container"><div class="chart-bar-fill" style="width:' + pct + '%;"></div></div>';
                    timelineHtml += '<div class="chart-count">' + count + '</div></div>';
                }
                $('#timeline-chart').html(timelineHtml);
                $('#timeline-section').show();
            } else {
                $('#timeline-section').hide();
            }
        }

        function loadAwanaOverview(thenClub) {
            showLoading('Loading Awana clubs...', false);
            ajaxPost({ action: 'list_awana' }, function(data) {
                if (data && data.error) {
                    alert('Error: ' + data.error + (data.traceback ? '\n\n' + data.traceback : ''));
                    return;
                }
                renderAwanaOverview(data || {});
                if (thenClub && clubKeys.indexOf(thenClub) >= 0) {
                    openClubTab(thenClub);
                } else {
                    showOverviewTab();
                }
            }, { showLoading: true });
        }

        $(document).on('click', '.age-bar-clickable', function() {
            var bracket = String($(this).attr('data-age-bracket') || '');
            if (!currentOrgId || !bracket) return;
            $('.age-bar-clickable').removeClass('active');
            $(this).addClass('active');
            showLoading('Loading people for age ' + bracket + '...', false);
            $('#age-drilldown').show().html('<div class="empty-state">Loading people...</div>');
            ajaxPost({
                action: 'get_age_people',
                org_id: currentOrgId,
                bracket: bracket
            }, function(data) {
                if (data.error) {
                    $('#age-drilldown').html('<div class="info-banner">' + esc(data.error) + '</div>');
                    return;
                }
                var peopleIds = collectPeopleIds(data.people);
                var html = '<div class="finance-drill-title">';
                html += '<span>Age ' + esc(data.label) + ' — ' + (data.count || 0) + ' people</span>';
                html += drillActionsHtml({
                    peopleIds: peopleIds,
                    closeBtnId: 'btn-close-age-drill'
                });
                html += '</div>';
                if (!data.people || !data.people.length) {
                    html += '<div class="empty-state">No people found in this age group.</div>';
                } else {
                    html += '<table class="people-table"><thead><tr><th>Person</th><th>Age</th></tr></thead><tbody>';
                    data.people.forEach(function(p) {
                        html += '<tr><td>';
                        if (p.people_id) {
                            html += personLink(p.people_id, p.name);
                        } else {
                            html += esc(p.name);
                        }
                        html += '</td><td>' + (p.age == null ? 'Unknown' : p.age) + '</td></tr>';
                    });
                    html += '</tbody></table>';
                }
                $('#age-drilldown').html(html).show();
            }, { showLoading: true });
        });

        $(document).on('click', '#btn-close-age-drill', function() {
            $('#age-drilldown').hide().empty();
            $('.age-bar-clickable').removeClass('active');
        });

        $(document).on('click', '.stat-card-clickable[data-gender]', function() {
            var gender = String($(this).attr('data-gender') || '');
            if (!currentOrgId || !gender) return;
            $('.stat-card-clickable[data-gender]').removeClass('active');
            $(this).addClass('active');
            var label = gender === 'female' ? 'Female' : 'Male';
            showLoading('Loading ' + label.toLowerCase() + ' members...', false);
            $('#gender-drilldown').show().html('<div class="empty-state">Loading people...</div>');
            ajaxPost({
                action: 'get_gender_people',
                org_id: currentOrgId,
                gender: gender
            }, function(data) {
                if (data.error) {
                    $('#gender-drilldown').html('<div class="info-banner">' + esc(data.error) + '</div>');
                    return;
                }
                var peopleIds = collectPeopleIds(data.people);
                var html = '<div class="section" style="margin:0;">';
                html += '<div class="finance-drill-title">';
                html += '<span>' + esc(data.label) + ' — ' + (data.count || 0) + ' people</span>';
                html += drillActionsHtml({
                    peopleIds: peopleIds,
                    closeBtnId: 'btn-close-gender-drill'
                });
                html += '</div>';
                if (!data.people || !data.people.length) {
                    html += '<div class="empty-state">No people found for this gender.</div>';
                } else {
                    html += '<table class="people-table"><thead><tr><th>Person</th></tr></thead><tbody>';
                    data.people.forEach(function(p) {
                        html += '<tr><td>';
                        if (p.people_id) {
                            html += personLink(p.people_id, p.name);
                        } else {
                            html += esc(p.name);
                        }
                        html += '</td></tr>';
                    });
                    html += '</tbody></table>';
                }
                html += '</div>';
                $('#gender-drilldown').html(html).show();
            }, { showLoading: true });
        });

        $(document).on('click', '#btn-close-gender-drill', function() {
            $('#gender-drilldown').hide().empty();
            $('.stat-card-clickable[data-gender]').removeClass('active');
        });

        function filterGradePeople(people, genderFilter) {
            genderFilter = genderFilter || 'all';
            if (genderFilter === 'all') return people || [];
            return (people || []).filter(function(p) {
                return (p.gender || '') === genderFilter;
            });
        }

        function gradeFilterLabel(filter) {
            if (filter === 'male') return 'Male';
            if (filter === 'female') return 'Female';
            if (filter === 'unknown') return 'Unknown';
            return 'All';
        }

        function renderGradeDrilldown() {
            var allPeople = gradeDrillState.people || [];
            var filter = gradeDrillState.filter || 'all';
            var filtered = filterGradePeople(allPeople, filter);
            var maleCount = filterGradePeople(allPeople, 'male').length;
            var femaleCount = filterGradePeople(allPeople, 'female').length;
            var peopleIds = collectPeopleIds(filtered);
            var title = 'Grade ' + esc(gradeDrillState.label);
            if (filter !== 'all') {
                title += ' · ' + esc(gradeFilterLabel(filter));
            }
            title += ' — ' + filtered.length + ' people';

            var html = '<div class="finance-drill-title">';
            html += '<span>' + title + '</span>';
            html += drillActionsHtml({
                peopleIds: peopleIds,
                closeBtnId: 'btn-close-grade-drill'
            });
            html += '</div>';
            html += '<div class="grade-gender-filters">';
            html += '<button type="button" class="grade-gender-filter' + (filter === 'all' ? ' active' : '') + '" data-grade-gender="all">All (' + allPeople.length + ')</button>';
            html += '<button type="button" class="grade-gender-filter' + (filter === 'male' ? ' active' : '') + '" data-grade-gender="male">Male (' + maleCount + ')</button>';
            html += '<button type="button" class="grade-gender-filter' + (filter === 'female' ? ' active' : '') + '" data-grade-gender="female">Female (' + femaleCount + ')</button>';
            html += '</div>';
            if (!filtered.length) {
                html += '<div class="empty-state">No people found for this grade' +
                    (filter === 'all' ? '' : ' / ' + gradeFilterLabel(filter).toLowerCase()) + '.</div>';
            } else {
                html += '<table class="people-table"><thead><tr><th>Person</th><th>Grade</th><th>Gender</th></tr></thead><tbody>';
                filtered.forEach(function(p) {
                    html += '<tr><td>';
                    if (p.people_id) {
                        html += personLink(p.people_id, p.name);
                    } else {
                        html += esc(p.name);
                    }
                    html += '</td><td>' + esc(p.grade || gradeDrillState.label) + '</td>';
                    html += '<td>' + esc(gradeFilterLabel(p.gender || 'unknown')) + '</td></tr>';
                });
                html += '</tbody></table>';
            }
            $('#grade-drilldown').html(html).show();
        }

        $(document).on('click', '.grade-bar-clickable', function() {
            var grade = String($(this).attr('data-grade') || '');
            if (!currentOrgId || !grade) return;
            $('.grade-bar-clickable').removeClass('active');
            $(this).addClass('active');
            showLoading('Loading people for grade ' + grade + '...', false);
            $('#grade-drilldown').show().html('<div class="empty-state">Loading people...</div>');
            ajaxPost({
                action: 'get_grade_people',
                org_id: currentOrgId,
                grade: grade
            }, function(data) {
                if (data.error) {
                    $('#grade-drilldown').html('<div class="info-banner">' + esc(data.error) + '</div>');
                    return;
                }
                gradeDrillState = {
                    label: data.label || grade,
                    people: data.people || [],
                    filter: 'all'
                };
                renderGradeDrilldown();
            }, { showLoading: true });
        });

        $(document).on('click', '.grade-gender-filter', function() {
            var next = String($(this).attr('data-grade-gender') || 'all');
            gradeDrillState.filter = next;
            renderGradeDrilldown();
        });

        $(document).on('click', '#btn-close-grade-drill', function() {
            $('#grade-drilldown').hide().empty();
            $('.grade-bar-clickable').removeClass('active');
            gradeDrillState = { label: '', people: [], filter: 'all' };
        });

        $(document).on('click', '.marital-bar-clickable', function() {
            var status = String($(this).attr('data-marital-status') || '');
            if (!currentOrgId || !status) return;
            $('.marital-bar-clickable').removeClass('active');
            $(this).addClass('active');
            showLoading('Loading people for ' + status + '...', false);
            $('#marital-drilldown').show().html('<div class="empty-state">Loading people...</div>');
            ajaxPost({
                action: 'get_marital_people',
                org_id: currentOrgId,
                status: status
            }, function(data) {
                if (data.error) {
                    $('#marital-drilldown').html('<div class="info-banner">' + esc(data.error) + '</div>');
                    return;
                }
                var peopleIds = collectPeopleIds(data.people);
                var html = '<div class="finance-drill-title">';
                html += '<span>' + esc(data.label) + ' — ' + (data.count || 0) + ' people</span>';
                html += drillActionsHtml({
                    peopleIds: peopleIds,
                    closeBtnId: 'btn-close-marital-drill'
                });
                html += '</div>';
                if (!data.people || !data.people.length) {
                    html += '<div class="empty-state">No people found for this marital status.</div>';
                } else {
                    html += '<table class="people-table"><thead><tr><th>Person</th><th>Marital Status</th></tr></thead><tbody>';
                    data.people.forEach(function(p) {
                        html += '<tr><td>';
                        if (p.people_id) {
                            html += personLink(p.people_id, p.name);
                        } else {
                            html += esc(p.name);
                        }
                        html += '</td><td>' + esc(p.marital_status || data.label) + '</td></tr>';
                    });
                    html += '</tbody></table>';
                }
                $('#marital-drilldown').html(html).show();
            }, { showLoading: true });
        });

        $(document).on('click', '#btn-close-marital-drill', function() {
            $('#marital-drilldown').hide().empty();
            $('.marital-bar-clickable').removeClass('active');
        });

        $(document).on('click', '.subgroup-item-clickable', function() {
            var subgroupId = String($(this).attr('data-subgroup-id') || '');
            var subgroupName = String($(this).attr('data-subgroup-name') || 'Subgroup');
            if (!currentOrgId || !subgroupId) return;
            $('.subgroup-item-clickable').removeClass('active');
            $(this).addClass('active');
            showLoading('Loading people for ' + subgroupName + '...', false);
            $('#subgroup-drilldown').show().html('<div class="empty-state">Loading people...</div>');
            ajaxPost({
                action: 'get_subgroup_people',
                org_id: currentOrgId,
                subgroup_id: subgroupId
            }, function(data) {
                if (data.error) {
                    $('#subgroup-drilldown').html('<div class="info-banner">' + esc(data.error) + '</div>');
                    return;
                }
                var peopleIds = collectPeopleIds(data.people);
                var html = '<div class="finance-drill-title">';
                html += '<span>' + esc(data.label) + ' — ' + (data.count || 0) + ' people</span>';
                html += drillActionsHtml({
                    peopleIds: peopleIds,
                    closeBtnId: 'btn-close-subgroup-drill'
                });
                html += '</div>';
                if (!data.people || !data.people.length) {
                    html += '<div class="empty-state">No people found in this subgroup.</div>';
                } else {
                    html += '<table class="people-table"><thead><tr><th>Person</th></tr></thead><tbody>';
                    data.people.forEach(function(p) {
                        html += '<tr><td>';
                        if (p.people_id) {
                            html += personLink(p.people_id, p.name);
                        } else {
                            html += esc(p.name);
                        }
                        html += '</td></tr>';
                    });
                    html += '</tbody></table>';
                }
                $('#subgroup-drilldown').html(html).show();
            }, { showLoading: true });
        });

        $(document).on('click', '#btn-close-subgroup-drill', function() {
            $('#subgroup-drilldown').hide().empty();
            $('.subgroup-item-clickable').removeClass('active');
        });

        $(document).on('click', '.finance-stat-clickable', function() {
            var status = String($(this).data('finance-status') || '');
            if (!currentOrgId || !status) return;
            $('.finance-stat-clickable').removeClass('active');
            $(this).addClass('active');
            showLoading('Loading people...', false);
            $('#finance-drilldown').show().html('<div class="empty-state">Loading people...</div>');
            ajaxPost({
                action: 'get_finance_people',
                org_id: currentOrgId,
                status: status
            }, function(data) {
                if (data.error) {
                    $('#finance-drilldown').html('<div class="info-banner">' + esc(data.error) + '</div>');
                    return;
                }
                var money = function(n) {
                    return '$' + (n || 0).toFixed(2).replace(/\d(?=(\d{3})+\.)/g, '$&,');
                };
                var peopleIds = collectPeopleIds(data.people);
                var html = '<div class="finance-drill-title">';
                html += '<span>' + esc(data.label) + ' — ' + (data.count || 0) + ' people</span>';
                html += drillActionsHtml({
                    peopleIds: peopleIds,
                    closeBtnId: 'btn-close-finance-drill'
                });
                html += '</div>';
                if (!data.people || !data.people.length) {
                    html += '<div class="empty-state">No people found for this category.</div>';
                } else {
                    html += '<table class="people-table"><thead><tr><th>Person</th><th>Paid</th><th>Balance Due</th></tr></thead><tbody>';
                    data.people.forEach(function(p) {
                        html += '<tr><td>';
                        if (p.people_id) {
                            html += personLink(p.people_id, p.name);
                        } else {
                            html += esc(p.name);
                        }
                        html += '</td><td>' + money(p.total_paid) + '</td>';
                        html += '<td>' + money(p.balance_due) + '</td></tr>';
                    });
                    html += '</tbody></table>';
                }
                $('#finance-drilldown').html(html).show();
            }, { showLoading: true });
        });

        $(document).on('click', '#btn-close-finance-drill', function() {
            $('#finance-drilldown').hide().empty();
            $('.finance-stat-clickable').removeClass('active');
        });


        function renderBreadcrumb() {
            var parts = ['<a data-nav="summary">Overview</a>'];
            if (regState.question) {
                parts.push('<a data-nav="question">' + esc(regState.question.label) + '</a>');
            }
            if (regState.option) {
                parts.push('<a data-nav="option">' + esc(regState.option.text) + '</a>');
            }
            if (regState.person) {
                parts.push('<span>' + esc(regState.person.name) + '</span>');
            }
            $('#reg-breadcrumb').html(parts.join(' <i class="fa fa-chevron-right"></i> '));
        }

        function loadClubOverview() {
            if (!currentOrgId) return;
            showLoading('Loading clubbers...', false);
            $('#club-overview-view').html('<div class="empty-state">Loading...</div>');
            clubPost({ action: 'get_club_roster' }, function(data) {
                if (data && data.error) {
                    $('#club-overview-view').html('<div class="info-banner">Error: ' + esc(data.error) + '</div>');
                    return;
                }
                var people = (data && data.people) || [];
                if (!people.length) {
                    $('#club-overview-view').html('<div class="empty-state">No clubbers in this club.</div>');
                    return;
                }
                var ids = collectPeopleIds(people);
                var html = '<div class="reg-meta" style="margin-bottom:14px;">Clubbers: <strong>' +
                    people.length + '</strong></div>';
                html += drillActionsHtml({ peopleIds: ids });
                html += '<table class="people-table"><thead><tr><th>Person</th><th>Age</th><th>Grade</th></tr></thead><tbody>';
                people.forEach(function(p) {
                    html += '<tr><td>' + personLink(p.people_id, p.name);
                    if (p.has_allergy) {
                        html += ' <a href="#" class="allergy-flag" title="Has allergy — open Allergies">A</a>';
                    }
                    html += '</td>';
                    html += '<td>' + esc(p.age === 0 || p.age ? String(p.age) : '') + '</td>';
                    html += '<td>' + esc(p.grade || '') + '</td></tr>';
                });
                html += '</tbody></table>';
                $('#club-overview-view').html(html);
            }, { showLoading: true });
        }

        $(document).on('click', '.allergy-flag', function(e) {
            e.preventDefault();
            e.stopPropagation();
            setClubSubtab('allergies', true);
        });

        function loadAllergies() {
            if (!currentOrgId) return;
            showLoading('Loading allergies...', false);
            $('#allergies-view').html('<div class="empty-state">Loading...</div>');
            clubPost({ action: 'get_allergy_people' }, function(data) {
                if (data && data.error) {
                    $('#allergies-view').html('<div class="info-banner">Error: ' + esc(data.error) + '</div>');
                    return;
                }
                var people = (data && data.people) || [];
                if (!people.length) {
                    $('#allergies-view').html('<div class="empty-state">No participants with allergy notes on file.</div>');
                    return;
                }
                var ids = collectPeopleIds(people);
                var html = '<div class="reg-meta" style="margin-bottom:14px;">Participants with allergies: <strong>' +
                    people.length + '</strong></div>';
                html += drillActionsHtml({ peopleIds: ids });
                html += '<table class="people-table"><thead><tr><th>Person</th><th>Allergies</th></tr></thead><tbody>';
                people.forEach(function(p) {
                    html += '<tr><td>' + personLink(p.people_id, p.name) + '</td><td>' + esc(p.allergy) + '</td></tr>';
                });
                html += '</tbody></table>';
                $('#allergies-view').html(html);
            }, { showLoading: true });
        }

        function loadContacts() {
            if (!currentOrgId) return;
            showLoading('Loading contacts...', false);
            $('#contacts-view').html('<div class="empty-state">Loading...</div>');
            clubPost({ action: 'get_contact_people' }, function(data) {
                if (data && data.error) {
                    $('#contacts-view').html('<div class="info-banner">Error: ' + esc(data.error) + '</div>');
                    return;
                }
                var people = (data && data.people) || [];
                if (!people.length) {
                    $('#contacts-view').html('<div class="empty-state">No participants with parent or emergency contact info on file.</div>');
                    return;
                }
                var ids = collectPeopleIds(people);
                var html = '<div class="reg-meta" style="margin-bottom:14px;">Participants with contacts: <strong>' +
                    people.length + '</strong></div>';
                html += drillActionsHtml({ peopleIds: ids });
                html += '<table class="people-table"><thead><tr>';
                html += '<th>Person</th><th>Mother</th><th>Father</th><th>Emergency Contact</th><th>Emergency Phone</th>';
                html += '</tr></thead><tbody>';
                people.forEach(function(p) {
                    html += '<tr>';
                    html += '<td>' + personLink(p.people_id, p.name) + '</td>';
                    html += '<td>' + esc(p.mother || '') + '</td>';
                    html += '<td>' + esc(p.father || '') + '</td>';
                    html += '<td>' + esc(p.em_contact || '') + '</td>';
                    html += '<td>' + esc(p.em_phone || '') + '</td>';
                    html += '</tr>';
                });
                html += '</tbody></table>';
                $('#contacts-view').html(html);
            }, { showLoading: true });
        }

        function loadRegistrationSummary() {
            if (!currentOrgId) return;
            showLoading('Loading registration questions...', true);
            $('#reg-view').html('<div class="empty-state">Loading registration questions...</div>');
            clubPost({ action: 'get_registration_summary' }, function(data) {
                if (data.error) {
                    $('#reg-view').html('<div class="info-banner">Error: ' + esc(data.error) + '</div>');
                    return;
                }
                regState.summary = data;
                regState.view = 'summary';
                regState.question = null;
                regState.option = null;
                regState.person = null;
                renderRegistrationSummary(data);
            }, { showLoading: true });
        }

        function renderChoiceOptions(options, clickable) {
            var html = '';
            var maxC = 0;
            (options || []).forEach(function(o) { if (o.count > maxC) maxC = o.count; });
            (options || []).forEach(function(o) {
                if (!o.count) return;
                var barPct = maxC > 0 ? Math.round((o.count / maxC) * 100) : 0;
                if (o.is_other_group && o.variants && o.variants.length) {
                    html += '<div class="other-group-bar">';
                    html += '<button type="button" class="other-group-toggle" data-expanded="0">';
                    html += '<i class="fa fa-chevron-right other-chevron"></i>';
                    html += '<div class="chart-label">Other</div>';
                    html += '<div class="chart-bar-container"><div class="chart-bar-fill" style="width:' + barPct + '%;">' + (o.pct || 0) + '%</div></div>';
                    html += '<div class="chart-count">' + o.count + '</div>';
                    html += '</button>';
                    html += '<div class="other-variants">';
                    html += '<p class="other-variant-meta">' + (o.variant_count || o.variants.length) +
                        ' free-text answers collapsed — expand to view, or click Other to see everyone</p>';
                    if (clickable) {
                        html += '<div class="chart-bar clickable-option" data-ovalue="' + encodeURIComponent('__other__') +
                            '" data-otext="' + encodeURIComponent('Other (all)') + '">';
                        html += '<div class="chart-label">All Other</div>';
                        html += '<div class="chart-bar-container"><div class="chart-bar-fill" style="width:' + barPct + '%;">' + (o.pct || 0) + '%</div></div>';
                        html += '<div class="chart-count">' + o.count + '</div></div>';
                    }
                    var maxV = 0;
                    o.variants.forEach(function(v) { if (v.count > maxV) maxV = v.count; });
                    o.variants.forEach(function(v) {
                        if (!v.count) return;
                        var vp = maxV > 0 ? Math.round((v.count / maxV) * 100) : 0;
                        if (clickable) {
                            html += '<div class="chart-bar clickable-option" data-ovalue="' + encodeURIComponent(v.value) +
                                '" data-otext="' + encodeURIComponent(v.text) + '">';
                        } else {
                            html += '<div class="chart-bar">';
                        }
                        html += '<div class="chart-label">' + esc(v.text) + '</div>';
                        html += '<div class="chart-bar-container"><div class="chart-bar-fill" style="width:' + vp + '%;">' + (v.pct || 0) + '%</div></div>';
                        html += '<div class="chart-count">' + v.count + '</div></div>';
                    });
                    html += '</div></div>';
                    return;
                }
                if (clickable) {
                    html += '<div class="chart-bar clickable-option" data-ovalue="' + encodeURIComponent(o.value) +
                        '" data-otext="' + encodeURIComponent(o.text) + '">';
                } else {
                    html += '<div class="chart-bar">';
                }
                html += '<div class="chart-label">' + esc(o.text) + '</div>';
                html += '<div class="chart-bar-container"><div class="chart-bar-fill" style="width:' + barPct + '%;">' + (o.pct || 0) + '%</div></div>';
                html += '<div class="chart-count">' + o.count + '</div></div>';
            });
            return html;
        }

        function renderRegistrationSummary(data) {
            renderBreadcrumb();
            if (currentClubKey) $('#btn-reg-excel').show();
            if (!data.is_registration_form) {
                $('#reg-view').html('<div class="info-banner">' + esc(data.message) + '</div>');
                return;
            }

            if (!data.questions || data.questions.length === 0) {
                $('#reg-view').html('<div class="empty-state">' + esc(data.message || 'No registration questions found.') + '</div>');
                return;
            }

            var html = '<div class="reg-meta" style="margin-bottom:14px;">Completed registrants: <strong>' + data.completed_count + '</strong></div>';

            if (data.message) {
                html += '<div class="empty-state" style="margin-bottom:14px;">' + esc(data.message) + '</div>';
            }

            data.questions.forEach(function(q) {
                html += '<div class="reg-question-card" data-qid="' + esc(q.id) + '">';
                html += '<div class="reg-question-title">' + esc(q.label) + '</div>';
                html += '<div class="reg-meta">' + q.answered + ' answered</div>';
                if (q.kind === 'choice') {
                    html += renderChoiceOptions(q.options || [], false);
                } else if (q.preview && q.preview.length) {
                    html += '<div class="reg-preview">' + esc(q.preview.join(' · ')) + '</div>';
                }
                html += '</div>';
            });
            $('#reg-view').html(html);
        }

        function findQuestion(qid) {
            if (!regState.summary || !regState.summary.questions) return null;
            for (var i = 0; i < regState.summary.questions.length; i++) {
                if (regState.summary.questions[i].id === qid) return regState.summary.questions[i];
            }
            return null;
        }

        $(document).on('click', '.reg-question-card', function() {
            var qid = $(this).data('qid');
            var q = findQuestion(String(qid));
            if (!q) return;
            openQuestion(q);
        });

        $(document).on('click', '.other-group-toggle', function(e) {
            e.preventDefault();
            e.stopPropagation();
            var $btn = $(this);
            var $variants = $btn.siblings('.other-variants');
            var expanded = $btn.attr('data-expanded') === '1';
            if (expanded) {
                $btn.attr('data-expanded', '0');
                $variants.removeClass('expanded');
                $btn.find('.other-chevron').removeClass('fa-chevron-down').addClass('fa-chevron-right');
            } else {
                $btn.attr('data-expanded', '1');
                $variants.addClass('expanded');
                $btn.find('.other-chevron').removeClass('fa-chevron-right').addClass('fa-chevron-down');
            }
        });

        $(document).on('click', '.other-variants', function(e) {
            e.stopPropagation();
        });

        $('#btn-reg-excel').click(function() {
            if (!currentOrgId) return;
            var club = findClub(currentClubKey);
            var name = (club && club.label) ? club.label : 'Clubbers';
            exportRosterCsv(name + '-Clubbers.csv', 'clubbers');
        });

        function openQuestion(q) {
            regState.view = 'question';
            regState.question = q;
            regState.option = null;
            regState.person = null;
            renderBreadcrumb();

            if (q.kind === 'choice') {
                var html = '<button type="button" class="btn-back" data-nav="summary"><i class="fa fa-arrow-left"></i> Back</button>';
                html += '<h3 style="margin:16px 0 8px;">' + esc(q.label) + '</h3>';
                html += '<div class="reg-meta">' + q.answered + ' answered — click an option to see who selected it</div>';
                html += renderChoiceOptions(q.options || [], true);
                $('#reg-view').html(html);
            } else {
                showLoading('Loading answers...', true);
                $('#reg-view').html('<div class="empty-state">Loading answers...</div>');
                clubPost({ action: 'get_text_answers', question_id: q.id }, function(data) {
                    if (data.error) {
                        $('#reg-view').html('<div class="info-banner">' + esc(data.error) + '</div>');
                        return;
                    }
                    renderTextAnswers(q, data);
                }, { showLoading: true });
            }
        }

        function renderTextAnswers(q, data) {
            var answeredIds = collectPeopleIds(data.answered_people);
            var html = '<div class="finance-drill-title">';
            html += '<span>' + esc(q.label) + '</span>';
            html += drillActionsHtml({ backNav: 'summary', peopleIds: answeredIds });
            html += '</div>';
            html += '<div class="reg-meta">' + (data.answered_people || []).length + ' answered</div>';
            html += '<table class="people-table"><thead><tr><th>Person</th><th>Answer</th></tr></thead><tbody>';
            (data.answered_people || []).forEach(function(p) {
                html += '<tr><td>' + personLink(p.people_id, p.name);
                html += ' <a href="#" class="person-drill" data-pid="' + p.people_id + '" data-pname="' + encodeURIComponent(p.name) + '" title="Full Q&A">Q&A</a></td>';
                html += '<td>' + esc(p.answer) + '</td></tr>';
            });
            html += '</tbody></table>';
            $('#reg-view').html(html);
        }

        $(document).on('click', '.clickable-option', function() {
            var ovalue = decodeURIComponent(String($(this).attr('data-ovalue') || ''));
            var otext = decodeURIComponent(String($(this).attr('data-otext') || ''));
            if (!regState.question) return;
            loadOptionPeople({ value: ovalue, text: otext });
        });

        $(document).on('click', '.person-drill', function(e) {
            e.preventDefault();
            var pid = parseInt($(this).attr('data-pid'), 10);
            var pname = decodeURIComponent(String($(this).attr('data-pname') || ''));
            openPerson(pid, pname);
        });

        function openPerson(peopleId, name) {
            regState.view = 'person';
            regState.person = { people_id: peopleId, name: name };
            renderBreadcrumb();
            showLoading('Loading full Q&A...', true);
            $('#reg-view').html('<div class="empty-state">Loading full Q&A...</div>');
            clubPost({ action: 'get_person_answers', people_id: peopleId }, function(data) {
                if (data.error) {
                    $('#reg-view').html('<div class="info-banner">' + esc(data.error) + '</div>');
                    return;
                }
                var backNav = regState.option ? 'option' : (regState.question ? 'question' : 'summary');
                var html = '<button type="button" class="btn-back" data-nav="' + backNav + '"><i class="fa fa-arrow-left"></i> Back</button>';
                html += '<h3 style="margin:16px 0 8px;">' + personLink(data.people_id, data.name) + '</h3>';
                html += '<table class="people-table"><thead><tr><th>Question</th><th>Answer</th></tr></thead><tbody>';
                (data.answers || []).forEach(function(a) {
                    if (a.blank || !a.answer) return;
                    html += '<tr><td>' + esc(a.label) + '</td><td>' + esc(a.answer) + '</td></tr>';
                });
                html += '</tbody></table>';
                $('#reg-view').html(html);
            }, { showLoading: true });
        }

        function loadOptionPeople(o) {
            regState.option = o;
            regState.person = null;
            regState.view = 'option';
            renderBreadcrumb();
            showLoading('Loading people...', true);
            $('#reg-view').html('<div class="empty-state">Loading people...</div>');
            clubPost({
                action: 'get_option_people',
                question_id: regState.question.id,
                option_value: o.value
            }, function(data) {
                if (data.error) {
                    $('#reg-view').html('<div class="info-banner">' + esc(data.error) + '</div>');
                    return;
                }
                var peopleIds = collectPeopleIds(data.people);
                var html = '<div class="finance-drill-title">';
                html += '<span>' + esc(regState.question.label) + ' — ' + esc(o.text) + '</span>';
                html += drillActionsHtml({ backNav: 'question', peopleIds: peopleIds });
                html += '</div>';
                html += '<div class="reg-meta">' + (data.people || []).length + ' people</div>';
                html += '<table class="people-table"><thead><tr><th>Person</th><th>Answer</th></tr></thead><tbody>';
                (data.people || []).forEach(function(p) {
                    html += '<tr><td>' + personLink(p.people_id, p.name);
                    html += ' <a href="#" class="person-drill" data-pid="' + p.people_id + '" data-pname="' + encodeURIComponent(p.name) + '">Q&A</a></td>';
                    html += '<td>' + esc(p.answer) + '</td></tr>';
                });
                html += '</tbody></table>';
                $('#reg-view').html(html);
            }, { showLoading: true });
        }

        $(document).on('click', '[data-nav]', function(e) {
            e.preventDefault();
            var nav = $(this).data('nav');
            if (nav === 'summary') {
                if (regState.summary) renderRegistrationSummary(regState.summary);
                else loadRegistrationSummary();
            } else if (nav === 'question' && regState.question) {
                openQuestion(regState.question);
            } else if (nav === 'option' && regState.question && regState.option) {
                loadOptionPeople(regState.option);
            }
        });

        loadAwanaOverview(initialClub || '');

    }

    if (window.jQuery) {
        $(document).ready(initDashboard);
    } else {
        var checkJQuery = setInterval(function() {
            if (window.jQuery) {
                clearInterval(checkJQuery);
                $(document).ready(initDashboard);
            }
        }, 50);
    }
})();
</script>
'''
    # Inject deep-link org (safe ints / escaped name for JS string)
    try:
        _safe_name = _json_quote(_initial_org_name) if _initial_org_name else '""'
    except:
        _safe_name = '""'
    try:
        _safe_club = _json_quote(_initial_club) if _initial_club else '""'
    except:
        _safe_club = '""'
    model.Form = model.Form.replace('__INITIAL_ORG_ID__', str(int(_initial_org_id or 0)))
    model.Form = model.Form.replace('__INITIAL_ORG_NAME__', _safe_name)
    model.Form = model.Form.replace('__INITIAL_CLUB__', _safe_club)
