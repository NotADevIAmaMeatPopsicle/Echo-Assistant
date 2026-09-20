"""Calendar event identity and freshness without persisting agenda contents."""
import hashlib
import json
import re


def event_version(event):
    return hashlib.sha256(json.dumps({key:event.get(key) for key in
        ('uid','summary','description','location','start','end','recurrence_id','rrule','status')},
        sort_keys=True,separators=(',',':')).encode()).hexdigest()


def single_event(event):
    return (valid_identifier(event.get('uid'))
            and not event.get('recurrence_id') and not event.get('rrule'))


def valid_identifier(value):
    return isinstance(value,str) and 0<len(value)<=512 and not any(ord(c)<32 for c in value)


def event_reference(event,calendar,on_date):
    if not valid_identifier(event.get('uid')):return None
    recurrence=event.get('recurrence_id')
    if recurrence is not None and recurrence!='' and not valid_identifier(recurrence):return None
    result={'calendar':calendar,'uid':event['uid'],'on_date':on_date,'version':event_version(event)}
    if recurrence:result['recurrence_id']=recurrence
    return result


def change_scopes(event):
    if not valid_identifier(event.get('uid')):return {'edit':[],'delete':[]}
    if single_event(event):return {'edit':['single'],'delete':['single']}
    if valid_identifier(event.get('recurrence_id')):
        return {'edit':['occurrence','following'],'delete':['occurrence','following','series']}
    # A series UID without a provider occurrence ID must never be used to guess
    # an occurrence. Deleting the explicitly reviewed entire series is possible.
    return {'edit':[],'delete':['series']} if event.get('rrule') and not event.get('recurrence_id') else {'edit':[],'delete':[]}


def following_start_locked(event):
    rule=event.get('rrule')
    # HA's ical 14.2.0 splits COUNT series using the replacement start, which
    # can remove a remaining occurrence when its start moves later. Unknown
    # patterns cannot prove that they are uncounted. Preserve their start.
    return not isinstance(rule,str) or not rule or bool(re.search(r'(?:^|;)COUNT=',rule,re.I))
