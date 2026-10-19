# XRD Plotter updates

The app includes **Check for Updates**, **Update Settings**, background checks,
download progress, signed manifests, SHA-256 package verification, a detached
installer and startup confirmation with rollback. The default update server is
https://github.com/Greenbean0123/xrd-plotter/releases/latest/download/updates.json
and the initial signed 0.0.2 baseline is published. A newer version will be
offered only after the publisher uploads its packages and signed manifest.

For testing or publishing, set the HTTPS manifest URL in **Update Settings**.
The publisher can also set `manifest_url` in `src/update_config.json` before
building. This file contains only the public verification key, never a secret.
Automatic checks run after startup and do not download/install without consent.
Offline automatic checks fail quietly; manual checks show the error.

## Publishing a release

1. Keep `.release-keys/update-signing-key.pem` private and backed up. It was
   generated locally and is excluded from Git and all distribution packages.
   Losing it prevents signing updates for builds that trust its public key.
2. Set the next version, for example `0.0.3`, in `src/app_version.py` and rebuild
   both architectures on Mac and the EXE on Windows.
3. Mac builds produce a DMG for initial installation AND an `_update.zip` of the
   signed app for automatic installation. The updater does not install DMGs.
4. Upload the EXE and Mac update ZIPs to a stable HTTPS download service, such
   as GitHub Releases. Then generate the signed manifest, for example:

```text
python tools/release_updates.py --version 0.0.3 --notes "Bug fixes" --base-url https://example.com/releases/0.0.3 --asset windows-x86_64=dist/XRD_Plotter_Win.exe --asset macos-arm64=dist/XRD_Plotter_0.0.3_Mac_arm64_update.zip --asset macos-x86_64=dist/XRD_Plotter_0.0.3_Mac_x86_64_update.zip
```

The example URL is a placeholder, not a live update server. The Windows asset
path must match your actual EXE file. Put `releases/updates.json` at the fixed
HTTPS manifest URL only after all referenced packages are uploaded.

## Installation behavior

Only standalone EXEs and standalone Mac apps can replace themselves. The Mac
source launcher cannot update its source folder automatically. Move a Mac app
out of its DMG into a writable Applications folder before updating.

The installer verifies the signed manifest and package again, prepares the new
application, then waits for the old application to exit. It keeps a sibling
`.previous-...` backup. A new app that fails to signal GUI readiness within
120 seconds is stopped and the previous app is restored and reopened. Backups
are retained for recovery rather than automatically deleted.

Current inputs, colors, labels, ordering and layout are saved before restarting
and restored when the updated app opens. Input files, exported figures and user
preferences remain outside the replaced executable/app bundle. The new app
needs access to the original input files; moved/missing files are skipped.

Manifest signatures authenticate the publisher separately from Apple Developer
ID signing. Mac packages currently have ad-hoc code signatures and are not
notarized. macOS may still require approval when launching downloaded apps.

The transaction code and Windows installer are tested locally; actual Mac
installation, permissions and Gatekeeper behavior require validation on a Mac.
The Windows end-to-end test uses an isolated temporary installation and the same
binary under a simulated future manifest. It tests the installer mechanism,
not a real online release or a migration between two published versions.
