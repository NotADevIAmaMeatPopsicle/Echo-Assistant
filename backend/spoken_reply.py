"""Keep spoken answers within the local synthesizer's bound without losing context.

The full answer remains in the API's volatile conversation. This only limits
the speech portion, with an explicit invitation to continue.
"""
import re


def spoken_reply(text):
    text=re.sub(r'\s+',' ',str(text)).strip()
    if not text:return 'I did not receive an answer. Please try again.'
    if len(text)<=1200:return text
    ending=' I can continue if you would like.'
    prefix=text[:1200-len(ending)]
    sentences=list(re.finditer(r'[.!?]["\u201d\u2019]?\s',prefix))
    if sentences and sentences[-1].end()>=300:
        prefix=prefix[:sentences[-1].end()].rstrip()
    else:
        prefix=prefix.rsplit(' ',1)[0].rstrip(',;:')+'…'
        prefix=prefix[:1200-len(ending)]
    return prefix+ending
