"""Additional reference formats: XY profiles and calculated CIF powder patterns."""
from pathlib import Path
import re
import numpy as np


SUBSCRIPT_DIGITS = str.maketrans('0123456789', '₀₁₂₃₄₅₆₇₈₉')


def format_formula(formula):
    """Use Unicode subscripts, keeping chemical symbols upright."""
    formula = re.sub(r'\s+', '', str(formula))
    return re.sub(r'\d+', lambda m: m.group().translate(SUBSCRIPT_DIGITS), formula)


def auto_formula_title(title):
    """Format recognizable multi-element formula tokens, not names or #IDs."""
    if '$' in title:
        return title  # Preserve explicit user-supplied MathText.
    token = r'(?<![A-Za-z0-9])(?:[A-Z][a-z]?(?:\d+(?:\.\d+)?)?){2,}(?![A-Za-z0-9])'
    return re.sub(token, lambda m: format_formula(m.group()), title)


def card_title(name, formula='', number=''):
    label = name.strip()
    if formula and formula not in ('?', '.'):
        label += ' ' + format_formula(formula)
    else:
        label = auto_formula_title(label)
    if number:
        label += ' #' + str(number).lstrip('#')
    return label.strip()


def read_xy(path):
    rows = []
    for line_number, line in enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(), 1):
        line = line.strip()
        if not line or line.startswith(('#', '!', ';')):
            continue
        parts = re.split(r'[\s,]+', line)
        try:
            rows.append([float(parts[0]), float(parts[1])])
        except (IndexError, ValueError) as e:
            # Permit text headers before the first numeric data row only.
            if not rows and re.search(r'[A-Za-z]', line):
                continue
            raise ValueError(f'{Path(path).name}: invalid XY row {line_number}') from e
    peaks = np.asarray(rows, dtype=float)
    if peaks.ndim != 2 or len(peaks) < 2 or not np.isfinite(peaks).all() or peaks[:, 1].max() <= 0:
        raise ValueError(f'{Path(path).name}: XY requires at least two finite angle/intensity rows and a positive maximum')
    peaks = peaks[np.argsort(peaks[:, 0], kind='stable')]
    records = [{'2theta': float(t), 'intensity': float(i)} for t, i in peaks]
    return dict(path=str(path), label=auto_formula_title(Path(path).stem), peaks=peaks, records=records,
                kind='profile', source_format='xy', intensity_column=2,
                processing='First two columns; no background subtraction or peak detection')


def read_cif(path, wavelength=1.54059, upper_angle=100):
    try:
        import gemmi
    except ImportError as e:
        raise ValueError('CIF support requires Gemmi. Run Install again to install the updated dependencies.') from e
    if not np.isfinite(wavelength) or wavelength <= 0:
        raise ValueError('CIF wavelength must be a positive number in angstroms')
    document = gemmi.cif.read_file(str(path))
    blocks = [b for b in document if b.find_value('_cell_length_a') and len(b.find_values('_atom_site_fract_x'))]
    if len(blocks) != 1:
        raise ValueError(f'{Path(path).name}: expected exactly one crystal-structure block with fractional atom coordinates')
    block = blocks[0]
    structure = gemmi.make_small_structure_from_block(block)
    if structure.spacegroup is None or not structure.sites or not structure.cell.is_crystal():
        raise ValueError(f'{Path(path).name}: invalid crystal cell, atoms or unrecognized symmetry')
    sites = structure.get_all_unit_cell_sites()
    if not sites or any(s.element.atomic_number == 0 or s.element.it92 is None for s in sites):
        raise ValueError(f'{Path(path).name}: unsupported or missing atom element')
    if any(not np.isfinite(s.occ) or s.occ < 0 or not np.isfinite(s.u_iso) for s in sites):
        raise ValueError(f'{Path(path).name}: invalid atom occupancy or displacement')
    upper_angle = min(179.0, max(100.0, float(upper_angle)))
    dmin = wavelength / (2 * np.sin(np.deg2rad(upper_angle / 2)))
    # Include all reciprocal directions: multiplicity is counted by summing their intensities.
    hkls = gemmi.make_miller_array(structure.cell, structure.spacegroup, dmin, unique=False)
    if len(hkls) > 100000:
        raise ValueError('CIF unit cell is too large for this interactive powder calculator')
    reflections = []
    for hkl in hkls:
        d = structure.cell.calculate_d(hkl)
        theta = np.arcsin(np.clip(wavelength / (2 * d), 0, 1))
        angle = float(np.rad2deg(theta) * 2)
        if angle < 0.1 or angle > upper_angle:
            continue
        stol2 = 1 / (4 * d * d)
        amplitude = 0j
        for site in sites:
            # Isotropic displacement approximation; neutral-atom IT92 form factors.
            form = site.element.it92.calculate_sf(stol2)
            thermal = np.exp(-8 * np.pi**2 * max(0, site.u_iso) * stol2)
            phase = 2 * np.pi * (hkl[0] * site.fract.x + hkl[1] * site.fract.y + hkl[2] * site.fract.z)
            amplitude += site.occ * form * thermal * np.exp(1j * phase)
        lorentz_polarization = (1 + np.cos(2 * theta)**2) / (np.sin(theta)**2 * np.cos(theta))
        intensity = float(abs(amplitude)**2 * lorentz_polarization)
        reflections.append((angle, intensity, d, tuple(int(v) for v in hkl)))
    reflections.sort(key=lambda r: r[0])
    merged = []
    for angle, intensity, d, hkl in reflections:
        if merged and abs(angle - merged[-1]['2theta']) < 1e-5:
            merged[-1]['intensity'] += intensity
            merged[-1]['multiplicity'] += 1
        else:
            merged.append({'2theta': angle, 'intensity': intensity, 'd': d,
                           'h': hkl[0], 'k': hkl[1], 'l': hkl[2], 'multiplicity': 1})
    maximum = max((r['intensity'] for r in merged), default=0)
    if maximum <= 0:
        raise ValueError(f'{Path(path).name}: no calculated diffraction peaks')
    rows = [r for r in merged if r['intensity'] / maximum > 1e-8]
    for i, r in enumerate(rows, 1):
        r['no'] = i
        r['intensity'] = 100 * r['intensity'] / maximum
    card_number = ''
    for tag in ['_database_code_pdf', '_database_code_ICSD', '_database_code_cod', '_database_code_CSD']:
        value = block.find_value(tag)
        if value and value not in ('?', '.'):
            card_number = gemmi.cif.as_string(value)
            break
    def cif_text(tag):
        raw = block.find_value(tag)
        return gemmi.cif.as_string(raw) if raw and raw not in ('?', '.') else ''
    name = cif_text('_chemical_name_common') or cif_text('_chemical_name_systematic')
    formula = cif_text('_chemical_formula_structural') or cif_text('_chemical_formula_sum')
    label = card_title(name or Path(path).stem, formula if name else '', card_number)
    label += ' [CIF calculated]'
    return dict(path=str(path), label=label, peaks=np.array([[r['2theta'], r['intensity']] for r in rows]),
                records=rows, kind='sticks', source_format='cif', wavelength=float(wavelength),
                card_number=card_number, calculation_range=[0.1, upper_angle], expanded_atom_count=len(sites),
                model='Kinematic powder; IT92 neutral form factors; isotropic U; occupancy; multiplicity; Lorentz-polarization; no anomalous scattering, texture or line broadening')
