"""Release boundary checks, not a proof of anonymity for arbitrary new content."""
from pathlib import Path
import importlib.util
import json
import re
import tempfile

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('demo_data',ROOT/'supplychain/data.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
SKIP={'.git','.venv','__pycache__','.pytest_cache'}
ALLOWED={'.py','.md','.toml','.csv','.json','.png','.yml','.txt','.gitignore'}
PATTERNS={
    'private_sku':re.compile(r'\b(?:LOCAL_\d{4}|PRINT_\d{2}_\d{3})\b'),
    'email':re.compile(r'\b[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'),
    'mobile':re.compile(r'(?<![0-9A-Za-z_.])1[3-9]\d{9}(?![0-9A-Za-z_.])'),
    'isbn':re.compile(r'(?<![0-9A-Za-z_.])97[89]\d{10}(?![0-9A-Za-z_.])'),
    'github_secret':re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b'),
    'private_key':re.compile(r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----'),
    'absolute_local_path':re.compile(r'[A-Z]:[\\/](?:Users|02_Documents)[\\/]'),
}

def main():
    errors=[];count=0
    for p in ROOT.rglob('*'):
        if not p.is_file() or any(part in SKIP or part.endswith('.egg-info') for part in p.relative_to(ROOT).parts):continue
        count+=1
        if p.name not in {'LICENSE','.gitignore','.gitattributes'} and p.suffix not in ALLOWED: errors.append(f'Unexpected file type: {p.relative_to(ROOT)}')
        if p.suffix=='.png':continue
        text=p.read_text(encoding='utf-8')
        for name,pattern in PATTERNS.items():
            if pattern.search(text):errors.append(f'{name}: {p.relative_to(ROOT)}')
    manifest=json.loads((ROOT/'data/demo/manifest.json').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory() as temp:
        mod.generate_demo(temp,seed=manifest['seed'],n_skus=manifest['n_skus'],n_days=manifest['n_days'])
        for name,expected in manifest['sha256'].items():
            if mod.sha256(ROOT/'data/demo'/name)!=expected or mod.sha256(Path(temp)/name)!=expected:
                errors.append(f'Not identical to independently generated fixture: {name}')
    summary=json.loads((ROOT/'reports/demo/summary.json').read_text(encoding='utf-8'))
    if summary['data_mode']!='independent_synthetic' or summary['data_sha256']!=manifest['sha256']:
        errors.append('Published results are not linked to approved synthetic fixtures')
    if errors:raise SystemExit('\n'.join(errors))
    print(f'PASS: {count} release files; synthetic fixtures regenerated; result hashes and sensitive-pattern checks passed.')

if __name__=='__main__':main()
