import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tarfile

EXPECTED = {
    "booter_load_ad102.bin": "6ee05b20e1dc244c08c052f36ef28469b8d09f4955d1fe33e48a179e11a7fd49",
    "v67-ad102-610.43.03-four-plm.bin": "44c36b2d6b3424e53e18f3e55db85c833655de071ce66ce42749588a4a7dc8cb",
    "gsp_ga10x.bin": "572373620a37418f24dc16b5031c39338778c3257e48e8408de9a57291b24f3a",
    "gsp_boot_ad102.bin": "45d6335a8185d6ff13e8d1484cea73f68d3d13aa1c19dc080ed1c3482dd5bac0",
    "gsp_boot_desc_ad102.bin": "83f8f3f1f5f9496e0ea8fc7103c2beb64d0b6de2f5ffe725f13514de5a95fa42",
}
SOURCE_DIR = "NVIDIA-kernel-module-source-610.43.03"
PKG_NAME = "nvidia-utils-610.43.03-1-x86_64_v3.pkg.tar.zst"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="从 NVIDIA 610.43.03 官方输入生成五个 AD102 家族固件资产")
    parser.add_argument("--out", default="assets", help="输出目录")
    parser.add_argument("--cache", default=None, help="下载缓存目录，默认 <out>/../inputs")
    parser.add_argument("--python", default=sys.executable, help="运行生成器所用的解释器")
    args = parser.parse_args()

    if not shutil.which("zstd"):
        parser.exit(1, "需要 zstd 可执行文件在 PATH 里（生成器用 zstd -dc 解 .pkg.tar.zst），"
                       "Windows 上可 winget install Facebook.Zstandard\n")

    repo = pathlib.Path(__file__).resolve().parent.parent
    firmware = repo / "firmware"
    out = pathlib.Path(args.out).resolve()
    cache = pathlib.Path(args.cache).resolve() if args.cache else out.parent / "inputs"
    work = out.parent / "inputs-src"
    out.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)

    subprocess.run([args.python, str(firmware / "fetch_artifacts.py"), str(cache)], check=True)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    with tarfile.open(cache / f"{SOURCE_DIR}.tar.xz") as archive:
        archive.extractall(work)

    subprocess.run([args.python, str(firmware / "generate_v67.py"),
                    str(cache / PKG_NAME), str(out)], check=True)
    subprocess.run([args.python, str(firmware / "extract_boot_assets.py"),
                    str(work / SOURCE_DIR), str(out), "--chip", "ad102"], check=True)

    manifest = json.loads((firmware / "artifacts-610.43.03.json").read_text())
    bad = []
    for name, want in EXPECTED.items():
        path = out / name
        if not path.is_file():
            bad.append(f"{name}: missing")
            continue
        got = sha256(path)
        if got != want:
            bad.append(f"{name}: {got} != {want}")
        print(f"{name} {path.stat().st_size} {got}")
    if bad:
        parser.exit(1, "资产校验失败：\n" + "\n".join(bad) + "\n")
    print(f"五个资产已写入 {out}")


if __name__ == "__main__":
    main()