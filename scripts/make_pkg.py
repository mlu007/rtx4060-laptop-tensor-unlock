import argparse
import hashlib
import pathlib
import shutil

ASSETS = [
    "booter_load_ad102.bin",
    "v67-ad102-610.43.03-four-plm.bin",
    "gsp_ga10x.bin",
    "gsp_boot_ad102.bin",
    "gsp_boot_desc_ad102.bin",
]
EXTRA = [
    "before-after.png",
    "benchmark.py",
    "compare.py",
    "THIRD_PARTY_NOTICES.md",
    "UPSTREAM-WINDOWS-NOTICES.md",
    "NVIDIA-FILES.md",
    "LICENSE",
]


def main():
    parser = argparse.ArgumentParser(description="组装 Windows 安装包目录（不安装任何东西）")
    parser.add_argument("--build", default="build", help="build.py 的输出目录")
    parser.add_argument("--assets", default="assets", help="五个固件资产所在目录")
    parser.add_argument("--out", default="pkg", help="安装包输出目录")
    args = parser.parse_args()

    repo = pathlib.Path(__file__).resolve().parent.parent

    def resolve(value):
        path = pathlib.Path(value)
        return path if path.is_absolute() else (repo / path).resolve()

    build = resolve(args.build)
    assets = resolve(args.assets)
    out = resolve(args.out)

    for name in ("UNLOCK4090.EFI", "UNLOCK4090M.EFI"):
        if not (build / name).is_file():
            parser.exit(1, f"缺少 {build / name}，先跑 build.py\n")
    for name in ASSETS:
        if not (assets / name).is_file():
            parser.exit(1, f"缺少 {assets / name}\n")

    if out.exists():
        shutil.rmtree(out)
    (out / "GPU4090-ASSETS").mkdir(parents=True)

    for name in ("UNLOCK4090.EFI", "UNLOCK4090M.EFI"):
        shutil.copy2(build / name, out / name)
    for name in ASSETS:
        shutil.copy2(assets / name, out / "GPU4090-ASSETS" / name)
    (out / "ASSETS.LIST").write_text("".join(f"GPU4090-ASSETS\\{n}\n" for n in ASSETS), encoding="ascii")

    for pattern in ("*.ps1", "*.cmd"):
        for path in (repo / "package").glob(pattern):
            shutil.copy2(path, out / path.name)
    for name in EXTRA:
        path = repo / name
        if path.exists():
            shutil.copy2(path, out / name)
    shutil.copytree(repo / "LICENSES", out / "LICENSES")
    shutil.copytree(repo / "package" / "tools", out / "tools")

    readme = (repo / "README.md").read_text(encoding="utf-8")
    (out / "README.md").write_text(readme, encoding="utf-8")

    lines = []
    for path in sorted(out.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            rel = path.relative_to(out).as_posix()
            lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {rel}")
    (out / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="ascii")

    total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"{len(lines)} files, {total / 2**20:.1f} MiB in {out}")


if __name__ == "__main__":
    main()