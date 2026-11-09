"""Build and authenticate the personal fork's native v2 update artifacts.

No private key is used by the Windows build. The trusted publication job signs
the envelope and feed after validating the successful protected-branch run.
"""

import base64
import hashlib
import json
import lzma
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import zipfile


KEY_ID = b"fork-stable-20261109"
MAX_PAYLOAD = 256 * 1024 * 1024
REPOSITORY = "mennya/tdesktop-no-stories"


class UpdateError(Exception):
    pass


def counter_from_env(env=None):
    env = os.environ if env is None else env
    counter = env.get("FORK_BUILD_COUNTER", "")
    if not counter:
        run, attempt = env.get("GITHUB_RUN_NUMBER", ""), env.get("GITHUB_RUN_ATTEMPT", "1")
        if not re.fullmatch(r"[1-9][0-9]*", run) or not re.fullmatch(r"[1-9][0-9]*", attempt):
            raise UpdateError("Provide a positive FORK_BUILD_COUNTER or GitHub run number.")
        if int(attempt) > 99:
            raise UpdateError("Too many attempts for this run; dispatch a fresh build.")
        counter = str(int(run) * 1000 + int(attempt) * 10)
    if not re.fullmatch(r"[1-9][0-9]*", counter) or int(counter) > 0xFFFFFFFF:
        raise UpdateError("Fork build number must be a positive uint32.")
    return int(counter)


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def version_base(text):
    if not re.fullmatch(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", text):
        raise UpdateError("Bad application version.")
    a, b, c = map(int, text.split("."))
    return a * 1000000 + b * 1000 + c


def checksum_file(directory):
    directory = Path(directory)
    text = "".join(f"{sha256(p)}  {p.name}\n" for p in sorted(directory.iterdir())
                   if p.is_file() and p.name != "SHA256SUMS.txt")
    (directory / "SHA256SUMS.txt").write_text(text, encoding="utf-8")


def parse_envelope(blob):
    """Strict native wire-format parser; no decompression or code execution."""
    at = 0

    def take(size):
        nonlocal at
        if size < 0 or at + size > len(blob):
            raise UpdateError("Truncated update envelope.")
        value = blob[at:at + size]
        at += size
        return value

    def number(fmt):
        return struct.unpack(fmt, take(struct.calcsize(fmt)))[0]

    def sized(cap):
        size = number("<I")
        if not 0 < size <= cap:
            raise UpdateError("Bad envelope field size.")
        return take(size)

    if take(4) != b"TDUP" or number("<I") != 2:
        raise UpdateError("Expected a native v2 update.")
    channel, target_os, arch = number("<B"), number("<B"), number("<B")
    version, created = number("<Q"), number("<Q")
    manifest = sized(256 * 1024)
    signed_region = blob[:at]
    manifest_signature = sized(256)
    count_at = at
    count = number("<I")
    if count > 16:
        raise UpdateError("Too many update signatures.")
    signatures = [(sized(64), sized(512)) for _ in range(count)]
    payload = sized(MAX_PAYLOAD)
    if at != len(blob):
        raise UpdateError("Trailing update data.")
    return dict(channel=channel, os=target_os, arch=arch, version=version,
                created=created, manifest=manifest, manifest_signature=manifest_signature,
                signed_region=signed_region, count_at=count_at,
                signatures=signatures, payload=payload)


def signing_input(envelope):
    return envelope["signed_region"] + hashlib.sha256(envelope["payload"]).digest()


def program_file(name):
    parts = name.split("/")
    if any(not p or p in (".", "..") or ":" in p or "\\" in p
           or p.endswith((" ", ".")) for p in parts):
        return False
    folded = name.lower()
    return (folded in {"telegram.exe", "updater.exe", "build-info.json", "legal", "license", "readme.txt"}
            or folded.endswith(".dll") and (len(parts) == 1 or parts[0].lower() == "modules"))


def payload_hashes(payload, expected_base):
    if len(payload) < 10 or payload[0] >= 225:
        raise UpdateError("Bad Windows LZMA header.")
    dictionary, original = struct.unpack_from("<II", payload, 1)
    if not 4096 <= dictionary <= 128 * 1024 * 1024 or not 0 < original <= 1024 * 1024 * 1024:
        raise UpdateError("Windows LZMA bounds exceeded.")
    try:
        # LzmaCompress emits no EOS marker. Its known output size is part of
        # the Windows header; asking a raw decoder for one more byte can decode
        # range-coder flush bits as extra output. Adapt the uint32 size to the
        # standard LZMA-Alone uint64 header so liblzma enforces that boundary.
        alone = payload[:5] + struct.pack("<Q", original) + payload[9:]
        decoder = lzma.LZMADecompressor(lzma.FORMAT_ALONE, memlimit=256 * 1024 * 1024)
        uncompressed = decoder.decompress(alone, max_length=original + 1)
    except lzma.LZMAError as error:
        raise UpdateError("Invalid Windows LZMA payload.") from error
    if len(uncompressed) != original or not decoder.eof or decoder.unused_data:
        raise UpdateError("Incomplete or overlong Windows LZMA payload.")
    view, at = memoryview(uncompressed), 0

    def take(size):
        nonlocal at
        if size < 0 or at + size > len(view):
            raise UpdateError("Truncated QDataStream update.")
        value = view[at:at + size]
        at += size
        return value

    def number():
        return struct.unpack(">I", take(4))[0]

    if number() != expected_base:
        raise UpdateError("Inner application version differs from envelope.")
    count = number()
    if not 0 < count <= 4096:
        raise UpdateError("Bad Windows payload file count.")
    hashes, folded = {}, set()
    for _ in range(count):
        length = number()
        if not 0 < length <= 2048 or length % 2:
            raise UpdateError("Bad Windows payload filename length.")
        try:
            name = bytes(take(length)).decode("utf-16-be")
        except UnicodeError as error:
            raise UpdateError("Invalid Windows payload filename.") from error
        size, data_size = number(), number()
        if data_size == 0xFFFFFFFF:
            data_size = 0
        if size != data_size or not program_file(name) or name.lower() in folded:
            raise UpdateError("Unsafe, duplicate or inconsistent payload file.")
        folded.add(name.lower())
        hashes[name] = hashlib.sha256(take(size)).hexdigest()
    if at != len(view):
        raise UpdateError("Trailing Windows payload data.")
    return hashes


def portable_hashes(path, info):
    result, folded, total = {}, set(), 0
    with zipfile.ZipFile(path) as archive:
        if len(archive.infolist()) > 4096:
            raise UpdateError("Too many portable archive entries.")
        for item in archive.infolist():
            if item.is_dir():
                continue
            prefix = "Telegram No Stories/"
            if not item.filename.startswith(prefix):
                raise UpdateError("Portable archive has an unexpected root.")
            name = item.filename[len(prefix):]
            total += item.file_size
            if (name.lower() in folded or total > 1024 * 1024 * 1024
                    or item.flag_bits & 1 or (item.external_attr >> 16) & 0o170000 == 0o120000):
                raise UpdateError("Duplicate or oversized portable file.")
            folded.add(name.lower())
            if name == "TelegramForcePortable/KEEP-THIS-FOLDER.txt":
                continue
            if not program_file(name):
                raise UpdateError("Portable archive contains account data or an unsafe path.")
            with archive.open(item) as stream:
                digest, carry, identity_found = hashlib.sha256(), b"", False
                identity = f"Telegram-No-Stories fork-build:{info['fork_build']} windows-x64\0".encode()
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    identity_found |= identity in carry + chunk
                    carry = chunk[-len(identity):]
                result[name] = digest.hexdigest()
                if name == "Telegram.exe" and not identity_found:
                    raise UpdateError("Executable does not contain the configured fork build identity.")
            if name == "build-info.json":
                if item.file_size > 4096 or json.loads(archive.read(item)) != info:
                    raise UpdateError("Portable build manifest differs from release manifest.")
            if name in ("Telegram.exe", "Updater.exe"):
                with archive.open(item) as stream:
                    header = stream.read(4096)
                    if len(header) < 64 or header[:2] != b"MZ":
                        raise UpdateError("Portable program is not a PE executable.")
                    offset = struct.unpack_from("<I", header, 60)[0]
                    if not 64 <= offset <= 1024 * 1024:
                        raise UpdateError("PE header offset exceeds bounds.")
                    stream.seek(offset)
                    if stream.read(6) != b"PE\0\0\x64\x86":
                        raise UpdateError("Portable program is not Windows AMD64.")
    if (result.get("Telegram.exe") != info.get("executable_sha256")
            or result.get("Updater.exe") != info.get("updater_sha256")
            or "build-info.json" not in result):
        raise UpdateError("Portable executable hashes or required files differ.")
    return result


def openssl(args, data=None):
    result = subprocess.run(["openssl", *args], input=data, capture_output=True)
    if result.returncode:
        # Do not include key material, raw responses or secret-bearing stderr.
        raise UpdateError("OpenSSL update-signature operation failed.")
    return result.stdout


def sign_bytes(data, key, scratch):
    source, signature = scratch / "signing-input", scratch / "signature"
    source.write_bytes(data)
    openssl(["pkeyutl", "-sign", "-rawin", "-inkey", str(key),
             "-in", str(source), "-out", str(signature)])
    result = signature.read_bytes()
    if len(result) != 64:
        raise UpdateError("Expected an Ed25519 signature.")
    return result


def verify_bytes(data, signature, public_key, scratch):
    source, sig = scratch / "verify-input", scratch / "verify-signature"
    source.write_bytes(data)
    sig.write_bytes(signature)
    openssl(["pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", str(public_key),
             "-in", str(source), "-sigfile", str(sig)])


def select_build(directory, commit, build=None):
    directory = Path(directory)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise UpdateError("An exact source commit is required.")
    candidates = []
    for path in directory.glob("*-build-info.json"):
        if path.stat().st_size > 4096:
            raise UpdateError("Oversized build manifest.")
        info = json.loads(path.read_text(encoding="utf-8"))
        counter = info.get("fork_build")
        if (info.get("commit") != commit or info.get("platform") != "windows-x64"
                or info.get("configuration") != "Release"
                or info.get("build_kind") != "production"
                or info.get("fork_auto_updates") is not True
                or type(counter) is not int or not 0 < counter <= 0xFFFFFFFF):
            raise UpdateError("Artifact is not a production fork update build.")
        version_base(info.get("version", ""))
        prefix = f"telegram-no-stories-{info['version']}-win-x64-{commit[:8]}-b{counter}-production"
        if path.name != prefix + "-build-info.json":
            raise UpdateError("Build manifest filename does not match its identity.")
        if build is None or counter == build:
            candidates.append((counter, info, prefix))
    if not candidates:
        raise UpdateError("Requested fork build is absent.")
    candidates.sort(key=lambda x: x[0])
    if len({x[0] for x in candidates}) != len(candidates):
        raise UpdateError("Duplicate build manifests.")
    return candidates[-1]


def verify_artifact_checksums(directory):
    directory = Path(directory)
    checksums = directory / "SHA256SUMS.txt"
    if not checksums.is_file() or checksums.stat().st_size > 128 * 1024:
        raise UpdateError("Package checksum manifest is absent or too large.")
    seen = set()
    for line in checksums.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        if not match or match[2] in seen or match[2] == "SHA256SUMS.txt":
            raise UpdateError("Bad package checksum entry.")
        seen.add(match[2])
        file = directory / match[2]
        if not file.is_file() or file.is_symlink() or sha256(file) != match[1]:
            raise UpdateError("A package checksum did not match.")
    actual = {p.name for p in directory.iterdir() if p.is_file()} - {"SHA256SUMS.txt"}
    if actual != seen:
        raise UpdateError("Package checksum coverage is incomplete.")


def sign_release(directory, output, trust_directory, commit, key_bytes, build=None):
    directory, output, trust = Path(directory), Path(output), Path(trust_directory)
    verify_artifact_checksums(directory)
    counter, info, prefix = select_build(directory, commit, build)
    base = version_base(info["version"])
    filename = f"td-update-win-x64-{base}-fork-{counter}"
    unsigned_path = directory / (filename + ".unsigned")
    if unsigned_path.stat().st_size > MAX_PAYLOAD + 512 * 1024:
        raise UpdateError("Oversized unsigned envelope.")
    unsigned = unsigned_path.read_bytes()
    envelope = parse_envelope(unsigned)
    expected_manifest = (trust / "manifest.min.json").read_bytes()
    expected_signature = (trust / "manifest.sig").read_bytes()
    if ((envelope["channel"], envelope["os"], envelope["arch"]) != (0, 0, 1)
            or envelope["version"] != (base << 32 | counter)
            or envelope["signatures"] or envelope["manifest"] != expected_manifest
            or envelope["manifest_signature"] != expected_signature):
        raise UpdateError("Unsigned envelope identity or trust files did not match.")
    expected_files = portable_hashes(directory / (prefix + "-portable.zip"), info)
    if payload_hashes(envelope["payload"], base) != expected_files:
        raise UpdateError("Native update payload differs from the portable package.")
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="fork-sign-") as private:
        scratch = Path(private)
        key = scratch / "key.pem"
        key.write_bytes(key_bytes)
        key.chmod(0o600)
        public = trust / "root-public.pem"
        derived = openssl(["pkey", "-in", str(key), "-pubout"])
        if derived.strip() != public.read_bytes().strip():
            raise UpdateError("Signing secret does not match the pinned fork public key.")
        verify_bytes(expected_manifest, expected_signature, public, scratch)
        signature = sign_bytes(signing_input(envelope), key, scratch)
        verify_bytes(signing_input(envelope), signature, public, scratch)
        encoded_signature = (struct.pack("<II", 1, len(KEY_ID)) + KEY_ID
                             + struct.pack("<I", len(signature)) + signature)
        blob = unsigned[:envelope["count_at"]] + encoded_signature
        blob += struct.pack("<I", len(envelope["payload"])) + envelope["payload"]
        signed = parse_envelope(blob)
        if signed["signatures"] != [(KEY_ID, signature)]:
            raise UpdateError("Signed envelope round trip failed.")
        package = output / filename
        package.write_bytes(blob)
        for suffix in ("-portable.zip", "-setup.exe", "-build-info.json"):
            source = directory / (prefix + suffix)
            if not source.is_file():
                raise UpdateError("A release package is missing.")
            # Copies are data only; publication never executes downloaded tools.
            import shutil
            shutil.copyfile(source, output / source.name)
        release = dict(product="telegram-no-stories", platform="windows-x64",
                       version=info["version"], base_version=base, build=counter,
                       commit=commit, tag=f"fork-v{info['version']}-b{counter}",
                       filename=filename, sha256=sha256(package), size=package.stat().st_size)
        document = json.loads(expected_manifest)
        document["release"] = release
        data = json.dumps(document, separators=(",", ":"), ensure_ascii=True).encode()
        feed_signature = sign_bytes(data, key, scratch)
        verify_bytes(data, feed_signature, public, scratch)
        wrapper = {"data": base64.b64encode(data).decode(),
                   "signature": base64.b64encode(feed_signature).decode()}
        (output / "fork-update.json").write_text(json.dumps(wrapper) + "\n", encoding="utf-8")
    checksum_file(output)
    return release
