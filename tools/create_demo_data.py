"""Create synthetic demonstration scans/references, not experimental data."""
from pathlib import Path
import csv
import math

ROOT = Path(__file__).resolve().parents[1]


def peak(x, center, width):
    return math.exp(-0.5 * ((x - center) / width) ** 2)


def create_pdf(path):
    lines = ['Name: Synthetic Demo Reference I/Ic 1.0', 'PDF Card No.: DEMO-001',
             'No. 2Theta d Intensity h k l', '1 25.00 3.55 100.00 1 0 0',
             '2 43.00 2.10 65.00 1 1 0', '3 62.00 1.50 45.00 1 1 1',
             'Note: Synthetic illustration only; not a measured reference card.']
    content = b'BT /F1 11 Tf 40 760 Td 16 TL\n'
    for line in lines:
        escaped = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        content += f'({escaped}) Tj T*\n'.encode('ascii')
    content += b'ET\n'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               f'<< /Length {len(content)} >>\nstream\n'.encode() + content + b'endstream']
    result = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f'{index} 0 obj\n'.encode() + obj + b'\nendobj\n')
    xref = len(result)
    result.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        result.extend(f'{offset:010d} 00000 n \n'.encode())
    result.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    path.write_bytes(result)


def main():
    output = ROOT / 'demo-data'
    output.mkdir(exist_ok=True)
    for sample, shift in [('A', 0.0), ('B', 0.4)]:
        with (output / f'Synthetic Demo {sample}.csv').open('w', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(['twotheta', 'obs', 'background'])
            for index in range(801):
                x = 10 + index / 10
                background = 30 + 0.15 * x
                intensity = sum(amplitude * peak(x, center + shift, width)
                                for center, width, amplitude in [(25, .30, 1000), (43, .40, 650), (62, .32, 450)])
                writer.writerow([f'{x:.2f}', f'{intensity + background:.6f}', f'{background:.6f}'])
    for label, shift in [('A', 0.0), ('B', 0.4)]:
        with (output / f'Synthetic Reference {label}.xy').open('w', encoding='utf-8') as stream:
            for index in range(801):
                x = 10 + index / 10
                y = sum(amplitude * peak(x, center + shift, .20) for center, amplitude in [(25, 100), (43, 65), (62, 45)])
                stream.write(f'{x:.2f} {y:.6f}\n')
    create_pdf(output / 'Synthetic Reference Demo.pdf')
    (output / 'README.txt').write_text('All data in this directory are synthetic demonstrations, not experimental measurements or validated crystallographic references.\n', encoding='utf-8')


if __name__ == '__main__':
    main()
