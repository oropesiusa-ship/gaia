"""Canonical immutable task/trace custody; no tool accepts an arbitrary path."""
import json
import os
from pathlib import Path
import re
import tempfile
from ..provenance import canonical_json
from .schema import KINDS,seal,validate,validate_task


class CognitiveStore:
    def __init__(self,state):self.root=Path(state)/'cognition'

    def path(self,kind,identifier):
        if kind not in KINDS or not re.fullmatch(r'cg[a-f0-9]{24}',identifier):raise ValueError('INVALID_STORE_ID')
        path=self.root/kind.lower()/(identifier+'.json')
        if any(p.is_symlink()for p in (self.root.parent,self.root,path.parent,path)):raise ValueError('STORE_SYMLINK_DENIED')
        return path

    def put(self,value):
        validate(value);path=self.path(value['kind'],value['id']);path.parent.mkdir(parents=True,exist_ok=True)
        raw=canonical_json(value)
        if path.exists():
            if path.read_bytes()!=raw:raise ValueError('IMMUTABLE_STORE_CONFLICT')
            return value
        fd,tmp=tempfile.mkstemp(prefix='.pending-',dir=path.parent)
        try:
            with os.fdopen(fd,'wb')as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno());os.fchmod(stream.fileno(),0o444)
            try:os.link(tmp,path)
            except FileExistsError:
                if path.read_bytes()!=raw:raise ValueError('IMMUTABLE_STORE_CONFLICT')
            directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(directory)
            finally:os.close(directory)
        finally:Path(tmp).unlink(missing_ok=True)
        return value

    def get(self,identifier,kind):
        path=self.path(kind,identifier)
        if path.stat().st_size>4*2**20:raise ValueError('STORE_INPUT_BOUND')
        raw=path.read_bytes();v=validate(json.loads(raw))
        if v['kind']!=kind or v['id']!=identifier or canonical_json(v)!=raw:raise ValueError('STORE_IDENTITY_MISMATCH')
        return v

    def list(self,kind):
        self.path(kind,'cg'+'0'*24)
        return sorted([self.get(p.stem,kind)for p in (self.root/kind.lower()).glob('cg*.json')],key=lambda v:(v['created_at'],v['id']))

    def save_task(self,task):return self.put(seal('TASK',validate_task(task)))
