"""Create a local Ed25519 signing key and publish-ready signed update manifests."""
from pathlib import Path
import argparse
import base64
import hashlib
import json
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import updater
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--init-key', action='store_true')
    parser.add_argument('--version')
    parser.add_argument('--notes', default='')
    parser.add_argument('--base-url', help='HTTPS directory containing the release assets')
    parser.add_argument('--asset', action='append', default=[], metavar='PLATFORM=FILE')
    parser.add_argument('--output', type=Path, default=ROOT / 'releases' / 'updates.json')
    args = parser.parse_args()
    key_path = ROOT / '.release-keys' / 'update-signing-key.pem'
    config_path = ROOT / 'src' / 'update_config.json'
    config = json.loads(config_path.read_text(encoding='utf-8'))
    if args.init_key:
        if not key_path.exists():
            if config.get('public_key'):
                raise SystemExit('A public key is already configured. Restore its original private key instead of replacing it.')
            key_path.parent.mkdir(parents=True, exist_ok=True)
            private = Ed25519PrivateKey.generate()
            with key_path.open('xb') as stream:
                stream.write(private.private_bytes(serialization.Encoding.PEM,
                             serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            key_path.chmod(0o600)
        private = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        public = base64.b64encode(private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
        if config.get('public_key') and config['public_key'] != public:
            raise SystemExit('The local private key does not match the configured public key.')
        config['public_key'] = public
        config_path.write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
        print('Signing key ready. Keep .release-keys private and backed up; never include it in downloads.')
        return
    if not args.version or not args.base_url or not args.asset:
        parser.error('--version, --base-url and at least one --asset are required')
    updater.version_tuple(args.version)
    from app_version import __version__
    if args.version != __version__:
        parser.error(f'The manifest version must match src/app_version.py ({__version__}). Update the version and rebuild first.')
    updater.require_https(args.base_url)
    private = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    assets = {}
    for value in args.asset:
        key, filename = value.split('=', 1)
        if key not in ('windows-x86_64', 'macos-arm64', 'macos-x86_64'):
            parser.error(f'Unsupported platform: {key}')
        file = Path(filename)
        if key in assets:
            parser.error(f'Duplicate platform: {key}')
        assets[key] = {'url': args.base_url.rstrip('/') + '/' + quote(file.name),
                       'size': file.stat().st_size, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                       'format': 'app-zip' if key.startswith('macos-') else 'exe'}
    payload = {'schema': 1, 'version': args.version, 'notes': args.notes, 'assets': assets}
    envelope = {'payload': payload, 'signature': base64.b64encode(private.sign(updater.canonical(payload))).decode()}
    # Validate using exactly the public key embedded in the application.
    for key in assets:
        updater.verify_manifest(envelope, config['public_key'], '0.0.0', key=key)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(envelope, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Signed update manifest: {args.output}')


if __name__ == '__main__':
    main()
