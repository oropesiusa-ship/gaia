"""Storage by owner with session gates (1.1 §6) and bounded, rotated telemetry (1.1 §9)."""
import json
import os
from pathlib import Path
import shutil
from .clock import stamp
from .lineage import LineageStore,engine_state_dir
from .policy import disk_bytes
from .store import durable

GATES=(70,85,95)
TELEMETRY_FILE_BYTES=1*2**20
TELEMETRY_FILES=8
LOG_BYTES=8*2**20


def size(path):return disk_bytes(path)if Path(path).exists()else 0


def storage_by_owner(root,state,session):
    """Bytes per owner for a session: its campaigns, itself, its lineages' shared state, learning, cognition,
    observations, inference scratch and numpy engine state, plus its evidence and telemetry."""
    root,state=Path(root),Path(state);contract=session.read();owners=dict.fromkeys(
        ('campaigns','session','evidence','telemetry','logs','shared_state','learning','cognition','observations','inference_scratch','engine'),0)
    for campaign in {e['payload']['campaign_id']for e in session.events()if e['kind']=='CAMPAIGN_STARTED'}:
        owners['campaigns']+=size(state/'autonomy'/'campaigns'/campaign)
    for name,owner in (('evidence','evidence'),('telemetry','telemetry'),('logs','logs')):owners[owner]=size(session.root/name)
    owners['session']=size(session.root)-owners['evidence']-owners['telemetry']-owners['logs']
    for lineage_id in contract['lineages']:
        lineage=LineageStore(state,lineage_id).root;sub=lineage/'subsystems'
        parts={'learning':size(sub/'learning'),'cognition':size(sub/'cognition'),'observations':size(sub/'observations'),'inference_scratch':size(lineage/'inference')}
        for k,v in parts.items():owners[k]+=v
        owners['shared_state']+=size(lineage)-sum(parts.values())
        owners['engine']+=size(root/engine_state_dir(lineage_id))
    return owners


def filesystem(path):
    usage=shutil.disk_usage(path);reserve=max(5*2**30,usage.total//10)
    return {'total_bytes':usage.total,'free_bytes':usage.free,'reserve_bytes':reserve,'below_reserve':usage.free<reserve}


def gates(used,ceiling):
    """Highest crossed gate (percent of the session storage ceiling), or None."""
    percent=100*used/ceiling if ceiling else 100
    return next((g for g in reversed(GATES)if percent>=g),None),percent


class Telemetry:
    """Append-only samples in at most TELEMETRY_FILES files of TELEMETRY_FILE_BYTES each; the oldest file is dropped."""
    def __init__(self,directory):self.directory=Path(directory)

    def files(self):return sorted(self.directory.glob('samples-*.jsonl'))if self.directory.exists()else[]

    def append(self,sample):
        self.directory.mkdir(parents=True,exist_ok=True);files=self.files()
        line=(json.dumps({**sample,'clock':sample.get('clock')or stamp()},sort_keys=True,default=str)+'\n').encode()
        if not files or files[-1].stat().st_size+len(line)>TELEMETRY_FILE_BYTES:
            index=int(files[-1].stem.split('-')[1])+1 if files else 1
            files.append(self.directory/f'samples-{index:06d}.jsonl')
        with files[-1].open('ab')as f:f.write(line);f.flush();os.fsync(f.fileno())
        for old in self.files()[:-TELEMETRY_FILES]:old.unlink()

    def samples(self):
        rows=[]
        for path in self.files():rows+=[json.loads(x)for x in path.read_text().splitlines()if x.strip()]
        return rows


def bound_log(path,limit=LOG_BYTES):
    """Keep a campaign log within limit bytes: the head is kept and the tail truncated, recorded once."""
    path=Path(path)
    if path.exists()and path.stat().st_size>limit:
        with path.open('r+b')as f:f.truncate(limit);f.seek(limit);f.write(b'\n[GAIA: log truncated at the session log bound]\n')
        return True
    return False
