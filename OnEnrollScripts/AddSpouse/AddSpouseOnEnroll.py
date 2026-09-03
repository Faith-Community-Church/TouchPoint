# OnEnroll Script: Add Spouse to Organization
# Purpose: When a person enrolls, add their spouse to the same involvement.
#   If no spouse is on the record, email staff so they can follow up.
# Author: Jake Pierson
# Date: 2026-09-03
#
# Install: Involvement -> Settings -> Registration -> OnEnroll Script
# Runtime: TouchPoint IronPython 2.7 (no f-strings, no except/as)

# Staff who receive the "no spouse" alert (PeopleId). Change this to the
# person who should act when a registrant has no linked spouse.
NOTIFY_PEOPLE_ID = 834
QUEUED_BY = 834
EMAIL_FROM_ADDRESS = 'jpierson@fcchudson.com'
EMAIL_FROM_NAME = 'TouchPoint Script - Add Spouse'

MARITAL_STATUS = {
    0: 'Unknown',
    10: 'Single',
    20: 'Married',
    30: 'Separated',
    40: 'Divorced',
    50: 'Widowed',
}


def _s(val, default=''):
    if val is None:
        return default
    try:
        s = unicode(val).strip()
    except:
        s = str(val).strip()
    if s == '' or s == 'None':
        return default
    return s


def _html(val):
    s = _s(val)
    return (s
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))


def _marital_label(person):
    mid = None
    if person is not None:
        try:
            mid = person.MaritalStatusId
        except:
            mid = None
    if mid is None:
        return 'Unknown'
    try:
        mid = int(mid)
    except:
        return _s(mid, 'Unknown')
    if mid in MARITAL_STATUS:
        return MARITAL_STATUS[mid]
    return str(mid)


def _notify_no_spouse(people_id, org_id):
    person = model.GetPerson(people_id)
    org = model.GetOrganization(org_id)

    person_name = 'Unknown'
    if person is not None:
        person_name = _s(person.Name, 'PeopleId ' + str(people_id))

    org_name = 'Organization ' + str(org_id)
    if org is not None:
        org_name = _s(org.name, org_name)

    host = _s(model.CmsHost).rstrip('/')
    person_url = host + '/Person2/' + str(people_id)
    org_url = host + '/Org/' + str(org_id)
    marital = _marital_label(person)
    spouse_name = ''
    if person is not None:
        spouse_name = _s(person.SpouseName)

    subject = 'No spouse on record: {0} enrolled in {1}'.format(person_name, org_name)

    spouse_row = ''
    if spouse_name:
        spouse_row = (
            '<tr><td style="padding:6px 12px 6px 0;color:#001429;">Spouse name on record</td>'
            '<td style="padding:6px 0;color:#001429;">{0}</td></tr>'
        ).format(_html(spouse_name))

    body = (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#001429;line-height:1.5;">'
        '<p style="margin:0 0 12px 0;">A person enrolled in an involvement that auto-adds the spouse, '
        'but <strong>no spouse is linked</strong> on their record.</p>'
        '<table style="border-collapse:collapse;">'
        '<tr><td style="padding:6px 12px 6px 0;color:#001429;">Person</td>'
        '<td style="padding:6px 0;"><a href="{0}">{1}</a> (#{2})</td></tr>'
        '<tr><td style="padding:6px 12px 6px 0;color:#001429;">Involvement</td>'
        '<td style="padding:6px 0;"><a href="{3}">{4}</a> (#{5})</td></tr>'
        '<tr><td style="padding:6px 12px 6px 0;color:#001429;">Marital status</td>'
        '<td style="padding:6px 0;color:#001429;">{6}</td></tr>'
        '{7}'
        '</table>'
        '<p style="margin:16px 0 0 0;color:#012B58;">The enrollee was not auto-added a spouse. '
        'Link a spouse on their record if this involvement should include both.</p>'
        '</div>'
    ).format(
        person_url,
        _html(person_name),
        people_id,
        org_url,
        _html(org_name),
        org_id,
        _html(marital),
        spouse_row,
    )

    model.Transactional = True
    model.Email(
        NOTIFY_PEOPLE_ID,
        QUEUED_BY,
        EMAIL_FROM_ADDRESS,
        EMAIL_FROM_NAME,
        subject,
        body,
    )


people_id = Data.PeopleId
org_id = int(Data.OrganizationId)

# GetSpouse returns None when SpouseId is missing (GetPersonData(0) is empty)
spouse = model.GetSpouse(people_id)

if spouse is not None:
    spouse_id = spouse.PeopleId
    if not model.InOrg(spouse_id, org_id):
        model.AddMemberToOrg(spouse_id, org_id)
else:
    _notify_no_spouse(people_id, org_id)
