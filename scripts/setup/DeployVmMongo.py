"""Idempotently deploy only the owned MongoDB container; retain its volume."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT
import json
import secrets
import paramiko
from resource_scope import OWNER


def main():
    private=ROOT/'.runtime/vm-app-private.json'
    cfg=json.loads(private.read_text(encoding='utf-8'))
    admin=json.loads((ROOT/'.runtime/vm-bootstrap-private.json').read_text(encoding='utf-8'))
    assert cfg['owner']==OWNER and cfg['host']=='192.168.6.100'
    cfg.setdefault('mongo_password',secrets.token_urlsafe(32))
    private.write_text(json.dumps(cfg,indent=2),encoding='utf-8')
    ssh=paramiko.SSHClient();ssh.load_system_host_keys()
    known=ROOT/'.runtime/vm-known-hosts'
    if known.exists():ssh.load_host_keys(str(known))
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(cfg['host'],port=admin['ssh_port'],username=admin['ssh_user'],password=admin['ssh_password'],look_for_keys=False,allow_agent=False,timeout=8)
    ssh.save_host_keys(str(known))
    def run(command,timeout=30):
        _,out,err=ssh.exec_command(command,timeout=timeout);text=out.read().decode();error=err.read().decode()
        if out.channel.recv_exit_status():raise RuntimeError('Owned MongoDB setup failed: '+error[-400:])
        return text
    try:
        items=[json.loads(line) for line in run("docker ps -a --format '{{json .}}'").splitlines()]
        existing=next((r for r in items if r['Names']=='aillisten-dev-mongo'),None)
        if existing:
            label=run("docker inspect --format '{{index .Config.Labels \"aillisten.owner\"}}' aillisten-dev-mongo").strip()
            if label!=OWNER:raise RuntimeError('Reserved MongoDB name belongs to another project')
            if existing['State']!='running':run('docker start aillisten-dev-mongo')
            print('Owned MongoDB container ready; data volume retained');return
        if ':37017 ' in run('ss -lntH'):raise RuntimeError('MongoDB port belongs to another process')
        volumes=run('docker volume ls -q --filter name=^aillisten-dev-mongo-data$').split()
        if volumes:
            if run("docker volume inspect --format '{{index .Labels \"aillisten.owner\"}}' aillisten-dev-mongo-data").strip()!=OWNER:
                raise RuntimeError('MongoDB volume ownership mismatch')
        else:run('docker volume create --label aillisten.owner=aillisten-dev/v1 aillisten-dev-mongo-data')
        run('mkdir -p /opt/aillisten/dev/private && chmod 700 /opt/aillisten/dev/private')
        sftp=ssh.open_sftp()
        with sftp.open('/opt/aillisten/dev/private/mongo.env','w') as file:file.write('MONGO_INITDB_ROOT_USERNAME=aillisten_admin\nMONGO_INITDB_ROOT_PASSWORD='+cfg['mongo_password']+'\n')
        sftp.chmod('/opt/aillisten/dev/private/mongo.env',0o600);sftp.close()
        if not run('docker images -q mongo:7.0').strip():run('docker pull mongo:7.0',timeout=300)
        run('docker create --name aillisten-dev-mongo --label aillisten.owner=aillisten-dev/v1 --memory 768m --cpus 1.5 --restart unless-stopped -p 192.168.6.100:37017:27017 --mount type=volume,source=aillisten-dev-mongo-data,target=/data/db --env-file /opt/aillisten/dev/private/mongo.env mongo:7.0 --wiredTigerCacheSizeGB 0.25')
        run('docker start aillisten-dev-mongo')
        print('Created dedicated MongoDB on port 37017')
    finally:ssh.close()


if __name__=='__main__':main()
