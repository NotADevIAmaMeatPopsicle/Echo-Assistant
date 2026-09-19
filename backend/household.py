"""Explicit household lists and notes, encrypted with the existing host protector."""
import base64
from copy import deepcopy
import json
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HouseholdUnavailable(RuntimeError):
    pass


class HouseholdConflict(ValueError):
    pass


class Entry(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str = Field(pattern=r'^[0-9a-f]{32}$')
    kind: Literal['shopping', 'tasks', 'notes']
    text: str = Field(min_length=1, max_length=500)
    done: bool = False

    @field_validator('text')
    @classmethod
    def clean_text(cls, value):
        if not value.strip() or any(ord(c) < 32 and c not in '\n\t' for c in value):
            raise ValueError('Use readable text.')
        return value.strip()


class Document(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    items: list[Entry] = Field(default_factory=list, max_length=200)


class HouseholdStore:
    def __init__(self, root: Path | None, protector):
        self.path = root / 'local/echo-household.json' if root else None
        self.protector, self.lock = protector, RLock()
        self.document, self.error = Document(), False
        if self.path and self.path.exists():
            try:
                if self.path.stat().st_size > 800_000:
                    raise ValueError('Oversized household file')
                envelope = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(envelope, dict) or envelope.get('version') != 1:
                    raise ValueError('Unsupported household file')
                raw = protector.decrypt(base64.b64decode(envelope['protected'], validate=True))
                self.document = Document.model_validate_json(raw)
                ids = [item.id for item in self.document.items]
                if len(set(ids)) != len(ids):
                    raise ValueError('Duplicate item')
            except (OSError, ValueError, TypeError, KeyError, RuntimeError):
                self.error = True

    def snapshot(self):
        with self.lock:
            if self.error:
                raise HouseholdUnavailable('Saved lists could not be read. The existing file is preserved.')
            return {**self.document.model_dump(), 'storage': 'encrypted' if self.path else 'session'}

    def change(self, revision, *, text=None, kind=None, identifier=None, done=None, delete=False, position=None):
        with self.lock:
            self.snapshot()
            if revision != self.document.revision:
                raise HouseholdConflict('The list changed on another screen. Refresh before trying again.')
            draft = deepcopy(self.document)
            if identifier:
                item = next((item for item in draft.items if item.id == identifier), None)
                if item is None:
                    raise KeyError(identifier)
                if delete:
                    draft.items.remove(item)
                else:
                    values = item.model_dump()
                    if text is not None:
                        values['text'] = text
                    if done is not None:
                        values['done'] = done
                    draft.items[draft.items.index(item)] = Entry.model_validate(values)
                    if position is not None:
                        siblings=[entry for entry in draft.items if entry.kind==item.kind]
                        if type(position) is not int or not 0<=position<len(siblings): raise ValueError('Choose a position in this list')
                        moved=next(entry for entry in siblings if entry.id==identifier)
                        siblings.remove(moved); siblings.insert(position,moved)
                        ordered=iter(siblings)
                        draft.items=[next(ordered) if entry.kind==item.kind else entry for entry in draft.items]
            else:
                if len(draft.items) >= 200:
                    raise ValueError('The household board is full. Remove an item first.')
                draft.items.append(Entry(id=uuid4().hex, kind=kind, text=text))
            draft.revision += 1
            if self.path:
                temporary = self.path.with_suffix('.tmp')
                try:
                    protected = self.protector.encrypt(draft.model_dump_json().encode('utf-8'))
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    temporary.write_text(json.dumps({'version': 1, 'protected': base64.b64encode(protected).decode('ascii')}), encoding='utf-8')
                    temporary.replace(self.path)
                except (OSError, RuntimeError):
                    raise HouseholdUnavailable('The change could not be saved. Previous items are unchanged.') from None
            self.document = draft
            return self.snapshot()
