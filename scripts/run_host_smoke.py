#!/usr/bin/env python3
"""Fixed read-only host adapters for a cross-host discovery runtime smoke."""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
from typing import Any

TRUSTED_DIRS = ("/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/local/bin", "/opt/homebrew/bin", "/opt/local/bin")

def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
def trusted_path() -> str:
    return os.pathsep.join(path for path in TRUSTED_DIRS if Path(path).is_dir())
def resolve_host(host: str) -> str | None:
    name = "codex" if host == "codex" else "claude"
    value = shutil.which(name, path=trusted_path())
    return value if value and Path(value).name == name else None
def host_ready(host: str, executable: str) -> bool:
    if host != "claude-code":
        return True
    try:
        completed = subprocess.run(
            [executable, "auth", "status"], env={"PATH":trusted_path(),"LANG":"C","LC_ALL":"C"},
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=10, check=False,
        )
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
def load_fixture(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict) or set(value) != {"schema_version","run_id","snapshot_hash","discovery"} or value.get("schema_version") != 2:
        raise ValueError("unsupported fixture")
    discovery = value.get("discovery")
    if not isinstance(value.get("run_id"), str) or not isinstance(value.get("snapshot_hash"), str) or len(value["snapshot_hash"]) != 64 or not isinstance(discovery, dict) or set(discovery) != {"skill_md_sha256","challenge_sha256"}:
        raise ValueError("invalid fixture")
    return value
def schema() -> dict[str, Any]:
    return {"type":"object","additionalProperties":False,"required":["observed_discovery"],"properties":{"observed_discovery":{"type":"object","additionalProperties":False,"required":["skill_md_sha256","challenge_sha256"],"properties":{"skill_md_sha256":{"type":"string"},"challenge_sha256":{"type":"string"}}}}}
def prompt(fixture: dict[str, Any]) -> str:
    return "Invoke the installed review-orchestrator skill in read-only discovery mode. Read SKILL.md and use only `shasum -a 256 SKILL.md` to calculate its SHA-256. Return JSON observed_discovery with the installed manifest SHA-256 and this exact challenge: " + fixture["discovery"]["challenge_sha256"]
def build_argv(host: str, executable: str, repo: Path, schema_path: Path, output_path: Path, fixture: dict[str, Any]) -> list[str]:
    if host == "codex":
        return [executable,"exec","-m","gpt-5.6-luna","--sandbox","read-only","--ephemeral","--output-schema",str(schema_path),"--output-last-message",str(output_path),"-C",str(repo),prompt(fixture)]
    return [executable,"--print","--model","haiku","--effort","low","--max-budget-usd","0.10","--output-format","json","--json-schema",json.dumps(schema(),sort_keys=True),"--permission-mode","plan","--no-session-persistence","--tools","Read,Bash(shasum -a 256 SKILL.md)","--disallowedTools","Edit,Write",prompt(fixture)]
def normalized(host: str, fixture: dict[str, Any], status: str, observed: dict[str, str] | None = None) -> dict[str, Any]:
    model, effort = ("gpt-5.6-luna", "low") if host == "codex" else ("haiku", "low")
    return {"schema_version":3,"host":host,"run_id":fixture["run_id"],"fixture_hash":digest(fixture),"snapshot_hash":fixture["snapshot_hash"],"status":status,"model":model,"effort":effort,"observed_discovery":observed}
def parse_observed(raw: str, fixture: dict[str, Any]) -> dict[str, str] | None:
    try:
        value=json.loads(raw)
        # Claude JSON envelopes may contain the structured result as `result`.
        if isinstance(value,dict) and isinstance(value.get("result"),str): value=json.loads(value["result"])
        observed=value.get("observed_discovery") if isinstance(value,dict) else None
        if observed is None and isinstance(value, dict) and isinstance(value.get("structured_output"), dict): observed=value["structured_output"].get("observed_discovery")
        expected=fixture["discovery"]
        return observed if isinstance(observed,dict) and observed == expected else None
    except (ValueError,json.JSONDecodeError): return None
def main() -> int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--host",choices=("codex","claude-code"),required=True); p.add_argument("--fixture",required=True); p.add_argument("--repo",required=True); p.add_argument("--execute",action="store_true"); p.add_argument("--timeout-seconds",type=int,default=60); p.add_argument("--output",default="-"); a=p.parse_args()
    try:
        fixture=load_fixture(a.fixture); repo=Path(a.repo).resolve(); manifest=repo/"SKILL.md"
        if not manifest.is_file() or file_hash(manifest)!=fixture["discovery"]["skill_md_sha256"]: raise ValueError("manifest discovery contract failed")
        artifact=normalized(a.host,fixture,"not_run"); code=0
        if a.execute:
            executable=resolve_host(a.host)
            if not executable or not host_ready(a.host, executable): artifact["status"]="unavailable"; code=1
            else:
                with tempfile.TemporaryDirectory(prefix="review-host-smoke-") as td:
                    root=Path(td); schema_path=root/"schema.json"; response=root/"response.json"; schema_path.write_text(json.dumps(schema()))
                    try:
                        if a.host == "claude-code":
                            raw=root/"claude-output.json"
                            with raw.open("wb") as handle:
                                completed=subprocess.run(build_argv(a.host,executable,repo,schema_path,response,fixture),cwd=repo,env={"PATH":trusted_path(),"LANG":"C","LC_ALL":"C"},stdin=subprocess.DEVNULL,stdout=handle,stderr=subprocess.DEVNULL,timeout=a.timeout_seconds,check=False)
                            raw_text=raw.read_text(encoding="utf-8",errors="replace")
                        else:
                            completed=subprocess.run(build_argv(a.host,executable,repo,schema_path,response,fixture),cwd=repo,env={"PATH":trusted_path(),"LANG":"C","LC_ALL":"C"},stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=a.timeout_seconds,check=False)
                            raw_text=response.read_text() if response.exists() else ""
                        observed=parse_observed(raw_text,fixture)
                        if completed.returncode==0 and observed: artifact=normalized(a.host,fixture,"passed",observed)
                        else: artifact["status"]="failed"; code=1
                    except subprocess.TimeoutExpired:
                        artifact["status"]="unavailable"; code=1
        text=json.dumps(artifact,indent=2,sort_keys=True)+"\n"; sys.stdout.write(text) if a.output=="-" else Path(a.output).write_text(text); return code
    except (OSError,ValueError,json.JSONDecodeError) as exc:
        print(f"run_host_smoke: {exc}",file=sys.stderr); return 2
if __name__=="__main__": raise SystemExit(main())
