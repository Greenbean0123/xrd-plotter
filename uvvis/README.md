# UV-Vis Plotter 0.0.1

Independent desktop application with an English interface. Requires Python 3.9+ with Tkinter, NumPy and Matplotlib.

Run `python uvvis_plotter.py`, or open the packaged `UV-Vis Plotter 0.0.1.exe`.

1. Add CSV files (JASCO XYDATA exports or simple two-column wavelength/absorbance files). Multiple spectra are overlaid.
2. Choose Global maximum (default), Maximum in wavelength range, or Raw absorbance. Each spectrum is divided by its own positive maximum. Range mode finds the largest measured absorbance within the inclusive wavelength range and divides the entire spectrum by that value; values outside the range can exceed 1. No baseline subtraction or smoothing is applied.
3. Set X/Y minimum and maximum; blank limits are automatic. Click Update plot after editing. The toolbar also supports zoom and pan.
4. Select a curve to change its label and color. Adjust the title, grid and legend.
5. Select a curve in the list and toggle Show selected / Export selected independently. The list displays both flags. Figure and CSV exports use the Export flag; the preview uses Show.
6. Set figure width and height in inches and export DPI. Preview preserves the aspect ratio. PNG pixel dimensions equal inches multiplied by DPI; PDF/SVG retain the selected physical size. Export plotted data includes raw values, processed values and normalization divisors across the full scan, independently of visible axis limits.
7. Legend and Grid respond immediately. Click Update plot after changing numeric fields, or press Enter.

## GitHub update checks

Checks run in the background on startup (can be disabled), with a manual Check for Updates button. Settings are separate from XRD under `%LOCALAPPDATA%/UV-Vis Plotter/updates.json`. The default GitHub repository is `Greenbean0123/xrd-plotter`. The repository address and release-tag details are hidden in the interface. The automatic-check preference is saved immediately.

Publish UV-Vis releases with tags `uvvis-v0.0.1`, `uvvis-v0.0.2`, etc., and attach the matching EXE to each GitHub release. The checker ignores XRD tags, draft releases and prereleases. It reports when no UV-Vis releases exist. An available update offers to open its GitHub release page for manual download; it does not replace the running executable automatically.

Input files are read locally and are never modified. No experimental files are bundled.

Build a Windows executable with `python -m pip install pyinstaller` then `python build_windows.py`.


## Mac trial builds

Mac trial installers are built with `.github/workflows/build-uvvis-macos.yml`.
The workflow uploads build artifacts only; it does not create or update a public
GitHub release. Public release of the Mac builds is pending user trial approval.
Apple Silicon and Intel builds are separate. Open the matching DMG and drag
UV-Vis Plotter.app to Applications, then launch it from Applications.

For a local build on a Mac, install the packages in requirements.txt plus
PyInstaller and Pillow, then run `python build_macos.py` from this folder.
Outputs are written to cloud-output/. The build verifies the architecture,
ad-hoc code signature, frozen GUI initialization, PNG/PDF/SVG exports and DMG
integrity. Update preferences are stored in
`~/Library/Application Support/UV-Vis Plotter/updates.json`.
