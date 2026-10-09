"""Optional Python fallback for privately resolving browser settings without CORS."""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from .http import Client, FetchError
from .inspire import Inspire
from .pipeline import resolve_targets
from .storage import write_json


def export_profile(config, destination='private-profile.yaml', *, settings_only=False):
    with TemporaryDirectory(prefix='arxiv-private-profile-') as tmp:
        if settings_only:
            path = Path(destination)
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json(path, config)
            path.chmod(0o600)
            return
        client = Client(Path(tmp) / 'cache', config['updates']['user_agent'])
        warnings = []
        targets, followed, complete = resolve_targets(config, Inspire(client, config['updates']), Path(tmp), warnings)
        if not complete:
            raise ValueError('Could not resolve the private profile: ' + '; '.join(warnings))
        data = config | {'_reader_cache': {'targets': targets, 'followed': followed,
                                         'updated_at': datetime.now(timezone.utc).isoformat()}}
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(mode=0o600, exist_ok=True)
        path.chmod(0o600)
        # JSON is valid YAML; native browser JSON parsing needs no YAML dependency.
        write_json(path, data)
        path.chmod(0o600)
