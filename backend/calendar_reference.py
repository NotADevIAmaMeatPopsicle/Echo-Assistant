"""Calendar event identity and freshness without persisting agenda contents."""
import hashlib
import json


def event_version(event):
    return hashlib.sha256(json.dumps({key:event.get(key) for key in
        ('uid','summary','description','location','start','end','recurrence_id','rrule','status')},
        sort_keys=True,separators=(',',':')).encode()).hexdigest()


def single_event(event):
    uid=event.get('uid')
    return (isinstance(uid,str) and 0<len(uid)<=512 and not any(ord(c)<32 for c in uid)
            and not event.get('recurrence_id') and not event.get('rrule'))
