import hashlib
import struct
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from vchat_core import image_codec


def encrypted_image(key, version=b"V2", prefix=None, tail=None, xor_key=0x88):
    prefix = prefix if prefix is not None else b"\x89PNG\r\n\x1a\n" + b"synthetic image segment"
    middle = b"unaltered synthetic middle"
    tail = tail if tail is not None else b"synthetic xor tail"
    pad = 16 - len(prefix) % 16
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    ciphertext = encryptor.update(prefix + bytes([pad]) * pad) + encryptor.finalize()
    data = b"\x07\x08" + version + b"\x08\x07"
    data += struct.pack("<LL", len(prefix), len(tail)) + b"\x00"
    data += ciphertext + middle + bytes(x ^ xor_key for x in tail)
    return data, prefix + middle + tail


class ImageCodecTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def decode(self, payload, key=None):
        source = self.root / "synthetic.dat"
        output = self.root / "decoded.png"
        source.write_bytes(payload)
        path, fmt = image_codec.decrypt_dat(source, output, aes_key=key)
        return path.read_bytes() if path else None, fmt

    def test_scanner_hex_key_decodes_the_original_v2_payload(self):
        key = bytes(range(16))
        payload, expected = encrypted_image(key)
        actual, fmt = self.decode(payload, key.hex())
        self.assertEqual(actual, expected)
        self.assertEqual(fmt, "png")

    def test_raw_bytes_and_legacy_ascii_keys_remain_supported(self):
        for supplied in (b"0123456789abcdef", "0123456789abcdef"):
            with self.subTest(key_type=type(supplied).__name__):
                payload, expected = encrypted_image(b"0123456789abcdef")
                self.assertEqual(self.decode(payload, supplied), (expected, "png"))

    def test_invalid_keys_are_rejected_without_truncation(self):
        payload, _ = encrypted_image(bytes(range(16)))
        for invalid in (b"x" * 17, b"x" * 32, "x" * 17, "g" * 32, "好" * 16):
            with self.subTest(kind=type(invalid).__name__, length=len(invalid)):
                with self.assertRaises(ValueError):
                    self.decode(payload, invalid)

    def test_v1_uses_its_fixed_key_without_dynamic_key(self):
        key = hashlib.md5(b"0").hexdigest()[:16].encode("ascii")
        payload, expected = encrypted_image(key, version=b"V1")
        self.assertEqual(self.decode(payload), (expected, "png"))

    def test_old_xor_format_detects_its_own_key(self):
        expected = b"\x89PNG\r\n\x1a\nsynthetic old image"
        payload = bytes(value ^ 0xB3 for value in expected)
        self.assertEqual(self.decode(payload), (expected, "png"))

    def test_v2_without_a_key_does_not_write_a_decoded_file(self):
        payload, _ = encrypted_image(bytes(range(16)))
        self.assertEqual(self.decode(payload), (None, None))
        self.assertFalse((self.root / "decoded.png").exists())

    def test_overlapping_or_oversized_xor_segment_is_rejected_without_output(self):
        key = bytes(range(16))
        payload, _ = encrypted_image(key)
        aes_size = struct.unpack_from("<L", payload, 6)[0]
        aligned = aes_size + (16 - aes_size % 16)
        for xor_size in (len(payload) + 100, len(payload) - 15 - aligned + 1):
            with self.subTest(xor_size=xor_size):
                malformed = bytearray(payload)
                struct.pack_into("<L", malformed, 10, xor_size)
                self.assertEqual(self.decode(malformed, key), (None, None))
                self.assertFalse((self.root / "decoded.png").exists())

    def test_invalid_pkcs7_padding_is_rejected_without_output(self):
        key = bytes(range(16))
        prefix = b"\x89PNG\r\n\x1a\n" + b"12345678"
        encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
        ciphertext = encryptor.update(prefix + bytes(16)) + encryptor.finalize()
        payload = image_codec.V2_MAGIC_6 + struct.pack("<LL", len(prefix), 0) + b"\x00" + ciphertext
        self.assertEqual(self.decode(payload, key), (None, None))
        self.assertFalse((self.root / "decoded.png").exists())

    def test_padding_length_must_match_declared_plaintext_length(self):
        key = bytes(range(16))
        prefix = b"\x89PNG\r\n\x1a\n" + b"12345678"
        encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
        ciphertext = encryptor.update(prefix + b"extra123" + bytes([8]) * 8) + encryptor.finalize()
        payload = image_codec.V2_MAGIC_6 + struct.pack("<LL", len(prefix), 0) + b"\x00" + ciphertext
        self.assertEqual(self.decode(payload, key), (None, None))
        self.assertFalse((self.root / "decoded.png").exists())

    def test_tail_inference_rejects_overlapping_segments(self):
        payload, _ = encrypted_image(bytes(range(16)), tail=b"\xff\xd9", xor_key=0x73)
        malformed = bytearray(payload)
        struct.pack_into("<L", malformed, 10, len(payload) - 15)
        source = self.root / "overlap.dat"
        source.write_bytes(malformed)
        self.assertIsNone(image_codec.infer_v2_xor_key(source, "jpg"))


if __name__ == "__main__":
    unittest.main()
