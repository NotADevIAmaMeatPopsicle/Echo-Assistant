"""Check publishable source for private artifacts and common credential formats.

This complements a dedicated secret scanner; it is not a complete security audit.
With a Git index, inspect staged bytes so the result applies to the proposed commit.
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = {'local','backups','output','.venv','.pio','.playwright-cli','node_modules',
           '__pycache__','.pytest_cache','.codex-remote-attachments'}
FORBIDDEN_SUFFIXES = {'.bin','.elf','.map','.pem','.key','.pfx','.p12','.dpapi',
                      '.echo-backup','.sqlite','.sqlite3','.db','.onnx','.safetensors','.log'}
PATTERNS = {
    'private key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    'GitHub credential': re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b'),
    'provider credential': re.compile(rb'\b(?:sk-(?:proj-|ant-api\d+-)?[A-Za-z0-9_-]{24,}|hf_[A-Za-z0-9]{25,}|AKIA[A-Z0-9]{16})\b'),
    'personal Windows path': re.compile(rb'(?i)[a-z]:[\\/](?:Users|Documents and Settings)[\\/][^\s\x00]+'),
    'personal macOS path': re.compile(rb'/Users/[A-Za-z0-9_.-]+/'),
}


def inspect(staged=True):
    result = subprocess.run(['git','ls-files','-z'],cwd=ROOT,capture_output=True)
    indexed = result.returncode == 0 and bool(result.stdout)
    paths = result.stdout.decode().strip('\0').split('\0') if indexed else [
        p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*')
        if p.is_file() and not any(part in PRIVATE|{'.git'} for part in p.relative_to(ROOT).parts)]
    findings=[]
    for name in paths:
        p=Path(name)
        if (set(p.parts)&PRIVATE or p.suffix.lower() in FORBIDDEN_SUFFIXES
            or (p.name.startswith('.env') and p.name!='.env.example')
            or p.name.startswith('secrets.')
            or name.startswith(('deploy/host/context/','deploy/remote/backend/'))):
            findings.append((name,0,'private/generated artifact'));continue
        if (ROOT/p).is_symlink():
            findings.append((name,0,'symbolic link requires explicit review'));continue
        raw=subprocess.check_output(['git','show',':'+name],cwd=ROOT) if indexed and staged else (ROOT/p).read_bytes()
        for kind, pattern in PATTERNS.items():
            for match in pattern.finditer(raw):
                findings.append((name,raw[:match.start()].count(b'\n')+1,kind))
    return len(paths),findings


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worktree',action='store_true')
    args=parser.parse_args()
    count,findings=inspect(staged=not args.worktree)
    for name,line,kind in findings:print(f'{name}:{line}: {kind}')
    print(f'Publication guard: {count} files, {len(findings)} findings. Matched values are never printed.')
    sys.exit(bool(findings))
