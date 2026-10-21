"""Independent immutable local-intelligence evidence. Heavy reproducible artifacts stay separate."""
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
from ..provenance import canonical_json
from .schema import KINDS, validate


class IntelligenceStore:
    def __init__(self,state):
        self.directory=Path(state)/'local-intelligence'

    def path(self,kind,identifier):
        if kind not in KINDS or not re.fullmatch(r'li[a-f0-9]{24}',identifier): raise ValueError('Invalid intelligence ID')
        p=self.directory/kind.lower()/(identifier+'.json')
        if self.directory.is_symlink() or p.parent.is_symlink() or p.is_symlink(): raise ValueError('Intelligence symlink denied')
        return p

    def put(self,value):
        validate(value)
        if self.directory.is_symlink(): raise ValueError('Intelligence store symlink')
        self.directory.mkdir(parents=True,exist_ok=True)
        with (self.directory/'.lock').open('a+b') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            p=self.path(value['kind'],value['id']);p.parent.mkdir(exist_ok=True)
            data=canonical_json(value)
            if p.exists():
                if p.read_bytes()!=data: raise ValueError('Intelligence overwrite denied')
                return value
            fd,tmp=tempfile.mkstemp(prefix='.pending-',dir=p.parent)
            try:
                with os.fdopen(fd,'wb') as stream:
                    stream.write(data);stream.flush();os.fchmod(stream.fileno(),0o444);os.fsync(stream.fileno())
                os.link(tmp,p)
                self._sync(p.parent);self._sync(self.directory)
            finally:Path(tmp).unlink(missing_ok=True)
        return value

    def _sync(self,path):
        fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)

    def read(self,identifier,kind=None):
        if identifier=='latest':
            values=self.list(kind or 'SELECTION')
            if not values:raise ValueError('No intelligence artifacts')
            return values[-1]
        candidates=[self.path(k,identifier) for k in ([kind] if kind else sorted(KINDS))]
        p=next((p for p in candidates if p.exists()),None)
        if p is None:raise ValueError('Unknown intelligence artifact')
        data=p.read_bytes();value=validate(json.loads(data))
        if value['id']!=identifier or canonical_json(value)!=data:raise ValueError('Intelligence canonical identity mismatch')
        return value

    def list(self,kind):
        if kind not in KINDS or self.directory.is_symlink() or (self.directory/kind.lower()).is_symlink():raise ValueError('Invalid intelligence category')
        return sorted([self.read(p.stem,kind) for p in (self.directory/kind.lower()).glob('li*.json')],key=lambda v:(v['created_at'],v['id']))
