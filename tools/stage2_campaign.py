"""Dedicated Stage2 campaign entrypoint, not a general CLI.

All new inference scratch is bound to attempt/backend-work and its frozen
directory identity. Historical backend work remains preserved and irrelevant
to this operational scope, never adopted. Original artifacts and selection are
still qualified unchanged. Direct external gaia.py CLI runs are uninstrumented.
"""
import argparse
import runpy
import sys
from pathlib import Path
from tools.stage2_scratch import Lifecycle,instrument


def main():
    p=argparse.ArgumentParser(description=__doc__)
    # Preserve the existing /proc controller detector and telemetry role token.
    p.add_argument('command',choices=['autonomy-run'])
    p.add_argument('--session',required=True)
    p.add_argument('--campaign',required=True)
    p.add_argument('--state-dir',required=True)
    p.add_argument('--journal',required=True)
    p.add_argument('--scratch-root',required=True)
    p.add_argument('--scratch-device',type=int,required=True)
    p.add_argument('--scratch-inode',type=int,required=True)
    args=p.parse_args()
    scratch=Path(args.scratch_root)
    if scratch!=Path(args.state_dir).parent/'backend-work' or not scratch.is_absolute():
        p.error('STAGE2_SCRATCH_ROOT_BINDING_MISMATCH')
    lifecycle=Lifecycle(args.journal,args.session,args.campaign,scratch,
                        {'device':args.scratch_device,'inode':args.scratch_inode})
    root=Path(__file__).resolve().parents[1]
    sys.argv=[str(root/'gaia.py'),'autonomy-run',args.campaign,'--state-dir',args.state_dir,'--authorize-campaign']
    with instrument(lifecycle):runpy.run_path(str(root/'gaia.py'),run_name='__main__')


if __name__=='__main__':main()
