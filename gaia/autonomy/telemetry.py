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


def memory():
    """Host memory against the plan reserve: stop before available memory falls below max(2 GiB, 15 % of RAM)."""
    info={}
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            k,v=line.split(':',1);info[k]=int(v.split()[0])*1024
    except (OSError,ValueError):return {'available_bytes':None,'total_bytes':None,'reserve_bytes':None,'below_reserve':False}
    total,available=info.get('MemTotal'),info.get('MemAvailable');reserve=max(2*2**30,int(0.15*total))if total else None
    return {'available_bytes':available,'total_bytes':total,'reserve_bytes':reserve,'swap_free_bytes':info.get('SwapFree'),
            'below_reserve':bool(available is not None and reserve and available<reserve)}


def vram():
    """GPU memory in use, from nvidia-smi when present (bounded call); absent GPUs are reported, never guessed."""
    import subprocess
    try:
        out=subprocess.run(['nvidia-smi','--query-gpu=index,memory.used,memory.total','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=5)
        rows=[[int(x)for x in line.split(',')]for line in out.stdout.strip().splitlines()]if out.returncode==0 else[]
        return {'gpus':[{'index':i,'used_mib':u,'total_mib':t}for i,u,t in rows],'source':'NVIDIA_SMI'if rows else'UNAVAILABLE'}
    except (OSError,ValueError,subprocess.SubprocessError):return {'gpus':[],'source':'UNAVAILABLE'}


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
        for path in self.files():
            try:lines=path.read_text().splitlines()
            except OSError:continue  # rotated away while reading
            for x in lines:
                try:rows.append(json.loads(x))
                except ValueError:pass  # a line still being written
        return rows


def bound_log(path,limit=LOG_BYTES):
    """Keep a campaign log within limit bytes: the head is kept and the tail truncated, recorded once."""
    path=Path(path)
    if path.exists()and path.stat().st_size>limit:
        with path.open('r+b')as f:f.truncate(limit);f.seek(limit);f.write(b'\n[GAIA: log truncated at the session log bound]\n')
        return True
    return False
