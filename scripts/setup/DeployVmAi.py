"""Deploy a separate AI data stack without adopting other projects' containers."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT

import json
import secrets

import paramiko
from resource_scope import OWNER


def main():
    private = ROOT / ".runtime/vm-app-private.json"
    admin = json.loads((ROOT / ".runtime/vm-bootstrap-private.json").read_text(encoding="utf-8"))
    cfg = json.loads(private.read_text(encoding="utf-8"))
    assert cfg["owner"] == OWNER and cfg["host"] == "192.168.6.100"
    for key in ("minio_password", "milvus_password", "neo4j_password", "qdrant_key"):
        cfg.setdefault(key, secrets.token_urlsafe(32))
    private.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    known = ROOT / ".runtime/vm-known-hosts"
    if known.exists():
        client.load_host_keys(str(known))
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(cfg["host"], port=admin["ssh_port"], username=admin["ssh_user"],
                   password=admin["ssh_password"], timeout=8, look_for_keys=False, allow_agent=False)
    client.save_host_keys(str(known))

    def run(command, timeout=300):
        _, out, err = client.exec_command(command, timeout=timeout)
        result, error = out.read().decode(errors="replace"), err.read().decode(errors="replace")
        code = out.channel.recv_exit_status()
        if code:
            raise RuntimeError("Owned AI stack deployment failed: " + error[-1000:])
        return result

    try:
        # Fail before mutation on container, volume, network, or port collisions.
        containers = json.loads(run("docker inspect $(docker ps -aq)"))
        for item in containers:
            if item["Name"].lstrip("/").startswith("aillisten-dev-"):
                if item["Config"].get("Labels", {}).get("aillisten.owner") != OWNER:
                    raise RuntimeError("A reserved container is not owned by this project")
        for kind in ("volume", "network"):
            ids = run(f"docker {kind} ls -q --filter name=aillisten-dev").split()
            if ids:
                resources = json.loads(run(f"docker {kind} inspect " + " ".join(ids)))
                for item in resources:
                    if (item.get("Labels") or {}).get("aillisten.owner") != OWNER:
                        raise RuntimeError("A reserved storage/network resource is unowned")
        listen = run("ss -lntH")
        for port in (39000,39001,39530,39091,47474,47687,36333,36334):
            if f":{port} " in listen and not any(
                str(port) in item.get("HostConfig", {}).get("PortBindings", {}).__str__()
                for item in containers if item["Name"].startswith("/aillisten-dev-")):
                raise RuntimeError("A reserved AI service port is already occupied")
        run("mkdir -p /opt/aillisten/dev/ai /opt/aillisten/dev/private && chmod 700 /opt/aillisten/dev/private")
        sftp = client.open_sftp()
        sftp.put(str(ROOT / "infra/vm/docker-compose.ai.yml"), "/opt/aillisten/dev/ai/docker-compose.yml")
        env = "\n".join(f"{name}={cfg[key]}" for name, key in (
            ("AILLISTEN_MINIO_PASSWORD", "minio_password"), ("AILLISTEN_NEO4J_PASSWORD", "neo4j_password"),
            ("AILLISTEN_QDRANT_KEY", "qdrant_key"))) + "\n"
        milvus = "common:\n  security:\n    authorizationEnabled: true\n    defaultRootPassword: " + cfg["milvus_password"] + "\n"
        for filename, content in (("ai.env", env), ("milvus.yaml", milvus)):
            path = "/opt/aillisten/dev/private/" + filename
            with sftp.open(path, "w") as out:
                out.write(content)
            sftp.chmod(path, 0o600)
        sftp.close()
        print("Starting only aillisten-dev AI containers; private configuration uploaded", flush=True)
        run("cd /opt/aillisten/dev/ai && docker compose --env-file ../private/ai.env up -d", timeout=600)
        result = run("docker ps --filter label=aillisten.owner=aillisten-dev/v1 --format '{{.Names}} | {{.Status}}'")
        print(result, flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
