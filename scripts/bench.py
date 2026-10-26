import argparse
import json
import pathlib
import statistics
import threading
import time

import pynvml
import torch

THROTTLE = {
    "GpuIdle": 0x1,
    "AppClocks": 0x2,
    "SwPowerCap": 0x4,
    "HwSlowdown": 0x8,
    "SyncBoost": 0x10,
    "SwThermal": 0x20,
    "HwThermal": 0x40,
    "HwPowerBrake": 0x80,
    "DisplayClock": 0x100,
}


class Probe:
    """后台按固定间隔读 NVML，测量循环里不插入任何外部调用。"""

    def __init__(self):
        pynvml.nvmlInit()
        self.handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        self.rows = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.rows.append((
                    float(pynvml.nvmlDeviceGetClockInfo(self.handle, pynvml.NVML_CLOCK_SM)),
                    pynvml.nvmlDeviceGetPowerUsage(self.handle) / 1000.0,
                    float(pynvml.nvmlDeviceGetTemperature(self.handle, pynvml.NVML_TEMPERATURE_GPU)),
                    pynvml.nvmlDeviceGetCurrentClocksThrottleReasons(self.handle),
                ))
            except pynvml.NVMLError:
                pass
            self._stop.wait(0.02)

    def start(self):
        self.rows = []
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join()
        return self.rows


def medians(rows):
    return {
        "sm_mhz_median": statistics.median(r[0] for r in rows),
        "sm_mhz_max": max(r[0] for r in rows),
        "power_w_median": statistics.median(r[1] for r in rows),
        "power_w_max": max(r[1] for r in rows),
        "temp_c_median": statistics.median(r[2] for r in rows),
        "temp_c_max": max(r[2] for r in rows),
    }


def gemm_modes(n, iters, probe):
    torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = False
    torch.backends.cuda.matmul.allow_bf16_reduced_precision_reduction = False

    def measure(dtype, tf32):
        torch.backends.cuda.matmul.allow_tf32 = tf32
        a = torch.randn((n, n), device="cuda", dtype=dtype)
        b = torch.randn((n, n), device="cuda", dtype=dtype)
        c = torch.empty_like(a)
        for _ in range(3):
            torch.mm(a, b, out=c)
        torch.cuda.synchronize()
        probe.start()
        times = []
        for _ in range(iters):
            start = torch.cuda.Event(True)
            end = torch.cuda.Event(True)
            start.record()
            torch.mm(a, b, out=c)
            end.record()
            end.synchronize()
            times.append(start.elapsed_time(end))
        rows = probe.stop()
        del a, b, c
        torch.cuda.empty_cache()
        ms = statistics.median(times)
        tflops = 2 * n ** 3 / (ms * 1e-3) / 1e12
        result = {"ms": round(ms, 3), "tflops": round(tflops, 3), "samples": len(rows)}
        result.update({k: round(v, 4) for k, v in medians(rows).items()})
        result["tflops_per_mhz"] = round(tflops / result["sm_mhz_median"], 6) if result["sm_mhz_median"] else None
        return result

    return {
        "fp16_f32acc": measure(torch.float16, False),
        "bf16_f32acc": measure(torch.bfloat16, False),
        "tf32": measure(torch.float32, True),
        "fp32_simt": measure(torch.float32, False),
    }


def throttle_probe(n, seconds, probe):
    a = torch.randn((n, n), device="cuda", dtype=torch.float16)
    b = torch.randn((n, n), device="cuda", dtype=torch.float16)
    c = torch.empty_like(a)
    probe.start()
    deadline = time.perf_counter() + seconds
    iterations = 0
    while time.perf_counter() < deadline:
        torch.mm(a, b, out=c)
        iterations += 1
    torch.cuda.synchronize()
    rows = probe.stop()
    hits = {name: sum(1 for r in rows if r[3] & bit) for name, bit in THROTTLE.items()}
    return {
        "samples": len(rows),
        "iterations": iterations,
        "size": n,
        "seconds": seconds,
        **{k: round(v, 4) for k, v in medians(rows).items()},
        "throttle": {name: hits for name, hits in hits.items() if hits},
    }


def main():
    parser = argparse.ArgumentParser(description="张量吞吐与降频诊断")
    parser.add_argument("--size", type=int, default=8192, help="GEMM 维度，默认 8192")
    parser.add_argument("--iters", type=int, default=20, help="每种模式的测量次数")
    parser.add_argument("--throttle", action="store_true", help="改为 30 秒持续满载的降频诊断")
    parser.add_argument("--throttle-size", type=int, default=4096)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--tag", default="current", help="输出文件名后缀")
    args = parser.parse_args()

    probe = Probe()
    print(f"torch={torch.__version__} cuda={torch.version.cuda} gpu={torch.cuda.get_device_name(0)}")
    free, total = torch.cuda.mem_get_info()
    print(f"vram free={free / 2**30:.2f} GiB total={total / 2**30:.2f} GiB")

    if args.throttle:
        report = throttle_probe(args.throttle_size, args.seconds, probe)
        print(json.dumps(report, indent=2))
    else:
        report = {"size": args.size, "iters": args.iters,
                  "modes": gemm_modes(args.size, args.iters, probe)}
        for name, mode in report["modes"].items():
            print(f"{name:14s} {mode['tflops']:8.2f} TFLOPS  "
                  f"clock {mode['sm_mhz_median']:6.0f} max {mode['sm_mhz_max']:6.0f} MHz  "
                  f"{mode['tflops_per_mhz']} TF/MHz  {mode['power_w_median']:.1f} W  {mode['temp_c_median']:.0f} C")

    out = pathlib.Path(__file__).resolve().parent.parent / f"bench-{args.tag}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"written {out}")


if __name__ == "__main__":
    main()