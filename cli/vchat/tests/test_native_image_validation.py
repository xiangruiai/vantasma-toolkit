"""Exercise native candidate validation with synthetic files; never scan a process."""
import binascii
import os
from pathlib import Path
import random
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


ROOT = Path(__file__).resolve().parents[1]
KEY = bytes(range(16))


def segment(marker, payload):
    return bytes((0xFF, marker)) + struct.pack('>H', len(payload) + 2) + payload


def jpeg(first='jfif'):
    app = segment(0xE0, b'JFIF\0\x01\x01\0\0\x01\0\x01\0\0')
    if first in ('exif', 'large-exif'):
        exif = b'Exif\0\0II\x2a\0\x08\0\0\0\0\0\0\0\0\0'
        app = segment(0xE1, exif + (b'\0' * 2048 if first == 'large-exif' else b''))
    if first == 'dqt':
        app = b''
    quant = segment(0xDB, b'\0' + bytes([1]) * 64)
    frame = segment(0xC0, b'\x08\0\x02\0\x02\x01\x01\x11\0')
    scan = segment(0xDA, b'\x01\x01\0\0\x3f\0')
    return b'\xff\xd8' + app + quant + frame + scan + b'\0\xff\xd9'


def png():
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', binascii.crc32(kind + body))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\0' + b'\xff\0\0\xff' * 2) * 2))
            + chunk(b'IEND', b''))


def gif(version=b'89a'):
    return (b'GIF' + version + bytes.fromhex('01000100800000000000ffffff')
            + bytes.fromhex('2c00000000010001000002024401003b'))


def webp(kind=b'VP8L'):
    if kind == b'VP8L':
        body = b'\x2f\0\0\0\0\0'
    elif kind == b'VP8 ':
        body = b'\x10\0\0\x9d\x01\x2a\x02\0\x02\0'
    else:
        body = b'\0' * 10
    chunk = kind + struct.pack('<I', len(body)) + body + (b'\0' if len(body) % 2 else b'')
    return b'RIFF' + struct.pack('<I', 4 + len(chunk)) + b'WEBP' + chunk


def encrypted_dat(plain, xor=0x88, aes_size=None, bad_padding=False):
    aes_size = min(len(plain), 1024) if aes_size is None else aes_size
    pad = 16 - aes_size % 16
    block = plain[:aes_size] + bytes([pad]) * pad
    if bad_padding:
        block = block[:-1] + bytes([block[-1] ^ 1])
    enc = Cipher(algorithms.AES(KEY), modes.ECB()).encryptor()
    cipher = enc.update(block) + enc.finalize()
    tail = bytes(b ^ xor for b in plain[aes_size:])
    return b'\x07\x08V2\x08\x07' + struct.pack('<II', aes_size, len(tail)) + b'\0' + cipher + tail


@unittest.skipUnless(sys.platform == 'darwin', 'native scanner uses macOS CommonCrypto')
class NativeImageValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        harness = cls.root / 'harness.c'
        source = ROOT / 'vchat_native/find_image_key_macos.c'
        harness.write_text(f'''#define main scanner_unused_main
#include "{source}"
#undef main
int main(int argc, char **argv) {{
    if (argc != 2) return 70;
    unsigned char key[16]; for (int i=0; i<16; i++) key[i]=(unsigned char)i;
#ifdef VCHAT_IMAGE_STRUCTURE_VALIDATION
    image_sample sample;
    if (read_image_sample(argv[1], &sample) != 0) {{ puts("0"); return 0; }}
    unsigned char xor_key=0;
    printf("%d\\n", try_key(key, &sample, &xor_key));
#else
    unsigned char ct[16];
    if (read_ct_block(argv[1], ct) != 0) {{ puts("0"); return 0; }}
    printf("%d\\n", try_key(key, ct));
#endif
    return 0;
}}
''')
        cls.binary = cls.root / 'candidate-test'
        subprocess.run(['cc', '-O2', '-Wall', '-Wno-deprecated-declarations', str(harness),
                        '-o', str(cls.binary), '-framework', 'CoreFoundation', '-framework', 'Security'],
                       check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def accepted(self, plain, **kwargs):
        path = self.root / 'sample.dat'
        path.write_bytes(encrypted_dat(plain, **kwargs))
        result = subprocess.run([str(self.binary), str(path)], check=True,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.stderr, '')
        return result.stdout.strip() == '1'

    def test_rejects_false_jpeg_with_segment_larger_than_file(self):
        fake = b'\xff\xd8\xff\xe1' + struct.pack('>H', 59771) + b'\0' * 4000
        self.assertFalse(self.accepted(fake))

    def test_rejects_magic_only_or_random_headers(self):
        for prefix in (b'\xff\xd8\xff\xe0', b'\x89PNG', b'GIF89a', b'RIFFxxxxWEBP', b'wxgf'):
            with self.subTest(prefix=prefix):
                self.assertFalse(self.accepted(prefix + b'\0' * 80))

    def test_accepts_standard_jpeg_header_variants(self):
        for first in ('jfif', 'exif', 'dqt', 'large-exif'):
            with self.subTest(first=first):
                self.assertTrue(self.accepted(jpeg(first), xor=0x57))

    def test_rejects_jpeg_without_sof_or_sos_and_zero_dimensions(self):
        self.assertFalse(self.accepted(b'\xff\xd8' + segment(0xE0, b'JFIF\0' + b'\0' * 9) + b'\xff\xd9'))
        self.assertFalse(self.accepted(jpeg().replace(b'\x08\0\x02\0\x02', b'\x08\0\0\0\x02')))

    def test_accepts_png_gif_and_webp_headers(self):
        for data in (png(), gif(), gif(b'87a'), webp(), webp(b'VP8 '), webp(b'VP8X')):
            with self.subTest(kind=data[:12]):
                self.assertTrue(self.accepted(data))

    def test_rejects_invalid_png_ihdr_crc_and_webp_length(self):
        data = bytearray(png()); data[29] ^= 1
        self.assertFalse(self.accepted(bytes(data)))
        data = bytearray(webp()); data[4:8] = struct.pack('<I', 9000000)
        self.assertFalse(self.accepted(bytes(data)))

    def test_requires_consistent_aes_padding(self):
        self.assertFalse(self.accepted(jpeg(), bad_padding=True))

    def test_rejects_impossible_v2_segment_sizes(self):
        path = self.root / 'bad.dat'
        data = bytearray(encrypted_dat(jpeg()))
        data[6:10] = struct.pack('<I', 0xffffffff)
        path.write_bytes(data)
        result = subprocess.run([str(self.binary), str(path)], check=True,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.stdout.strip(), '0')

    def test_accepts_actual_macos_encoded_images(self):
        # Generate private synthetic pixels; sips is the built-in macOS encoder.
        width = height = 32
        pixels = random.Random(12345).randbytes(width * height * 3)
        bitmap = (b'BM' + struct.pack('<IHHI', 54 + len(pixels), 0, 0, 54)
                  + struct.pack('<IIIHHIIIIII', 40, width, height, 1, 24, 0,
                                len(pixels), 2835, 2835, 0, 0) + pixels)
        source = self.root / 'synthetic.bmp'
        source.write_bytes(bitmap)
        for kind in ('jpeg', 'png', 'gif'):
            with self.subTest(format=kind):
                output = self.root / ('encoded.' + kind)
                subprocess.run(['/usr/bin/sips', '-s', 'format', kind, str(source),
                                '--out', str(output)], check=True, capture_output=True, timeout=10)
                self.assertTrue(self.accepted(output.read_bytes(), xor=0x57))


if __name__ == '__main__':
    unittest.main()
