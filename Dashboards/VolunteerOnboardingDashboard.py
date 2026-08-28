#Roles=Admin,Access,Staff,Elders
# Script: VolunteerOnboardingDashboard.py
# Purpose: Staff companion dashboard for volunteer onboarding (Kids + Student Ministry).
#   Lists Prospects for configured Involvements, expandable step checklist,
#   Extra Value / Note / BackgroundCheck writebacks, Admin config JSON.
# Author: Jake Pierson
# Date: 2026-08-18
#
# Install: Special Content -> Python Scripts -> name VolunteerOnboardingDashboard
# Run: /PyScriptForm/VolunteerOnboardingDashboard
# Config (ONLY file needed): Special Content → Text → VolunteerOnboardingDashboardConfig
#   Edit that JSON manually (or seed defaults from the Config tab).
#
# IronPython notes (TouchPoint embeds IronPython 2.7):
#   - print without parentheses; except Exception, ex
#   - Put UI in model.Form on GET (PyScriptForm ignores Output)
#   - Prefer model.DynamicData() for SQL params
#   - Prefer token replace / concat over .format() for large HTML
#   - No f-strings, no pathlib, no requests

SCRIPT_PATH = '/PyScriptForm/VolunteerOnboardingDashboard'
CONFIG_CONTENT_NAME = 'VolunteerOnboardingDashboardConfig'
MEMBER_TYPE_PROSPECT = 311
REPORT_TYPE_PMM = 1
REPORT_TYPE_MS_TRAINING = 3
STATUS_NOT_SUBMITTED = 1
STATUS_SUBMITTED = 2
STATUS_COMPLETED = 3
STATUS_EMAILED = 4

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

# Last config-load diagnostic shown on Config tab (parse ok / fail reason)
_CONFIG_LOAD_INFO = ''


def _ensure_newtonsoft():
    """TouchPoint IronPython needs an explicit CLR reference before Newtonsoft imports."""
    try:
        import clr
        clr.AddReference('Newtonsoft.Json')
        return True
    except:
        try:
            import clr
            clr.AddReferenceToFile('Newtonsoft.Json.dll')
            return True
        except:
            return False


def _netobj_to_py(obj):
    """Convert .NET objects from JavaScriptSerializer into plain Python types."""
    if obj is None:
        return None
    if obj is True or obj is False:
        return bool(obj)
    try:
        from System import Boolean, DBNull
        if isinstance(obj, Boolean):
            return bool(obj)
        if obj is DBNull.Value:
            return None
    except:
        pass
    num = None
    try:
        num = _json_number(obj)
    except:
        num = None
    if num is not None:
        try:
            if '.' in num:
                return float(num)
            return int(num)
        except:
            pass
    if isinstance(obj, float):
        return float(obj)
    if isinstance(obj, (str, unicode)):
        return _s(obj)
    try:
        from System import String
        if isinstance(obj, String):
            return _s(obj)
    except:
        pass
    # IDictionary (Dictionary[str,object] from JavaScriptSerializer)
    try:
        if hasattr(obj, 'Keys') and hasattr(obj, '__getitem__'):
            d = {}
            for k in obj.Keys:
                d[_s(k)] = _netobj_to_py(obj[k])
            return d
    except:
        pass
    # IList / ArrayList
    try:
        if hasattr(obj, 'Count') and not hasattr(obj, 'Keys'):
            return [_netobj_to_py(obj[i]) for i in range(int(obj.Count))]
    except:
        pass
    try:
        return [_netobj_to_py(x) for x in list(obj)]
    except:
        pass
    return _s(obj)


def _parse_config_json(raw):
    """Parse Special Content JSON → Python dict. Tries Newtonsoft, then JavaScriptSerializer.
    Returns (dict_or_None, status_message).
    """
    raw = _s(raw)
    if not raw:
        return None, 'empty'
    ns_err = ''
    js_err = ''
    # 1) Newtonsoft
    try:
        _ensure_newtonsoft()
        from Newtonsoft.Json.Linq import JObject
        root = JObject.Parse(raw)
        parsed = _jobj_to_py(root)
        if isinstance(parsed, dict) and parsed:
            return parsed, 'ok:newtonsoft'
        ns_err = 'newtonsoft got ' + type(parsed).__name__
    except Exception, ex:
        ns_err = _s(ex)[:80]
    # 2) ASP.NET JavaScriptSerializer
    try:
        import clr
        try:
            clr.AddReference('System.Web.Extensions')
        except:
            pass
        from System.Web.Script.Serialization import JavaScriptSerializer
        ser = JavaScriptSerializer()
        try:
            ser.MaxJsonLength = 10 * 1024 * 1024
        except:
            pass
        parsed = _netobj_to_py(ser.DeserializeObject(raw))
        if isinstance(parsed, dict) and parsed:
            return parsed, 'ok:javascriptserializer'
        js_err = 'javascriptserializer got ' + type(parsed).__name__
    except Exception, ex:
        js_err = _s(ex)[:80]
    return None, 'fail ns=[' + ns_err + '] js=[' + js_err + ']'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _b(val):
    s = _s(val).lower()
    return s in ('1', 'true', 'yes', 'on')


def _html(val):
    s = _s(val)
    s = s.replace('&', '&amp;')
    s = s.replace('<', '&lt;')
    s = s.replace('>', '&gt;')
    s = s.replace('"', '&quot;')
    return s


def _js_str(val):
    """Single-quoted JS string literal (WAF-safe paths only)."""
    s = _s(val)
    s = s.replace('\\', '\\\\')
    s = s.replace("'", "\\'")
    s = s.replace('\r', '')
    s = s.replace('\n', '')
    return "'" + s + "'"


def _dd():
    return model.DynamicData()


def _get(name, default=''):
    """Read a posted form / query value from PyScriptForm Data.
    Prefer model.DataHas + model.Dictionary — more reliable than Data.GetValue
    for some DynamicData / IronPython binder cases.
    Also checks Request.Form and Request.QueryString (GET saves like do=sapp / do=scfg).
    """
    try:
        if model.DataHas(name):
            return model.Dictionary(name)
    except:
        pass
    # Raw ASP.NET collections — needed when binder skips long/odd query values
    try:
        from System.Web import HttpContext
        req = HttpContext.Current.Request
        form = req.Form
        if form is not None and form.AllKeys is not None:
            for k in form.AllKeys:
                if k == name:
                    return form[name]
        qs = req.QueryString
        if qs is not None and qs.AllKeys is not None:
            for k in qs.AllKeys:
                if k == name:
                    return qs[name]
    except:
        pass
    try:
        v = Data.GetValue(name)
        if not _is_null(v):
            return v
    except:
        pass
    return default


def _form_val(name, default=''):
    v = _get(name, None)
    if v is None:
        return default
    return _s(v, default)


def _form_key_set():
    """All request field names (Form + QueryString)."""
    keys = set()
    try:
        from System.Web import HttpContext
        req = HttpContext.Current.Request
        for coll in (req.Form, req.QueryString):
            if coll is None or coll.AllKeys is None:
                continue
            for k in coll.AllKeys:
                if k:
                    keys.add(_s(k))
    except:
        pass
    return keys


def _posted_or_keep(name, existing, alt_name=None):
    """Use posted/query value when the field was in the request; otherwise keep existing.
    Always read via _get (Form + QueryString) — never Request.Form alone (GET saves
    put values in QueryString; Form[name] is empty there and was wiping saves).
    """
    for n in (name, alt_name):
        if not n:
            continue
        present = False
        try:
            if model.DataHas(n):
                present = True
        except:
            pass
        if not present:
            try:
                if n in _form_key_set():
                    present = True
            except:
                pass
        if not present:
            continue
        v = _get(n, None)
        if v is None:
            return ''
        try:
            return unicode(v).strip()
        except:
            try:
                return str(v).strip()
            except:
                return ''
    return _s(existing, '')


def _request_diag():
    """Short diagnostic of what the current request actually contained."""
    bits = []
    try:
        bits.append('method=' + _s(model.HttpMethod))
    except:
        bits.append('method=?')
    # HttpContext AllKeys is unreliable here (often 0); Data binder is what PyScriptForm uses.
    data_hits = []
    for n in ('do', 'action', 'area_key', 'list_key', 'orgid', 'cfg_label', 'cfg_roles',
              'cfg_students_orgid', 'cfg_littles_orgid', 'cfg_kids_orgid', 'cfg_from_peopleid'):
        try:
            if model.DataHas(n):
                data_hits.append(n + '=' + _s(model.Dictionary(n))[:24])
        except:
            pass
    bits.append('data=' + (str(len(data_hits)) if data_hits else '0'))
    if data_hits:
        bits.append('saw=' + ','.join(data_hits[:10]))
    try:
        raw = _raw_content_text(CONFIG_CONTENT_NAME)
        bits.append('store=' + ('empty' if not raw else (str(len(raw)) + 'b')))
    except Exception, ex:
        bits.append('store_err=' + _s(ex)[:40])
    return '; '.join(bits)


# Short flash codes only in URLs — free-text msgs (emails, @, HTML) trip Azure App Gateway WAF.
FLASH = {
    'ok_sent': 'Application email queued.',
    'ok_saved': 'Saved.',
    'ok_config': 'Config saved.',
    'ok_area': 'Area added.',
    'ok_list': 'List added.',
    'ok_note': 'Note saved.',
    'ok_ev': 'Date saved.',
    'ok_approval': 'Approval updated.',
    'ok_member': 'Moved to Member.',
    'err_confirm': 'Application already sent. Use Re-send and confirm to send again.',
    'err_template': 'Email template missing or has no HTML body. Check Config / Special Content.',
    'err_template_unset': 'No application email template selected in Config for this list.',
    'err_template_missing': 'Email template not found in Special Content (check Name).',
    'err_template_body': 'Email template has no usable HTML body (Unlayer must be saved with exported HTML).',
    'err_no_to': 'No primary Email Address on the recipient (Address 1 required).',
    'err_no_from': 'Email from PeopleId not set in Config for this area.',
    'err_from_email': 'From PeopleId has no primary Email Address.',
    'err_queue_user': 'Cannot determine current user for email queue.',
    'err_email': 'Email queue failed. Try again or check TouchPoint email logs.',
    'err_ev': 'Email queued but Application Sent EV write failed.',
    'err_auth': 'Not authorized.',
    'err_view': 'View only — action blocked.',
    'err_generic': 'Something went wrong. Try again.',
}

# Extra detail appended on the continue page only (never in the URL — WAF-safe)
_FLASH_DETAIL = ''


def _flash_detail_set(text):
    global _FLASH_DETAIL
    _FLASH_DETAIL = _s(text)


def _flash_detail_clear():
    global _FLASH_DETAIL
    _FLASH_DETAIL = ''


def _flash_text(code):
    c = _s(code)
    if c in FLASH:
        msg = FLASH[c]
    else:
        # Legacy free-text flash (sanitized display only)
        msg = _s(c)
    # Show detail on errors and on config save (so we can confirm orgids stuck)
    if _FLASH_DETAIL and (c.startswith('err_') or c == 'ok_config'):
        msg = msg + ' — ' + _FLASH_DETAIL
    return msg


def _b64url_decode(s):
    """Decode URL-safe base64 to a unicode string (IronPython / .NET)."""
    s = _s(s)
    if not s:
        return ''
    s = s.replace('-', '+').replace('_', '/')
    pad = len(s) % 4
    if pad:
        s = s + ('=' * (4 - pad))
    try:
        from System import Convert
        from System.Text import Encoding
        raw = Convert.FromBase64String(s)
        return Encoding.UTF8.GetString(raw)
    except:
        return ''


def _parse_cfg_payload(p):
    """Parse packed config payload (base64url JSON object) → dict of field→value."""
    raw = _b64url_decode(p)
    if not raw:
        return None
    try:
        from Newtonsoft.Json.Linq import JObject
        obj = JObject.Parse(raw)
        parsed = _jobj_to_py(obj)
        if isinstance(parsed, dict):
            return parsed
    except:
        pass
    return None


def _qs_flash(code):
    """Querystring flash — codes only (WAF-safe)."""
    c = _s(code) or 'ok_saved'
    # Allow only simple tokens in the URL
    safe = []
    for ch in c:
        o = ord(ch)
        if (o >= 97 and o <= 122) or (o >= 48 and o <= 57) or ch == '_':
            safe.append(ch)
    c = ''.join(safe) or 'ok_saved'
    return 'msg=' + c


def _redirect(extra=''):
    url = SCRIPT_PATH
    if extra:
        if extra.startswith('?'):
            url = url + extra
        else:
            url = url + '?' + extra
    print 'REDIRECT=' + url


def _continue_page(next_url, flash_code):
    """200 HTML continue page instead of 302 — avoids App Gateway WAF on Location headers.
    Sets model.Form (GET) and print (POST) because PyScriptForm ignores Output on GET.
    Auto-redirect only on simple successes; config save stays readable so diagnostics show.
    """
    msg = _flash_text(flash_code)
    _flash_detail_clear()
    code = _s(flash_code)
    is_err = code.startswith('err_')
    # Keep config results on screen (need to read orgids / request diag)
    stay = is_err or code == 'ok_config'
    html = '<!DOCTYPE html><html><head><meta charset="utf-8"/>'
    html += '<title>Volunteer Onboarding</title>'
    if not stay:
        html += '<script>window.setTimeout(function(){window.location.replace(' + _js_str(next_url) + ');},80);</script>'
    html += '</head><body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;padding:28px;color:#001429">'
    html += '<p style="font-size:16px;font-weight:700">' + _html(msg) + '</p>'
    html += '<p><a href="' + _html(next_url) + '" style="color:#00AEEF;font-weight:600">Continue</a></p>'
    html += '</body></html>'
    try:
        model.Form = html
    except:
        pass
    print html


def _show(html):
    model.Form = html


def _user_pid():
    try:
        return int(model.UserPeopleId)
    except:
        return 0


def _user_email():
    try:
        return _s(model.EmailAddress)
    except:
        return ''


def _user_name():
    try:
        return _s(model.UserName)
    except:
        return 'Staff'


def _is_admin():
    return model.UserIsInRole('Admin')


def _has_role(name):
    if not name:
        return False
    try:
        return model.UserIsInRole(name)
    except:
        return False


def _today_str():
    from System import DateTime
    return DateTime.Today.ToString('yyyy-MM-dd')


def _fmt_date(val):
    s = _s(val)
    if not s:
        return ''
    try:
        from System import DateTime
        return DateTime.Parse(s).ToString('M/d/yyyy')
    except:
        return s


AREA_ORDER = ['kids', 'student', 'adult', 'mcl', 'worship', 'outreach', 'missions']

LIST_FIELD_DEFS = [
    ('label', 'Label'),
    ('orgid', 'Involvement #'),
    ('email_template', 'Application email template'),
    ('adult_reg_url', 'Adult OnlineReg URL'),
    ('minor_reg_url', 'Minor OnlineReg URL'),
    ('ev_app_sent', 'EV: Application Sent'),
    ('ev_app_reviewed', 'EV: Application Reviewed'),
    ('ev_handbook', 'EV: Handbook Signed'),
    ('ev_training', 'EV: In Person Training'),
    ('kw_interview', 'Keyword: Interview (marks complete)'),
    ('kw_references', 'Keyword: References (marks complete)'),
    ('kw_shadowing', 'Keyword: Shadowing (marks complete)'),
    ('kw_fl_training', 'Keyword: FL Training (optional)'),
]


def _slug_key(s):
    """Safe config key: lowercase letters, digits, underscore."""
    out = []
    for ch in _s(s).lower():
        o = ord(ch)
        if (o >= 97 and o <= 122) or (o >= 48 and o <= 57) or ch == '_':
            out.append(ch)
        elif ch in (' ', '-', '.'):
            out.append('_')
    key = ''.join(out).strip('_')
    while '__' in key:
        key = key.replace('__', '_')
    return key


def _empty_list_cfg(label=''):
    return {
        'label': _s(label) or 'New list',
        'orgid': 0,
        'email_template': '',
        'adult_reg_url': '',
        'minor_reg_url': '',
        'ev_app_sent': '',
        'ev_app_reviewed': '',
        'ev_handbook': '',
        'ev_training': '',
        'kw_interview': '',
        'kw_references': '',
        'kw_shadowing': '',
        'kw_fl_training': '',
        'track': 'full',
        'has_fl_training': False,
    }


def _empty_area_cfg(label=''):
    return {
        'label': _s(label) or 'New area',
        'roles': [],
        'view_only_role': '',
        'email_from_peopleid': 0,
        'prior_app_orgid': 0,
        'cpp_violation_ev': '',
        'lists': {},
    }


def _area_keys(cfg):
    areas = cfg.get('areas') or {}
    keys = []
    for k in AREA_ORDER:
        if k in areas:
            keys.append(k)
    for k in areas.keys():
        if k not in keys:
            keys.append(k)
    return keys


# ---------------------------------------------------------------------------
# Config (Special Content JSON)
# ---------------------------------------------------------------------------

def _default_config():
    return {
        'version': 1,
        'progress_note': _default_progress_note_cfg(),
        'areas': {
            'kids': {
                'label': 'Kids Ministry',
                'roles': ['Next Gen'],
                'view_only_role': '',
                'email_from_peopleid': 0,
                'prior_app_orgid': 502,
                'cpp_violation_ev': 'CPP Violation/Next Gen Service Ineligibility',
                'lists': {
                    'littles': {
                        'label': 'Faith Littles',
                        'orgid': 582,
                        'email_template': 'Kids Min Application',
                        'adult_reg_url': 'https://fcchudson.tpsdb.com/OnlineReg/1742',
                        'minor_reg_url': 'https://fcchudson.tpsdb.com/OnlineReg/1780',
                        'ev_app_sent': 'KIDS MIN Volunteer Application Sent',
                        'ev_app_reviewed': 'KIDS MIN Volunteer Application Reviewed',
                        'ev_handbook': 'Littles Handbook Signed',
                        'ev_training': '',
                        'kw_interview': 'CSP KM: Faith Littles Interview Complete',
                        'kw_references': 'CSP KM: Faith Littles Reference Check Complete',
                        'kw_shadowing': 'CSP KM: Faith Littles Shadowing Complete',
                        'kw_fl_training': 'CSP KM: Faith Littles Training Complete',
                        'track': 'full',
                        'has_fl_training': True,
                    },
                    'kids': {
                        'label': 'Faith Kids',
                        'orgid': 579,
                        'email_template': 'Kids Min Application',
                        'adult_reg_url': 'https://fcchudson.tpsdb.com/OnlineReg/1742',
                        'minor_reg_url': 'https://fcchudson.tpsdb.com/OnlineReg/1780',
                        'ev_app_sent': 'KIDS MIN Volunteer Application Sent',
                        'ev_app_reviewed': 'KIDS MIN Volunteer Application Reviewed',
                        'ev_handbook': 'Kids Handbook Signed',
                        'ev_training': 'Kids In Person Training',
                        'kw_interview': 'CSP KM: Faith Kids Interview Complete',
                        'kw_references': 'CSP KM: Faith Kids Reference Check Complete',
                        'kw_shadowing': 'CSP KM: Faith Kids Shadowing Complete',
                        'kw_fl_training': '',
                        'track': 'full',
                        'has_fl_training': False,
                    },
                },
            },
            'student': {
                'label': 'Student Ministry',
                'roles': ['Next Gen'],
                'view_only_role': '',
                'email_from_peopleid': 0,
                'prior_app_orgid': 0,
                'cpp_violation_ev': 'CPP Violation/Next Gen Service Ineligibility',
                'lists': {
                    'students': {
                        'label': 'Student Ministry',
                        'orgid': 0,
                        'email_template': '',
                        'adult_reg_url': '',
                        'minor_reg_url': '',
                        'ev_app_sent': '',
                        'ev_app_reviewed': '',
                        'ev_handbook': '',
                        'ev_training': '',
                        'kw_interview': '',
                        'kw_references': '',
                        'kw_shadowing': '',
                        'kw_fl_training': '',
                        'track': 'full',
                        'has_fl_training': False,
                    },
                },
            },
            'adult': {
                'label': 'Adult Ministries',
                'roles': ['Adult Min'],
                'view_only_role': '',
                'lists': {
                    'hospitality': {'label': 'Hospitality', 'orgid': 0, 'track': 'simple'},
                    'safety': {'label': 'Safety', 'orgid': 0, 'track': 'full'},
                    'medical': {'label': 'Medical', 'orgid': 0, 'track': 'simple'},
                },
            },
            'mcl': {
                'label': 'Missional Community Leaders',
                'roles': ['Missional Communities'],
                'view_only_role': '',
                'lists': {},
            },
            'worship': {
                'label': 'Worship Ministry',
                'roles': ['Worship Ministry'],
                'view_only_role': '',
                'lists': {},
            },
            'outreach': {
                'label': 'Outreach',
                'roles': ['Outreach Ministry'],
                'view_only_role': '',
                'lists': {},
            },
            'missions': {
                'label': 'Missions',
                'roles': ['Missions'],
                'view_only_role': '',
                'lists': {},
            },
        },
    }


def _default_progress_note_cfg():
    """Church-wide Progress Note keyword + Extra Value dropdown → step bucket map."""
    return {
        'keyword': 'CSP: Progress Note',
        'ev_question': 'CSP: Progress Note',
        'option_map': {
            'Application': 'application',
            'Background Check': 'background',
            'Video Training': 'video',
            'Interview': 'interview',
            'References': 'references',
            'Shadowing': 'shadowing',
            'Other': 'other',
        },
    }


def _progress_note_cfg(cfg=None):
    """Normalized progress_note block from config (with defaults)."""
    base = _default_progress_note_cfg()
    if cfg is None:
        try:
            cfg = _load_config()
        except:
            cfg = {}
    raw = (cfg or {}).get('progress_note')
    if not isinstance(raw, dict):
        return base
    out = {
        'keyword': _s(raw.get('keyword')) or base['keyword'],
        'ev_question': _s(raw.get('ev_question')) or base['ev_question'],
        'option_map': {},
    }
    om = raw.get('option_map')
    if not isinstance(om, dict) or not om:
        om = base['option_map']
    for k in om.keys():
        label = _s(k)
        bucket = _s(om.get(k))
        if label and bucket:
            out['option_map'][label] = bucket
    if not out['option_map']:
        out['option_map'] = dict(base['option_map'])
    return out


def _pn_bucket_for_option(cfg, option_label):
    om = _progress_note_cfg(cfg).get('option_map') or {}
    label = _s(option_label).strip()
    if not label:
        return 'other'
    b = _s(om.get(label))
    if b:
        return b
    low = label.lower()
    for k in om.keys():
        if _s(k).strip().lower() == low:
            return _s(om.get(k)) or 'other'
    # Fuzzy / alias match (TouchPoint option wording can differ slightly)
    aliases = [
        ('application', 'application'),
        ('background', 'background'),
        ('video', 'video'),
        ('interview', 'interview'),
        ('reference', 'references'),
        ('shadow', 'shadowing'),
        ('other', 'other'),
    ]
    for needle, bucket in aliases:
        if needle in low:
            return bucket
    return 'other'


def _pn_option_lookup(cfg):
    """OptionId → Name for dropdown(s) on the Progress Note keyword."""
    pn = _progress_note_cfg(cfg)
    kw = _s(pn.get('keyword'))
    if not kw:
        return {}
    kw_esc = kw.replace("'", "''")
    sql = """
SELECT o.KeywordExtraValueOptionId AS OptId, o.Name AS OptName
FROM dbo.Keyword k
INNER JOIN dbo.KeywordExtraValue kev ON kev.KeywordId = k.KeywordId
INNER JOIN dbo.KeywordExtraValueOption o ON o.KeywordExtraValueId = kev.KeywordExtraValueId
WHERE LTRIM(RTRIM(k.Description)) = N'""" + kw_esc + """'
  AND kev.DataType = 5
"""
    out = {}
    try:
        for r in list(q.QuerySql(sql)):
            oid = _i(r.OptId, 0)
            name = _s(r.OptName).strip()
            if oid > 0 and name:
                out[str(oid)] = name
                out[name.lower()] = name
    except:
        pass
    return out


def _pn_resolve_option_label(cfg, response, instructions, lookup=None):
    """Turn EV Response / Instructions into a dropdown option label."""
    if lookup is None:
        lookup = _pn_option_lookup(cfg)
    # 1) Explicit dashboard marker on Instructions (survives failed EV writes)
    instr = _s(instructions)
    if instr.startswith('VODPN:'):
        return instr[6:].strip()
    resp = _s(response).strip()
    if not resp:
        return ''
    # 2) Response is option id
    if resp in lookup:
        return _s(lookup.get(resp))
    # 3) Response is option name
    if resp.lower() in lookup:
        return _s(lookup.get(resp.lower()))
    # 4) Numeric id not in cache — still try as label for fuzzy bucket map
    try:
        if int(resp) > 0 and resp in lookup:
            return _s(lookup.get(resp))
    except:
        pass
    return resp


def _pn_option_for_bucket(cfg, bucket):
    """First dropdown label that maps to this bucket (for preselect)."""
    om = _progress_note_cfg(cfg).get('option_map') or {}
    for label, b in om.items():
        if _s(b) == _s(bucket):
            return _s(label)
    return ''


def _pn_allowed_option_labels(cfg, is_minor):
    """Dropdown labels allowed for this person (minors hide BC / Video / Shadowing)."""
    om = _progress_note_cfg(cfg).get('option_map') or {}
    hide = set(['background', 'video', 'shadowing']) if is_minor else set()
    out = []
    for label, bucket in om.items():
        if _s(bucket) in hide:
            continue
        out.append(_s(label))
    return out


def _pn_stack_bucket(title):
    t = _s(title)
    if t == 'Application':
        return 'application'
    if t == 'Background Check':
        return 'background'
    if t == 'Video Training':
        return 'video'
    return ''


def _pn_single_bucket(step_key):
    k = _s(step_key)
    if k in ('interview', 'references', 'shadowing'):
        return k
    return ''


def _pn_bucket_complete(steps, bucket):
    """True when the mapped tile/column is fully complete (stacks = both children)."""
    bucket = _s(bucket)
    if not bucket or bucket == 'other':
        return False
    for block in steps or []:
        if block.get('type') == 'stack':
            if _pn_stack_bucket(block.get('title')) != bucket:
                continue
            kids = block.get('children') or []
            if not kids:
                return False
            for ch in kids:
                if not ch.get('complete'):
                    return False
            return True
        st = block.get('step') or {}
        if _pn_single_bucket(st.get('key')) == bucket:
            return bool(st.get('complete'))
    return False


def _jobj_to_py(tok):
    """Convert Newtonsoft JToken to Python dict/list/scalars (IronPython-safe)."""
    if tok is None:
        return None
    # Prefer numeric JTokenType — ToString() is unreliable across IronPython/CLR builds
    type_id = -1
    tname = ''
    try:
        type_id = int(tok.Type)
    except:
        pass
    try:
        tname = _s(tok.Type.ToString())
    except:
        tname = ''
    # JTokenType: Object=1, Array=2, Integer=6, Float=7, String=8, Boolean=9, Null=10
    is_object = (type_id == 1) or (tname == 'Object') or (tname.endswith('.Object'))
    is_array = (type_id == 2) or (tname == 'Array') or (tname.endswith('.Array'))
    if is_object or (hasattr(tok, 'Properties') and not is_array and type_id not in (6, 7, 8, 9, 10)):
        try:
            d = {}
            for prop in tok.Properties():
                d[_s(prop.Name)] = _jobj_to_py(prop.Value)
            return d
        except:
            if is_object:
                raise
    if is_array:
        return [_jobj_to_py(x) for x in tok]
    if type_id == 6 or tname == 'Integer' or tname.endswith('.Integer'):
        return int(tok)
    if type_id == 7 or tname == 'Float' or tname.endswith('.Float'):
        return float(tok)
    if type_id == 9 or tname == 'Boolean' or tname.endswith('.Boolean'):
        return bool(tok)
    if type_id == 10 or tname == 'Null' or tname.endswith('.Null'):
        return None
    if type_id == 8 or tname == 'String' or tname.endswith('.String'):
        try:
            return _s(tok.Value)
        except:
            return _s(tok)
    return _s(tok)


def _py_to_json(obj):
    """Serialize Python object to indented JSON (easier to edit in Special Content)."""
    return _py_to_json_walk(obj, 0)


def _json_number(obj):
    """Return JSON number text for int-like CLR/Python values, or None."""
    if obj is True or obj is False:
        return None
    try:
        from System import Boolean
        if isinstance(obj, Boolean):
            return None
    except:
        pass
    if isinstance(obj, (int, long)) and not isinstance(obj, bool):
        return str(int(obj))
    try:
        from System import Int32, Int64, Int16, Byte, UInt32
        if isinstance(obj, (Int32, Int64, Int16, Byte, UInt32)):
            return str(int(obj))
    except:
        pass
    try:
        if hasattr(obj, 'GetType'):
            tn = obj.GetType().FullName
            if tn in ('System.Int32', 'System.Int64', 'System.Int16', 'System.Byte'):
                return str(int(obj))
    except:
        pass
    return None


def _py_to_json_walk(obj, indent=0):
    """Serialize Python/CLR object to JSON string (IronPython — no stdlib json).
    indent>=0 → pretty-print with 2-space indents; use indent=None for compact.
    """
    pretty = indent is not None
    pad = ('  ' * indent) if pretty else ''
    pad1 = ('  ' * (indent + 1)) if pretty else ''
    nl = '\n' if pretty else ''
    sp = ' ' if pretty else ''

    if obj is None:
        return 'null'
    if obj is True:
        return 'true'
    if obj is False:
        return 'false'
    try:
        from System import Boolean
        if isinstance(obj, Boolean):
            return 'true' if bool(obj) else 'false'
    except:
        pass
    num = _json_number(obj)
    if num is not None:
        return num
    if isinstance(obj, float):
        return repr(float(obj))
    if isinstance(obj, dict):
        if not obj:
            return '{}'
        prefer = ['version', 'progress_note', 'sender_peopleid', 'areas', 'label', 'roles', 'view_only_role',
                  'email_from_peopleid', 'prior_app_orgid', 'cpp_violation_ev', 'lists',
                  'keyword', 'ev_question', 'option_map',
                  'orgid', 'email_template', 'adult_reg_url', 'minor_reg_url',
                  'ev_app_sent', 'ev_app_reviewed', 'ev_handbook', 'ev_training',
                  'kw_interview', 'kw_references', 'kw_shadowing', 'kw_fl_training',
                  'track', 'has_fl_training']
        keys = list(obj.keys())
        ordered = []
        seen = set()
        for pref in prefer:
            for k in keys:
                sk = _s(k)
                if sk == pref and sk not in seen:
                    ordered.append(k)
                    seen.add(sk)
        rest = sorted(keys, key=lambda x: _s(x))
        for k in rest:
            sk = _s(k)
            if sk not in seen:
                ordered.append(k)
                seen.add(sk)
        parts = []
        for k in ordered:
            val = _py_to_json_walk(obj[k], (indent + 1) if pretty else None)
            parts.append(pad1 + _json_quote(_s(k)) + ':' + sp + val)
        return '{' + nl + (',' + nl).join(parts) + nl + pad + '}'
    if isinstance(obj, (list, tuple)):
        if not obj:
            return '[]'
        parts = []
        for x in obj:
            parts.append(pad1 + _py_to_json_walk(x, (indent + 1) if pretty else None))
        return '[' + nl + (',' + nl).join(parts) + nl + pad + ']'
    return _json_quote(_s(obj))


def _json_pretty_text(raw):
    """Pretty-print a JSON string for display/editing; returns original on failure."""
    raw = _s(raw)
    if not raw:
        return ''
    try:
        _ensure_newtonsoft()
        from Newtonsoft.Json import Formatting
        from Newtonsoft.Json.Linq import JToken
        tok = JToken.Parse(raw)
        return _s(tok.ToString(Formatting.Indented))
    except:
        pass
    parsed, _status = _parse_config_json(raw)
    if isinstance(parsed, dict):
        return _py_to_json(parsed)
    return raw


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
            parts.append(ch)
    parts.append('"')
    return ''.join(parts)


def _jobject_set_orgid(raw, area_key, list_key, orgid):
    """Surgically set areas.{area}.lists.{list}.orgid in stored JSON via JObject.
    Returns (new_json_text, error_message).
    """
    area_key = _s(area_key)
    list_key = _s(list_key)
    orgid = _i(orgid, 0)
    try:
        _ensure_newtonsoft()
        from Newtonsoft.Json.Linq import JObject, JValue, JProperty
    except Exception, ex:
        return None, 'no JObject: ' + _s(ex)[:60]
    try:
        if raw:
            root = JObject.Parse(raw)
        else:
            root = JObject.Parse(_py_to_json_walk(_default_config()))
    except Exception, ex:
        # Corrupt store — start from defaults
        try:
            root = JObject.Parse(_py_to_json_walk(_default_config()))
        except Exception, ex2:
            return None, 'parse fail: ' + _s(ex)[:40] + '/' + _s(ex2)[:40]

    try:
        areas = root['areas']
        try:
            areas_is_obj = areas is not None and areas.Type.ToString() == 'Object'
        except:
            areas_is_obj = False
        if not areas_is_obj:
            areas = JObject()
            root['areas'] = areas
        area = areas[area_key]
        try:
            area_is_obj = area is not None and area.Type.ToString() == 'Object'
        except:
            area_is_obj = False
        if not area_is_obj:
            area = JObject.Parse(_py_to_json_walk(_empty_area_cfg(area_key)))
            areas[area_key] = area
        lists = area['lists']
        try:
            lists_is_obj = lists is not None and lists.Type.ToString() == 'Object'
        except:
            lists_is_obj = False
        if not lists_is_obj:
            lists = JObject()
            area['lists'] = lists
        lc = lists[list_key]
        try:
            lc_is_obj = lc is not None and lc.Type.ToString() == 'Object'
        except:
            lc_is_obj = False
        if not lc_is_obj:
            lc = JObject.Parse(_py_to_json_walk(_empty_list_cfg(list_key)))
            lists[list_key] = lc
        lc['orgid'] = JValue(int(orgid))
        # Prefer compact ToString(Formatting.None) when available
        try:
            from Newtonsoft.Json import Formatting
            text = root.ToString(Formatting.Indented)
        except:
            text = root.ToString()
        return _s(text), ''
    except Exception, ex:
        return None, 'set path fail: ' + _s(ex)[:80]


def _action_set_orgid(area_key, list_key, orgid):
    """Minimal Inv# save via GET. Prefers full parse→edit→pretty write (no Newtonsoft required)."""
    if not _is_admin():
        return 'err_auth'
    area_key = _slug_key(area_key) or _s(area_key)
    list_key = _slug_key(list_key) or _s(list_key)
    orgid = _i(orgid, 0)
    if not area_key or not list_key:
        _flash_detail_set('missing area/list — ' + _request_diag())
        return 'err_generic'

    cfg = _load_config()
    areas = cfg.get('areas') or {}
    area = areas.get(area_key) or _empty_area_cfg(area_key)
    lists = area.get('lists') or {}
    lc = _normalize_list_cfg(lists.get(list_key) or _empty_list_cfg(list_key), list_key)
    lc['orgid'] = orgid
    lists[list_key] = lc
    area['lists'] = lists
    areas[area_key] = area
    cfg['areas'] = areas

    try:
        text = _save_config(cfg)
    except Exception, ex:
        _flash_detail_set('WriteContentText: ' + _s(ex)[:100])
        return 'err_generic'

    again = _load_config()
    got = _i(((((again.get('areas') or {}).get(area_key) or {}).get('lists') or {}).get(list_key) or {}).get('orgid'), 0)
    if got != orgid:
        _flash_detail_set(
            'wrote ' + str(len(_s(text))) + 'b set ' + str(orgid) + ' but load got ' + str(got)
            + ' — ' + _s(_CONFIG_LOAD_INFO)
        )
        return 'err_generic'

    _flash_detail_set(area_key + '/' + list_key + ' orgid=' + str(got) + ' — ' + _s(_CONFIG_LOAD_INFO))
    return 'ok_config'


def _deep_merge(base, overlay):
    if not isinstance(base, dict):
        return overlay
    out = {}
    for k in base.keys():
        out[k] = base[k]
    if not isinstance(overlay, dict):
        return out
    for k in overlay.keys():
        if k in out and isinstance(out[k], dict) and isinstance(overlay[k], dict):
            out[k] = _deep_merge(out[k], overlay[k])
        else:
            out[k] = overlay[k]
    return out


def _raw_content_text(name):
    """Read Special Content text without _s() swallowing a body equal to 'null'."""
    try:
        raw = model.TextContent(name)
    except:
        return ''
    if raw is None:
        return ''
    try:
        return unicode(raw).strip()
    except:
        try:
            return str(raw).strip()
        except:
            return ''


def _from_person(people_id):
    """Resolve From address/name from a PeopleId (primary EmailAddress + Name)."""
    pid = _i(people_id, 0)
    if pid <= 0:
        return '', ''
    sql = """
SELECT TOP 1
    p.Name,
    p.EmailAddress
FROM dbo.People p
WHERE p.PeopleId = @pid
  AND ISNULL(p.IsDeceased, 0) = 0
"""
    p = _dd()
    p.AddValue('pid', pid)
    rows = list(q.QuerySql(sql, p))
    if not rows:
        return '', ''
    return _s(rows[0].EmailAddress), _s(rows[0].Name)


def _load_config():
    global _CONFIG_LOAD_INFO
    cfg = _default_config()
    raw = _raw_content_text(CONFIG_CONTENT_NAME)
    if not raw:
        _CONFIG_LOAD_INFO = 'store empty — using script defaults'
    else:
        parsed, status = _parse_config_json(raw)
        if isinstance(parsed, dict):
            cfg = _deep_merge(cfg, parsed)
            # Surface a key value so Config tab proves the file was applied
            try:
                st_org = _i(((((parsed.get('areas') or {}).get('student') or {}).get('lists') or {}).get('students') or {}).get('orgid'), 0)
            except:
                st_org = -1
            _CONFIG_LOAD_INFO = status + ' · file student.orgid=' + str(st_org) + ' · ' + str(len(raw)) + ' chars'
        else:
            _CONFIG_LOAD_INFO = status + ' · ' + str(len(raw)) + ' chars (defaults only — fix JSON or re-paste script)'

    areas = cfg.get('areas') or {}
    kids = areas.get('kids') or {}
    # Prefer sender_peopleid from JSON if kids From PeopleId empty
    if not _i(kids.get('email_from_peopleid'), 0) and _i(cfg.get('sender_peopleid'), 0):
        kids['email_from_peopleid'] = _i(cfg.get('sender_peopleid'), 0)
    # Drop legacy keys from in-memory kids if present
    if 'email_from_addr' in kids:
        try:
            del kids['email_from_addr']
        except:
            kids['email_from_addr'] = ''
    if 'email_from_name' in kids:
        try:
            del kids['email_from_name']
        except:
            kids['email_from_name'] = ''
    areas['kids'] = kids

    # Ensure every area/list has the Kids-style step mapping fields
    for ak in list(areas.keys()):
        areas[ak] = _normalize_area_cfg(areas.get(ak) or {}, ak)
        if ak == 'student':
            lists = areas[ak].get('lists') or {}
            if not lists:
                seed = ((_default_config().get('areas') or {}).get('student') or {}).get('lists') or {}
                areas[ak]['lists'] = {}
                for lk in seed.keys():
                    areas[ak]['lists'][lk] = _normalize_list_cfg(seed.get(lk) or {}, lk)

    cfg['areas'] = areas
    cfg['progress_note'] = _progress_note_cfg(cfg)
    return cfg


def _save_config(cfg):
    kids = ((cfg.get('areas') or {}).get('kids')) or {}
    pid = _i(kids.get('email_from_peopleid'), 0)
    cfg['sender_peopleid'] = pid
    text = _py_to_json(cfg)
    model.WriteContentText(CONFIG_CONTENT_NAME, text)
    return text


def _action_seed_config(force=False):
    """Write default config JSON into Special Content text (no form fields needed)."""
    if not _is_admin():
        return 'err_auth'
    raw = _raw_content_text(CONFIG_CONTENT_NAME)
    if raw and not force:
        _flash_detail_set('store already has ' + str(len(raw)) + ' chars — edit Special Content, or add &force=1 to overwrite')
        return 'ok_config'
    try:
        text = _save_config(_default_config())
        _flash_detail_set('seeded ' + CONFIG_CONTENT_NAME + ' (' + str(len(text)) + ' chars). Edit in Special Content → Text.')
        return 'ok_config'
    except Exception, ex:
        _flash_detail_set('seed failed: ' + _s(ex)[:100])
        return 'err_generic'


def _list_cfg(cfg, area_key, list_key):
    areas = cfg.get('areas') or {}
    area = areas.get(area_key) or {}
    lists = area.get('lists') or {}
    return area, lists.get(list_key) or {}


def _orgid(list_cfg):
    return _i(list_cfg.get('orgid'), 0)


def _can_see_area(cfg, area_key):
    if _is_admin():
        return True
    areas = cfg.get('areas') or {}
    area = areas.get(area_key) or {}
    roles = area.get('roles') or []
    if not (_has_role('Staff') or _has_role('Elders')):
        return False
    for r in roles:
        if _has_role(_s(r)):
            return True
    return False


def _is_view_only(cfg, area_key):
    if _is_admin():
        return False
    areas = cfg.get('areas') or {}
    area = areas.get(area_key) or {}
    vor = _s(area.get('view_only_role'))
    if vor and _has_role(vor):
        # View-only if they have the VO role and do NOT have a write ministry role alone
        # Spec: View Only role picker — those users cannot write.
        return True
    return False


def _configured_lists(cfg, area_key):
    """Return list_key -> list_cfg for lists with orgid > 0."""
    areas = cfg.get('areas') or {}
    area = areas.get(area_key) or {}
    lists = area.get('lists') or {}
    out = {}
    for k in lists.keys():
        lc = lists[k] or {}
        if _orgid(lc) > 0:
            out[k] = lc
    return out


def _visible_areas(cfg):
    """Areas the current user can see that have at least one configured list (work tabs)."""
    areas = cfg.get('areas') or {}
    visible = []
    for k in _area_keys(cfg):
        if not _can_see_area(cfg, k):
            continue
        configured = _configured_lists(cfg, k)
        if configured:
            visible.append((k, areas.get(k) or {}, configured))
    return visible


def _home_areas(cfg):
    """Areas visible by role for Home tiles — includes unconfigured (show as not set up)."""
    areas = cfg.get('areas') or {}
    out = []
    for k in _area_keys(cfg):
        if not _can_see_area(cfg, k):
            continue
        out.append((k, areas.get(k) or {}, _configured_lists(cfg, k)))
    return out


def _list_order(configured):
    order = ['littles', 'kids', 'students', 'hospitality', 'safety', 'medical']
    ordered = []
    for o in order:
        if o in configured:
            ordered.append(o)
    for k in configured.keys():
        if k not in ordered:
            ordered.append(k)
    return ordered


def _normalize_list_cfg(lc, key=''):
    """Ensure a list has the same step-mapping fields as Kids / Littles."""
    base = _empty_list_cfg(_s((lc or {}).get('label')) or key)
    if not isinstance(lc, dict):
        return base
    out = {}
    for k in base.keys():
        out[k] = base[k]
    for k in lc.keys():
        out[k] = lc[k]
    out['orgid'] = _i(out.get('orgid'), 0)
    out['has_fl_training'] = bool(out.get('has_fl_training'))
    if not _s(out.get('track')):
        out['track'] = 'full'
    if not _s(out.get('label')):
        out['label'] = _s(key) or 'List'
    return out


def _normalize_area_cfg(area, area_key=''):
    base = _empty_area_cfg(_s((area or {}).get('label')) or area_key)
    if not isinstance(area, dict):
        area = {}
    out = {}
    for k in base.keys():
        if k == 'lists':
            continue
        out[k] = area[k] if k in area else base[k]
    out['email_from_peopleid'] = _i(out.get('email_from_peopleid'), 0)
    out['prior_app_orgid'] = _i(out.get('prior_app_orgid'), 0)
    out['roles'] = area.get('roles') if isinstance(area.get('roles'), list) else (base.get('roles') or [])
    lists_in = area.get('lists') if isinstance(area.get('lists'), dict) else {}
    lists_out = {}
    for lk in lists_in.keys():
        lists_out[lk] = _normalize_list_cfg(lists_in.get(lk) or {}, lk)
    # If Student (or any full-track area) has zero lists, seed from defaults when available
    out['lists'] = lists_out
    return out


def _person_is_minor(person):
    age = person.Age
    try:
        if age is None or _is_null(age):
            return False
        return int(age) < 18
    except:
        return False


def _area_metrics(cfg, area_key, area_cfg, configured):
    """Roll-up Prospect / Ready / Minor / CPP-flagged counts for an area."""
    metrics = {
        'prospects': 0,
        'ready': 0,
        'minors': 0,
        'flagged': 0,
        'has_cpp': bool(_s(area_cfg.get('cpp_violation_ev'))),
        'lists': [],
    }
    cpp_ev = _s(area_cfg.get('cpp_violation_ev'))
    for lk in _list_order(configured):
        lc = configured[lk]
        orgid = _orgid(lc)
        row = {
            'key': lk,
            'label': _s(lc.get('label')) or lk,
            'orgid': orgid,
            'prospects': 0,
            'ready': 0,
            'minors': 0,
            'flagged': 0,
        }
        if orgid <= 0:
            metrics['lists'].append(row)
            continue
        try:
            people = _load_prospects(orgid)
        except:
            people = []
        for person in people:
            row['prospects'] += 1
            is_minor = _person_is_minor(person)
            if is_minor:
                row['minors'] += 1
            steps = _build_steps(person, area_cfg, lc, is_minor)
            if _required_complete(steps):
                row['ready'] += 1
            if cpp_ev and _ev_any(_i(person.PeopleId), cpp_ev):
                row['flagged'] += 1
        metrics['prospects'] += row['prospects']
        metrics['ready'] += row['ready']
        metrics['minors'] += row['minors']
        metrics['flagged'] += row['flagged']
        metrics['lists'].append(row)
    return metrics


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------

def _keyword_id(description):
    desc = _s(description)
    if not desc:
        return 0
    sql = """
SELECT TOP 1 KeywordId
FROM dbo.Keyword
WHERE Description = @desc
"""
    p = _dd()
    p.AddValue('desc', desc)
    rows = list(q.QuerySql(sql, p))
    if not rows:
        return 0
    return _i(rows[0].KeywordId, 0)


def _has_keyword_note(people_id, keyword_desc):
    kid = _keyword_id(keyword_desc)
    if kid <= 0:
        return False, ''
    sql = """
SELECT TOP 1 tn.TaskNoteId, tn.CreatedDate, tn.Notes, tn.Instructions
FROM dbo.TaskNote tn
JOIN dbo.TaskNoteKeyword tnk ON tnk.TaskNoteId = tn.TaskNoteId
WHERE tn.AboutPersonId = @pid
  AND tnk.KeywordId = @kid
  AND ISNULL(tn.IsArchived, 0) = 0
ORDER BY tn.CreatedDate DESC
"""
    p = _dd()
    p.AddValue('pid', people_id)
    p.AddValue('kid', kid)
    try:
        rows = list(q.QuerySql(sql, p))
    except:
        return False, ''
    if not rows:
        return False, ''
    r = rows[0]
    when = _fmt_date(r.CreatedDate)
    return True, when


_ALL_KEYWORDS_CACHE = None


def _all_active_keywords():
    """Active Keyword.Description values (church-wide list), cached per script run."""
    global _ALL_KEYWORDS_CACHE
    if _ALL_KEYWORDS_CACHE is not None:
        return _ALL_KEYWORDS_CACHE
    sql = """
SELECT Description
FROM dbo.Keyword
WHERE ISNULL(IsActive, 1) = 1
  AND LTRIM(RTRIM(ISNULL(Description, ''))) <> ''
ORDER BY Description
"""
    rows = []
    try:
        rows = list(q.QuerySql(sql))
    except:
        rows = []
    out = []
    seen = set()
    for r in rows:
        desc = _s(r.Description)
        if not desc or desc in seen:
            continue
        seen.add(desc)
        out.append(desc)
    _ALL_KEYWORDS_CACHE = out
    return out


def _note_keyword_options(complete_kw, cfg=None):
    """Keyword choices for Add note.
    Default / pinned: Progress Note keyword. Empty keyword = fallback.
    Complete keyword (when configured) still available to mark the step done.
    """
    complete_kw = _s(complete_kw)
    pn = _progress_note_cfg(cfg)
    pn_kw = _s(pn.get('keyword'))
    opts = []
    seen = set()

    if pn_kw:
        opts.append((pn_kw, pn_kw + ' — progress note'))
        seen.add(pn_kw)

    # Fail-safe: note with no keyword
    opts.append(('', 'No keyword (fallback)'))
    seen.add('')

    if complete_kw and complete_kw not in seen:
        opts.append((complete_kw, complete_kw + ' — marks complete'))
        seen.add(complete_kw)

    for desc in _all_active_keywords():
        if not desc or desc in seen:
            continue
        seen.add(desc)
        opts.append((desc, desc))
    return opts


def _progress_notes_for_people(pids, cfg):
    """Load Progress Note keyword notes grouped by person + step bucket.
    Returns { people_id: { bucket: [ {id, text, when, option}, ... ] } }
    """
    out = {}
    clean = []
    seen = set()
    for p in (pids or []):
        pid = _i(p, 0)
        if pid > 0 and pid not in seen:
            seen.add(pid)
            clean.append(pid)
    if not clean:
        return out
    pn = _progress_note_cfg(cfg)
    kw = _s(pn.get('keyword'))
    if not kw:
        return out
    id_csv = ','.join([str(x) for x in clean])
    kw_esc = kw.replace("'", "''")
    lookup = _pn_option_lookup(cfg)
    sql = """
SELECT tn.AboutPersonId AS PeopleId,
       tn.TaskNoteId,
       tn.Notes,
       tn.Instructions,
       tn.CreatedDate,
       kev.Name AS EvName,
       kev.DataType AS EvDataType,
       tnev.Response AS EvResponse
FROM dbo.TaskNote tn
INNER JOIN dbo.TaskNoteKeyword tnk ON tnk.TaskNoteId = tn.TaskNoteId
INNER JOIN dbo.Keyword k ON k.KeywordId = tnk.KeywordId
LEFT JOIN dbo.TaskNoteExtraValue tnev ON tnev.TaskNoteId = tn.TaskNoteId
LEFT JOIN dbo.KeywordExtraValue kev ON kev.KeywordExtraValueId = tnev.KeywordExtraValueId
WHERE ISNULL(tn.IsArchived, 0) = 0
  AND tn.AboutPersonId IN (""" + id_csv + """)
  AND LTRIM(RTRIM(k.Description)) = N'""" + kw_esc + """'
ORDER BY tn.CreatedDate DESC, tn.TaskNoteId DESC
"""
    rows = []
    try:
        rows = list(q.QuerySql(sql))
    except:
        rows = []
    ev_name = _s(pn.get('ev_question'))
    best = {}
    for r in rows:
        pid = _i(r.PeopleId, 0)
        tnid = _i(r.TaskNoteId, 0)
        if pid <= 0 or tnid <= 0:
            continue
        option = _pn_resolve_option_label(cfg, r.EvResponse, r.Instructions, lookup)
        evn = _s(r.EvName)
        dt = _i(r.EvDataType, 0)
        score = 0
        if option:
            score += 10
        if _s(r.Instructions).startswith('VODPN:'):
            score += 8
        if ev_name and evn.lower() == ev_name.lower():
            score += 5
        elif dt == KEV_DROPDOWN:
            score += 2
        elif dt > 0:
            score += 1
        key = (pid, tnid)
        prev = best.get(key)
        if prev is None or score > prev['score']:
            best[key] = {
                'score': score,
                'pid': pid,
                'id': tnid,
                'text': _s(r.Notes),
                'when': _fmt_date(r.CreatedDate),
                'option': option,
            }
    for key in best.keys():
        item = best[key]
        option = _s(item.get('option'))
        bucket = _pn_bucket_for_option(cfg, option) if option else 'other'
        note = {
            'id': item['id'],
            'text': item['text'],
            'when': item['when'],
            'option': option or 'Other',
        }
        pid = item['pid']
        if pid not in out:
            out[pid] = {}
        if bucket not in out[pid]:
            out[pid][bucket] = []
        out[pid][bucket].append(note)
    return out


def _posted_kev_map():
    """Answers from hidden kev_json (preferred) or individual kev_* form fields."""
    raw = _s(_form_val('kev_json'))
    if raw:
        parsed, _status = _parse_config_json(raw)
        if isinstance(parsed, dict):
            out = {}
            for k in parsed.keys():
                out[_s(k)] = _s(parsed.get(k))
            return out
    # Fallback: scan request keys
    out = {}
    try:
        for k in _form_key_set():
            ks = _s(k)
            if ks.startswith('kev_'):
                out[ks] = _s(_form_val(ks))
    except:
        pass
    return out


# KeywordExtraValue DataType codes (CmsData.Codes.KeywordExtraValueDataTypeCode)
KEV_HEADER = 1
KEV_INSTRUCTIONS = 2
KEV_TEXT = 3
KEV_MULTILINE = 4
KEV_DROPDOWN = 5
KEV_YESNO = 6
KEV_CHECKBOXES = 7
KEV_DATE = 8

_KEV_MAP_CACHE = None


def _keyword_extra_questions_map():
    """Description → list of KeywordExtraValue questions visible to the current user.
    Used by the Add note modal when a keyword with related questions is selected.
    """
    global _KEV_MAP_CACHE
    if _KEV_MAP_CACHE is not None:
        return _KEV_MAP_CACHE
    sql = """
SELECT k.Description,
       kev.KeywordExtraValueId,
       kev.DataType,
       kev.SortOrder,
       kev.Name,
       kev.RoleId,
       r.RoleName,
       o.KeywordExtraValueOptionId,
       o.Name AS OptionName
FROM dbo.Keyword k
INNER JOIN dbo.KeywordExtraValue kev ON kev.KeywordId = k.KeywordId
LEFT JOIN dbo.Roles r ON r.RoleId = kev.RoleId
LEFT JOIN dbo.KeywordExtraValueOption o ON o.KeywordExtraValueId = kev.KeywordExtraValueId
WHERE ISNULL(k.IsActive, 1) = 1
ORDER BY k.Description, kev.SortOrder, o.KeywordExtraValueOptionId
"""
    rows = []
    try:
        rows = list(q.QuerySql(sql))
    except:
        rows = []
    out = {}
    is_admin = _is_admin()
    # Group options under each question
    for r in rows:
        desc = _s(r.Description)
        if not desc:
            continue
        role_name = _s(r.RoleName)
        role_id = _i(r.RoleId, 0)
        if role_id > 0 and role_name and not is_admin and not _has_role(role_name):
            continue
        qid = _i(r.KeywordExtraValueId, 0)
        if qid <= 0:
            continue
        if desc not in out:
            out[desc] = []
        qlist = out[desc]
        item = None
        for existing in qlist:
            if existing.get('id') == qid:
                item = existing
                break
        if item is None:
            item = {
                'id': qid,
                'dt': _i(r.DataType, 0),
                'name': _s(r.Name),
                'opts': [],
            }
            qlist.append(item)
        opt_id = _i(r.KeywordExtraValueOptionId, 0)
        if opt_id > 0:
            item['opts'].append({'id': opt_id, 'name': _s(r.OptionName)})
    _KEV_MAP_CACHE = out
    return out


def _questions_for_keyword(keyword_desc):
    m = _keyword_extra_questions_map()
    d = _s(keyword_desc).strip()
    if not d:
        return []
    if d in m:
        return m[d]
    low = d.lower()
    for k in m.keys():
        if _s(k).strip().lower() == low:
            return m[k]
    return []


def _insert_task_note_extra_value(task_note_id, kev_id, data_type, response, modified_by):
    """Insert TaskNoteExtraValue; return new TaskNoteExtraValueId or 0."""
    # Prefer ExecuteSql — QuerySql INSERT/OUTPUT is often blocked in PyScript
    try:
        if response is None:
            model.ExecuteSql(
                "INSERT INTO dbo.TaskNoteExtraValue "
                "(KeywordExtraValueId, TaskNoteId, ModifiedBy, ModifiedDate, DataType, Response) "
                "VALUES (" + str(int(kev_id)) + "," + str(int(task_note_id)) + ","
                + str(int(modified_by)) + ",GETDATE()," + str(int(data_type)) + ",NULL)"
            )
        else:
            esc = _s(response).replace("'", "''")
            model.ExecuteSql(
                "INSERT INTO dbo.TaskNoteExtraValue "
                "(KeywordExtraValueId, TaskNoteId, ModifiedBy, ModifiedDate, DataType, Response) "
                "VALUES (" + str(int(kev_id)) + "," + str(int(task_note_id)) + ","
                + str(int(modified_by)) + ",GETDATE()," + str(int(data_type)) + ",N'" + esc + "')"
            )
        p2 = _dd()
        p2.AddValue('tnId', int(task_note_id))
        p2.AddValue('kevId', int(kev_id))
        rows = list(q.QuerySql("""
SELECT TOP 1 TaskNoteExtraValueId AS Id
FROM dbo.TaskNoteExtraValue
WHERE TaskNoteId = @tnId AND KeywordExtraValueId = @kevId
ORDER BY TaskNoteExtraValueId DESC
""", p2))
        if rows:
            return _i(rows[0].Id, 0)
    except:
        pass
    return 0


def _save_note_extra_answers(task_note_id, keyword_desc):
    """Persist KeywordExtraValue answers posted with the note form."""
    task_note_id = _i(task_note_id, 0)
    if task_note_id <= 0:
        return
    questions = _questions_for_keyword(keyword_desc)
    if not questions:
        return
    posted = _posted_kev_map()
    owner = _user_pid()
    if owner <= 0:
        owner = 1
    for qu in questions:
        dt = _i(qu.get('dt'), 0)
        qid = _i(qu.get('id'), 0)
        if qid <= 0 or dt <= KEV_INSTRUCTIONS:
            continue
        if dt == KEV_CHECKBOXES:
            tnev_id = _insert_task_note_extra_value(task_note_id, qid, dt, None, owner)
            if tnev_id <= 0:
                continue
            for opt in (qu.get('opts') or []):
                oid = _i(opt.get('id'), 0)
                if oid <= 0:
                    continue
                field = 'kev_c_' + str(qid) + '_' + str(oid)
                checked = _s(posted.get(field)) or _s(_form_val(field))
                resp = 'True' if checked in ('1', 'true', 'True', 'on', 'yes', 'Yes') else 'False'
                esc = resp.replace("'", "''")
                try:
                    model.ExecuteSql(
                        "INSERT INTO dbo.TaskNoteExtraValueOption "
                        "(TaskNoteExtraValueId, KeywordExtraValueOptionId, Response) "
                        "VALUES (" + str(tnev_id) + "," + str(oid) + ",N'" + esc + "')"
                    )
                except:
                    pass
            continue
        field = 'kev_' + str(qid)
        raw = _s(posted.get(field))
        if not raw:
            raw = _s(_form_val(field))
        if dt == KEV_YESNO:
            if raw.lower() in ('1', 'true', 'yes', 'on'):
                raw = 'True'
            else:
                raw = 'False'
        elif dt == KEV_DROPDOWN:
            if not raw:
                raw = None
        elif not raw:
            raw = None
        _insert_task_note_extra_value(task_note_id, qid, dt, raw, owner)


def _ev_date(people_id, field):
    """Return formatted date only when PeopleExtra has a real DateValue."""
    field = _s(field)
    if not field:
        return ''
    sql = """
SELECT TOP 1 pe.Type, pe.DateValue, pe.StrValue, pe.Data
FROM dbo.PeopleExtra pe
WHERE pe.PeopleId = @pid
  AND pe.Field = @field
"""
    p = _dd()
    p.AddValue('pid', people_id)
    p.AddValue('field', field)
    rows = list(q.QuerySql(sql, p))
    if not rows:
        return ''
    r = rows[0]
    if r.DateValue is not None and not _is_null(r.DateValue):
        return _fmt_date(r.DateValue)
    # Some churches store dates as Code/Text — only accept parseable date strings
    typ = _s(r.Type).lower()
    if typ in ('code', 'text'):
        raw = _s(r.StrValue) or _s(r.Data)
        if not raw:
            return ''
        if raw.lower().startswith('unknown type'):
            return ''
        try:
            from System import DateTime
            return DateTime.Parse(raw).ToString('M/d/yyyy')
        except:
            return ''
    return ''


def _ev_any(people_id, field):
    """True only when the Extra Value has a real affirmative value.

    Bit fields: model.ExtraValue returns 'False' as a string when unchecked — that
    must NOT count as flagged. Null / missing / empty / False / 0 = not flagged.
    """
    field = _s(field)
    if not field:
        return False
    sql = """
SELECT TOP 1
    pe.Type,
    pe.StrValue,
    pe.Data,
    pe.DateValue,
    pe.BitValue,
    pe.IntValue
FROM dbo.PeopleExtra pe
WHERE pe.PeopleId = @pid
  AND pe.Field = @field
"""
    p = _dd()
    p.AddValue('pid', people_id)
    p.AddValue('field', field)
    rows = list(q.QuerySql(sql, p))
    if not rows:
        return False
    r = rows[0]
    typ = _s(r.Type).lower()
    if typ == 'bit':
        try:
            if r.BitValue is None or _is_null(r.BitValue):
                return False
            return bool(r.BitValue) is True
        except:
            return False
    if typ == 'date':
        if r.DateValue is None or _is_null(r.DateValue):
            return False
        return True
    if typ == 'int':
        if r.IntValue is None or _is_null(r.IntValue):
            return False
        return _i(r.IntValue, 0) != 0
    if typ in ('code', 'text', ''):
        v = _s(r.StrValue) or _s(r.Data)
        if not v:
            return False
        if v.lower() in ('false', 'no', '0', 'n', 'none', 'null'):
            return False
        return True
    # Data / unknown — require a meaningful non-empty, non-false signal
    v = _s(model.ExtraValue(people_id, field))
    if not v:
        return False
    if v.lower() in ('false', 'no', '0', 'n', 'none', 'null', ';;false;;', ';false;'):
        return False
    # Bit-style dump from Data type often looks like ";;False;;"
    if 'false' in v.lower() and 'true' not in v.lower():
        return False
    return True


def _latest_bg(people_id, report_type_id):
    sql = """
SELECT TOP 1
    bg.ID AS BgId,
    bg.Created,
    bg.Updated,
    bg.StatusID,
    bg.ReportLink,
    bg.ApprovalStatus,
    bg.ErrorMessages,
    bg.ServiceCode,
    (SELECT COUNT(*) FROM dbo.BackgroundChecks x
     WHERE x.PeopleID = bg.PeopleID AND x.ReportTypeID = bg.ReportTypeID) AS RunCount
FROM dbo.BackgroundChecks bg
WHERE bg.PeopleID = @pid
  AND bg.ReportTypeID = @rtype
ORDER BY bg.Created DESC, bg.ID DESC
"""
    p = _dd()
    p.AddValue('pid', people_id)
    p.AddValue('rtype', report_type_id)
    rows = list(q.QuerySql(sql, p))
    if not rows:
        return None
    return rows[0]


def _status_label(status_id):
    sid = _i(status_id, -1)
    if sid == 0:
        return 'Error'
    if sid == 1:
        return 'Not Submitted'
    if sid == 2:
        return 'Submitted'
    if sid == 3:
        return 'Complete'
    if sid == 4:
        return 'Emailed'
    return 'Unknown'


def _parent_or_preferred_email(people_id, is_minor):
    """Return (email, recipient_people_id). For minors, prefer a parent adult.

    model.Email only queues people with a non-empty primary EmailAddress
    (EmailAddress2 alone is ignored by TouchPoint's emailer). Select recipients
    who actually have Address1 so we do not report success with a silent no-op.
    """
    if not is_minor:
        sql = """
SELECT TOP 1
    p.PeopleId AS RecipientId,
    p.EmailAddress AS Email
FROM dbo.People p
WHERE p.PeopleId = @pid
  AND NULLIF(p.EmailAddress, '') IS NOT NULL
  AND (ISNULL(p.SendEmailAddress1, 1) = 1 OR ISNULL(p.SendEmailAddress2, 0) = 1)
"""
        p = _dd()
        p.AddValue('pid', people_id)
        rows = list(q.QuerySql(sql, p))
        if rows and _s(rows[0].Email):
            return _s(rows[0].Email), _i(rows[0].RecipientId, people_id)
        return '', people_id
    # Minor: primary/secondary adult with primary EmailAddress
    sql = """
SELECT TOP 1
    a.PeopleId AS RecipientId,
    a.EmailAddress AS Email
FROM dbo.People child
JOIN dbo.People a ON a.FamilyId = child.FamilyId
WHERE child.PeopleId = @pid
  AND a.PeopleId <> child.PeopleId
  AND a.PositionInFamilyId IN (10, 20)
  AND ISNULL(a.IsDeceased, 0) = 0
  AND NULLIF(a.EmailAddress, '') IS NOT NULL
  AND (ISNULL(a.SendEmailAddress1, 1) = 1 OR ISNULL(a.SendEmailAddress2, 0) = 1)
ORDER BY a.PositionInFamilyId ASC
"""
    p = _dd()
    p.AddValue('pid', people_id)
    rows = list(q.QuerySql(sql, p))
    if rows and _s(rows[0].Email):
        return _s(rows[0].Email), _i(rows[0].RecipientId, people_id)
    # fallback: volunteer's own primary email
    return _parent_or_preferred_email(people_id, False)


def _prior_app(people_id, prior_orgid):
    oid = _i(prior_orgid, 0)
    if oid <= 0:
        return False
    # Member/Previous only (not Prospect)
    sql = """
SELECT TOP 1 om.PeopleId
FROM dbo.OrganizationMembers om
JOIN lookup.MemberType mt ON mt.Id = om.MemberTypeId
WHERE om.PeopleId = @pid
  AND om.OrganizationId = @oid
  AND (
        mt.Description = 'Member'
     OR mt.Description = 'Previous'
     OR mt.Code IN ('M','P')
  )
"""
    p = _dd()
    p.AddValue('pid', people_id)
    p.AddValue('oid', oid)
    rows = list(q.QuerySql(sql, p))
    return bool(rows)


def _load_prospects(orgid):
    sql = """
SELECT
    p.PeopleId,
    p.Name2 AS Name,
    p.Name AS PreferredName,
    p.Age,
    p.EmailAddress,
    p.EmailAddress2,
    p.FamilyId,
    om.EnrollmentDate AS ProspectSince,
    o.OrganizationName,
    o.OrganizationId
FROM dbo.OrganizationMembers om
JOIN dbo.People p ON p.PeopleId = om.PeopleId
JOIN dbo.Organizations o ON o.OrganizationId = om.OrganizationId
WHERE om.OrganizationId = @oid
  AND om.MemberTypeId = @prospect
  AND ISNULL(p.IsDeceased, 0) = 0
ORDER BY om.EnrollmentDate ASC, p.Name2 ASC
"""
    p = _dd()
    p.AddValue('oid', orgid)
    p.AddValue('prospect', MEMBER_TYPE_PROSPECT)
    return list(q.QuerySql(sql, p))


def _org_name(orgid):
    sql = 'SELECT TOP 1 OrganizationName FROM dbo.Organizations WHERE OrganizationId = @oid'
    p = _dd()
    p.AddValue('oid', orgid)
    rows = list(q.QuerySql(sql, p))
    if rows:
        return _s(rows[0].OrganizationName)
    return 'Involvement ' + str(orgid)


# ---------------------------------------------------------------------------
# Step model
# ---------------------------------------------------------------------------

def _step(key, label, complete, value='', state='empty', meta=None):
    return {
        'key': key,
        'label': label,
        'complete': complete,
        'value': value,
        'state': state,  # empty | complete | danger
        'meta': meta or {},
    }


def _build_steps(person, area_cfg, list_cfg, is_minor):
    pid = _i(person.PeopleId)
    steps = []
    stacked = []

    # Application Sent + Reviewed (stacked)
    ev_sent = _s(list_cfg.get('ev_app_sent'))
    ev_rev = _s(list_cfg.get('ev_app_reviewed'))
    sent_dt = _ev_date(pid, ev_sent)
    rev_dt = _ev_date(pid, ev_rev)
    stacked.append(_step('app_sent', 'Application Sent', bool(sent_dt), sent_dt,
                         'complete' if sent_dt else 'empty',
                         {'ev': ev_sent}))
    stacked.append(_step('app_reviewed', 'Application Reviewed', bool(rev_dt), rev_dt,
                         'complete' if rev_dt else 'empty',
                         {'ev': ev_rev}))
    steps.append({'type': 'stack', 'title': 'Application', 'children': stacked})

    if is_minor:
        # Interview + References (same keyword tiles as adult) + Handbook
        kw_i = _s(list_cfg.get('kw_interview'))
        ok, when = _has_keyword_note(pid, kw_i)
        steps.append({'type': 'single', 'step': _step('interview', 'Interview', ok, when,
                     'complete' if ok else 'empty', {'keyword': kw_i})})
        kw_r = _s(list_cfg.get('kw_references'))
        ok, when = _has_keyword_note(pid, kw_r)
        steps.append({'type': 'single', 'step': _step('references', 'References Checked', ok, when,
                     'complete' if ok else 'empty', {'keyword': kw_r})})
        _append_training_handbook_steps(steps, list_cfg, pid)
        return steps

    # Adult full track
    # Background Check (PMM)
    bg = _latest_bg(pid, REPORT_TYPE_PMM)
    bg_children = []
    if bg is None:
        bg_children.append(_step('bc_sent', 'Background Check Sent', False, '', 'empty'))
        bg_children.append(_step('bc_reviewed', 'Background Check Reviewed', False, '', 'empty'))
    else:
        sid = _i(bg.StatusID)
        sent_ok = sid in (STATUS_SUBMITTED, STATUS_COMPLETED, STATUS_EMAILED)
        status = _status_label(sid)
        link = _s(bg.ReportLink)
        val = status
        if sent_ok:
            when = _fmt_date(bg.Created)
            if when:
                val = status + ' · ' + when
        bg_children.append(_step('bc_sent', 'Background Check Sent', sent_ok, val,
                                 'complete' if sent_ok else 'empty',
                                 {'bgid': _i(bg.BgId), 'link': link, 'runcount': _i(bg.RunCount)}))
        appr = _s(bg.ApprovalStatus) or 'Pending'
        appr_l = appr.lower()
        bc_done = appr_l == 'approved'
        bc_state = 'complete' if bc_done else ('danger' if 'not approved' in appr_l or appr_l == 'denied' else 'empty')
        bg_children.append(_step('bc_reviewed', 'Background Check Reviewed', bc_done, appr, bc_state,
                                 {'bgid': _i(bg.BgId), 'approval': appr, 'link': link, 'runcount': _i(bg.RunCount)}))
    steps.append({'type': 'stack', 'title': 'Background Check', 'children': bg_children})

    # Video Training (MinistrySafe training ReportType 3)
    tr = _latest_bg(pid, REPORT_TYPE_MS_TRAINING)
    tr_children = []
    if tr is None:
        tr_children.append(_step('video_sent', 'Video Training Sent', False, '', 'empty'))
        tr_children.append(_step('video_done', 'Video Training Complete', False, '', 'empty'))
    else:
        sid = _i(tr.StatusID)
        sent_ok = sid in (STATUS_SUBMITTED, STATUS_COMPLETED, STATUS_EMAILED)
        status = _status_label(sid)
        tr_children.append(_step('video_sent', 'Video Training Sent', sent_ok, status,
                                 'complete' if sent_ok else 'empty',
                                 {'bgid': _i(tr.BgId), 'link': _s(tr.ReportLink)}))
        done = sid == STATUS_COMPLETED
        appr = _s(tr.ApprovalStatus)
        # Complete/passed: status Complete, optionally Approved
        if done and appr and appr.lower() == 'approved':
            val = 'Passed · Approved'
            done = True
        elif done:
            val = 'Complete'
        else:
            val = status
            done = False
        tr_children.append(_step('video_done', 'Video Training Complete', done, val,
                                 'complete' if done else 'empty',
                                 {'bgid': _i(tr.BgId), 'link': _s(tr.ReportLink)}))
    steps.append({'type': 'stack', 'title': 'Video Training', 'children': tr_children})

    # Interview / References / Shadowing
    for key, label, cfgkey in [
        ('interview', 'Interview', 'kw_interview'),
        ('references', 'References Checked', 'kw_references'),
        ('shadowing', 'Shadowing Complete', 'kw_shadowing'),
    ]:
        kw = _s(list_cfg.get(cfgkey))
        ok, when = _has_keyword_note(pid, kw)
        steps.append({'type': 'single', 'step': _step(key, label, ok, when,
                     'complete' if ok else 'empty', {'keyword': kw})})

    if list_cfg.get('has_fl_training'):
        kw = _s(list_cfg.get('kw_fl_training'))
        ok, when = _has_keyword_note(pid, kw)
        steps.append({'type': 'single', 'step': _step('fl_training', 'FL Diapering / Potty Training', ok, when,
                     'complete' if ok else 'empty', {'keyword': kw})})

    _append_training_handbook_steps(steps, list_cfg, pid)

    return steps


def _append_training_handbook_steps(steps, list_cfg, pid):
    """Handbook / training end steps.
    Faith Littles (has_fl_training): Handbook Signed only — diapering module covers training.
    Other lists: In Person Training + Handbook Signed stack (like Application).
    """
    ev_hb = _s(list_cfg.get('ev_handbook'))
    hb_dt = _ev_date(pid, ev_hb)
    if list_cfg.get('has_fl_training'):
        steps.append({'type': 'single', 'step': _step('handbook', 'Handbook signed', bool(hb_dt), hb_dt,
                     'complete' if hb_dt else 'empty', {'ev': ev_hb})})
        return
    train_children = []
    ev_tr = _s(list_cfg.get('ev_training'))
    tr_dt = _ev_date(pid, ev_tr)
    train_children.append(_step('training', 'In-person training', bool(tr_dt), tr_dt,
                                'complete' if tr_dt else 'empty', {'ev': ev_tr}))
    train_children.append(_step('handbook', 'Handbook signed', bool(hb_dt), hb_dt,
                                'complete' if hb_dt else 'empty', {'ev': ev_hb}))
    steps.append({'type': 'stack', 'title': 'Training / Handbook', 'children': train_children})


def _required_complete(steps):
    for block in steps:
        if block.get('type') == 'stack':
            for ch in block.get('children') or []:
                if not ch.get('complete'):
                    return False
        else:
            st = block.get('step') or {}
            if not st.get('complete'):
                return False
    return True


def _step_progress(steps):
    """Count completed / total leaf steps for the collapsed progress bar."""
    done = 0
    total = 0
    for block in steps:
        if block.get('type') == 'stack':
            for ch in block.get('children') or []:
                total += 1
                if ch.get('complete'):
                    done += 1
        else:
            st = block.get('step') or {}
            total += 1
            if st.get('complete'):
                done += 1
    return done, total


def _step_incomplete(steps, step_key):
    for block in steps:
        if block.get('type') == 'stack':
            for ch in block.get('children') or []:
                if ch.get('key') == step_key:
                    return not ch.get('complete')
        else:
            st = block.get('step') or {}
            if st.get('key') == step_key:
                return not st.get('complete')
    return False


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def _action_save_area_config(area_key, posted=None):
    """Save a single ministry area.
    posted: optional dict of field→value (from GET packed payload). When None, read POST/form.
    """
    if not _is_admin():
        return 'err_auth'
    area_key = _slug_key(area_key) or _s(area_key)
    if not area_key:
        _flash_detail_set('missing area_key')
        return 'err_generic'
    cfg = _load_config()
    areas = cfg.get('areas') or {}
    area = areas.get(area_key) or _empty_area_cfg(area_key)

    def has_field(name):
        if posted is not None:
            return name in posted
        try:
            if model.DataHas(name):
                return True
        except:
            pass
        try:
            from System.Web import HttpContext
            req = HttpContext.Current.Request
            for coll in (req.Form, req.QueryString):
                if coll is None or coll.AllKeys is None:
                    continue
                for k in coll.AllKeys:
                    if k == name:
                        return True
        except:
            pass
        return False

    def take(name, existing):
        if posted is not None:
            if name in posted:
                try:
                    return unicode(posted.get(name)).strip()
                except:
                    return _s(posted.get(name), '')
            return _s(existing, '')
        if not has_field(name):
            return _s(existing, '')
        # Read Form/QueryString/Data via _get — do not use Form-only paths
        return _posted_or_keep(name, existing)

    area['label'] = take('cfg_label', area.get('label'))
    roles_raw = take('cfg_roles', ','.join(area.get('roles') or []))
    roles = []
    for part in _s(roles_raw).split(','):
        r = _s(part)
        if r:
            roles.append(r)
    area['roles'] = roles
    area['view_only_role'] = take('cfg_view_only_role', area.get('view_only_role'))
    area['prior_app_orgid'] = _i(take('cfg_prior_app_orgid', area.get('prior_app_orgid')), _i(area.get('prior_app_orgid'), 0))
    area['cpp_violation_ev'] = take('cfg_cpp_violation_ev', area.get('cpp_violation_ev'))
    area['email_from_peopleid'] = _i(take('cfg_from_peopleid', area.get('email_from_peopleid')), _i(area.get('email_from_peopleid'), 0))
    if 'email_from_addr' in area:
        area['email_from_addr'] = ''
    if 'email_from_name' in area:
        area['email_from_name'] = ''

    lists = area.get('lists') or {}
    list_keys = _list_order(lists) if lists else []
    for lk in lists.keys():
        if lk not in list_keys:
            list_keys.append(lk)

    saw_list = False
    orgid_bits = []
    expected_orgids = {}
    for lk in list_keys:
        lc = _normalize_list_cfg(lists.get(lk) or _empty_list_cfg(lk), lk)
        for field, _lab in LIST_FIELD_DEFS:
            n = 'cfg_' + lk + '_' + field
            if has_field(n):
                saw_list = True
            if field == 'orgid':
                lc['orgid'] = _i(take(n, lc.get('orgid')), _i(lc.get('orgid'), 0))
            else:
                lc[field] = take(n, lc.get(field))
        lists[lk] = lc
        expected_orgids[lk] = _i(lc.get('orgid'), 0)
        orgid_bits.append(_s(lk) + '=' + str(expected_orgids[lk]))
    area['lists'] = lists
    areas[area_key] = area
    cfg['areas'] = areas

    got_area = has_field('cfg_label') or has_field('cfg_roles') or has_field('cfg_from_peopleid') or has_field('cfg_cpp_violation_ev')
    if not got_area and not saw_list:
        _flash_detail_set('no cfg fields received — ' + _request_diag())
        return 'err_generic'

    try:
        written = _save_config(cfg)
        if not written:
            _flash_detail_set('WriteContentText returned empty — ' + _request_diag())
            return 'err_generic'
    except Exception, ex:
        _flash_detail_set('write failed: ' + _s(ex)[:100])
        return 'err_generic'

    # Round-trip verify — proves Special Content actually persisted
    try:
        reloaded = _load_config()
        ra = ((reloaded.get('areas') or {}).get(area_key) or {})
        rlists = ra.get('lists') or {}
        mismatch = []
        for lk in expected_orgids.keys():
            got = _i((rlists.get(lk) or {}).get('orgid'), 0)
            if got != expected_orgids[lk]:
                mismatch.append(_s(lk) + ':' + str(expected_orgids[lk]) + '→' + str(got))
        if mismatch:
            _flash_detail_set('wrote but reload mismatch ' + ','.join(mismatch) + ' — ' + _request_diag())
            return 'err_generic'
    except Exception, ex:
        _flash_detail_set('reload check failed: ' + _s(ex)[:80])
        return 'err_generic'

    _flash_detail_set(area_key + ' orgids ' + (', '.join(orgid_bits) if orgid_bits else 'none') + ' | ' + _request_diag())
    return 'ok_config'


def _action_add_area():
    if not _is_admin():
        return 'err_auth'
    cfg = _load_config()
    areas = cfg.get('areas') or {}
    key = _slug_key(_form_val('new_area_key') or _form_val('new_area_label'))
    label = _form_val('new_area_label') or key
    if not key:
        return 'err_generic'
    if key in areas:
        return 'err_generic'
    area = _empty_area_cfg(label)
    roles_raw = _form_val('new_area_roles')
    roles = []
    for part in _s(roles_raw).split(','):
        r = _s(part)
        if r:
            roles.append(r)
    area['roles'] = roles
    areas[key] = area
    cfg['areas'] = areas
    try:
        _save_config(cfg)
    except:
        return 'err_generic'
    return 'ok_area'


def _action_add_list():
    if not _is_admin():
        return 'err_auth'
    cfg = _load_config()
    areas = cfg.get('areas') or {}
    ak = _slug_key(_form_val('area_key'))
    if not ak or ak not in areas:
        return 'err_generic'
    area = areas.get(ak) or {}
    lists = area.get('lists') or {}
    key = _slug_key(_form_val('new_list_key') or _form_val('new_list_label'))
    label = _form_val('new_list_label') or key
    if not key:
        return 'err_generic'
    if key in lists:
        return 'err_generic'
    lists[key] = _empty_list_cfg(label)
    area['lists'] = lists
    areas[ak] = area
    cfg['areas'] = areas
    try:
        _save_config(cfg)
    except:
        return 'err_generic'
    return 'ok_list'


def _action_set_ev_date(people_id, field, date_str):
    field = _s(field)
    date_str = _s(date_str)
    if not field or not date_str:
        return 'err_generic'
    try:
        from System import DateTime
        dt = DateTime.Parse(date_str)
        model.AddExtraValueDate(people_id, field, dt)
        return 'ok_ev'
    except:
        return 'err_generic'


def _looks_like_unlayer(s):
    t = _s(s).lstrip()
    if not t.startswith('{'):
        return False
    tl = t.lower()
    return ('"html"' in tl) or ('"rawhtml"' in tl) or ('"design"' in tl)


def _jstring(tok):
    if tok is None:
        return ''
    try:
        if tok.Type.ToString() == 'Null':
            return ''
    except:
        pass
    try:
        v = tok.Value
        if v is not None:
            return unicode(v)
    except:
        pass
    try:
        return unicode(tok)
    except:
        return ''


def _unlayer_html(body):
    """Extract renderable HTML from Unlayer JSON ({ design, rawHtml|html })."""
    s = _s(body).lstrip()
    if not s:
        return ''
    if not s.startswith('{'):
        return _s(body)
    # Preferred: Newtonsoft case-insensitive property walk
    try:
        from Newtonsoft.Json.Linq import JObject
        obj = JObject.Parse(s)
        found = {}
        for prop in obj.Properties():
            try:
                key = _s(prop.Name).lower()
            except:
                continue
            if key in ('rawhtml', 'html'):
                found[key] = _jstring(prop.Value).strip()
        if found.get('rawhtml'):
            return found['rawhtml']
        if found.get('html'):
            return found['html']
    except:
        pass
    # Regex fallback when IronPython/JSON binder fails
    try:
        import re
        for pat in (
            r'"rawHtml"\s*:\s*"((?:\\.|[^"\\])*)"',
            r'"html"\s*:\s*"((?:\\.|[^"\\])*)"',
        ):
            m = re.search(pat, s, re.IGNORECASE | re.DOTALL)
            if not m:
                continue
            raw = m.group(1)
            try:
                from Newtonsoft.Json import JsonConvert
                return _s(JsonConvert.DeserializeObject('"' + raw + '"'))
            except:
                try:
                    return raw.decode('unicode_escape')
                except:
                    return raw.replace('\\"', '"').replace('\\n', '\n').replace('\\/', '/')
    except:
        pass
    return ''


def _load_email_template(name):
    """Load Title + HTML body for an email template (Name or Title match).
    Returns (title, body). body is None when missing/unusable.
    """
    name = _s(name)
    if not name:
        return None, None
    sql = """
SELECT TOP 1 c.Name, c.Title, c.TypeID, c.Body
FROM dbo.Content c
WHERE (LTRIM(RTRIM(c.Name)) = @name OR LTRIM(RTRIM(ISNULL(c.Title, ''))) = @name)
  AND c.TypeID IN (0, 2, 7)
ORDER BY CASE WHEN LTRIM(RTRIM(c.Name)) = @name THEN 0 ELSE 1 END,
         CASE c.TypeID WHEN 7 THEN 0 WHEN 2 THEN 1 ELSE 2 END
"""
    p = _dd()
    p.AddValue('name', name)
    try:
        rows = list(q.QuerySql(sql, p))
    except:
        rows = []
    if not rows:
        # Fallback: model.Content looks up by Name across types
        try:
            body = _s(model.Content(name))
            if body:
                if _looks_like_unlayer(body):
                    parsed = _unlayer_html(body)
                    if parsed and not _looks_like_unlayer(parsed):
                        return name, parsed
                    return name, None
                return name, body
        except:
            pass
        return None, None
    row = rows[0]
    title = _s(row.Title) or _s(row.Name) or name
    try:
        body = unicode(row.Body).strip()
    except:
        body = _s(row.Body).strip()
    typeid = _i(row.TypeID, 0)
    if typeid == 7 or _looks_like_unlayer(body):
        parsed = _unlayer_html(body)
        if not parsed or _looks_like_unlayer(parsed):
            return title, None
        body = parsed
    if not body:
        return title, None
    return title, body


def _email_templates():
    """Email / Unlayer templates for Config dropdowns (TypeID 2, 7)."""
    sql = """
SELECT c.Name, c.Title, c.TypeID
FROM dbo.Content c
WHERE c.TypeID IN (2, 7)
ORDER BY ISNULL(NULLIF(LTRIM(RTRIM(c.Title)), ''), c.Name)
"""
    try:
        return list(q.QuerySql(sql))
    except:
        return []


def _template_select_html(input_name, selected):
    """Dropdown of email templates; value = Content.Name (stable)."""
    selected = _s(selected)
    templates = _email_templates()
    html = '<select name="' + _html(input_name) + '">'
    html += '<option value="">-- select email template --</option>'
    matched = False
    for t in templates:
        name = _s(t.Name)
        title = _s(t.Title) or name
        typeid = _i(t.TypeID, 0)
        if not name:
            continue
        sel = ''
        if name == selected or title == selected:
            sel = ' selected="selected"'
            matched = True
        kind = 'Unlayer' if typeid == 7 else 'Email'
        label = title
        if title != name:
            label = title + ' — ' + name
        label = label + ' (' + kind + ')'
        html += '<option value="' + _html(name) + '"' + sel + '>' + _html(label) + '</option>'
    # Keep a mistyped / deleted / HTML-only value visible so Save does not wipe it
    if selected and not matched:
        html += '<option value="' + _html(selected) + '" selected="selected">'
        html += _html(selected) + ' (current — not in Email/Unlayer list)</option>'
    html += '</select>'
    return html


def _replace_token(text, token, value):
    variants = [
        '{{{' + token + '}}}',
        '{{' + token + '}}',
        '{' + token + '}',
    ]
    out = _s(text)
    for v in variants:
        out = out.replace(v, _s(value))
    return out


def _action_send_application(cfg, area_key, list_key, people_id, confirm_resend):
    """Returns a FLASH code (ok_* / err_*)."""
    area_cfg, list_cfg = _list_cfg(cfg, area_key, list_key)
    ev_sent = _s(list_cfg.get('ev_app_sent'))
    already = _ev_date(people_id, ev_sent)
    if already and not confirm_resend:
        return 'err_confirm'
    sql = 'SELECT TOP 1 Age, Name, NickName, PreferredName FROM dbo.People WHERE PeopleId = @pid'
    p = _dd()
    p.AddValue('pid', people_id)
    rows = list(q.QuerySql(sql, p))
    age = _i(rows[0].Age, 99) if rows else 99
    first = ''
    if rows:
        first = _s(rows[0].PreferredName) or _s(rows[0].NickName) or (_s(rows[0].Name).split(' ')[0] if _s(rows[0].Name) else '')
    is_minor = age < 18
    url = _s(list_cfg.get('minor_reg_url') if is_minor else list_cfg.get('adult_reg_url'))
    template = _s(list_cfg.get('email_template'))
    if not template:
        _flash_detail_set('open Config for this list and pick an Application email template')
        return 'err_template_unset'
    to_email, recipient_pid = _parent_or_preferred_email(people_id, is_minor)
    if not to_email or recipient_pid <= 0:
        return 'err_no_to'
    from_pid = _i(area_cfg.get('email_from_peopleid'), 0)
    if from_pid <= 0:
        return 'err_no_from'
    from_addr, from_name = _from_person(from_pid)
    if not from_addr:
        return 'err_from_email'
    if not from_name:
        from_name = 'Staff'
    queued_by = _user_pid()
    if queued_by <= 0:
        return 'err_queue_user'
    title, body = _load_email_template(template)
    if title is None and body is None:
        _flash_detail_set('template "' + template + '"')
        return 'err_template_missing'
    if not body:
        _flash_detail_set('template "' + template + '"')
        return 'err_template_body'
    body = _replace_token(body, 'first', first)
    body = _replace_token(body, 'First', first)
    body = _replace_token(body, 'name', first)
    body = _replace_token(body, 'url', url)
    body = _replace_token(body, 'URL', url)
    body = _replace_token(body, 'applicationurl', url)
    body = _replace_token(body, 'ApplicationUrl', url)
    if url and url not in body:
        body = body + '<p><a href="' + url + '">Open application</a></p>'
    subject = title or 'Volunteer Application'
    query = 'peopleids=(' + str(int(recipient_pid)) + ')'
    try:
        model.Email(query, queued_by, from_addr, from_name, subject, body)
    except:
        return 'err_email'
    if ev_sent:
        try:
            from System import DateTime
            model.AddExtraValueDate(people_id, ev_sent, DateTime.Today)
        except:
            return 'err_ev'
    return 'ok_sent'


def _action_add_note(people_id, keyword_desc, note_text):
    """Create a person note. Empty keyword = progress note (does not complete step).
    Step completion is still detected only via the configured Complete keyword.
    When the keyword has KeywordExtraValue questions, answers are saved onto the note.
    Progress-note step also stored as Instructions 'VODPN:<label>' for reliable tile icons.
    """
    keyword_desc = _s(keyword_desc)
    note_text = _s(note_text)
    if not note_text:
        return 'err_generic'
    kids = None
    if keyword_desc:
        kid = _keyword_id(keyword_desc)
        if kid <= 0:
            _flash_detail_set('keyword "' + keyword_desc + '" not found')
            return 'err_generic'
        kids = [kid]
    owner = _user_pid()
    if owner <= 0:
        return 'err_queue_user'
    # Progress-note step label (from form) — used for tile icons even if EV write fails
    pn_step = _s(_form_val('pn_step'))
    if not pn_step:
        # Derive from posted kev dropdown using option id lookup
        try:
            cfg = _load_config()
            lookup = _pn_option_lookup(cfg)
            posted = _posted_kev_map()
            for k in posted.keys():
                ks = _s(k)
                if ks.startswith('kev_c_') or ks == 'kev_json':
                    continue
                if ks.startswith('kev_'):
                    val = _s(posted.get(k)).strip()
                    if val and val in lookup:
                        pn_step = _s(lookup.get(val))
                        break
                    if val and val.lower() in lookup:
                        pn_step = _s(lookup.get(val.lower()))
                        break
        except:
            pass
    instructions = ''
    pn_cfg = _progress_note_cfg()
    if pn_step and keyword_desc:
        pn_kw = _s(pn_cfg.get('keyword'))
        if pn_kw and _s(keyword_desc).strip().lower() == pn_kw.strip().lower():
            instructions = 'VODPN:' + pn_step
    try:
        tnid = model.CreateTaskNote(
            owner, people_id, None, None, True, instructions, note_text, None, kids, False
        )
        if _i(tnid, 0) > 0 and keyword_desc:
            try:
                _save_note_extra_answers(tnid, keyword_desc)
            except:
                pass
        return 'ok_note'
    except:
        return 'err_generic'


def _action_set_approval(bg_id, approval):
    bg_id = _i(bg_id, 0)
    approval = _s(approval)
    if bg_id <= 0 or not approval:
        return 'err_generic'
    allowed = ['Pending', 'Approved', 'Not Approved']
    if approval not in allowed:
        return 'err_generic'
    sql = (
        "UPDATE dbo.BackgroundChecks SET ApprovalStatus = '" + approval
        + "', Updated = GETDATE() WHERE ID = " + str(bg_id)
    )
    try:
        model.ExecuteSql(sql)
        return 'ok_approval'
    except:
        return 'err_generic'


def _action_move_member(orgid, people_id):
    if not _is_admin():
        return 'err_auth'
    try:
        model.SetMemberType(people_id, orgid, 'Member')
        return 'ok_member'
    except:
        return 'err_generic'


# ---------------------------------------------------------------------------
# CSS / UI
# ---------------------------------------------------------------------------

def _styles():
    bp = BRAND['black-pearl']
    dr = BRAND['downriver']
    az = BRAND['azure']
    hk = BRAND['hawkes']
    ln = BRAND['linen']
    fo = BRAND['forest']
    vm = BRAND['vermillion']
    css = '''
<style>
.vod-root { max-width: 100%; margin: 0 auto; padding: 16px 20px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: ''' + bp + '''; background: #f5f5f5; box-sizing: border-box; }
.vod-header { background: ''' + bp + '''; color: #fff; padding: 20px 28px; border-radius: 12px; margin-bottom: 14px; box-shadow: 0 4px 15px rgba(0,20,41,.35); text-align: center; }
.vod-header h1 { margin: 0; font-size: 26px; font-weight: 700; color: #fff; }
.vod-header .sub { margin-top: 6px; font-size: 13px; opacity: .9; }
.vod-tabs { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-bottom: 14px; }
.vod-tab { display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; border-radius: 999px; background: #fff; border: 1px solid #e2e8f0; color: ''' + dr + '''; text-decoration: none; font-weight: 600; font-size: 13px; }
.vod-tab .fa-home { font-size: 14px; }
.vod-tab:hover { border-color: ''' + az + '''; color: ''' + az + '''; text-decoration: none; }
.vod-tab.active { background: ''' + dr + '''; color: #fff; border-color: ''' + dr + '''; }
.vod-panel { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 16px; box-shadow: 0 1px 4px rgba(0,0,0,.04); margin-bottom: 14px; }
.vod-toolbar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 10px; }
.vod-toolbar label { font-size: 12px; font-weight: 600; color: #64748b; margin: 0 4px 0 0; }
.vod-toolbar select, .vod-toolbar input[type=text], .vod-toolbar input[type=date] { border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 8px; font-size: 13px; }
.vod-msg { background: ''' + hk + '''; border: 1px solid ''' + az + '''; color: ''' + dr + '''; padding: 10px 12px; border-radius: 8px; margin-bottom: 12px; }
.vod-card { border: 1px solid #e2e8f0; border-radius: 10px; margin-bottom: 10px; background: #fff; overflow: hidden; }
.vod-card.flag-red { border-color: ''' + vm + '''; background: #fff5f5; }
.vod-card-h { display: flex; align-items: center; gap: 10px; padding: 12px 14px; cursor: pointer; flex-wrap: wrap; }
.vod-caret { width: 18px; color: #64748b; font-weight: 700; }
.vod-name { font-weight: 700; font-size: 15px; color: ''' + dr + '''; text-decoration: none; }
.vod-name:hover { color: ''' + az + '''; }
.vod-meta { font-size: 12px; color: #64748b; margin-left: auto; }
.vod-pills { display: flex; flex-wrap: wrap; gap: 6px; }
.vod-progress-wrap {
  display: flex; align-items: center; gap: 8px;
  flex: 0 1 160px; min-width: 110px; max-width: 200px;
}
.vod-progress {
  flex: 1; height: 8px; background: #e2e8f0; border-radius: 999px; overflow: hidden;
}
.vod-progress > i {
  display: block; height: 100%; width: 0;
  background: ''' + fo + '''; border-radius: 999px;
}
.vod-progress.is-ready > i { background: ''' + fo + '''; }
.vod-progress.is-partial > i { background: ''' + az + '''; }
.vod-progress.is-empty > i { background: #cbd5e1; width: 0 !important; }
.vod-progress-lbl { font-size: 11px; font-weight: 700; color: #64748b; white-space: nowrap; }
.vod-pill { display: inline-block; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; background: ''' + ln + '''; color: ''' + dr + '''; }
.vod-pill.minor { background: ''' + hk + '''; }
.vod-pill.prior { background: #e2e8f0; }
.vod-pill.ready { background: ''' + fo + '''; color: #fff; }
.vod-pill.danger { background: ''' + vm + '''; color: #fff; }
.vod-body { display: none; padding: 12px 14px 14px 14px; border-top: 1px solid #f1f5f9; }
.vod-card.open .vod-body { display: block; }
.vod-card.open .vod-caret:before { content: '\\25BC'; }
.vod-card:not(.open) .vod-caret:before { content: '\\25B6'; }
.vod-steps-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  align-items: stretch;
  padding-bottom: 4px;
}
.vod-stack, .vod-step-col {
  margin: 0;
  min-width: 0;
  max-width: none;
  min-height: 200px;
  height: 100%;
  padding: 10px 10px 12px;
  background: #f8fafc;
  border-radius: 8px;
  border: 2px solid #e2e8f0;
  box-sizing: border-box;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  overflow: visible;
  position: relative;
}
.vod-pn-icon {
  position: absolute;
  top: 6px;
  right: 6px;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 2px;
  min-width: 22px;
  height: 22px;
  padding: 0 5px;
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  background: #fff;
  color: ''' + az + ''';
  cursor: pointer;
  font-size: 12px;
  line-height: 1;
  box-shadow: 0 1px 2px rgba(0,0,0,.06);
}
.vod-pn-icon:hover { background: ''' + az + '''; color: #fff; border-color: ''' + az + '''; }
.vod-pn-icon-inline {
  position: static;
  margin-left: 6px;
  vertical-align: middle;
}
.vod-pn-count {
  font-size: 10px;
  font-weight: 700;
  font-style: normal;
}
.vod-pn-mark {
  font-size: 9px;
  font-weight: 800;
  letter-spacing: .02em;
  font-style: normal;
}
.vod-pn-icon .fa { margin-right: 1px; }
.vod-pn-view-list { margin: 0; padding: 0; list-style: none; }
.vod-pn-view-item {
  border-top: 1px solid #e2e8f0;
  padding: 10px 0;
}
.vod-pn-view-item:first-child { border-top: none; padding-top: 0; }
.vod-pn-view-when { font-size: 11px; font-weight: 700; color: #64748b; margin-bottom: 4px; }
.vod-pn-view-text { font-size: 13px; color: ''' + bp + '''; white-space: pre-wrap; line-height: 1.4; }
.vod-stack.done, .vod-step-col.done {
  border-color: ''' + fo + ''';
  background: #f0faf5;
  box-shadow: 0 0 0 1px ''' + fo + ''';
}
.vod-stack.done::before,
.vod-step-col.done::before {
  content: '\\2713';
  position: absolute;
  top: 6px;
  left: 6px;
  z-index: 2;
  width: 22px;
  height: 22px;
  border-radius: 999px;
  background: ''' + fo + ''';
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  line-height: 22px;
  text-align: center;
  box-shadow: 0 1px 2px rgba(0,0,0,.08);
}
.vod-stack.danger, .vod-step-col.danger {
  border-color: ''' + vm + ''';
  background: #fff5f5;
}
.vod-stack h4, .vod-step-col .vod-col-title {
  margin: 0 0 10px 0;
  font-size: 11px;
  color: ''' + az + ''';
  text-transform: uppercase;
  letter-spacing: .04em;
  font-weight: 700;
  text-align: center;
  width: 100%;
}
.vod-stack.done h4, .vod-step-col.done .vod-col-title {
  color: ''' + dr + ''';
}
.vod-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 6px 0;
  border-bottom: 1px solid #eef2f7;
  width: 100%;
}
.vod-step:last-child { border-bottom: none; }
.vod-step-col > .vod-step { border-bottom: none; padding: 0; width: 100%; }
.vod-step-head {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
}
.vod-circle {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: 2px solid #cbd5e1;
  background: #f1f5f9;
  flex-shrink: 0;
}
.vod-circle.ok { background: ''' + fo + '''; border-color: ''' + fo + '''; box-shadow: inset 0 0 0 3px #fff; }
.vod-circle.bad { background: ''' + vm + '''; border-color: ''' + vm + '''; }
.vod-step-main { width: 100%; }
.vod-step-label { font-weight: 600; font-size: 12px; line-height: 1.3; text-align: center; }
.vod-step-value {
  font-size: 11px;
  font-style: italic;
  color: #64748b;
  margin: 0;
  word-break: normal;
  overflow-wrap: anywhere;
  text-align: center;
  max-width: 100%;
}
.vod-step-actions {
  margin: 6px 0 0 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  justify-content: center;
  width: 100%;
}
.vod-links {
  margin-top: auto;
  padding-top: 8px;
  border-top: 1px solid #e2e8f0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  font-size: 11px;
  justify-content: center;
  width: 100%;
}
.vod-link { color: ''' + az + '''; text-decoration: none; font-weight: 600; background: none; border: none; padding: 0; cursor: pointer; font-size: 11px; }
.vod-link:hover { text-decoration: underline; }
.vod-link-muted { color: #64748b; }
.vod-note-input {
  width: 100%;
  max-width: 180px;
  box-sizing: border-box;
  padding: 5px 7px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 11px;
  text-align: center;
}
.vod-modal-backdrop {
  display: none;
  position: fixed;
  z-index: 10000;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  background: rgba(0, 20, 41, 0.45);
  align-items: center;
  justify-content: center;
  padding: 16px;
  box-sizing: border-box;
}
.vod-modal-backdrop.open { display: flex; }
.vod-modal {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0,0,0,.18);
  width: 100%;
  max-width: 520px;
  max-height: 90vh;
  overflow-y: auto;
  padding: 18px 20px 16px;
  color: ''' + bp + ''';
  text-align: left;
}
.vod-modal h3 {
  margin: 0 0 4px 0;
  font-size: 16px;
  font-weight: 700;
  color: ''' + dr + ''';
}
.vod-modal .vod-modal-sub {
  margin: 0 0 14px 0;
  font-size: 12px;
  color: #64748b;
}
.vod-modal label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  margin: 0 0 4px 0;
}
.vod-modal select,
.vod-modal textarea,
.vod-modal input[type=text],
.vod-modal input[type=date] {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 13px;
  margin-bottom: 12px;
  font-family: inherit;
}
.vod-modal textarea { min-height: 110px; resize: vertical; }
.vod-kev-box {
  display: none;
  margin: 0 0 12px 0;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}
.vod-kev-box.has-qs { display: block; }
.vod-kev-title {
  font-size: 11px; font-weight: 700; color: #64748b;
  text-transform: uppercase; letter-spacing: .03em;
  margin: 0 0 8px 0;
}
.vod-kev-q { margin: 0 0 10px 0; }
.vod-kev-q:last-child { margin-bottom: 0; }
.vod-kev-hdr {
  font-size: 15px; font-weight: 700; color: ''' + dr + ''';
  margin: 4px 0 6px 0;
}
.vod-kev-instr {
  font-size: 12px; color: #475569; margin: 0 0 8px 0; line-height: 1.4;
}
.vod-kev-check {
  display: flex; align-items: flex-start; gap: 8px;
  margin: 4px 0; font-size: 13px; color: ''' + bp + ''';
}
.vod-kev-check input { margin-top: 2px; }
.vod-kev-check label { font-weight: 500; color: ''' + bp + '''; margin: 0; }
.vod-modal-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 4px;
}
.vod-btn { display: inline-block; border: none; border-radius: 6px; padding: 5px 8px; font-size: 11px; font-weight: 700; cursor: pointer; text-decoration: none; }
.vod-btn-primary { background: ''' + az + '''; color: #fff; }
.vod-btn-success { background: ''' + fo + '''; color: #fff; }
.vod-btn-danger { background: ''' + vm + '''; color: #fff; }
.vod-btn-muted { background: #e2e8f0; color: ''' + bp + '''; }
.vod-btn:disabled { opacity: .55; cursor: not-allowed; }
.vod-config details { border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 10px; padding: 8px 12px; background: #fff; }
.vod-config summary {
  font-weight: 700; color: ''' + dr + '''; cursor: pointer;
  list-style: none; display: flex; align-items: center; gap: 8px;
}
.vod-config summary::-webkit-details-marker { display: none; }
.vod-config summary::marker { content: ''; }
.vod-config-area > summary .vod-area-caret {
  display: inline-block; width: 14px; text-align: center;
  transition: transform .15s ease; color: ''' + az + ''';
}
.vod-config-area[open] > summary .vod-area-caret { transform: rotate(90deg); }
.vod-config .grid { display: grid; grid-template-columns: 180px 1fr; gap: 8px; margin-top: 10px; align-items: center; }
.vod-config label { font-size: 12px; color: #64748b; }
.vod-config input, .vod-config select { width: 100%; padding: 6px 8px; border: 1px solid #cbd5e1; border-radius: 6px; }
.vod-config-add-list {
  display: flex; justify-content: center; margin-top: 12px; padding-top: 8px;
  border-top: 1px dashed #e2e8f0;
}
.vod-icon-btn {
  width: 36px; height: 36px; border-radius: 999px; border: 1px solid #cbd5e1;
  background: #f8fafc; color: ''' + dr + '''; font-size: 20px; font-weight: 700;
  line-height: 1; cursor: pointer; display: inline-flex; align-items: center; justify-content: center;
}
.vod-icon-btn:hover { background: ''' + az + '''; color: #fff; border-color: ''' + az + '''; }
.vod-add-area {
  margin-top: 16px; padding: 14px; border: 1px dashed #cbd5e1; border-radius: 10px; background: #f8fafc;
}
.vod-add-area h3 { margin: 0 0 10px 0; font-size: 14px; color: ''' + dr + '''; }
.vod-add-area .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.vod-add-area input { flex: 1; min-width: 140px; padding: 6px 8px; border: 1px solid #cbd5e1; border-radius: 6px; }
.vod-config-key { font-size: 11px; color: #94a3b8; font-weight: 500; margin-left: 8px; }
.vod-home-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
}
.vod-home-tile {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px 18px;
  box-shadow: 0 1px 4px rgba(0,0,0,.04);
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 180px;
}
.vod-home-tile.unconfigured { opacity: .72; border-style: dashed; }
.vod-home-tile h3 { margin: 0; font-size: 16px; color: ''' + dr + '''; font-weight: 700; }
.vod-home-tile .vod-home-sub { font-size: 12px; color: #64748b; margin-top: -6px; }
.vod-home-metrics { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.vod-home-metric {
  background: #f8fafc;
  border-radius: 8px;
  padding: 10px 12px;
  text-align: center;
}
.vod-home-metric .n { display: block; font-size: 28px; font-weight: 700; color: ''' + bp + '''; line-height: 1.1; }
.vod-home-metric .l { display: block; font-size: 11px; font-weight: 600; color: #64748b; text-transform: uppercase; letter-spacing: .03em; margin-top: 4px; }
.vod-home-metric.ready .n { color: ''' + fo + '''; }
.vod-home-metric.flag .n { color: ''' + vm + '''; }
.vod-home-metric.muted .n { color: #94a3b8; font-size: 22px; }
.vod-home-lists { border-top: 1px solid #f1f5f9; padding-top: 10px; display: flex; flex-direction: column; gap: 6px; }
.vod-home-list-row {
  display: flex; justify-content: space-between; align-items: center;
  font-size: 13px; color: ''' + dr + '''; text-decoration: none;
  padding: 4px 0;
}
.vod-home-list-row:hover { color: ''' + az + '''; text-decoration: none; }
.vod-home-list-row .counts { color: #64748b; font-size: 12px; font-weight: 600; }
.vod-home-cta { margin-top: auto; }
.vod-empty { text-align: center; color: #64748b; padding: 28px 12px; }
.vod-readonly .vod-step-actions { display: none !important; }
@media (max-width: 1100px) {
  .vod-steps-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  .vod-steps-row { grid-template-columns: 1fr; }
}
</style>
'''
    return css


def _js(cfg=None):
    # Inject script path + keyword extra-question map for the Add note modal.
    if cfg is None:
        try:
            cfg = _load_config()
        except:
            cfg = {}
    pn = _progress_note_cfg(cfg)
    kev_json = '{}'
    try:
        kev_json = _py_to_json_walk(_keyword_extra_questions_map(), None)
    except:
        kev_json = '{}'
    return '<script>var VOD_SCRIPT_PATH=' + _js_str(SCRIPT_PATH) + \
           ';var VOD_KEV_BY_KW=' + kev_json + \
           ';var VOD_PN_KW=' + _js_str(pn.get('keyword')) + \
           ';var VOD_PN_EV_NAME=' + _js_str(pn.get('ev_question')) + \
           ';var VOD_PN_ALLOWED=null;var VOD_PN_PRESELECT="";</script>' + \
r'''<script>
function vodToggle(id) {
  var el = document.getElementById(id);
  if (!el) return;
  if (el.className.indexOf(' open') >= 0) el.className = el.className.replace(' open', '');
  else el.className = el.className + ' open';
}
function vodConfirmResend(formId) {
  if (confirm('This application has already been sent. Please confirm that you want to re-send the application')) {
    var f = document.getElementById(formId);
    if (!f) return false;
    var inp = f.querySelector('input[name=confirm_resend]');
    if (inp) inp.value = '1';
    f.submit();
  }
  return false;
}
function vodEsc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
function vodFilterKevOpts(q) {
  var opts = q.opts || [];
  if (!window.VOD_PN_ALLOWED || !VOD_PN_ALLOWED.length) return opts;
  var f = document.getElementById('vod-note-form');
  var kw = (f && f.keyword) ? f.keyword.value : '';
  if (kw !== VOD_PN_KW || (q.name || '') !== VOD_PN_EV_NAME) return opts;
  var allow = {};
  var i;
  for (i = 0; i < VOD_PN_ALLOWED.length; i++) allow[VOD_PN_ALLOWED[i]] = true;
  var out = [];
  for (i = 0; i < opts.length; i++) {
    if (allow[opts[i].name]) out.push(opts[i]);
  }
  return out;
}
function vodApplyPnPreselect() {
  if (!window.VOD_PN_PRESELECT) return;
  var f = document.getElementById('vod-note-form');
  if (!f || !f.keyword || f.keyword.value !== VOD_PN_KW) return;
  var list = (window.VOD_KEV_BY_KW && VOD_KEV_BY_KW[VOD_PN_KW]) ? VOD_KEV_BY_KW[VOD_PN_KW] : [];
  var i, j, q, opts, opt, el;
  for (i = 0; i < list.length; i++) {
    q = list[i];
    if ((q.name || '') !== VOD_PN_EV_NAME || q.dt !== 5) continue;
    opts = vodFilterKevOpts(q);
    for (j = 0; j < opts.length; j++) {
      opt = opts[j];
      if (opt.name === VOD_PN_PRESELECT) {
        el = document.getElementById('kev_' + q.id);
        if (el) el.value = String(opt.id);
        return;
      }
    }
  }
}
function vodRenderKevQuestions() {
  var box = document.getElementById('vod-note-questions');
  if (!box) return;
  box.innerHTML = '';
  var f = document.getElementById('vod-note-form');
  var kw = (f && f.keyword) ? f.keyword.value : '';
  var list = (window.VOD_KEV_BY_KW && VOD_KEV_BY_KW[kw]) ? VOD_KEV_BY_KW[kw] : [];
  if (!list || !list.length) {
    box.className = 'vod-kev-box';
    return;
  }
  box.className = 'vod-kev-box has-qs';
  var html = '<div class="vod-kev-title">Related questions</div>';
  var i, q, j, opt, name, fid, opts;
  for (i = 0; i < list.length; i++) {
    q = list[i];
    name = vodEsc(q.name || '');
    fid = 'kev_' + q.id;
    if (q.dt === 1) {
      html += '<div class="vod-kev-q"><div class="vod-kev-hdr">' + name + '</div></div>';
      continue;
    }
    if (q.dt === 2) {
      html += '<div class="vod-kev-q"><div class="vod-kev-instr">' + name + '</div></div>';
      continue;
    }
    html += '<div class="vod-kev-q">';
    if (q.dt > 2) html += '<label for="' + fid + '">' + name + '</label>';
    if (q.dt === 3) {
      html += '<input type="text" id="' + fid + '" name="' + fid + '" />';
    } else if (q.dt === 4) {
      html += '<textarea id="' + fid + '" name="' + fid + '" rows="3"></textarea>';
    } else if (q.dt === 5) {
      opts = vodFilterKevOpts(q);
      html += '<select id="' + fid + '" name="' + fid + '"><option value="">—</option>';
      for (j = 0; j < opts.length; j++) {
        opt = opts[j];
        html += '<option value="' + vodEsc(opt.id) + '">' + vodEsc(opt.name) + '</option>';
      }
      html += '</select>';
    } else if (q.dt === 6) {
      html += '<select id="' + fid + '" name="' + fid + '">';
      html += '<option value="False">No</option><option value="True">Yes</option></select>';
    } else if (q.dt === 7) {
      for (j = 0; j < (q.opts || []).length; j++) {
        opt = q.opts[j];
        fid = 'kev_c_' + q.id + '_' + opt.id;
        html += '<div class="vod-kev-check">';
        html += '<input type="checkbox" id="' + fid + '" name="' + fid + '" value="1" />';
        html += '<label for="' + fid + '">' + vodEsc(opt.name) + '</label></div>';
      }
    } else if (q.dt === 8) {
      html += '<input type="date" id="' + fid + '" name="' + fid + '" />';
    }
    html += '</div>';
  }
  box.innerHTML = html;
  vodApplyPnPreselect();
}
function vodClosePnView(ev) {
  if (ev && ev.type === 'click' && ev.target && ev.currentTarget && ev.target !== ev.currentTarget) return;
  var m = document.getElementById('vod-pn-view-modal');
  if (!m) return false;
  m.className = (m.className || '').replace(' open', '').replace('open', '');
  return false;
}
function vodOpenPnNotes(btn, ev) {
  if (ev) {
    try { ev.stopPropagation(); ev.preventDefault(); } catch (e) {}
  }
  var m = document.getElementById('vod-pn-view-modal');
  if (!m || !btn) return false;
  var title = document.getElementById('vod-pn-view-title');
  var sub = document.getElementById('vod-pn-view-sub');
  var body = document.getElementById('vod-pn-view-body');
  var notes = [];
  try { notes = JSON.parse(btn.getAttribute('data-notes') || '[]'); } catch (e) { notes = []; }
  var label = btn.getAttribute('data-label') || 'Progress Note';
  if (title) title.textContent = 'Progress Note';
  if (sub) sub.textContent = label;
  if (body) {
    if (!notes.length) {
      body.innerHTML = '<p class="vod-modal-sub">No notes.</p>';
    } else {
      var html = '<ul class="vod-pn-view-list">';
      var i, n;
      for (i = 0; i < notes.length; i++) {
        n = notes[i] || {};
        html += '<li class="vod-pn-view-item">';
        html += '<div class="vod-pn-view-when">' + vodEsc(n.when || '') + (n.option ? ' · ' + vodEsc(n.option) : '') + '</div>';
        html += '<div class="vod-pn-view-text">' + vodEsc(n.text || '') + '</div>';
        html += '</li>';
      }
      html += '</ul>';
      body.innerHTML = html;
    }
  }
  if ((' ' + m.className + ' ').indexOf(' open ') < 0) {
    m.className = (m.className ? m.className + ' ' : '') + 'open';
  }
  return false;
}
function vodScrollOpenCard() {
  try {
    var m = (window.location.search || '').match(/[?&]open=(\d+)/);
    if (!m) return;
    var el = document.getElementById('vod_card_' + m[1]);
    if (el) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  } catch (e) {}
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', vodScrollOpenCard);
} else {
  vodScrollOpenCard();
}
function vodPrepareConfigSave() {
  return true;
}
function vodSaveArea(form) {
  // Pack area fields into one base64url JSON blob and GET-save (same WAF-safe pattern as do=sapp).
  if (!form) return false;
  var payload = {};
  var els = form.querySelectorAll('input[name], select[name], textarea[name]');
  var i;
  for (i = 0; i < els.length; i++) {
    var el = els[i];
    var n = el.name;
    if (!n || n === 'do' || n === 'p' || n === 'action') continue;
    if (el.type === 'checkbox' || el.type === 'radio') {
      if (el.checked) payload[n] = el.value;
      continue;
    }
    payload[n] = el.value;
  }
  var areaKey = payload.area_key || '';
  if (!areaKey) {
    alert('Missing area_key');
    return false;
  }
  var b64;
  try {
    b64 = btoa(unescape(encodeURIComponent(JSON.stringify(payload))));
    b64 = b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
  } catch (e) {
    alert('Could not pack config: ' + e);
    return false;
  }
  var url = VOD_SCRIPT_PATH + '?do=scfg&area_key=' + encodeURIComponent(areaKey) + '&p=' + encodeURIComponent(b64);
  window.location.replace(url);
  return false;
}
function vodAddList(areaKey) {
  var key = prompt('List key (letters/numbers/underscore only), e.g. littles:');
  if (key === null) return false;
  key = (key || '').replace(/[^a-zA-Z0-9_]/g, '').toLowerCase();
  if (!key) { alert('Enter a valid list key.'); return false; }
  var label = prompt('List display name:', key);
  if (label === null) return false;
  var f = document.getElementById('vod-add-list-form');
  if (!f) return false;
  f.area_key.value = areaKey;
  f.new_list_key.value = key;
  f.new_list_label.value = label || key;
  f.submit();
  return false;
}
function vodPackKevAnswers() {
  var f = document.getElementById('vod-note-form');
  if (!f) return true;
  var payload = {};
  var els = f.querySelectorAll('input[name^="kev_"], select[name^="kev_"], textarea[name^="kev_"]');
  var i, el, n;
  for (i = 0; i < els.length; i++) {
    el = els[i];
    n = el.name;
    if (!n || n === 'kev_json') continue;
    if (el.type === 'checkbox' || el.type === 'radio') {
      if (el.checked) payload[n] = el.value || '1';
      continue;
    }
    payload[n] = el.value;
  }
  var h = f.kev_json;
  if (!h) {
    h = document.createElement('input');
    h.type = 'hidden';
    h.name = 'kev_json';
    h.id = 'vod-kev-json';
    f.appendChild(h);
  }
  try { h.value = JSON.stringify(payload); } catch (e) { h.value = '{}'; }
  // Capture selected Progress Note step label for tile icons
  var pnStep = '';
  var sels = f.querySelectorAll('#vod-note-questions select');
  for (i = 0; i < sels.length; i++) {
    el = sels[i];
    if (el.selectedIndex > 0 && el.options[el.selectedIndex]) {
      pnStep = (el.options[el.selectedIndex].text || '').replace(/^\s+|\s+$/g, '');
      if (pnStep && pnStep !== '—') break;
    }
  }
  if (!pnStep && window.VOD_PN_PRESELECT) pnStep = VOD_PN_PRESELECT;
  if (f.pn_step) f.pn_step.value = pnStep || '';
  return true;
}
function vodCloseNote(ev) {
  if (ev && ev.type === 'click' && ev.target && ev.currentTarget && ev.target !== ev.currentTarget) return;
  var m = document.getElementById('vod-note-modal');
  if (!m) return false;
  m.className = (m.className || '').replace(' open', '').replace('open', '');
  return false;
}
function vodOpenNote(pid, area, list, stepLabel, personName, defaultKw, options, pnOption, allowedOpts) {
  var m = document.getElementById('vod-note-modal');
  if (!m) {
    alert('Note popup is missing. Re-paste the Volunteer Onboarding script.');
    return false;
  }
  var f = document.getElementById('vod-note-form');
  if (!f) return false;
  f.people_id.value = pid;
  f.area.value = area || '';
  f.list.value = list || '';
  f.note_text.value = '';
  if (f.kev_json) f.kev_json.value = '';
  if (f.pn_step) f.pn_step.value = '';
  var title = document.getElementById('vod-note-title');
  var sub = document.getElementById('vod-note-sub');
  if (title) title.textContent = 'Add note — ' + (stepLabel || 'Step');
  if (sub) sub.textContent = personName || '';
  window.VOD_PN_PRESELECT = pnOption || '';
  window.VOD_PN_ALLOWED = allowedOpts || null;
  var sel = f.keyword;
  while (sel.options.length) sel.remove(0);
  options = options || [];
  var i, opt, val, lab;
  for (i = 0; i < options.length; i++) {
    val = options[i][0];
    lab = options[i][1];
    opt = document.createElement('option');
    opt.value = val;
    opt.textContent = lab;
    if (val === defaultKw) opt.selected = true;
    sel.appendChild(opt);
  }
  sel.onchange = vodRenderKevQuestions;
  f.onsubmit = vodPackKevAnswers;
  vodRenderKevQuestions();
  if ((' ' + m.className + ' ').indexOf(' open ') < 0) {
    m.className = (m.className ? m.className + ' ' : '') + 'open';
  }
  try { f.note_text.focus(); } catch (e) {}
  return false;
}
function vodOpenNoteBtn(btn) {
  if (!btn) return false;
  var options = [];
  var allowed = null;
  try {
    options = JSON.parse(btn.getAttribute('data-options') || '[]');
  } catch (e) {
    options = [];
  }
  try {
    allowed = JSON.parse(btn.getAttribute('data-allowed') || 'null');
  } catch (e) {
    allowed = null;
  }
  return vodOpenNote(
    parseInt(btn.getAttribute('data-pid'), 10) || 0,
    btn.getAttribute('data-area') || '',
    btn.getAttribute('data-list') || '',
    btn.getAttribute('data-step') || '',
    btn.getAttribute('data-person') || '',
    btn.getAttribute('data-default') || '',
    options,
    btn.getAttribute('data-pn-option') || '',
    allowed
  );
}
document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape' || e.keyCode === 27) {
    vodCloseNote();
    vodClosePnView();
  }
});
</script>
'''


def _note_modal_html():
    """Shared note popup used by interview / references / shadowing / FL training."""
    html = '<div id="vod-note-modal" class="vod-modal-backdrop" onclick="return vodCloseNote(event)">'
    html += '<div class="vod-modal" role="dialog" aria-modal="true" aria-labelledby="vod-note-title" onclick="event.stopPropagation()">'
    html += '<h3 id="vod-note-title">Add note</h3>'
    html += '<p id="vod-note-sub" class="vod-modal-sub"></p>'
    html += '<form id="vod-note-form" method="post" action="' + SCRIPT_PATH + '">'
    html += '<input type="hidden" name="action" value="add_note" />'
    html += '<input type="hidden" name="area" value="" />'
    html += '<input type="hidden" name="list" value="" />'
    html += '<input type="hidden" name="people_id" value="" />'
    html += '<input type="hidden" name="kev_json" id="vod-kev-json" value="" />'
    html += '<input type="hidden" name="pn_step" id="vod-pn-step" value="" />'
    html += '<label for="vod-note-keyword">Keyword</label>'
    html += '<select id="vod-note-keyword" name="keyword"></select>'
    html += '<div id="vod-note-questions" class="vod-kev-box"></div>'
    html += '<label for="vod-note-text">Note</label>'
    html += '<textarea id="vod-note-text" name="note_text" placeholder="Write your note…" required></textarea>'
    html += '<div class="vod-modal-actions">'
    html += '<button type="button" class="vod-btn vod-btn-muted" onclick="return vodCloseNote()">Cancel</button>'
    html += '<button type="submit" class="vod-btn vod-btn-primary">Save note</button>'
    html += '</div></form></div></div>'
    return html


def _pn_view_modal_html():
    """Read-only popup listing Progress Notes for a step / Other."""
    html = '<div id="vod-pn-view-modal" class="vod-modal-backdrop" onclick="return vodClosePnView(event)">'
    html += '<div class="vod-modal" role="dialog" aria-modal="true" aria-labelledby="vod-pn-view-title" onclick="event.stopPropagation()">'
    html += '<h3 id="vod-pn-view-title">Progress Note</h3>'
    html += '<p id="vod-pn-view-sub" class="vod-modal-sub"></p>'
    html += '<div id="vod-pn-view-body"></div>'
    html += '<div class="vod-modal-actions">'
    html += '<button type="button" class="vod-btn vod-btn-muted" onclick="return vodClosePnView()">Close</button>'
    html += '</div></div></div>'
    return html


def _pn_notes_json(notes):
    """Compact JSON array for data-notes attribute."""
    arr = []
    for n in (notes or []):
        arr.append({
            'id': _i(n.get('id'), 0),
            'text': _s(n.get('text')),
            'when': _s(n.get('when')),
            'option': _s(n.get('option')),
        })
    return _py_to_json_walk(arr, None)


def _pn_icon_html(notes, label, inline=False):
    """Sticky-note icon; opens Progress Note viewer popup. Count badge when >1."""
    notes = notes or []
    if not notes:
        return ''
    count = len(notes)
    cls = 'vod-pn-icon'
    if inline:
        cls += ' vod-pn-icon-inline'
    html = '<button type="button" class="' + cls + '" title="Progress Note"'
    html += ' data-label="' + _html(label) + '"'
    html += ' data-notes="' + _html(_pn_notes_json(notes)) + '"'
    html += ' onclick="return vodOpenPnNotes(this, event)">'
    html += '<i class="fa fa-sticky-note-o" aria-hidden="true"></i>'
    html += '<span class="vod-pn-mark">PN</span>'
    if count > 1:
        html += '<span class="vod-pn-count">' + str(count) + '</span>'
    html += '</button>'
    return html


def _note_open_button_html(person, area_key, list_key, list_cfg, cfg, is_minor,
                           step_label, complete_kw, pn_bucket, btn_label='Add note',
                           prefer_complete=False):
    """Add note button. Progress Note is default unless prefer_complete=True."""
    pid = _i(person.PeopleId)
    pn = _progress_note_cfg(cfg)
    pn_kw = _s(pn.get('keyword'))
    complete_kw = _s(complete_kw)
    opts = _note_keyword_options(complete_kw, cfg)
    if prefer_complete and complete_kw:
        default_kw = complete_kw
    elif pn_kw:
        default_kw = pn_kw
    else:
        default_kw = ''
    opts_js = '['
    first = True
    for val, lab in opts:
        if not first:
            opts_js += ','
        first = False
        opts_js += '[' + _json_quote(val) + ',' + _json_quote(lab) + ']'
    opts_js += ']'
    allowed = _pn_allowed_option_labels(cfg, is_minor)
    allowed_js = _py_to_json_walk(allowed, None)
    # Only preselect Progress Note EV when opening as a progress note
    pn_option = ''
    if (not prefer_complete) and pn_bucket:
        pn_option = _pn_option_for_bucket(cfg, pn_bucket)
    html = '<button type="button" class="vod-btn vod-btn-muted"'
    html += ' data-pid="' + str(pid) + '"'
    html += ' data-area="' + _html(area_key) + '"'
    html += ' data-list="' + _html(list_key) + '"'
    html += ' data-step="' + _html(step_label) + '"'
    html += ' data-person="' + _html(_s(person.Name)) + '"'
    html += ' data-default="' + _html(default_kw) + '"'
    html += ' data-pn-option="' + _html(pn_option) + '"'
    html += ' data-options="' + _html(opts_js) + '"'
    html += ' data-allowed="' + _html(allowed_js) + '"'
    html += ' onclick="return vodOpenNoteBtn(this)">'
    html += _html(btn_label) + '</button>'
    return html


def _pill(text, cls=''):
    return '<span class="vod-pill ' + cls + '">' + _html(text) + '</span>'


def _circle(state):
    cls = 'vod-circle'
    if state == 'complete':
        cls += ' ok'
    elif state == 'danger':
        cls += ' bad'
    return '<div class="' + cls + '"></div>'


def _short_label(key, label):
    """Shorter labels inside stacked columns."""
    m = {
        'app_sent': 'Sent',
        'app_reviewed': 'Reviewed',
        'bc_sent': 'Sent',
        'bc_reviewed': 'Reviewed',
        'video_sent': 'Sent',
        'video_done': 'Complete',
        'training': 'In-person training',
        'handbook': 'Handbook signed',
    }
    return m.get(key, label)


def _render_step_actions(st, person, area_key, list_key, list_cfg, view_only, is_admin, cfg=None, is_minor=False):
    """Primary actions only when incomplete; complete steps stay quiet."""
    key = st.get('key')
    meta = st.get('meta') or {}
    pid = _i(person.PeopleId)
    done = bool(st.get('complete'))
    html = ''
    if view_only:
        return html

    if key == 'app_sent':
        form_id = 'sendapp_' + str(pid)
        ev = _s(meta.get('ev'))
        # Use GET for email send — Azure App Gateway WAF often 403s POSTs that look like email/XSS.
        # Manual date: same set_ev_date path as Reviewed (in-person app + interview).
        # When complete: Re-send only (no date picker), matching Send disappearing.
        html += '<div class="vod-step-actions">'
        if done:
            html += '<form id="' + form_id + '" method="get" action="' + SCRIPT_PATH + '" style="display:inline">'
            html += '<input type="hidden" name="do" value="sapp" />'
            html += '<input type="hidden" name="area" value="' + _html(area_key) + '" />'
            html += '<input type="hidden" name="list" value="' + _html(list_key) + '" />'
            html += '<input type="hidden" name="pid" value="' + str(pid) + '" />'
            html += '<input type="hidden" name="confirm_resend" value="0" />'
            html += '<button type="button" class="vod-link vod-link-muted" onclick="return vodConfirmResend(\'' + form_id + '\')">Re-send</button>'
            html += '</form>'
        else:
            html += '<form method="get" action="' + SCRIPT_PATH + '" style="display:inline">'
            html += '<input type="hidden" name="do" value="sapp" />'
            html += '<input type="hidden" name="area" value="' + _html(area_key) + '" />'
            html += '<input type="hidden" name="list" value="' + _html(list_key) + '" />'
            html += '<input type="hidden" name="pid" value="' + str(pid) + '" />'
            html += '<button type="submit" class="vod-btn vod-btn-primary">Send</button>'
            html += '</form>'
            if ev:
                html += '<form method="post" action="' + SCRIPT_PATH + '" style="display:inline-flex;gap:6px;align-items:center;flex-wrap:wrap">'
                html += '<input type="hidden" name="action" value="set_ev_date" />'
                html += '<input type="hidden" name="area" value="' + _html(area_key) + '" />'
                html += '<input type="hidden" name="list" value="' + _html(list_key) + '" />'
                html += '<input type="hidden" name="people_id" value="' + str(pid) + '" />'
                html += '<input type="hidden" name="ev_field" value="' + _html(ev) + '" />'
                html += '<input type="date" name="ev_date" value="' + _today_str() + '" title="Mark application done in person (no email)" style="max-width:132px;font-size:11px;padding:4px;" />'
                html += '<button type="submit" class="vod-btn vod-btn-muted">Save date</button>'
                html += '</form>'
        html += '</div>'
    elif key == 'app_reviewed' or key == 'handbook' or key == 'training':
        ev = _s(meta.get('ev'))
        html += '<div class="vod-step-actions">'
        html += '<form method="post" action="' + SCRIPT_PATH + '" style="display:inline-flex;gap:6px;align-items:center;flex-wrap:wrap">'
        html += '<input type="hidden" name="action" value="set_ev_date" />'
        html += '<input type="hidden" name="area" value="' + _html(area_key) + '" />'
        html += '<input type="hidden" name="list" value="' + _html(list_key) + '" />'
        html += '<input type="hidden" name="people_id" value="' + str(pid) + '" />'
        html += '<input type="hidden" name="ev_field" value="' + _html(ev) + '" />'
        html += '<input type="date" name="ev_date" value="' + _today_str() + '" style="max-width:132px;font-size:11px;padding:4px;" />'
        html += '<button type="submit" class="vod-btn vod-btn-muted">' + ('Update' if done else 'Save') + '</button>'
        html += '</form></div>'
    elif key == 'bc_reviewed':
        bgid = _i(meta.get('bgid'), 0)
        if bgid:
            html += '<div class="vod-step-actions">'
            html += '<form method="post" action="' + SCRIPT_PATH + '" style="display:inline-flex;gap:6px;align-items:center;flex-wrap:wrap">'
            html += '<input type="hidden" name="action" value="set_approval" />'
            html += '<input type="hidden" name="area" value="' + _html(area_key) + '" />'
            html += '<input type="hidden" name="list" value="' + _html(list_key) + '" />'
            html += '<input type="hidden" name="people_id" value="' + str(pid) + '" />'
            html += '<input type="hidden" name="bg_id" value="' + str(bgid) + '" />'
            html += '<select name="approval" style="font-size:11px;padding:4px;">'
            cur = _s(meta.get('approval')) or 'Pending'
            for opt in ('Pending', 'Approved', 'Not Approved'):
                sel = ' selected="selected"' if opt == cur else ''
                html += '<option value="' + opt + '"' + sel + '>' + opt + '</option>'
            html += '</select>'
            html += '<button type="submit" class="vod-btn vod-btn-muted">Save</button>'
            html += '</form></div>'
        rc = _i(meta.get('runcount'), 0)
        if rc > 1:
            html += '<div class="vod-step-value">+' + str(rc - 1) + ' earlier run(s) on profile</div>'
    elif key == 'bc_sent':
        pass
    elif key in ('interview', 'references', 'shadowing', 'fl_training'):
        # Default to Complete keyword; Progress Note still available in the list
        kw = _s(meta.get('keyword'))
        bucket = _pn_single_bucket(key)
        step_label = _s(st.get('label')) or key
        html += '<div class="vod-step-actions">'
        html += _note_open_button_html(
            person, area_key, list_key, list_cfg, cfg, is_minor,
            step_label, kw, bucket,
            'Add note' if not done else 'Add another note',
            True
        )
        html += '</div>'
    return html


def _stack_footer_links(title, children, person, is_admin):
    """One shared Report / Volunteer link per BC or Video column."""
    pid = _i(person.PeopleId)
    link = ''
    for ch in children or []:
        meta = ch.get('meta') or {}
        if _s(meta.get('link')):
            link = _s(meta.get('link'))
            break
    if title not in ('Background Check', 'Video Training'):
        return ''
    html = '<div class="vod-links">'
    if link:
        html += '<a class="vod-link" href="' + _html(link) + '" target="_blank" rel="noopener">Report</a>'
    html += '<a class="vod-link vod-link-muted" href="/Volunteering/' + str(pid) + '" target="_blank" rel="noopener">Volunteer tab</a>'
    html += '</div>'
    return html


def _render_one_step_row(st, person, area_key, list_key, list_cfg, view_only, is_admin, use_short, cfg=None, is_minor=False):
    key = st.get('key')
    label = _short_label(key, st.get('label')) if use_short else st.get('label')
    html = '<div class="vod-step">'
    html += '<div class="vod-step-head">'
    html += _circle(st.get('state'))
    html += '<div class="vod-step-label">' + _html(label) + '</div>'
    html += '</div>'
    if st.get('value'):
        html += '<div class="vod-step-value">' + _html(st.get('value')) + '</div>'
    html += _render_step_actions(st, person, area_key, list_key, list_cfg, view_only, is_admin, cfg, is_minor)
    html += '</div>'
    return html


def _render_steps_html(steps, person, area_key, list_key, list_cfg, view_only, is_admin,
                       cfg=None, is_minor=False, pn_by_bucket=None):
    pn_by_bucket = pn_by_bucket or {}
    html = '<div class="vod-steps-row">'
    for block in steps:
        if block.get('type') == 'stack':
            title = _s(block.get('title'))
            children = block.get('children') or []
            all_done = True
            any_danger = False
            for ch in children:
                if not ch.get('complete'):
                    all_done = False
                if ch.get('state') == 'danger':
                    any_danger = True
            tile_cls = 'vod-stack'
            if any_danger:
                tile_cls += ' danger'
            elif all_done and children:
                tile_cls += ' done'
            bucket = _pn_stack_bucket(title)
            html += '<div class="' + tile_cls + '">'
            # Progress note icon on incomplete stacks only
            if bucket and not all_done:
                notes = pn_by_bucket.get(bucket) or []
                html += _pn_icon_html(notes, title)
            html += '<h4>' + _html(title) + '</h4>'
            for ch in children:
                html += _render_one_step_row(
                    ch, person, area_key, list_key, list_cfg, view_only, is_admin, True, cfg, is_minor
                )
            # Progress note entry for Application / BC / Video columns (while incomplete)
            if bucket and not view_only and not all_done:
                html += '<div class="vod-step-actions" style="margin-top:8px">'
                html += _note_open_button_html(
                    person, area_key, list_key, list_cfg, cfg, is_minor,
                    title, '', bucket, 'Progress note'
                )
                html += '</div>'
            html += _stack_footer_links(title, children, person, is_admin)
            html += '</div>'
        else:
            st = block.get('step') or {}
            tile_cls = 'vod-step-col'
            if st.get('state') == 'danger':
                tile_cls += ' danger'
            elif st.get('complete'):
                tile_cls += ' done'
            bucket = _pn_single_bucket(st.get('key'))
            html += '<div class="' + tile_cls + '">'
            if bucket and not st.get('complete'):
                notes = pn_by_bucket.get(bucket) or []
                html += _pn_icon_html(notes, _s(st.get('label')) or bucket)
            html += '<div class="vod-col-title">' + _html(st.get('label')) + '</div>'
            html += '<div class="vod-step">'
            html += '<div class="vod-step-head">'
            html += _circle(st.get('state'))
            html += '<div class="vod-step-label">' + ('Done' if st.get('complete') else 'Open') + '</div>'
            html += '</div>'
            if st.get('value'):
                html += '<div class="vod-step-value">' + _html(st.get('value')) + '</div>'
            html += _render_step_actions(st, person, area_key, list_key, list_cfg, view_only, is_admin, cfg, is_minor)
            html += '</div></div>'
    html += '</div>'
    return html


def _render_person_card(person, area_cfg, list_cfg, area_key, list_key, view_only, is_admin,
                        filter_step, filter_minor, open_pid=0, cfg=None, pn_by_bucket=None):
    pid = _i(person.PeopleId)
    age = person.Age
    try:
        age_i = int(age) if age is not None and not _is_null(age) else None
    except:
        age_i = None
    is_minor = (age_i is not None and age_i < 18)
    if filter_minor == '1' and not is_minor:
        return ''
    if filter_minor == '0' and is_minor:
        return ''

    steps = _build_steps(person, area_cfg, list_cfg, is_minor)
    # filter_step = people missing that step (or ready-only)
    if filter_step == 'ready':
        pass  # applied after ready computed
    elif filter_step:
        if not _step_incomplete(steps, filter_step):
            return ''
    ready = _required_complete(steps)
    if filter_step == 'ready' and not ready:
        return ''

    cpp_ev = _s(area_cfg.get('cpp_violation_ev'))
    flagged = _ev_any(pid, cpp_ev) if cpp_ev else False
    prior = _prior_app(pid, area_cfg.get('prior_app_orgid'))
    pn_by_bucket = pn_by_bucket or {}

    card_cls = 'vod-card'
    if flagged:
        card_cls += ' flag-red'
    if open_pid and pid == open_pid:
        card_cls += ' open'
    card_id = 'vod_card_' + str(pid)

    html = '<div class="' + card_cls + '" id="' + card_id + '">'
    html += '<div class="vod-card-h" onclick="vodToggle(\'' + card_id + '\')">'
    html += '<div class="vod-caret"></div>'
    html += '<a class="vod-name" href="/Person2/' + str(pid) + '" target="_blank" rel="noopener" onclick="event.stopPropagation()">' + _html(person.Name) + '</a>'
    # Other progress notes sit next to the name (always, no step to complete)
    other_notes = pn_by_bucket.get('other') or []
    if other_notes:
        html += _pn_icon_html(other_notes, 'Other', True)
    html += '<div class="vod-pills">'
    if is_minor:
        html += _pill('Minor', 'minor')
    if prior:
        html += _pill('Previous application', 'prior')
    if flagged:
        html += _pill('Service ineligible', 'danger')
    if ready:
        html += _pill('Ready for HR', 'ready')
    html += '</div>'
    done, total = _step_progress(steps)
    pct = 0
    if total > 0:
        pct = int((done * 100) / total)
    prog_cls = 'vod-progress'
    if total <= 0 or done <= 0:
        prog_cls += ' is-empty'
    elif done >= total:
        prog_cls += ' is-ready'
    else:
        prog_cls += ' is-partial'
    html += '<div class="vod-progress-wrap" title="' + str(done) + ' of ' + str(total) + ' steps complete">'
    html += '<div class="' + prog_cls + '"><i style="width:' + str(pct) + '%"></i></div>'
    html += '<span class="vod-progress-lbl">' + str(done) + '/' + str(total) + '</span>'
    html += '</div>'
    since = _fmt_date(person.ProspectSince)
    html += '<div class="vod-meta">Prospect since ' + _html(since)
    if age_i is not None:
        html += ' · Age ' + str(age_i)
    html += '</div></div>'

    html += '<div class="vod-body' + (' vod-readonly' if view_only else '') + '">'
    orgid = _orgid(list_cfg)
    if ready and is_admin:
        html += '<form method="post" action="' + SCRIPT_PATH + '" style="margin:0 0 12px 0">'
        html += '<input type="hidden" name="action" value="move_member" />'
        html += '<input type="hidden" name="area" value="' + _html(area_key) + '" />'
        html += '<input type="hidden" name="list" value="' + _html(list_key) + '" />'
        html += '<input type="hidden" name="people_id" value="' + str(pid) + '" />'
        html += '<input type="hidden" name="orgid" value="' + str(orgid) + '" />'
        html += '<button type="submit" class="vod-btn vod-btn-success" onclick="return confirm(\'Move this person from Prospect to Member?\')">Admin: Move Prospect → Member</button>'
        html += '</form>'
    html += '<div style="margin-bottom:8px;font-size:12px;display:flex;flex-wrap:wrap;gap:8px;align-items:center">'
    html += '<a href="/Org/' + str(orgid) + '" target="_blank" rel="noopener">' + _html(_s(person.OrganizationName) or _org_name(orgid)) + '</a>'
    if not view_only:
        html += _note_open_button_html(
            person, area_key, list_key, list_cfg, cfg, is_minor,
            'Other', '', 'other', 'Other progress note'
        )
    html += '</div>'
    html += _render_steps_html(
        steps, person, area_key, list_key, list_cfg, view_only, is_admin,
        cfg, is_minor, pn_by_bucket
    )
    html += '</div></div>'
    return html


def _render_list_page(cfg, area_key, list_key, msg, open_pid=0):
    area_cfg, list_cfg = _list_cfg(cfg, area_key, list_key)
    orgid = _orgid(list_cfg)
    view_only = _is_view_only(cfg, area_key)
    is_admin = _is_admin()
    filter_step = _form_val('filter_step', _s(_get('filter_step', '')))
    filter_minor = _form_val('filter_minor', _s(_get('filter_minor', '')))
    open_pid = _i(open_pid, 0)
    # Also accept querystring via Data on GET
    try:
        if not filter_step:
            filter_step = _s(Data.filter_step)
    except:
        pass
    try:
        if not filter_minor:
            filter_minor = _s(Data.filter_minor)
    except:
        pass
    try:
        if not open_pid:
            open_pid = _i(Data.open, 0)
    except:
        pass
    if not open_pid:
        open_pid = _i(_form_val('open'), 0)

    html = _styles() + _js(cfg)
    html += '<div class="vod-root">'
    html += '<div class="vod-header"><h1>Volunteer Onboarding</h1>'
    html += '<div class="sub">Kids &amp; Student Ministry · Prospects only</div></div>'

    html += _nav(cfg, area_key, list_key)

    if msg:
        html += '<div class="vod-msg">' + _html(msg) + '</div>'

    if orgid <= 0:
        html += '<div class="vod-panel vod-empty">This list has no Involvement # configured yet. Admins: open Config.</div></div>'
        return html

    if view_only:
        html += '<div class="vod-msg">View only — edits are disabled for your role.</div>'

    org_name = _org_name(orgid)
    html += '<div class="vod-panel">'
    html += '<div class="vod-toolbar">'
    html += '<strong><a href="/Org/' + str(orgid) + '" target="_blank" rel="noopener">' + _html(org_name) + '</a></strong>'
    html += '<span style="color:#64748b;font-size:12px;">Inv #' + str(orgid) + ' · Prospects</span>'
    html += '<form method="get" action="' + SCRIPT_PATH + '" style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-left:auto">'
    html += '<input type="hidden" name="area" value="' + _html(area_key) + '" />'
    html += '<input type="hidden" name="list" value="' + _html(list_key) + '" />'
    html += '<label>Step filter</label><select name="filter_step">'
    opts = [
        ('', 'All'),
        ('app_sent', 'Missing Application Sent'),
        ('app_reviewed', 'Missing Application Reviewed'),
        ('bc_sent', 'Missing BC Sent'),
        ('bc_reviewed', 'Missing BC Approved'),
        ('video_sent', 'Missing Video Sent'),
        ('video_done', 'Missing Video Complete'),
        ('interview', 'Missing Interview'),
        ('references', 'Missing References'),
        ('shadowing', 'Missing Shadowing'),
        ('fl_training', 'Missing FL Training'),
        ('training', 'Missing In-person training'),
        ('handbook', 'Missing Handbook signed'),
        ('ready', 'Ready for HR only'),
    ]
    for val, lab in opts:
        sel = ' selected="selected"' if filter_step == val else ''
        html += '<option value="' + val + '"' + sel + '>' + lab + '</option>'
    html += '</select>'
    html += '<label>Minor</label><select name="filter_minor">'
    for val, lab in [('', 'All ages'), ('1', 'Minors only'), ('0', 'Adults only')]:
        sel = ' selected="selected"' if filter_minor == val else ''
        html += '<option value="' + val + '"' + sel + '>' + lab + '</option>'
    html += '</select>'
    html += '<button type="submit" class="vod-btn vod-btn-muted">Apply</button>'
    html += '</form></div>'

    rows = _load_prospects(orgid)
    pn_map = {}
    if rows:
        pn_map = _progress_notes_for_people([_i(p.PeopleId) for p in rows], cfg)
    if not rows:
        html += '<div class="vod-empty">No Prospects on this Involvement.</div>'
    else:
        count = 0
        for person in rows:
            pid = _i(person.PeopleId)
            card = _render_person_card(
                person, area_cfg, list_cfg, area_key, list_key,
                view_only, is_admin, filter_step, filter_minor, open_pid,
                cfg, pn_map.get(pid) or {}
            )
            if card:
                html += card
                count += 1
        if count == 0:
            html += '<div class="vod-empty">No people match the current filters.</div>'
        else:
            html += '<div style="font-size:12px;color:#64748b;margin-top:8px;">Showing ' + str(count) + ' of ' + str(len(rows)) + ' Prospects (oldest first).</div>'

    html += '</div></div>'
    if not view_only:
        html += _note_modal_html()
    html += _pn_view_modal_html()
    return html


def _nav(cfg, area_key, list_key):
    html = '<div class="vod-tabs">'
    cls = 'vod-tab'
    if area_key == 'home' or (not area_key and not list_key):
        cls += ' active'
    html += '<a class="' + cls + '" href="' + SCRIPT_PATH + '?area=home"><i class="fa fa-home" aria-hidden="true"></i> Home</a>'
    for ak, area, configured in _visible_areas(cfg):
        ordered = _list_order(configured)
        for lk in ordered:
            lc = configured[lk]
            label = _s(lc.get('label')) or lk
            if len(ordered) > 1 or ak in ('kids', 'student'):
                label = _s(area.get('label')) + ': ' + label
            else:
                label = _s(area.get('label')) or label
            cls = 'vod-tab'
            if ak == area_key and lk == list_key:
                cls += ' active'
            html += '<a class="' + cls + '" href="' + SCRIPT_PATH + '?area=' + ak + '&list=' + lk + '">' + _html(label) + '</a>'
    if _is_admin():
        cls = 'vod-tab'
        if area_key == 'config':
            cls += ' active'
        html += '<a class="' + cls + '" href="' + SCRIPT_PATH + '?area=config">Config</a>'
    html += '</div>'
    return html


def _home_tile_html(title, subtitle, prospects, ready, minors, flagged, has_cpp, href, ready_href):
    """One Home metric tile."""
    html = '<div class="vod-home-tile">'
    html += '<h3>' + _html(title) + '</h3>'
    if subtitle:
        html += '<div class="vod-home-sub">' + _html(subtitle) + '</div>'
    html += '<div class="vod-home-metrics">'
    html += '<div class="vod-home-metric"><span class="n">' + str(prospects) + '</span><span class="l">Prospects</span></div>'
    html += '<div class="vod-home-metric ready"><span class="n">' + str(ready) + '</span><span class="l">Ready for HR</span></div>'
    html += '<div class="vod-home-metric"><span class="n">' + str(minors) + '</span><span class="l">Minors</span></div>'
    if has_cpp:
        flag_cls = 'vod-home-metric flag' if flagged > 0 else 'vod-home-metric muted'
        html += '<div class="' + flag_cls + '"><span class="n">' + str(flagged) + '</span><span class="l">CPP flagged</span></div>'
    else:
        adults = prospects - minors
        if adults < 0:
            adults = 0
        html += '<div class="vod-home-metric"><span class="n">' + str(adults) + '</span><span class="l">Adults</span></div>'
    html += '</div>'
    if href:
        html += '<div class="vod-home-cta"><a class="vod-btn vod-btn-primary" href="' + href + '">Open ' + _html(title) + '</a>'
        if ready > 0 and ready_href:
            html += ' <a class="vod-btn vod-btn-success" href="' + ready_href + '">Ready for HR</a>'
        html += '</div>'
    html += '</div>'
    return html


def _render_home_page(cfg, msg):
    html = _styles() + _js(cfg)
    html += '<div class="vod-root">'
    html += '<div class="vod-header"><h1>Volunteer Onboarding</h1>'
    html += '<div class="sub">Home · pipeline totals for your areas</div></div>'
    html += _nav(cfg, 'home', '')
    if msg:
        html += '<div class="vod-msg">' + _html(msg) + '</div>'

    home_areas = _home_areas(cfg)
    if not home_areas:
        html += '<div class="vod-panel vod-empty">No ministry areas are visible for your roles yet.</div></div>'
        return html

    html += '<div class="vod-home-grid">'
    for ak, area_cfg, configured in home_areas:
        area_label = _s(area_cfg.get('label')) or ak

        if not configured:
            html += '<div class="vod-home-tile unconfigured">'
            html += '<h3>' + _html(area_label) + '</h3>'
            html += '<div class="vod-home-sub">Not configured — set Involvement #s in Config</div>'
            html += '<div class="vod-home-metrics">'
            html += '<div class="vod-home-metric muted"><span class="n">—</span><span class="l">Prospects</span></div>'
            html += '<div class="vod-home-metric muted"><span class="n">—</span><span class="l">Ready for HR</span></div>'
            html += '</div>'
            if _is_admin():
                html += '<div class="vod-home-cta"><a class="vod-btn vod-btn-muted" href="' + SCRIPT_PATH + '?area=config">Open Config</a></div>'
            html += '</div>'
            continue

        m = _area_metrics(cfg, ak, area_cfg, configured)
        has_cpp = m['has_cpp']

        # Kids / Student: one Home tile per list (same full-track mapping)
        if ak in ('kids', 'student') and len(m['lists']) > 0:
            for lr in m['lists']:
                href = SCRIPT_PATH + '?area=' + ak + '&list=' + lr['key']
                ready_href = href + '&filter_step=ready'
                title = _s(lr['label']) or lr['key']
                sub = area_label + ' · Inv #' + str(lr['orgid'])
                html += _home_tile_html(
                    title, sub,
                    lr['prospects'], lr['ready'], lr['minors'], lr['flagged'], has_cpp,
                    href, ready_href
                )
            continue

        # Other areas: one roll-up tile
        first = m['lists'][0]['key'] if m['lists'] else ''
        href = SCRIPT_PATH + '?area=' + ak + '&list=' + first if first else ''
        ready_href = href + '&filter_step=ready' if href else ''
        sub = str(len(m['lists'])) + ' list' + ('s' if len(m['lists']) != 1 else '')
        html += _home_tile_html(
            area_label, sub,
            m['prospects'], m['ready'], m['minors'], m['flagged'], has_cpp,
            href, ready_href
        )

    html += '</div></div>'
    return html


def _render_config_page(cfg, msg):
    """Config = Special Content text file. Forms are not the source of truth."""
    areas = cfg.get('areas') or {}
    raw = _raw_content_text(CONFIG_CONTENT_NAME)
    html = _styles() + _js(cfg)
    html += '<div class="vod-root">'
    html += '<div class="vod-header"><h1>Volunteer Onboarding</h1><div class="sub">Admin Config</div></div>'
    html += _nav(cfg, 'config', '')
    if msg:
        html += '<div class="vod-msg">' + _html(msg) + '</div>'
    html += '<div class="vod-panel vod-config">'

    html += '<h2 style="margin:0 0 8px;font-size:18px;color:#012B58">Special Content config file</h2>'
    html += '<p style="font-size:14px;line-height:1.45;color:#334155">Edit the Text document named <code>' + CONFIG_CONTENT_NAME + '</code> '
    html += 'under <b>Administration → Special Content → Text</b>. The dashboard reads that JSON on every page load. '
    html += 'Empty Involvement # (<code>orgid: 0</code>) hides that list from the work tabs.</p>'

    html += '<p style="font-size:12px;color:#64748b;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px">'
    html += 'Store: '
    if not raw:
        html += '<b>empty</b> (script defaults only)'
    else:
        html += '<b>' + str(len(raw)) + '</b> chars in <code>' + CONFIG_CONTENT_NAME + '</code>'
    st = ((areas.get('student') or {}).get('lists') or {}).get('students') or {}
    kid_l = ((areas.get('kids') or {}).get('lists') or {}).get('littles') or {}
    html += ' · loaded student orgid=<b>' + str(_i(st.get('orgid'), 0)) + '</b>'
    html += ' · littles orgid=<b>' + str(_i(kid_l.get('orgid'), 0)) + '</b>'
    if _CONFIG_LOAD_INFO:
        html += '<br/>Load: ' + _html(_CONFIG_LOAD_INFO)
    html += '</p>'

    html += '<p style="font-size:12px;color:#64748b;margin:8px 0 0">Keep only <code>' + CONFIG_CONTENT_NAME + '</code>. Delete ConfigProbe, SenderAddr, SenderName, and SenderPid if present — leftovers.</p>'

    html += '<p style="margin:10px 0">'
    html += '<a class="vod-btn vod-btn-primary" href="' + SCRIPT_PATH + '?do=cfgseed">Write default JSON into Special Content</a> '
    html += '<a class="vod-btn vod-btn-muted" href="' + SCRIPT_PATH + '?do=cfgpretty">Re-save as pretty-printed</a>'
    html += '</p>'
    html += '<p style="font-size:12px;color:#64748b">After seeding (or if the file already exists), open Special Content → Text → <code>' + CONFIG_CONTENT_NAME + '</code>, '
    html += 'set <code>areas.student.lists.students.orgid</code> to your Involvement # (e.g. <code>85</code>), Save there, then reload this page.</p>'

    # Read-only summary of what the script currently loaded
    html += '<h3 style="margin:18px 0 8px;font-size:15px;color:#012B58">Currently loaded (read-only)</h3>'
    pn = _progress_note_cfg(cfg)
    html += '<div style="margin:0 0 14px;padding:10px 12px;border:1px solid #e2e8f0;border-radius:8px;background:#fff;font-size:13px;color:#334155">'
    html += '<div style="font-weight:700;color:#012B58;margin-bottom:4px">Progress notes</div>'
    html += 'Keyword: <code>' + _html(pn.get('keyword')) + '</code>'
    html += ' · EV question: <code>' + _html(pn.get('ev_question')) + '</code>'
    html += '<div style="font-size:12px;color:#64748b;margin-top:6px">option_map: '
    bits = []
    for lab, bucket in (pn.get('option_map') or {}).items():
        bits.append(_html(lab) + '→' + _html(bucket))
    html += ', '.join(bits) if bits else '—'
    html += '</div>'
    html += '<div style="font-size:12px;color:#64748b;margin-top:4px">Edit under <code>progress_note</code> in the Special Content JSON.</div>'
    html += '</div>'
    for ak in _area_keys(cfg):
        area = areas.get(ak) or {}
        lists = area.get('lists') or {}
        html += '<details class="vod-config-area">'
        html += '<summary><i class="fa fa-caret-right vod-area-caret" aria-hidden="true"></i>'
        html += '<span>' + _html(_s(area.get('label')) or ak) + '</span>'
        html += '<span class="vod-config-key">' + _html(ak) + '</span></summary>'
        html += '<div style="margin:10px 0;font-size:13px;color:#334155">'
        html += 'Roles: ' + _html(', '.join(area.get('roles') or []) or '—')
        html += ' · From PeopleId: ' + _html(area.get('email_from_peopleid') or '—')
        html += '</div>'
        if not lists:
            html += '<p style="color:#64748b;font-size:13px">No lists.</p>'
        for lk in _list_order(lists):
            lc = lists.get(lk) or {}
            orgid = _i(lc.get('orgid'), 0)
            html += '<div class="vod-config-list" style="margin-top:8px;padding:10px;border:1px solid #e2e8f0;border-radius:8px;background:#fff">'
            html += '<div style="font-weight:700;color:#012B58">' + _html(lc.get('label') or lk)
            html += ' <span class="vod-config-key">' + _html(lk) + '</span></div>'
            html += '<div style="font-size:13px;margin-top:4px">Involvement # <b>' + str(orgid) + '</b>'
            if orgid <= 0:
                html += ' <span style="color:#E52300">(hidden until orgid &gt; 0)</span>'
            html += '</div>'
            html += '<div style="font-size:12px;color:#64748b;margin-top:4px">template: ' + _html(lc.get('email_template') or '—') + '</div>'
            html += '</div>'
        html += '</details>'

    # Show raw file for copy/paste editing convenience (pretty-printed)
    html += '<h3 style="margin:18px 0 8px;font-size:15px;color:#012B58">Raw file contents</h3>'
    if raw:
        pretty = _json_pretty_text(raw)
        html += '<p style="font-size:12px;color:#64748b"><a href="' + SCRIPT_PATH + '?do=cfgpretty">Re-save Special Content as pretty-printed JSON</a></p>'
        html += '<textarea readonly rows="22" style="width:100%;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;padding:10px;border:1px solid #e2e8f0;border-radius:8px;background:#0f172a;color:#e2e8f0">' + _html(pretty) + '</textarea>'
    else:
        html += '<p style="color:#64748b">File is empty. Click <b>Write default JSON</b> above, then edit in Special Content.</p>'
        sample = _py_to_json(_default_config())
        html += '<p style="font-size:12px;color:#64748b">Preview of defaults that will be written:</p>'
        html += '<textarea readonly rows="12" style="width:100%;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;padding:10px;border:1px solid #e2e8f0;border-radius:8px">' + _html(sample) + '</textarea>'

    html += '</div></div>'
    return html



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    model.Title = 'Volunteer Onboarding'
    model.Header = 'Volunteer Onboarding'

    try:
        if not (model.UserIsInRole('Admin') or model.UserIsInRole('Access') or model.UserIsInRole('Staff') or model.UserIsInRole('Elders')):
            _show('<div class="alert alert-danger">Not authorized.</div>')
            return

        cfg = _load_config()
        action = _form_val('action')
        do = _form_val('do')
        msg_code = _form_val('msg')
        try:
            if not msg_code:
                msg_code = _s(Data.msg)
            if not do:
                do = _s(Data.do)
        except:
            pass
        msg = _flash_text(msg_code)

        area = _form_val('area')
        list_key = _form_val('list')
        try:
            if not area:
                area = _s(Data.area)
            if not list_key:
                list_key = _s(Data.list)
        except:
            pass

        # Send application via GET (do=sapp) — avoids App Gateway WAF 403 on POSTs
        if do == 'sapp':
            area = _form_val('area', area)
            list_key = _form_val('list', list_key)
            pid = _i(_form_val('pid'), 0) or _i(_form_val('people_id'), 0)
            confirm = _form_val('confirm_resend') == '1'
            if _is_view_only(cfg, area):
                code = 'err_view'
            else:
                code = _action_send_application(cfg, area, list_key, pid, confirm)
            # Flash on continue page; reopen this person's card after return
            next_url = SCRIPT_PATH + '?area=' + _s(area) + '&list=' + _s(list_key)
            if pid > 0:
                next_url += '&open=' + str(pid)
            _continue_page(next_url, code)
            return

        # Seed Special Content text with default JSON (manual-edit workflow)
        if do == 'cfgseed':
            if not _is_admin():
                _continue_page(SCRIPT_PATH + '?area=config', 'err_auth')
                return
            force = _form_val('force') == '1'
            result = _action_seed_config(force)
            next_url = SCRIPT_PATH + '?area=config'
            if result == 'ok_config':
                next_url += '&msg=ok_config'
            _continue_page(next_url, result)
            return

        # Re-write existing config JSON with indentation (easier to edit in Special Content)
        if do == 'cfgpretty':
            if not _is_admin():
                _continue_page(SCRIPT_PATH + '?area=config', 'err_auth')
                return
            raw = _raw_content_text(CONFIG_CONTENT_NAME)
            if not raw:
                _flash_detail_set('store empty — seed first')
                _continue_page(SCRIPT_PATH + '?area=config', 'err_generic')
                return
            pretty = _json_pretty_text(raw)
            try:
                model.WriteContentText(CONFIG_CONTENT_NAME, pretty)
                _flash_detail_set('reformatted ' + str(len(pretty)) + ' chars')
                _continue_page(SCRIPT_PATH + '?area=config&msg=ok_config', 'ok_config')
            except Exception, ex:
                _flash_detail_set(_s(ex)[:100])
                _continue_page(SCRIPT_PATH + '?area=config', 'err_generic')
            return

        # Minimal Inv# save via GET (do=setorg) — same Data-binder path as do=sapp
        if do == 'setorg':
            if not _is_admin():
                _continue_page(SCRIPT_PATH + '?area=config', 'err_auth')
                return
            result = _action_set_orgid(_form_val('area_key'), _form_val('list_key'), _form_val('orgid'))
            next_url = SCRIPT_PATH + '?area=config'
            if result == 'ok_config':
                next_url += '&msg=ok_config'
            _continue_page(next_url, result)
            return

        # Save area config via GET fields (do=scfg) — kept as fallback for older paste
        if do == 'scfg':
            if not _is_admin():
                _continue_page(SCRIPT_PATH + '?area=config', 'err_auth')
                return
            ak = _form_val('area_key')
            posted = None
            raw_p = _form_val('p')
            if raw_p:
                posted = _parse_cfg_payload(raw_p)
                if posted is None:
                    _flash_detail_set('packed payload invalid (len=' + str(len(_s(raw_p))) + ')')
                    _continue_page(SCRIPT_PATH + '?area=config', 'err_generic')
                    return
            result = _action_save_area_config(ak, posted)
            next_url = SCRIPT_PATH + '?area=config'
            if result == 'ok_config':
                next_url += '&msg=ok_config'
            _continue_page(next_url, result)
            return

        if model.HttpMethod == 'post' and action:
            result = 'err_generic'
            area = _form_val('area', area)
            list_key = _form_val('list', list_key)
            pid = _i(_form_val('people_id'), 0) or _i(_form_val('pid'), 0)

            if action == 'save_area_config':
                result = _action_save_area_config(_form_val('area_key'))
                area = 'config'
            elif action == 'save_config':
                # Legacy mega-form removed — point callers at per-area save
                result = _action_save_area_config(_form_val('area_key') or 'student')
                area = 'config'
            elif action == 'add_area':
                result = _action_add_area()
                area = 'config'
            elif action == 'add_list':
                result = _action_add_list()
                area = 'config'
            elif _is_view_only(cfg, area) and action not in ('',):
                result = 'err_view'
            elif action == 'set_ev_date':
                result = _action_set_ev_date(pid, _form_val('ev_field'), _form_val('ev_date'))
            elif action == 'add_note':
                result = _action_add_note(pid, _form_val('keyword'), _form_val('note_text'))
            elif action == 'set_approval':
                result = _action_set_approval(_form_val('bg_id'), _form_val('approval'))
            elif action == 'move_member':
                result = _action_move_member(_i(_form_val('orgid'), 0), pid)
            else:
                result = 'err_generic'

            # Continue page carries the flash; reopen card when we have a people id
            if action in ('save_area_config', 'save_config', 'add_area', 'add_list'):
                next_url = SCRIPT_PATH + '?area=config'
            else:
                next_url = SCRIPT_PATH + '?area=' + _s(area) + '&list=' + _s(list_key)
                if pid > 0:
                    next_url += '&open=' + str(pid)
            _continue_page(next_url, result)
            return

        # GET defaults
        if area == 'config':
            if not _is_admin():
                _show('<div class="alert alert-danger">Config is Admin only.</div>')
                return
            _show(_render_config_page(cfg, msg))
            return

        if not area or area == 'home':
            _show(_render_home_page(cfg, msg))
            return

        visible = _visible_areas(cfg)
        if not list_key:
            # area chosen without list — pick first configured list for that area
            for ak, _area, configured in visible:
                if ak == area and configured:
                    ordered = _list_order(configured)
                    list_key = ordered[0] if ordered else ''
                    break
            if not list_key:
                _show(_render_home_page(cfg, msg or 'No lists configured for that area yet.'))
                return

        if not _can_see_area(cfg, area):
            _show('<div class="alert alert-danger">Not authorized for this area.</div>')
            return

        _show(_render_list_page(cfg, area, list_key, msg, _i(_form_val('open'), 0)))
    except Exception, ex:
        import traceback
        err = _html(_s(ex))
        try:
            tb = _html(traceback.format_exc())
        except:
            tb = ''
        html = '<div class="alert alert-danger"><strong>Volunteer Onboarding error</strong><pre style="white-space:pre-wrap">' + err + '\n' + tb + '</pre></div>'
        # PyScriptForm POST returns stdout only — model.Form is ignored, which
        # otherwise produces a blank white page when an action throws.
        try:
            if model.HttpMethod == 'post':
                print html
                return
        except:
            pass
        _show(html)


main()
