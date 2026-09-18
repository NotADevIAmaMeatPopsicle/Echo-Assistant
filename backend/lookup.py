"""Preserve provider citations as safe, clickable references and clean spoken text."""
import ipaddress
import re
from urllib.parse import urlsplit


def safe_url(value):
    try:
        if not isinstance(value,str) or len(value)>2048 or '\\' in value or any(ord(c)<33 for c in value): return False
        url=urlsplit(value)
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.port not in (None,443): return False
        host=url.hostname.lower()
        if '.' not in host or host.endswith(('.localhost','.local','.internal')): return False
        try:
            if not ipaddress.ip_address(host).is_global: return False
        except ValueError:
            if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z][a-z0-9-]*',host):return False
        return True
    except ValueError:return False


class Answer(str):
    def __new__(cls,text,display_text=None,sources=None,searched=False):
        value=super().__new__(cls,text)
        value.display_text=display_text or text;value.sources=sources or [];value.searched=searched
        return value


def cited_answer(blocks,searched=False, *, limit=1100):
    sources=[];parts=[]
    for block in blocks:
        if not isinstance(block,dict) or block.get('type')!='output_text' or not isinstance(block.get('text'),str):continue
        text=block['text'];replacements=[];trailing=[]
        annotations=block.get('annotations',[])
        if not isinstance(annotations,list): annotations=[]
        for annotation in annotations:
            if not isinstance(annotation,dict) or annotation.get('type')!='url_citation':continue
            url=annotation.get('url');start=annotation.get('start_index');end=annotation.get('end_index')
            if not safe_url(url):continue
            existing=next((i for i,s in enumerate(sources) if s['url']==url),None)
            if existing is None:
                if len(sources)>=10:continue
                title=annotation.get('title')
                sources.append({'url':url,'title':title[:200] if isinstance(title,str) and title else urlsplit(url).hostname})
                existing=len(sources)-1
            label=f'[{existing+1}]'
            if (type(start)==int and type(end)==int and 0<=start<end<=len(text)
                    and not any(start<b and end>a for a,b,_ in replacements)):
                replacements.append((start,end,label))
            elif label not in trailing:
                # Some compatible providers give unusable character offsets.
                # Keep their verified citation metadata without deleting prose.
                trailing.append(label)
        for start,end,label in sorted(replacements,reverse=True):text=text[:start]+label+text[end:]
        if trailing:text+=' '+' '.join(trailing)
        parts.append(text)
    display=' '.join(parts).strip()
    if len(display)>limit:display=display[:limit-3].rsplit(' ',1)[0]+'…'
    # References remain in web display/history. The speaker never reads URLs or
    # provider-specific citation tokens aloud.
    spoken=re.sub(r'\[\d+\]|[^]*','',display)
    spoken=re.sub(r'\[([^\]]+)\]\(https?://[^)]+\)',r'\1',spoken)
    spoken=re.sub(r'https?://\S+','',spoken)
    spoken=re.sub(r'\*\*([^*]+)\*\*|__([^_]+)__',lambda match:match[1] or match[2],spoken)
    spoken=re.sub(r'`([^`]+)`',r'\1',spoken)
    spoken=re.sub(r'\s+',' ',spoken).strip()
    return Answer(spoken,display,sources,searched)


def lookup_request(text):
    return bool(re.match(r'\s*(?:please\s+)?(?:look\s+up\b|search\s+(?:the\s+web|online|for)\b|browse\s+(?:the\s+web|for)\b)',text,re.I))
