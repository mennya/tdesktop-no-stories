import base64
import json
import lzma
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zipfile

import fork_update_tools as updates


COMMIT = "a" * 40
BUILD = 20010
BASE = 7004001


def pe():
    result = bytearray(256)
    result[:2] = b"MZ"
    struct.pack_into("<I", result, 60, 128)
    result[128:134] = b"PE\0\0\x64\x86"
    return bytes(result)


class Fixture:
    def __init__(self, root):
        self.root = root
        self.trust, self.inputs = root / "trust", root / "inputs"
        self.trust.mkdir()
        self.inputs.mkdir()
        self.key = updates.openssl(["genpkey", "-algorithm", "ED25519"])
        self.public = updates.openssl(["pkey", "-pubout"], self.key)
        raw = updates.openssl(["pkey", "-pubout", "-outform", "DER"], self.key)[-32:]
        self.manifest = json.dumps(dict(format=1, manifest_version=1, issued=1, expires=0,
            keys=[dict(id=updates.KEY_ID.decode(), alg="Ed25519", x=base64.urlsafe_b64encode(raw).decode().rstrip("="))],
            channels={"stable": [[updates.KEY_ID.decode()]]}, revoked=[]), separators=(",", ":")).encode()
        (self.trust / "root-public.pem").write_bytes(self.public)
        (self.trust / "manifest.min.json").write_bytes(self.manifest)
        with tempfile.TemporaryDirectory() as private:
            directory = Path(private)
            key = directory / "fixture.pem"
            key.write_bytes(self.key)
            self.manifest_signature = updates.sign_bytes(self.manifest, key, directory)
        (self.trust / "manifest.sig").write_bytes(self.manifest_signature)
        self.info = dict(name="Telegram No Stories", version="7.4.1", commit=COMMIT,
            platform="windows-x64", configuration="Release", build_kind="production",
            official_auto_updates=False, fork_auto_updates=True, fork_build=BUILD,
            signed=False, update_signature="Ed25519",
            executable_sha256=__import__("hashlib").sha256(pe()).hexdigest(),
            updater_sha256=__import__("hashlib").sha256(pe() + b"updater").hexdigest())
        self.prefix = f"telegram-no-stories-7.4.1-win-x64-{COMMIT[:8]}-b{BUILD}-production"
        self.filename = f"td-update-win-x64-{BASE}-fork-{BUILD}"
        self.files = {"Telegram.exe": pe(), "Updater.exe": pe() + b"updater", "LICENSE": b"License fixture"}
        self.write()

    def write(self, *, payload_extra=None, target=(0, 0, 1), info=None):
        info = self.info if info is None else info
        document = (json.dumps(info, indent=2) + "\n").encode()
        files = dict(self.files, **{"build-info.json": document})
        with zipfile.ZipFile(self.inputs / (self.prefix + "-portable.zip"), "w", zipfile.ZIP_DEFLATED) as archive:
            for name, value in files.items():
                archive.writestr("Telegram No Stories/" + name, value)
            archive.writestr("Telegram No Stories/TelegramForcePortable/KEEP-THIS-FOLDER.txt", "Marker")
        (self.inputs / (self.prefix + "-build-info.json")).write_bytes(document)
        (self.inputs / (self.prefix + "-setup.exe")).write_bytes(b"installer fixture")
        files.update(payload_extra or {})
        data = bytearray(struct.pack(">II", BASE, len(files)))
        for name, value in files.items():
            encoded = name.encode("utf-16-be")
            data += struct.pack(">I", len(encoded)) + encoded + struct.pack(">II", len(value), len(value)) + value
        filters = dict(id=lzma.FILTER_LZMA1, dict_size=4 * 1024 * 1024, lc=3, lp=0, pb=2)
        payload = bytes([93]) + struct.pack("<II", filters["dict_size"], len(data))
        payload += lzma.compress(data, format=lzma.FORMAT_RAW, filters=[filters])
        blob = b"TDUP" + struct.pack("<IBBBQQI", 2, *target, BASE << 32 | BUILD, 1, len(self.manifest))
        blob += self.manifest + struct.pack("<I", len(self.manifest_signature)) + self.manifest_signature
        blob += struct.pack("<II", 0, len(payload)) + payload
        (self.inputs / (self.filename + ".unsigned")).write_bytes(blob)
        updates.checksum_file(self.inputs)

    def sign(self):
        return updates.sign_release(self.inputs, self.root / "signed", self.trust, COMMIT, self.key, BUILD)


class CounterTests(unittest.TestCase):
    def test_own_fix_and_retry_are_monotonic(self):
        first = updates.counter_from_env({"GITHUB_RUN_NUMBER": "20", "GITHUB_RUN_ATTEMPT": "1"})
        retry = updates.counter_from_env({"GITHUB_RUN_NUMBER": "20", "GITHUB_RUN_ATTEMPT": "2"})
        fresh = updates.counter_from_env({"GITHUB_RUN_NUMBER": "21"})
        self.assertLess(first, first + 1)
        self.assertLess(first + 1, retry)
        self.assertLess(retry, fresh)

    def test_counter_bounds(self):
        for env in ({}, {"FORK_BUILD_COUNTER": "0"}, {"FORK_BUILD_COUNTER": "4294967296"},
                    {"GITHUB_RUN_NUMBER": "20", "GITHUB_RUN_ATTEMPT": "100"}):
            with self.subTest(env=env), self.assertRaises(updates.UpdateError):
                updates.counter_from_env(env)


class SigningTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = Fixture(Path(self.temporary.name))

    def test_signs_only_the_verified_portable_payload(self):
        release = self.fixture.sign()
        signed = self.fixture.root / "signed"
        envelope = updates.parse_envelope((signed / release["filename"]).read_bytes())
        self.assertEqual(envelope["version"], BASE << 32 | BUILD)
        self.assertEqual([x[0] for x in envelope["signatures"]], [updates.KEY_ID])
        with tempfile.TemporaryDirectory() as temporary:
            updates.verify_bytes(updates.signing_input(envelope), envelope["signatures"][0][1],
                                 self.fixture.trust / "root-public.pem", Path(temporary))
            feed = json.loads((signed / "fork-update.json").read_text())
            data, signature = base64.b64decode(feed["data"]), base64.b64decode(feed["signature"])
            updates.verify_bytes(data, signature, self.fixture.trust / "root-public.pem", Path(temporary))
        self.assertEqual(json.loads(data)["release"], release)
        self.assertEqual(release["sha256"], updates.sha256(signed / release["filename"]))
        updates.verify_artifact_checksums(signed)

    def test_rejects_account_data_even_in_an_authenticated_build_artifact(self):
        for name in ("TelegramForcePortable/tdata/settings", "tdata/key_data", "../Telegram.exe"):
            with self.subTest(name=name):
                self.fixture.write(payload_extra={name: b"not allowed"})
                with self.assertRaises(updates.UpdateError):
                    self.fixture.sign()

    def test_rejects_wrong_architecture(self):
        self.fixture.write(target=(0, 0, 2))
        with self.assertRaisesRegex(updates.UpdateError, "identity"):
            self.fixture.sign()

    def test_rejects_modified_package(self):
        file = self.fixture.inputs / (self.fixture.filename + ".unsigned")
        file.write_bytes(file.read_bytes() + b"damage")
        with self.assertRaisesRegex(updates.UpdateError, "checksum"):
            self.fixture.sign()

    def test_rejects_payload_that_differs_from_portable(self):
        self.fixture.write(payload_extra={"unexpected.dll": b"unexpected"})
        with self.assertRaisesRegex(updates.UpdateError, "differs"):
            self.fixture.sign()

    def test_rejects_verification_and_mismatched_source(self):
        self.fixture.write(info=dict(self.fixture.info, build_kind="verification"))
        with self.assertRaises(updates.UpdateError):
            self.fixture.sign()
        self.fixture.write()
        with self.assertRaises(updates.UpdateError):
            updates.sign_release(self.fixture.inputs, self.fixture.root / "signed", self.fixture.trust,
                                 "b" * 40, self.fixture.key, BUILD)

    def test_rejects_other_private_key(self):
        other = updates.openssl(["genpkey", "-algorithm", "ED25519"])
        with self.assertRaisesRegex(updates.UpdateError, "pinned"):
            updates.sign_release(self.fixture.inputs, self.fixture.root / "signed", self.fixture.trust,
                                 COMMIT, other, BUILD)

    def test_rejects_truncated_or_overlong_envelope(self):
        original = (self.fixture.inputs / (self.fixture.filename + ".unsigned")).read_bytes()
        for data in (original[:20], original[:-1], original + b"trailing"):
            with self.assertRaises(updates.UpdateError):
                updates.parse_envelope(data)


if __name__ == "__main__":
    unittest.main()
