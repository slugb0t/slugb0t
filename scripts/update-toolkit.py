"""Build local SVG tool badges and audit their public repository evidence."""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
START, END = '<!-- toolkit:start -->', '<!-- toolkit:end -->'


def load_config():
    config = json.loads((ROOT / 'data/toolkit.json').read_text(encoding='utf-8'))
    ids = [tool['id'] for tool in config['tools']]
    if len(ids) != len(set(ids)):
        raise ValueError('Tool IDs must be unique.')
    groups = {group['id'] for group in config['groups']}
    for tool in config['tools']:
        if not re.fullmatch(r'[a-z0-9-]+', tool['id']) or tool['group'] not in groups:
            raise ValueError('Invalid tool ID or group.')
        if not tool['url'].startswith('https://') or not tool['evidence']:
            raise ValueError('Each tool needs an HTTPS link and evidence.')
        for item in tool['evidence']:
            if item['source'] not in config['sources'] or not item['contains']:
                raise ValueError('Invalid evidence source.')
    return config


def badge(tool):
    label = escape(tool['label'])
    width = max(87, round(len(tool['label']) * 7.4 + (48 if tool['icon'] else 25)))
    icon = ''
    if tool['icon']:
        source = ROOT / 'assets/toolkit/icons' / (tool['icon'] + '.svg')
        tree = ET.fromstring(source.read_text(encoding='utf-8'))
        ET.register_namespace('', 'http://www.w3.org/2000/svg')
        tree.attrib.update(x='11', y='9', width='18', height='18', fill='#bdb5db', color='#bdb5db')
        icon = ET.tostring(tree, encoding='unicode').replace('currentColor', '#bdb5db')
    x = 37 if icon else 12
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="36" viewBox="0 0 {width} 36" role="img" aria-label="{label}">\n'
        f'<title>{label}</title><rect x=".5" y=".5" width="{width - 1}" height="35" rx="6" fill="#1b2133" stroke="#45455f"/>\n'
        f'{icon}<text x="{x}" y="23" fill="#efe7d8" font-family="Segoe UI,Arial,sans-serif" font-size="13">{label}</text>\n</svg>\n'
    )


def readme_block(config):
    lines = [START, '']
    for group in config['groups']:
        if group.get('collapsed'):
            lines += ['<details>', f'<summary>{group["title"]}</summary>', '']
        else:
            lines += [f'**{group["title"]}**', '']
        lines.append('<p>')
        for tool in config['tools']:
            if tool['group'] == group['id']:
                lines.append(f'  <a href="{tool["url"]}"><img src="./assets/toolkit/{tool["id"]}.svg" alt="{escape(tool["label"])}" height="36"></a>')
        lines += ['</p>', '']
        if group.get('collapsed'):
            lines += ['</details>', '']
    return '\n'.join(lines) + END


def build(config, check):
    outputs = {ROOT / f'assets/toolkit/{tool["id"]}.svg': badge(tool) for tool in config['tools']}
    readme = ROOT / 'README.md'
    original = readme.read_text(encoding='utf-8')
    if original.count(START) != 1 or original.count(END) != 1:
        raise ValueError('README must contain one toolkit marker pair.')
    outputs[readme] = original[:original.index(START)] + readme_block(config) + original[original.index(END) + len(END):]
    changed = [path for path, content in outputs.items() if not path.exists() or path.read_text(encoding='utf-8') != content]
    if check:
        for path in changed:
            print('Needs regeneration: ' + path.relative_to(ROOT).as_posix())
        return not changed
    for path in changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(outputs[path], encoding='utf-8')
    print(f'Updated {len(changed)} files from {len(config["tools"])} curated tools.')
    return True


def fetch_source(item):
    path = urllib.parse.quote(item['path'], safe='/')
    endpoint = f'repos/{item["repository"]}/contents/{path}'
    try:
        if shutil.which('gh'):
            result = subprocess.run(['gh', 'api', '--hostname', 'github.com', endpoint], capture_output=True, text=True, timeout=35)
            if result.returncode:
                return None, 'GitHub source unavailable; check visibility, path, or rate limits.'
            data = json.loads(result.stdout)
        else:
            headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'profile-toolkit-audit'}
            token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
            if token:
                headers['Authorization'] = 'Bearer ' + token
            request = urllib.request.Request('https://api.github.com/' + endpoint, headers=headers)
            with urllib.request.urlopen(request, timeout=25) as response:
                data = json.load(response)
        return base64.b64decode(data['content']).decode('utf-8'), None
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired, urllib.error.URLError):
        return None, 'Could not read this public repository source.'


def audit(config, output, summary):
    source_ids = list(config['sources'])
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(fetch_source, [config['sources'][key] for key in source_ids]))
    sources = dict(zip(source_ids, results))
    confirmed, review = [], []
    for tool in config['tools']:
        available = [(sources[e['source']][0], e['contains']) for e in tool['evidence']]
        if any(text is not None and token.casefold() in text.casefold() for text, token in available):
            confirmed.append(tool['label'])
        else:
            review.append(tool['label'])
    # These are review prompts, not automatically asserted skills.
    candidates = {'Octokit':'octokit', 'Zod':'zod', 'NumPy':'numpy', 'PDFPlumber':'pdfplumber', 'PyMuPDF':'pymupdf', 'Pytest':'pytest', 'Tiptap':'@tiptap/', 'JupyterLab':'jupyterlab', 'Kysely':'kysely', 'Vitest':'vitest', 'Playwright':'playwright'}
    discovered = []
    for label, token in candidates.items():
        evidence = []
        for key, (text, error) in sources.items():
            path = config['sources'][key]['path']
            if text and (path.endswith('package.json') or path.endswith('.toml') or path.endswith('requirements.txt')) and token.casefold() in text.casefold():
                evidence.append(key)
        if evidence and label not in confirmed:
            discovered.append({'label': label, 'sources': evidence})
    unavailable = [{'source':key,'reason':error} for key, (_, error) in sources.items() if error]
    report = {'confirmed_tools':confirmed,'needs_review':review,'candidate_dependencies':discovered,'unavailable_sources':unavailable,'scope':'Only configured public repositories are checked. A dependency confirms project use, not personal proficiency. No badges or skills are added automatically.'}
    lines = ['## Toolkit evidence audit', '', f'- Curated tools found in current sources: {len(confirmed)}', f'- Curated tools needing a source review: {len(review)}', f'- Unavailable sources: {len(unavailable)}', '', report['scope'], '']
    if review:
        lines += ['### Review existing entries', '', ', '.join(review), '']
    if discovered:
        lines += ['### Dependencies to consider', '', *[f'- {item["label"]}: {", ".join(item["sources"])}' for item in discovered], '']
    for item in unavailable:
        lines.append(f'- Source {item["source"]}: {item["reason"]}')
    text = '\n'.join(lines) + '\n'
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    if summary:
        summary.parent.mkdir(parents=True, exist_ok=True)
        with summary.open('a', encoding='utf-8') as handle:
            handle.write(text)
    print(text)
    return not unavailable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check generated badges without changing files.')
    parser.add_argument('--audit', action='store_true', help='Read public repository evidence without editing the profile.')
    parser.add_argument('--report', type=Path, help='Write the audit as JSON.')
    parser.add_argument('--summary', type=Path, help='Append a readable audit summary.')
    args = parser.parse_args()
    config = load_config()
    if args.audit:
        return 0 if audit(config, args.report, args.summary) else 1
    return 0 if build(config, args.check) else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ValueError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
