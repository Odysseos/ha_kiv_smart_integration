# SPDX-License-Identifier: GPL-3.0-only
"""Static contract of the distribution, docs and unchanged manual YAML."""
import ast
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT/'custom_components/vakio_kiv_local/manifest.json').read_text())
    assert manifest['domain'] == 'vakio_kiv_local'
    assert manifest['name'] == 'Vakio KIV Local' and manifest['dependencies'] == ['mqtt']
    assert manifest['config_flow'] and manifest['version']
    assert len(list((ROOT/'custom_components').iterdir())) == 1
    json.loads((ROOT/'hacs.json').read_text())
    for name, expected in json.loads((ROOT/'tests/manual_sha256.json').read_text()).items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == expected, name
    for path in ROOT.rglob('*'):
        if any(part in ('.git','.deps','.venv','__pycache__') for part in path.parts) or not path.is_file():
            continue
        if path.suffix == '.py':
            ast.parse(path.read_text(), filename=str(path))
        if path.suffix == '.json':
            json.loads(path.read_text())
        if path.suffix == '.md':
            for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
                if not target.startswith(('https:','http:','#')):
                    assert (path.parent/target.split('#')[0]).exists(), (path,target)
    print('PASS: project metadata, Python/JSON syntax, docs links, unchanged manual YAML')


if __name__ == '__main__':
    main()
