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
VARIANTS = {
    "dryrun": ("DRYRUN4090.EFI", "只跑准入预检，不写 GPU、不碰显示驱动；倒计时结束进 Windows"),
    "reltest": ("RELTEST4090.EFI", "断开并重连显示驱动，验证控制台判据，不写 GPU；倒计时内按 U"),
    "unlockm": ("UNLOCK4090M.EFI", "真正执行事务；倒计时内按 U"),
}


def main():
    parser = argparse.ArgumentParser(description="生成三个可直接复制到 FAT32 U 盘的目录")
    parser.add_argument("--build", default="prebuilt", help="存放四个 EFI 的目录")
    parser.add_argument("--assets", default="assets", help="五个固件资产所在目录")
    parser.add_argument("--out", default="stick", help="输出目录")
    args = parser.parse_args()

    repo = pathlib.Path(__file__).resolve().parent.parent

    def resolve(value):
        path = pathlib.Path(value)
        return path if path.is_absolute() else (repo / path).resolve()

    build = resolve(args.build)
    assets = resolve(args.assets)
    out = resolve(args.out)

    for image, _ in VARIANTS.values():
        if not (build / image).is_file():
            parser.exit(1, f"缺少 {build / image}\n")
    for name in ASSETS:
        if not (assets / name).is_file():
            parser.exit(1, f"缺少 {assets / name}\n")

    if out.exists():
        shutil.rmtree(out)

    for variant, (image, purpose) in VARIANTS.items():
        root = out / variant
        (root / "EFI" / "BOOT").mkdir(parents=True)
        (root / "GPU4090-ASSETS").mkdir(parents=True)
        shutil.copy2(build / image, root / "EFI" / "BOOT" / "BOOTX64.EFI")
        for name in ASSETS:
            shutil.copy2(assets / name, root / "GPU4090-ASSETS" / name)
        lines = []
        for path in sorted(root.rglob("*")):
            if path.is_file():
                rel = path.relative_to(root).as_posix()
                lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {rel}")
        (root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="ascii")
        print(f"{root}  <- {image}  ({purpose})")

    print(f"\n把某个变体目录里的内容复制到 FAT32 U 盘根目录（一次只放一个），"
          f"开机进启动菜单选 UEFI USB。共 {len(VARIANTS)} 个变体。")


if __name__ == "__main__":
    main()