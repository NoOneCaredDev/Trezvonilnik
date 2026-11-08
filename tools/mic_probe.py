from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd


def settings_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
        return base / "Trezvonilnik" / "settings.json"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "trezvonilnik" / "settings.json"


def run_probe(device: int | None, rate: int, seconds: float = 3.0) -> tuple[bool, str]:
    chunks = 0
    peak = 0
    squares = 0.0
    count = 0
    statuses: list[str] = []
    errors: list[str] = []

    def callback(indata, frames, time_info, status):
        nonlocal chunks, peak, squares, count
        chunks += 1
        if status:
            statuses.append(str(status))
        x = np.asarray(indata, dtype=np.float32)
        if x.size:
            peak = max(peak, int(np.max(np.abs(x)) * 32768))
            squares += float(np.sum(x * x))
            count += int(x.size)

    try:
        with sd.InputStream(
            device=device, samplerate=rate, channels=1,
            dtype="float32", blocksize=0, callback=callback,
        ):
            time.sleep(seconds)
    except Exception as exc:
        return False, f"OPEN/CAPTURE ERROR: {type(exc).__name__}: {exc}"

    rms = (squares / count) ** 0.5 if count else 0.0
    dbfs = 20 * np.log10(max(rms, 1e-9))
    return True, (
        f"callbacks={chunks}, samples={count}, RMS={dbfs:.1f} dBFS, "
        f"peak={peak}, statuses={'; '.join(statuses) or 'none'}"
    )


def main() -> int:
    lines: list[str] = []

    def out(message: str = ""):
        print(message, flush=True)
        lines.append(message)

    out("=== TREZVONILNIK MICROPHONE PROBE ===")
    out(f"Python: {sys.version.split()[0]}")
    out(f"sounddevice: {sd.__version__}")
    out(f"PortAudio: {sd.get_portaudio_version()}")
    out(f"Default devices (input, output): {sd.default.device}")

    selected = None
    p = settings_path()
    out(f"Settings file: {p}")
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
        selected = cfg.get("mic_index")
        out(f"Configured mic_index: {selected!r}")
    except FileNotFoundError:
        out("Settings file not found; testing system default input.")
    except Exception as exc:
        out(f"Could not read settings: {exc}")

    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    out("\n--- Input devices ---")
    inputs = []
    for i, dev in enumerate(devices):
        if int(dev.get("max_input_channels", 0)) > 0:
            host = hostapis[int(dev["hostapi"])]["name"]
            default_mark = " [DEFAULT]" if i == sd.default.device[0] else ""
            selected_mark = " [APP SELECTED]" if i == selected else ""
            out(
                f"[{i}] {dev['name']} | host={host} | "
                f"channels={dev['max_input_channels']} | "
                f"default_rate={dev['default_samplerate']}"
                f"{default_mark}{selected_mark}"
            )
            inputs.append((i, dev))

    candidates: list[int | None] = []
    if selected is not None:
        candidates.append(int(selected))
    default_input = sd.default.device[0]
    if default_input is not None and int(default_input) >= 0:
        if int(default_input) not in candidates:
            candidates.append(int(default_input))
    if not candidates:
        candidates.append(None)

    out("\n--- Capture tests (close Trezvonilnik and other apps using the mic) ---")
    for device_id in candidates:
        try:
            info = sd.query_devices(device_id, "input")
            native_rate = int(info["default_samplerate"])
            name = info["name"]
        except Exception:
            native_rate, name = 48000, "System default input"
        out(f"\nDevice {device_id!r}: {name}")
        rates = [48000]
        if native_rate not in rates:
            rates.append(native_rate)
        for rate in rates:
            ok, detail = run_probe(device_id, rate)
            out(f"  {rate} Hz: {'OK' if ok else 'FAILED'} — {detail}")

    out("\nProbe finished. Send the complete output or the generated report.")
    report = Path.cwd() / "mic_probe_report.txt"
    report.write_text("\n".join(lines), encoding="utf-8")
    out(f"Report saved: {report.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
