"""Offline backup/restore. Stop writes and retain the pre-restore backup first."""
import argparse
import json
from pathlib import Path
from private_store import transaction


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['backup','restore'])
    parser.add_argument('path',type=Path)
    parser.add_argument('--confirm-replace',action='store_true')
    args=parser.parse_args()
    if args.action=='backup':
        with transaction() as state:
            # Refuse to overwrite an earlier backup.
            with args.path.open('x',encoding='utf-8') as out:
                json.dump(state,out,ensure_ascii=False,indent=2,allow_nan=False)
    else:
        if not args.confirm_replace:
            parser.error('Restore replaces private state. Back up first; then pass --confirm-replace.')
        data=json.loads(args.path.read_text(encoding='utf-8'))
        required={'schema','sequence','orders','lots','reservations','movements','preferences','audit','config'}
        if not isinstance(data,dict) or data.get('schema')!=1 or not required.issubset(data):
            parser.error('Unsupported or incomplete backup')
        with transaction() as state:
            state.clear();state.update(data)
    print('Completed:',args.action)


if __name__=='__main__':
    main()
