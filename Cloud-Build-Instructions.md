# XRD Plotter cloud builds

The GitHub Actions workflow `.github/workflows/build-macos.yml` builds version
0.0.2 (read from `src/app_version.py`) on separate Apple Silicon and Intel Macs.

Once this source has been pushed to a GitHub repository:

1. Open the repository's **Actions** tab.
2. Select **Build Mac applications** and choose **Run workflow**.
3. Wait for the AppleSilicon and Intel jobs to finish.
4. Download the two artifacts from the completed run. Each contains the matching
   DMG, SHA-256 checksum and build verification report.

Pushing a version tag such as `v0.0.2` also triggers the workflow. It uploads
build artifacts, without automatically publishing a public GitHub Release.

The build verifies application versions, CPU architecture, ad-hoc signatures,
PNG/PDF/SVG export using bundled samples, and DMG integrity. Interactive use still
needs a real-user check. Apple Developer ID signing and notarization are not
configured; downloaded applications may require approval in macOS settings.

Generated installers and local logs are excluded from Git. Only the source,
icons and the default sample data are uploaded. To omit sample data from a
public repository, replace it with shareable samples before publishing.

Runner reference: https://docs.github.com/en/actions/reference/runners/github-hosted-runners
