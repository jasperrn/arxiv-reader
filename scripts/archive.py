#!/usr/bin/env python3
"""Load/save the persistent data branch without modifying the source checkout.

Used inside Actions. Authentication uses the step's temporary GITHUB_TOKEN.
Never force-push: concurrent changes fail visibly instead of losing archive data.
"""
import argparse
import base64
import os
from pathlib import Path
import shutil
import subprocess


def git(*args, cwd=None, capture=False):
    env = os.environ.copy()
    token = env.pop('GITHUB_TOKEN', '')
    if token:
        # checkout v6 scopes its persisted credentials to the source checkout.
        # Supply archive credentials in process environment, never argv or disk.
        count = int(env.get('GIT_CONFIG_COUNT', '0'))
        server = env.get('GITHUB_SERVER_URL', 'https://github.com').rstrip('/')
        credential = base64.b64encode(('x-access-token:' + token).encode()).decode()
        # extraHeader is multi-valued: adding Authorization does not replace
        # checkout's existing header. An empty entry resets the inherited list.
        env[f'GIT_CONFIG_KEY_{count}'] = f'http.{server}/.extraheader'
        env[f'GIT_CONFIG_VALUE_{count}'] = ''
        env[f'GIT_CONFIG_KEY_{count + 1}'] = f'http.{server}/.extraheader'
        env[f'GIT_CONFIG_VALUE_{count + 1}'] = 'AUTHORIZATION: basic ' + credential
        env['GIT_CONFIG_COUNT'] = str(count + 2)
    env['GIT_TERMINAL_PROMPT'] = '0'
    return subprocess.run(['git', *args], cwd=cwd, check=True, text=True,
                          env=env, stdout=subprocess.PIPE if capture else None).stdout


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['load', 'save'])
    p.add_argument('--state', default='state')
    p.add_argument('--branch', default='data')
    p.add_argument('--public', action='store_true', help='Require anonymous public-collector state before committing')
    args = p.parse_args()
    state = Path(args.state).resolve()
    remote = git('remote', 'get-url', 'origin', capture=True).strip()
    if args.action == 'load':
        if state.exists() and any(state.iterdir()):
            raise SystemExit(f'Refusing to overwrite nonempty state directory: {state}')
        # An empty successful result means absent branch; network/auth failures raise.
        refs = git('ls-remote', '--heads', 'origin', 'refs/heads/' + args.branch, capture=True)
        git('init', '-b', args.branch, str(state))
        git('remote', 'add', 'origin', remote, cwd=state)
        if refs.strip():
            git('fetch', '--depth=1', 'origin', 'refs/heads/' + args.branch, cwd=state)
            git('reset', '--hard', 'FETCH_HEAD', cwd=state)
        (state / '.gitignore').write_text('*.tmp\n', encoding='utf-8')
    else:
        if not (state / '.git').exists():
            raise SystemExit('Archive checkout missing: run load first')
        if args.public:
            import json
            status = json.loads((state / 'status.json').read_text())
            targets = json.loads((state / 'targets.json').read_text()) if (state / 'targets.json').exists() else {}
            if not status.get('public_mode') or targets.get('targets'):
                raise SystemExit('Refusing to publish personalized archive state')
            for path in (state / 'days').glob('*.json'):
                for paper in json.loads(path.read_text())['papers']:
                    if paper.get('citation', {}).get('matches') or any(a.get('followed') for a in paper['authors']):
                        raise SystemExit('Refusing to publish personalized paper matches')
        git('config', 'user.name', 'github-actions[bot]', cwd=state)
        git('config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com', cwd=state)
        git('add', '--all', cwd=state)
        changed = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=state).returncode
        if changed == 1:
            git('commit', '-m', 'Update announcement archive and metadata cache', cwd=state)
            git('push', 'origin', 'HEAD:refs/heads/' + args.branch, cwd=state)
        elif changed != 0:
            raise SystemExit('Could not inspect archive changes')


if __name__ == '__main__':
    main()
