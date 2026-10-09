#!/usr/bin/env python3
"""Create a public GitHub template, push reviewed source, and enable Actions Pages.

Requires Git. Uses GitHub CLI, bootstrapping its official Linux release if absent.
Creates a clean staging checkout, so read-only or
non-Git workspaces are supported. No credentials are saved in this repository.
"""
import argparse
import hashlib
import io
import os
import platform
import tarfile
from urllib.request import Request, urlopen
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATHS = ['reader', 'scripts', 'tests', 'docs', '.github', '.gitignore', 'config.example.yaml',
                'pyproject.toml', 'requirements.txt', 'README.md', 'LICENSE', 'CONTRIBUTING.md']


def command(args, cwd=ROOT, capture=False):
    return subprocess.run(args, cwd=cwd, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def gh_api(endpoint, method='GET', payload=None):
    args = ['gh', 'api', '--method', method, endpoint]
    if payload is not None:
        args += ['--input', '-']
    result = subprocess.run(args, input=json.dumps(payload) if payload is not None else None,
                            text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout) if result.stdout.strip() else {}


def prepare(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise RuntimeError('Source staging requires an empty directory to avoid publishing leftover private files')
    import yaml
    settings = yaml.safe_load((ROOT / 'config.example.yaml').read_text())
    if any(settings.get(k) for k in ('inspire_author_id', 'followed_authors', 'tracked_publications')):
        raise RuntimeError('Public host configuration contains personal settings. Move them to private config.yaml.')
    for name in SOURCE_PATHS:
        source, target = ROOT / name, destination / name
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'), dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
    return destination


def ensure_github_cli():
    if shutil.which('gh'):
        return
    architecture = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(platform.machine())
    if platform.system() != 'Linux' or not architecture:
        raise SystemExit('Install GitHub CLI from https://cli.github.com/ and rerun this command.')

    def download(url, limit):
        with urlopen(Request(url, headers={'User-Agent': 'arxiv-reader-publisher/1.0'}), timeout=60) as response:
            body = response.read(limit + 1)
        if len(body) > limit:
            raise RuntimeError('GitHub CLI download exceeded the size limit')
        return body

    print('GitHub CLI is missing; downloading its official Linux release to a temporary directory.', flush=True)
    release = json.loads(download('https://api.github.com/repos/cli/cli/releases/latest', 2_000_000))
    archive = next(a for a in release['assets'] if a['name'].endswith('_linux_' + architecture + '.tar.gz'))
    checksum = next(a for a in release['assets'] if a['name'].endswith('_checksums.txt'))
    expected = next(line.split()[0] for line in download(checksum['browser_download_url'], 1_000_000).decode().splitlines()
                    if line.split()[-1] == archive['name'])
    body = download(archive['browser_download_url'], 50_000_000)
    if hashlib.sha256(body).hexdigest() != expected:
        raise RuntimeError('GitHub CLI checksum mismatch; refusing to execute the download')
    destination = Path(tempfile.mkdtemp(prefix='arxiv-github-cli-'))
    with tarfile.open(fileobj=io.BytesIO(body), mode='r:gz') as package:
        member = package.getmember(archive['name'][:-7] + '/bin/gh')
        if not member.isfile() or member.size > 100_000_000:
            raise RuntimeError('Unexpected GitHub CLI archive member')
        # Read only the known executable; never extract arbitrary archive paths.
        binary = destination / 'gh'
        binary.write_bytes(package.extractfile(member).read())
        binary.chmod(0o700)
    os.environ['PATH'] = str(destination) + os.pathsep + os.environ.get('PATH', '')
    command(['gh', '--version'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', default='arxiv-reader', help='New repository name in your personal GitHub account')
    parser.add_argument('--resume', help='Resume publishing a repository created by an earlier run (OWNER/NAME)')
    parser.add_argument('--prepare', type=Path, help='Only stage source files here, without contacting GitHub')
    parser.add_argument('--skip-browser-check', action='store_true', help='Use only when local browser execution is unavailable; CI still runs the browser tests')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', args.name):
        parser.error('--name may contain only letters, digits, underscore, dot and hyphen')
    if args.prepare:
        print('Prepared source in', prepare(args.prepare))
        return 0
    if not shutil.which('git'):
        raise SystemExit('Git is required. Install it from https://git-scm.com/downloads and rerun this command.')
    command([sys.executable, '-m', 'reader', '--config', 'config.example.yaml', 'validate'])
    command([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'])
    with tempfile.TemporaryDirectory(prefix='arxiv-publish-check-') as tmp:
        command([sys.executable, '-m', 'reader', '--output', tmp, 'demo'])
        if not args.skip_browser_check:
            command([sys.executable, 'scripts/browser_test.py', '--site', tmp])
        command([sys.executable, '-m', 'reader', '--output', tmp, 'demo', '--public'])
        if not args.skip_browser_check:
            command([sys.executable, 'scripts/browser_test.py', '--site', tmp, '--profile-fixture', 'tests/fixtures/browser-profile.json'])
    ensure_github_cli()
    # Login opens the device authorization flow when no account is configured.
    if subprocess.run(['gh', 'auth', 'status'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        command(['gh', 'auth', 'login', '--hostname', 'github.com', '--git-protocol', 'https', '--web', '--scopes', 'repo,workflow'])
    command(['gh', 'auth', 'setup-git'])
    user = gh_api('user')
    if args.resume:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.resume):
            parser.error('--resume must be OWNER/NAME')
        repo = gh_api('repos/' + args.resume)
        if repo['owner']['login'].lower() != user['login'].lower():
            raise SystemExit('This helper only publishes to your personal account.')
        if repo.get('private'):
            raise SystemExit('This helper expects a public repository; no visibility change was made.')
    else:
        # POST fails safely if the name is already taken; existing repositories are never overwritten.
        repo = gh_api('user/repos', 'POST', {'name': args.name, 'description': 'Personal daily arXiv reader with citation tracking and author highlighting',
                                           'private': False, 'is_template': True, 'auto_init': False})
    full_name = repo['full_name']
    # Retain a staging checkout if a push or configuration step fails, for easy recovery.
    staging = Path(tempfile.mkdtemp(prefix='arxiv-publish-'))
    prepare(staging)
    print(f'Publishing {full_name}; source staging checkout: {staging}', flush=True)
    print(f'If interrupted, rerun with --resume {full_name}', flush=True)
    command(['git', 'init', '-b', 'main'], staging)
    command(['git', 'config', 'user.name', user['login']], staging)
    command(['git', 'config', 'user.email', f'{user["id"]}+{user["login"]}@users.noreply.github.com'], staging)
    command(['git', 'remote', 'add', 'origin', repo['clone_url']], staging)
    # A resumed repository with commits is fetched first; ordinary push still enforces fast-forward.
    refs = command(['git', 'ls-remote', '--heads', 'origin', 'refs/heads/main'], staging, capture=True)
    if refs.strip():
        command(['git', 'fetch', 'origin', 'main'], staging)
        command(['git', 'reset', '--mixed', 'FETCH_HEAD'], staging)
    command(['git', 'add', '--all'], staging)
    changed = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=staging).returncode
    if changed == 1:
        command(['git', 'commit', '-m', 'Implement self-hosted arXiv daily reader'], staging)
    elif changed != 0:
        raise SystemExit('Could not inspect staged changes')
    command(['git', 'push', '-u', 'origin', 'main'], staging)
    gh_api('repos/' + full_name, 'PATCH', {'is_template': True})
    # Pages may not exist yet. Distinguish a missing site from authorization failures.
    try:
        gh_api('repos/' + full_name + '/pages')
    except RuntimeError as exc:
        if '404' not in str(exc):
            raise
        gh_api('repos/' + full_name + '/pages', 'POST', {'build_type': 'workflow'})
    else:
        gh_api('repos/' + full_name + '/pages', 'PUT', {'build_type': 'workflow'})
    for attempt in range(6):
        try:
            gh_api('repos/' + full_name + '/actions/workflows/daily.yml/dispatches', 'POST', {'ref': 'main'})
            break
        except RuntimeError:
            if attempt == 5:
                raise
            time.sleep(5)
    print(f'Repository: {repo["html_url"]}')
    print(f'Actions: {repo["html_url"]}/actions')
    command(['gh', 'run', 'list', '--repo', full_name, '--workflow', 'daily.yml', '--limit', '3'])
    print('Deployment requested. The workflow checks the site before publishing. Monitor the Actions link above for the final Pages URL.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError, OSError, ValueError, StopIteration, KeyError) as exc:
        raise SystemExit(f'Publishing stopped: {exc}. No force-push was attempted; use --resume after resolving authentication or repository permissions.')
