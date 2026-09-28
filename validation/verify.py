import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET

meta = json.loads((Path(__file__).parent / 'case.json').read_text())
work = Path(sys.argv[1]).resolve()
evidence = Path(sys.argv[2]).resolve()
evidence.mkdir(parents=True, exist_ok=True)
python = sys.executable
is_sphere = meta['repo'].endswith('spherical-cnn')
summary = {}

def run(label, command, expected=0, cwd=work, timeout=180):
  with (evidence / (label + '.log')).open('w') as log:
    result = subprocess.run(command, cwd=cwd, env=os.environ.copy(),
                            stdout=log, stderr=subprocess.STDOUT,
                            timeout=timeout, check=False)
  text = (evidence / (label + '.log')).read_text(errors='replace')
  print(label, result.returncode, text[-250:], flush=True)
  assert result.returncode == expected, (label, text[-8000:])
  return text

def test(label, files, expected=0, cwd=work, cover=False):
  xml = evidence / (label + '.xml')
  command = [python, '-m', 'pytest', *files, '-q', '--tb=short',
             '--junitxml=' + str(xml)]
  if cover:
    command += ['--cov=' + ('spherical_cnn.weather' if is_sphere else 'kubric'),
                '--cov-branch', '--cov-report=json:' + str(evidence / 'coverage.json')]
  run(label, command, expected=expected, cwd=cwd)
  doc = ET.parse(xml)
  suites = list(doc.getroot().iter('testsuite'))
  counts = [sum(int(s.attrib.get(key, 0)) for s in suites)
            for key in ('tests', 'failures', 'errors', 'skipped')]
  summary[label] = counts
  print(label, counts, flush=True)
  return counts

assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=work, text=True).strip() == meta['head']
source = work / meta['source']
fixed = source.read_bytes()
original = subprocess.check_output(['git', 'show', meta['base'] + ':' + meta['source']], cwd=work)
run('dependencies', [python, '-m', 'pip', 'freeze'])
run('test-dependency-check', [python, '-m', 'pip', 'check'])
try:
  counts = test('fixed-focused', [meta['test']], cover=True)
  assert counts == meta['restored-final'], counts
  if not is_sphere:
    assert test('fixed-suite', meta['suite_args']) == [106, 0, 0, 2]
  source.write_bytes(original)
  assert test('original-focused', [meta['test']], expected=1) == meta['original-final']
  if not is_sphere:
    existing = [x for x in meta['suite_args'] if x != meta['test']]
    assert test('existing-baseline', existing) == [70, 0, 0, 2]
finally:
  source.write_bytes(fixed)
assert test('restored-focused', [meta['test']]) == meta['restored-final']
run('source-restored', ['git', 'diff', '--exit-code'])
run('new-test-lint', [python, '-m', 'ruff', 'check', '--isolated',
    '--select', 'E9,F63,F7,F82,F401,F841', meta['test']])
run('source-correctness-lint', [python, '-m', 'ruff', 'check', '--isolated',
    '--select', 'E9,F63,F7,F82', meta['source']])
run('new-test-format', [python, '-m', 'pyink', '--check', '--pyink-indentation', '2',
    '--pyink-use-majority-quotes', '--line-length', '80' if is_sphere else '100', meta['test']])
run('patch-check', ['git', 'diff', '--check', meta['base']])
run('compile', [python, '-m', 'py_compile', meta['source'], meta['test']])
archive = subprocess.check_output(['git', 'archive', meta['head']], cwd=work)
with tempfile.TemporaryDirectory() as directory:
  export = Path(directory)
  with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
    tar.extractall(export, filter='data')
  module = 'spherical_cnn' if is_sphere else 'kubric'
  code = f'import {module}; from pathlib import Path; p=Path({module}.__file__).resolve(); print(p); assert p.is_relative_to(Path({str(export)!r}))'
  run('exported-import', [python, '-c', code], cwd=export)
  assert (export / meta['source']).read_bytes() == fixed
  counts = test('exported-suite', meta['suite_args'], cwd=export)
  assert counts == (meta['restored-final'] if is_sphere else [106, 0, 0, 2])
(evidence / 'summary.json').write_text(json.dumps({'head': meta['head'], 'tests': summary}, indent=2))
print('VERIFICATION COMPLETE', meta['head'], flush=True)
