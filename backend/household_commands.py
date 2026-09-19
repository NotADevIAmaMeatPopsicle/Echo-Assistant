"""Explicit, anchored list commands. Quoted documents are never executed."""
import re
from .household import HouseholdUnavailable,HouseholdConflict

LISTS=r'(shopping list|to[ -]?do list|task list|notes)'


def identify(value):
    return 'shopping' if value.lower()=='shopping list' else 'notes' if value.lower()=='notes' else 'tasks'


def parse(text):
    text=text.strip().rstrip('.!?')
    prefix=r'(?:please\s+)?'
    match=re.fullmatch(prefix+r'(?:show|read|list|what is on|what\'s on) (?:my |the )?'+LISTS,text,re.I)
    if match: return ('list',identify(match[1]),'')
    match=re.fullmatch(prefix+r'add (.{1,500}?) to (?:my |the )?'+LISTS,text,re.I)
    if match: return ('add',identify(match[2]),match[1])
    match=re.fullmatch(prefix+r'(?:save|make) (?:a )?note(?::| that)\s*(.{1,500})',text,re.I)
    if match: return ('add','notes',match[1])
    match=re.fullmatch(prefix+r'(?:remove|delete) (.{1,500}?) from (?:my |the )?'+LISTS,text,re.I)
    if match: return ('delete',identify(match[2]),match[1])
    match=re.fullmatch(prefix+r'(?:check off|complete) (.{1,500}?) (?:on|from) (?:my |the )?'+LISTS,text,re.I)
    if match: return ('complete',identify(match[2]),match[1])
    return None


def respond(store,command):
    action,kind,text=command
    label={'shopping':'shopping list','tasks':'to-do list','notes':'notes'}[kind]
    try:
        state=store.snapshot(); items=[i for i in state['items'] if i['kind']==kind]
        if action=='list':
            active=[i for i in items if not i['done']]
            reply=('Your '+label+': '+ '; '.join(i['text'] for i in active[:10]))[:950] if active else 'Your '+label+' is empty.'
            if len(active)>10: reply+=' More are on the Lists page.'
        elif action=='add':
            store.change(state['revision'],kind=kind,text=text); reply='Added to your '+label+': '+text
        else:
            matches=[i for i in items if i['text'].casefold().strip()==text.casefold().strip()]
            if len(matches)!=1:
                return {'status':'unavailable','capability':'household','text':'I could not identify one exact item. Use its full wording, or select it on Lists.'}
            store.change(state['revision'],identifier=matches[0]['id'],delete=action=='delete',done=True if action=='complete' else None)
            reply=('Removed ' if action=='delete' else 'Checked off ')+text+'.'
        return {'status':'complete','capability':'household','text':reply}
    except (HouseholdUnavailable,HouseholdConflict,ValueError) as error:
        return {'status':'unavailable','capability':'household','text':str(error)}
