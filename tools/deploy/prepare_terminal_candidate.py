"""Validate/extract a terminal UI artifact without touching production programs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from zipfile import ZipFile

release = Path(sys.argv[1]).resolve()
assert os.geteuid() == 0
assert release.parent == Path('/userdata/releases') and release.name.startswith('terminal-ui-')
package = release/'candidate.zip'
assert hashlib.sha256(package.read_bytes()).hexdigest() == sys.argv[2]
candidate = release/'candidate'
assert not candidate.exists(), 'Use a new release path'
candidate.mkdir()
with ZipFile(package) as archive:
    for entry in archive.infolist():
        destination = (candidate/entry.filename).resolve()
        assert candidate in destination.parents
        assert entry.filename == 'release-manifest.json' or entry.filename.startswith(('backend/app/', 'web/dist/', 'tools/'))
        archive.extract(entry, candidate)
manifest = json.loads((candidate/'release-manifest.json').read_text())
for name, digest in manifest['files'].items():
    assert hashlib.sha256((candidate/name).read_bytes()).hexdigest() == digest, name
source_env = Path('/home/ubuntu/elevator/backend/.env')
shutil.copy2(source_env, candidate/'backend/.env')
(candidate/'backend/.env').chmod(0o600)
release.chmod(0o700)
print(json.dumps(dict(candidate=str(candidate), verified_files=len(manifest['files']), package_sha256=sys.argv[2])))
