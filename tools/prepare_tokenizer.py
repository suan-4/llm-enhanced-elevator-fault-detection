"""Download pinned tokenizer/license only. Never creates a calibration profile.

Use on a networked staging computer, then copy verified assets to the terminal.
The running application never downloads assets or connects to HuggingFace.
"""
import argparse
import hashlib
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def prepare(source, target, fetch):
    files = source['files']
    revision = source['revision']
    if (not files or not set(files) <= {'tokenizer.json', 'LICENSE'}
            or len(revision) != 40 or any(c not in '0123456789abcdef' for c in revision)):
        raise ValueError('Expected pinned tokenizer/license manifest')
    target.mkdir(parents=True, exist_ok=True)
    for name, info in files.items():
        path = target/name
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != info['sha256']:
                raise ValueError('Existing asset differs; choose a new staging directory')
            continue
        raw = fetch(f"https://huggingface.co/{source['model_repository']}/resolve/{revision}/{name}")
        if hashlib.sha256(raw).hexdigest() != info['sha256']:
            raise ValueError('Downloaded asset hash mismatch; not adopted')
        # Exclusive creation: do not overwrite files produced by another operator.
        with path.open('xb') as output:
            output.write(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'backend/data/tokenizers/qwen3.5-4b')
    parser.add_argument('--proxy', default=None, help='Per-command proxy; never changes system settings')
    args = parser.parse_args()
    source = json.loads((ROOT/'backend/app/data/tokenizer-source.json').read_text(encoding='utf8'))
    with httpx.Client(proxy=args.proxy, trust_env=False, timeout=120, follow_redirects=True) as client:
        def fetch(url):
            response = client.get(url)
            response.raise_for_status()
            return response.content
        prepare(source, args.output, fetch)
    print('Pinned tokenizer assets verified. SDK calibration is a separate step.')


if __name__ == '__main__': main()
