# RTX 4060 Laptop 张量速率解锁（Windows UEFI 移植）

把 `MarvinFS/rtx4090-uefi`（源自 `JustAResearcher/gpu-unlock-ada` 的 `windows/ad104-msi` 与 `Zagitta/gpu-unlock`）移植到 **`10de:28a0` RTX 4060 Laptop（AD107）**，在 Windows 引导之前用 UEFI 程序解除 FP16/BF16 的 FP32-累加半速限制。

不刷写 VBIOS，不替换 NVIDIA 驱动，不修改 Windows 系统文件。

## 实测数据

本机 MECHREVO 翼龙15Pro GM5HG0A，RTX 4060 Laptop 8 GB（24 SM），Windows 11，驱动 610.62，torch 2.12.0+cu130，8192³ GEMM，20 次取中位数。

| 模式 | stock | 解锁 | 解锁 + 关 Whisper Mode |
|---|---:|---:|---:|
| FP16 → FP32 累加 | 10.78 | 24.27 | **49.74** |
| BF16 → FP32 累加 | 11.20 | 22.95 | **49.51** |
| TF32 | 7.37 | 10.45 | **23.71** |
| FP32 SIMT（对照） | 4.65 | 3.73 | 7.03 |
| SM 中位频率 | — | 1215 MHz | 2370–2535 MHz |

前两列同为 Whisper Mode 开启，第三列关闭。FP32 SIMT 是控制组，它的 per-MHz 速率在三种状态下一致（0.0031–0.0032 TF/MHz），说明变化来自被解锁的累加路径与频率，不是功耗假象。

寄存器侧判据（启动日志）：

```
AD102 before-firmware: readout1=0x410080 fields=0 0 2 0 0 2 0 2 0 full=0
selector result: SS0=0x88888888 matched=1
selector result: SS1=0x8 matched=1
AD102 selectors-applied: readout1=0 fields=0 0 0 0 0 0 0 0 0 full=1
PCIe FLR returned: result=0
AD102 post-FLR: readout1=0 full=1
POST-GOP SS0=0x88888888 SS1=0x8
TRANSACTION OK
```

30 秒持续满载诊断（关 Whisper Mode）：

```
sm_mhz  median=2130  min=1860  max=2535
power   median=101.9 W  max=120.8 W
temp    median=83 C  max=86 C
throttle SwThermal 886/1080  SwPowerCap 169/1080
```

瓶颈已经是散热，不是解锁。

## 原理

消费级 Ada 卡的 FP32-累加张量路径被固件限到 FP16-累加速率的一半。这条限制由速度选择器 `SS0`/`SS1` 和四个 PLM 权限寄存器共同决定，且只有 NVIDIA 自己的签名固件链能改写它们。程序在 Windows 引导前：

1. 读卡自身 VBIOS（`BAR0+0x300000`，1 MiB）解析 FWSEC 描述符；
2. 用签名 GSP Falcon 加载 FWSEC 建立 WPR2；
3. 在 SEC2 上运行 AD102 家族 Booter 与四 PLM payload，把 `WPR_CFG`/`WPR`/`FEAT_OVR_PLM` 打开到全 1；
4. 写 `SS0=0x88888888`、`SS1=0x8`，回读确认生效；
5. 做一次 PCIe FLR，确认选择器保持；
6. 交棒原有的 Windows Boot Manager。

选择器是易失寄存器，完全断电后回到原值，所以每次冷启动都要跑一次。这不是永久修改硬件，也无法改到永久——那需要改写卡上签名的固件。

## 相对上游的改动

| 文件 | 改动 |
|---|---|
| `port.h` | `GU_BOARD_ID` → `0x28a010de`；`GU_PLATFORM` 增加 `entry_command` 记录固件进入时的 PCI command |
| `vendor/prep_610.h` | 新增 `GU_AD107_RTX_4060_LAPTOP 0x28a0u` 与 `GU_AD_PINNED_BOOTER_FAMILY(d)`（AD102 / AD103 canary / AD107） |
| `vendor/unlock_610.c` | 四处把 `0x2684` 硬判定改为家族判定：`unlock_assets()`、`is_ad102()`、`gpu_unlock_610_load_shared()`、`gpu_unlock_610_unlock()`。不改这里，0x28a0 会落到 GA102 资产集，其 booter 在 Ada 上 halt |
| `app.c` | `Discover()` 在 `GuCheckConfig` 之前先通过 `PciIo->Attributes` 打开 memory decode 并重读 config；记录 `entry_command`；新增只读的 `FLR_capable` 日志；事务核心 `.device` → `0x28a0` |
| `release.c` | preflight 冗余处理 memory decode；`SameAfterDriver` 的 decode 位以固件入口 command 为第二判据 |
| `package/Install-Gpu4090Unlock.ps1` | GPU 检查 `DEV_28A0`；启动项名 `RTX 4060 Laptop unlock` |
| `tests/` | 夹具 device id 同步为 28a0（PROM/config 字节仍是原先的 4090 捕获，用于验证逻辑而非硬件） |

`Alive()` 的控制台判据**没有**放宽：实机 RELTEST 证明 `DisconnectController` 级联拆掉 GPU 的 GOP 子之后，系统表的 `ConsoleOutHandle`/`ConOut`/`ConIn` 指针不变，判据照旧通过。

## 环境要求

- Windows 11，UEFI 引导，**Secure Boot 关闭**（EFI 未签名）
- 恰好一张 `10de:28a0`
- BitLocker 先挂起：`Suspend-BitLocker -MountPoint C: -RebootCount 3`
- 目标卷需要约 85 MB FAT32 空间：ESP 有余量就用 ESP，否则安装器新建 128 MB 分区（不缩卷，用已有未分配空间）
- 建议关闭 Whisper Mode，电源方案切「卓越性能」，否则频率被压在 1100–1300 MHz

## 构建

需要 Python 3 与 zig **0.14.1**。

```sh
python build.py --zig zig --out build
```

产出四个镜像：`UNLOCK4090.EFI`（倒计时后自动解锁）、`UNLOCK4090M.EFI`（按 U 解锁）、`DRYRUN4090.EFI`（全部写门关闭，只跑准入预检）、`RELTEST4090.EFI`（只做显示释放与重连，不写 GPU）。

### 固件资产

仓库自带 `assets/` 里已生成的五个文件：

```
booter_load_ad102.bin                   57672  sha256 6ee05b20e1dc244c08c052f36ef28469b8d09f4955d1fe33e48a179e11a7fd49
v67-ad102-610.43.03-four-plm.bin        64000  sha256 44c36b2d6b3424e53e18f3e55db85c833655de071ce66ce42749588a4a7dc8cb
gsp_ga10x.bin                        84277400  sha256 572373620a37418f24dc16b5031c39338778c3257e48e8408de9a57291b24f3a
gsp_boot_ad102.bin                      36864  sha256 45d6335a8185d6ff13e8d1484cea73f68d3d13aa1c19dc080ed1c3482dd5bac0
gsp_boot_desc_ad102.bin                    84  sha256 83f8f3f1f5f9496e0ea8fc7103c2beb64d0b6de2f5ffe725f13514de5a95fa42
```

要自己从 NVIDIA 官方输入重新生成（`firmware/` 内是上游的生成器）：

```sh
python scripts/make_assets.py --out assets
```

脚本会下载 NVIDIA `610.43.03` 的 kernel module source 与 CachyOS `nvidia-utils` 包，按 `firmware/artifacts-610.43.03.json` 的 SHA-256 校验后生成。需要一个可用的 `zstd` 可执行文件在 `PATH` 里（生成器用 `zstd -dc` 解 `.pkg.tar.zst`），Windows 上可以 `winget install Facebook.Zstandard`。

## 安装

```sh
python scripts/make_pkg.py --build build --assets assets --out pkg
```

先看计划（默认 dry run，不改任何东西），需要管理员：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File pkg\Install-Gpu4090Unlock.ps1
```

确认无误后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File pkg\Install-Gpu4090Unlock.ps1 -Apply
```

安装器会：选目标卷并复制 EFI 与五个资产（读回校验 SHA-256）→ 复制 `{bootmgr}` 建一个固件启动项、指向 `\EFI\GPU4090\UNLOCK4090.EFI` 并放到第一位 → 关闭 Windows 快速启动（`HiberbootEnabled=0`，原值写入安装记录，卸载时还原）→ 移除新分区的盘符 → 把检查与卸载脚本复制到 `C:\ProgramData\Gpu4090Unlock`。

Windows Boot Manager 保留在第二位，作为回退。

重启后：先跑解锁条目，3 秒倒计时结束自动解锁并进 Windows；倒计时内按 Esc 打开菜单，选 2 进不解锁的 Windows。

## 验证

```powershell
C:\ProgramData\Gpu4090Unlock\Check.cmd
```

它读安装记录、固件启动顺序、目标卷上的文件哈希和本次启动的日志 `\GPU4090-UNLOCK\RUNnnnn.TXT`。

吞吐测量：

```sh
python scripts/bench.py            # 四种模式的 TFLOPS 与 SM 时钟归一化
python scripts/bench.py --throttle # 30 秒满载，记录时钟/功耗/温度与降频原因
```

安装后启动日志写在 `GPU4090` 卷（无盘符），用 `scripts/mount_volume.ps1` 临时挂载读取，或直接用 `Check.cmd`。

## 卸载与恢复

```powershell
C:\ProgramData\Gpu4090Unlock\Uninstall.cmd            # 计划
C:\ProgramData\Gpu4090Unlock\Uninstall.cmd /apply??   # 见脚本内 -Apply
```

删除固件启动项、目标卷上的文件，并还原快速启动设置。新增的分区保留，可在磁盘管理里删除回收空间。

黑屏或进不去 Windows：长按电源断电，然后在固件启动菜单（本机 F7）选 `Windows Boot Manager`。事务被中断后必须完全断电再试，不要软重启。

## 已知限制

- 单机、单 VBIOS（`95.07.40.40.32`）、单厂商验证。其他 AD107 板卡需自行确认准入日志全过。
- 散热是当前瓶颈（83–86 ℃，82% 采样命中软件温控）。
- 本机固件不支持 S3，只有 S0 modern standby；休眠唤醒、驱动更新、`devcon restart` 之后都要重启重新解锁。
- 打开快速启动时，"关机"是会话休眠，卡可能以 stock 状态启动；安装器默认把它关掉。

## 许可与来源

代码 GPL-2.0-only，与上游一致。保留 `LICENSE`、`LICENSE-gpu-unlock-ada`、`THIRD_PARTY_NOTICES.md`、`UPSTREAM-WINDOWS-NOTICES.md`、`NVIDIA-FILES.md`、`provenance.json`。

`assets/` 里的五个文件是 NVIDIA 的签名固件，按 NVIDIA 自己的许可原样附带，来源与 SHA-256 见上表；上游项目不分发这些文件。若权利人提出要求，删除对应文件即可，`scripts/make_assets.py` 能重新生成。

上游：
- `MarvinFS/rtx4090-uefi`（本仓库的直接基线）
- `JustAResearcher/gpu-unlock-ada`（Ada 资产、Booter 与四 PLM payload）
- `Zagitta/gpu-unlock`（机制最初实现）
- `impacifist/Windows-GPU-UNLOCK`（UEFI 策略参考）
- `Q1y1ng/gpu-unlock-win`（笔记本 dGPU 直连拓扑的实测参考）