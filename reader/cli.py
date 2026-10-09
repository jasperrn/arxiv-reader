import argparse
import logging
from pathlib import Path
import sys
from .build import build, validate_site
from .config import load_config, ConfigError
from .pipeline import update


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build and update a personal arXiv announcement archive')
    parser.add_argument('--config', default='config.yaml')
    parser.add_argument('--state', default='state')
    parser.add_argument('--output', default='site')
    parser.add_argument('--verbose', action='store_true')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('validate', help='Validate configuration')
    p = sub.add_parser('update', help='Capture feeds and refresh recent metadata')
    p.add_argument('--public', action='store_true', help='Collect general reference metadata without personal settings')
    p.add_argument('--recheck-all', action='store_true', help='Recheck older archived papers too, within the request budget')
    p.add_argument('--feed-dir', type=Path, help='Import saved RSS snapshots named CATEGORY.xml instead of live feeds')
    sub.add_parser('build', help='Build site from the local archive, without networking').add_argument('--public', action='store_true')
    profile_parser = sub.add_parser('export-profile', help='Resolve your bibliography and export a private browser configuration')
    profile_parser.add_argument('--file', default='private-profile.yaml')
    profile_parser.add_argument('--settings-only', action='store_true', help='Export settings offline; let the browser resolve publications')
    sub.add_parser('check-site', help='Validate generated site assets and data')
    sub.add_parser('demo', help='Generate a clearly labelled offline demonstration').add_argument('--public', action='store_true')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format='%(levelname)s: %(message)s')
    try:
        if args.command == 'demo':
            from .demo import demo
            demo(args.output, public=args.public)
            logging.info('Synthetic demo built in %s', args.output)
            return 0
        if args.command == 'check-site':
            logging.info('Site valid: %d captured dates', validate_site(args.output))
            return 0
        config = load_config(args.config)
        if args.command == 'export-profile':
            from .profile import export_profile
            export_profile(config, args.file, settings_only=args.settings_only)
            logging.info('Private browser configuration saved to %s. Do not commit or publish this file.', args.file)
            return 0
        if args.command == 'validate':
            logging.info('Configuration valid: %s', ', '.join(config['categories']))
        elif args.command == 'update':
            feeds = {c: args.feed_dir / (c + '.xml') for c in config['categories']} if args.feed_dir else None
            status = update(config, args.state, feed_files=feeds, recheck_all=args.recheck_all, public=args.public)
            # Fail visibly when collection fails completely; workflows can still publish the saved archive.
            return 2 if not status['feeds_succeeded'] else 0
        elif args.command == 'build':
            build(config, args.state, args.output, public=args.public)
            logging.info('Built %s (%d captured dates)', args.output, validate_site(args.output))
    except (ConfigError, ValueError, OSError) as exc:
        logging.error('%s', exc)
        return 1
    return 0
