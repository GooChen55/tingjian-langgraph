"""Read-only inventory comparison of all containers outside this project."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT
import argparse
import json
import paramiko
from resource_scope import OWNER


def inventory():
    cfg=json.loads((ROOT/'.runtime/vm-bootstrap-private.json').read_text(encoding='utf-8'))
    ssh=paramiko.SSHClient();ssh.load_system_host_keys();ssh.load_host_keys(str(ROOT/'.runtime/vm-known-hosts'))
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    ssh.connect(cfg['host'],port=cfg['ssh_port'],username=cfg['ssh_user'],password=cfg['ssh_password'],timeout=8,look_for_keys=False,allow_agent=False)
    try:
        _,out,err=ssh.exec_command("docker ps -a --format '{{json .}}'",timeout=15)
        rows=[json.loads(line) for line in out.read().decode().splitlines()]
        if out.channel.recv_exit_status():raise RuntimeError('Container inventory failed')
        return {r['Names']:{'id':r['ID'],'image':r['Image'],'state':r['State']} for r in rows if not r['Names'].startswith('aillisten-dev-')}
    finally:ssh.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--capture',action='store_true');args=parser.parse_args()
    path=ROOT/'.runtime/fusion-foreign-container-baseline.json'
    current=inventory()
    if args.capture:
        if path.exists():raise RuntimeError('Baseline already exists; refusing to overwrite evidence')
        path.write_text(json.dumps(current,indent=2),encoding='utf-8')
        print('Captured foreign container inventory:',len(current))
    else:
        before=json.loads(path.read_text(encoding='utf-8'))
        reboot_file=ROOT/'.runtime/fusion-vm-reboot-observation.json'
        observation=json.loads(reboot_file.read_text(encoding='utf-8')) if reboot_file.exists() else None
        expected=observation['post_reboot_inventory'] if observation else before
        assert expected==current,'Foreign container inventory changed; inspect before claiming isolation'
        report={'owner':OWNER,'passed':True,'foreign_containers_unchanged_since_checkpoint':len(current),
                'original_baseline_retained':True,'vm_reboot_observed':bool(observation),
                'changes_across_reboot':list(observation['external_reboot_changes']) if observation else []}
        (ROOT/'.runtime/fusion-isolation-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report))
