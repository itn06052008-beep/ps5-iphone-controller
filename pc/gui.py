"""
PS5 Pad – Desktop GUI for Windows

Provides a one-click desktop window with:
- Automatic iPhone Wi-Fi IP discovery (port 7777) or USB cable forwarding
- Live mode switching: LoL Keyboard (WASD), LoL Tốc Chiến style, or standard PS5/DS4 gamepad
- Saved preferences in config.json
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import companion  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

DEFAULT_CONFIG = {
    "transport": "wifi",
    "mode": "lol_wasd",
    "last_ip": "192.168.1.7",
    "auto_connect": True,
}

MODE_OPTIONS = [
    ("lol_wasd", "⚔️ Liên Minh Huyền Thoại — Keyboard (WASD)"),
    ("lol", "🎯 Liên Minh Huyền Thoại — Kiểu Tốc Chiến (Chuột + QWER)"),
    ("gamepad", "🎮 Tay cầm PS5 chuẩn (ViGEmBus – Steam / Game PC)"),
]

MODE_CHEATSHEET = {
    "lol_wasd": (
        "Cần trái: Di chuyển W / A / S / D (8 hướng)   |   Cần phải: Di chuyển con trỏ chuột (240 Hz)\n"
        "□: Chuột phải (Chiêu 1)   |   △: Left Shift (Chiêu 2)   |   ○: E (Chiêu 3)   |   R2: R (Chiêu cuối)\n"
        "✕ / R1: Chuột trái (Đánh thường / Xác nhận)   |   L1: Q (Bổ trợ 1)   |   L2: F (Bổ trợ 2)   |   R3: C (Hủy)\n"
        "L3 (giữ): Ctrl (cộng chiêu)   |   D-pad ↑←→↓: 4 / 1 / 2 / 3   |   Touchpad: Y   |   PS: B   |   Options: P   |   Create: Tab\n"
        "Mẹo LMHT: Nhấn Esc → Phím tắt (Hotkeys) → chuyển sang Keyboard (WASD) và thử ở Phòng Tập trước."
    ),
    "lol": (
        "Cần trái: Di chuyển tướng kiểu Tốc Chiến (tự rê chuột quanh tướng + click phải)   |   Cần phải: Rê chuột\n"
        "□ / △ / ○ / R2: Q / W / E / R   |   ✕: A (Đánh thường)   |   L1 / L2: D / F (Phép bổ trợ)\n"
        "R1 / R3: Chuột trái / phải   |   L3 (giữ): Ctrl (cộng chiêu)\n"
        "D-pad ↑←→↓: 4 / 1 / 2 / 3   |   Touchpad: Y (Khóa cam)   |   PS: B (Biến về)   |   Options: P   |   Create: Tab"
    ),
    "gamepad": (
        "Giả lập tay cầm PlayStation chuẩn (DualShock 4 qua driver ViGEmBus).\n"
        "Dùng cho Steam (bật PlayStation Controller Support), FIFA/FC, Elden Ring, GTA V và game hỗ trợ tay cầm.\n"
        "Đủ 2 cần analog, L1/L2/R1/R2, L3/R3, D-pad, △○✕□, Touchpad, PS, Create, Options + rung trên iPhone."
    ),
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update(data)
    except Exception:
        pass
    if cfg.get("transport") not in ("wifi", "usb"):
        cfg["transport"] = "wifi"
    if cfg.get("mode") not in ("lol_wasd", "lol", "gamepad"):
        cfg["mode"] = "lol_wasd"
    if not isinstance(cfg.get("last_ip"), str) or not cfg["last_ip"].strip():
        cfg["last_ip"] = "192.168.1.7"
    cfg["auto_connect"] = bool(cfg.get("auto_connect", True))
    return cfg


def save_config(cfg: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _local_ipv4_subnets() -> list[tuple[str, ipaddress.IPv4Network]]:
    """Return local non-loopback IPv4 addresses and their /24 networks."""
    found: list[tuple[str, ipaddress.IPv4Network]] = []
    seen: set[str] = set()

    def add_ip(ip_str: str) -> None:
        if not ip_str or ip_str.startswith("127.") or ip_str.startswith("169.254."):
            return
        if ip_str in seen:
            return
        seen.add(ip_str)
        try:
            net = ipaddress.IPv4Network(f"{ip_str}/24", strict=False)
            found.append((ip_str, net))
        except ValueError:
            pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            add_ip(s.getsockname()[0])
    except OSError:
        pass

    try:
        _host, _aliases, ips = socket.gethostbyname_ex(socket.gethostname())
        for ip in ips:
            add_ip(ip)
    except OSError:
        pass

    return found


async def _probe_port(host: str, port: int, timeout: float, sem: asyncio.Semaphore) -> str | None:
    async with sem:
        writer = None
        try:
            _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
            return host
        except Exception:
            return None
        finally:
            if writer is not None:
                try:
                    writer.close()
                    await asyncio.wait_for(writer.wait_closed(), timeout=0.2)
                except Exception:
                    pass


async def discover_iphone_ip(preferred_ip: str = "", port: int = companion.PORT) -> str | None:
    """Check preferred_ip first, then scan local /24 subnets for an iPhone listening on port."""
    preferred = preferred_ip.strip()
    sem = asyncio.Semaphore(64)
    if preferred:
        if await _probe_port(preferred, port, 0.6, sem):
            return preferred

    candidates: list[str] = []
    local_ips = {ip for ip, _net in _local_ipv4_subnets()}
    for _ip, net in _local_ipv4_subnets():
        for host in net.hosts():
            h = str(host)
            if h not in local_ips and h != preferred:
                candidates.append(h)

    if not candidates:
        return None

    tasks = [asyncio.create_task(_probe_port(h, port, 0.35, sem)) for h in candidates]
    try:
        for done in asyncio.as_completed(tasks):
            result = await done
            if result:
                return result
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return None


def _start_silent_usb_forward() -> subprocess.Popen | None:
    if shutil.which("iproxy"):
        cmd = ["iproxy", str(companion.PORT), str(companion.PORT)]
    else:
        py = sys.executable
        cmd = [py, "-m", "pymobiledevice3", "usbmux", "forward", str(companion.PORT), str(companion.PORT)]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        return subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
    except Exception:
        return None


class ControllerBackend:
    """Runs the asyncio transport loop and mapper in a background daemon thread."""

    def __init__(self, initial_mode: str, on_status, on_ip_found, on_pps) -> None:
        self._on_status = on_status
        self._on_ip_found = on_ip_found
        self._on_pps = on_pps
        self._mode = initial_mode
        self._gamepad_cache: companion.VirtualPad | None = None
        self._mapper = None
        self._tick_task: asyncio.Task | None = None
        self._worker_task: asyncio.Task | None = None
        self._usb_proc: subprocess.Popen | None = None
        self._rumble_sink = None

        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, name="ps5pad-asyncio", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    def _make_mapper(self, mode: str):
        if mode == "lol_wasd":
            return companion.LolWasdMapper()
        if mode == "lol":
            return companion.LolMapper()
        if self._gamepad_cache is None:
            self._gamepad_cache = companion.VirtualPad()
        return self._gamepad_cache

    def _switch_mapper_in_loop(self, mode: str) -> None:
        self._mode = mode
        if self._tick_task is not None:
            self._tick_task.cancel()
            self._tick_task = None
        if self._mapper is not None:
            try:
                self._mapper.neutral()
            except Exception:
                pass
            self._mapper.rumble_sink = None

        mapper = self._make_mapper(mode)
        mapper.loop = self._loop
        mapper.rumble_sink = self._rumble_sink
        self._mapper = mapper
        if isinstance(mapper, companion._Win32InputMapper):
            self._tick_task = self._loop.create_task(mapper.tick_loop())

    def set_mode(self, mode: str) -> None:
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._switch_mapper_in_loop, mode)

    def start(self, transport: str, preferred_ip: str) -> None:
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._start_in_loop, transport, preferred_ip)

    def _start_in_loop(self, transport: str, preferred_ip: str) -> None:
        self._stop_in_loop(quiet=True)
        if self._mapper is None:
            self._switch_mapper_in_loop(self._mode)
        self._worker_task = self._loop.create_task(self._connection_loop(transport, preferred_ip))

    def stop(self) -> None:
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._stop_in_loop, False)

    def _stop_in_loop(self, quiet: bool = False) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            self._worker_task = None
        self._terminate_usb()
        self._rumble_sink = None
        if self._mapper is not None:
            self._mapper.rumble_sink = None
            try:
                self._mapper.neutral()
            except Exception:
                pass
        self._on_pps(0)
        if not quiet:
            self._on_status("Đã dừng", "stopped")

    def _terminate_usb(self) -> None:
        if self._usb_proc is not None:
            try:
                self._usb_proc.terminate()
            except Exception:
                pass
            self._usb_proc = None

    def shutdown(self) -> None:
        if not self._loop.is_running():
            return
        done = threading.Event()

        def _cleanup():
            self._stop_in_loop(quiet=True)
            if self._tick_task is not None:
                self._tick_task.cancel()
                self._tick_task = None
            self._loop.stop()
            done.set()

        self._loop.call_soon_threadsafe(_cleanup)
        done.wait(timeout=2)

    async def _connection_loop(self, transport: str, preferred_ip: str) -> None:
        current_ip = preferred_ip.strip()
        has_usbmux = False
        if transport == "usb":
            try:
                import pymobiledevice3.usbmux  # noqa: F401
                has_usbmux = True
            except ImportError:
                has_usbmux = False
        try:
            if transport == "usb" and not has_usbmux:
                self._on_status("Đang mở kết nối cáp USB…", "searching")
                self._usb_proc = _start_silent_usb_forward()
                if self._usb_proc is None:
                    self._on_status("Không tìm thấy công cụ chuyển tiếp USB (pymobiledevice3/iproxy)", "error")
                    return
                await asyncio.sleep(1.2)

            while True:
                reader = writer = None
                host = "127.0.0.1"
                if transport == "usb":
                    self._on_status("Đang chờ iPhone qua cáp USB…", "searching")
                    if has_usbmux:
                        stream = await companion.open_direct_usb_stream(companion.PORT)
                        if stream is None:
                            await asyncio.sleep(0.8)
                            continue
                        reader, writer = stream
                else:
                    self._on_status("Đang tìm iPhone trong mạng Wi-Fi…", "searching")
                    found = await discover_iphone_ip(current_ip, companion.PORT)
                    if not found:
                        self._on_status("Chưa thấy iPhone (mở app, chọn 'Cáp USB / Wi-Fi')", "searching")
                        await asyncio.sleep(1.2)
                        continue
                    current_ip = found
                    host = found
                    self._on_ip_found(found)

                if writer is None:
                    try:
                        reader, writer = await asyncio.wait_for(
                            asyncio.open_connection(host, companion.PORT), timeout=3.0
                        )
                    except Exception:
                        await asyncio.sleep(1.0)
                        continue

                sock = writer.get_extra_info("socket")
                if sock is not None:
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

                async def sink(data: bytes, w=writer) -> None:
                    w.write(data)
                    await w.drain()

                self._rumble_sink = sink
                if self._mapper is not None:
                    self._mapper.rumble_sink = sink

                label = "cáp USB trực tiếp" if (transport == "usb" and has_usbmux) else (
                    "cáp USB" if transport == "usb" else f"Wi-Fi ({host})"
                )
                self._on_status(f"Đã kết nối iPhone qua {label}", "connected")

                pkt_count = 0
                t_rate = time.monotonic()
                buf = bytearray()
                try:
                    while True:
                        chunk = await reader.read(4096)
                        if not chunk:
                            raise ConnectionResetError("EOF")
                        buf.extend(chunk)
                        if self._mapper is not None:
                            pkt_count += companion.drain_packets(buf, self._mapper)
                        now = time.monotonic()
                        if now - t_rate >= 1.0:
                            self._on_pps(round(pkt_count / (now - t_rate)))
                            pkt_count = 0
                            t_rate = now
                except (asyncio.IncompleteReadError, ConnectionError, OSError):
                    self._on_status("Mất kết nối, đang tìm lại iPhone…", "searching")
                finally:
                    self._rumble_sink = None
                    if self._mapper is not None:
                        self._mapper.rumble_sink = None
                        self._mapper.neutral()
                    self._on_pps(0)
                    try:
                        writer.close()
                    except Exception:
                        pass
                await asyncio.sleep(0.8)
        except asyncio.CancelledError:
            raise
        finally:
            self._terminate_usb()


class PS5PadApp:
    """Tkinter desktop window for controlling connection and active mapper mode."""

    STATUS_COLORS = {
        "connected": "#16a34a",
        "searching": "#d97706",
        "stopped": "#6b7280",
        "error": "#dc2626",
    }

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.cfg = load_config()
        self.running = False

        self.root.title("PS5 Pad – Bộ điều khiển trên PC")
        self.root.resizable(False, False)
        self.root.configure(padx=16, pady=14)

        self.transport_var = tk.StringVar(value=self.cfg["transport"])
        self.ip_var = tk.StringVar(value=self.cfg["last_ip"])
        self.mode_var = tk.StringVar(value=self.cfg["mode"])
        self.auto_var = tk.BooleanVar(value=self.cfg["auto_connect"])
        self.status_var = tk.StringVar(value="Đang khởi tạo…")
        self.pps_var = tk.StringVar(value="0 gói/giây")

        self._build_ui()
        self._update_cheatsheet()
        self._update_ip_state()

        self.backend = ControllerBackend(
            initial_mode=self.mode_var.get(),
            on_status=self._handle_status,
            on_ip_found=self._handle_ip_found,
            on_pps=self._handle_pps,
        )

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        if self.auto_var.get():
            self._connect()
        else:
            self._set_status_ui("Đã dừng (bấm Kết nối để bắt đầu)", "stopped")

    def _build_ui(self) -> None:
        # Status header
        top = ttk.Frame(self.root)
        top.pack(fill="x", pady=(0, 10))

        self.dot = tk.Canvas(top, width=14, height=14, highlightthickness=0)
        self.dot_id = self.dot.create_oval(2, 2, 12, 12, fill="#6b7280", outline="")
        self.dot.pack(side="left", padx=(0, 8))

        ttk.Label(top, textvariable=self.status_var, font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Label(top, textvariable=self.pps_var, foreground="#4b5563").pack(side="right")

        # Connection settings
        conn_box = ttk.LabelFrame(self.root, text="Kết nối iPhone", padding=(12, 8))
        conn_box.pack(fill="x", pady=(0, 10))

        row1 = ttk.Frame(conn_box)
        row1.pack(fill="x", pady=(0, 6))
        ttk.Radiobutton(
            row1, text="Wi-Fi (Tự động tìm iPhone)", value="wifi",
            variable=self.transport_var, command=self._on_transport_change,
        ).pack(side="left", padx=(0, 16))
        ttk.Radiobutton(
            row1, text="Cáp USB", value="usb",
            variable=self.transport_var, command=self._on_transport_change,
        ).pack(side="left")

        row2 = ttk.Frame(conn_box)
        row2.pack(fill="x", pady=(0, 6))
        ttk.Label(row2, text="IP iPhone:").pack(side="left", padx=(0, 8))
        self.ip_entry = ttk.Entry(row2, textvariable=self.ip_var, width=20)
        self.ip_entry.pack(side="left", padx=(0, 10))
        self.toggle_btn = ttk.Button(row2, text="Kết nối", width=15, command=self._toggle_connect)
        self.toggle_btn.pack(side="right")

        ttk.Checkbutton(
            conn_box, text="Tự động kết nối khi mở app",
            variable=self.auto_var, command=self._save_prefs,
        ).pack(anchor="w")

        # Mode selection
        mode_box = ttk.LabelFrame(self.root, text="Chế độ hoạt động (đổi trực tiếp khi đang chơi)", padding=(12, 8))
        mode_box.pack(fill="x", pady=(0, 10))

        for val, label in MODE_OPTIONS:
            ttk.Radiobutton(
                mode_box, text=label, value=val,
                variable=self.mode_var, command=self._on_mode_change,
            ).pack(anchor="w", pady=2)

        # Cheat sheet
        help_box = ttk.LabelFrame(self.root, text="Hướng dẫn nút bấm nhanh", padding=(12, 8))
        help_box.pack(fill="x")
        self.cheat_label = ttk.Label(help_box, text="", justify="left", font=("Segoe UI", 9))
        self.cheat_label.pack(anchor="w")

    def _save_prefs(self) -> None:
        self.cfg["transport"] = self.transport_var.get()
        self.cfg["mode"] = self.mode_var.get()
        ip = self.ip_var.get().strip()
        if ip:
            self.cfg["last_ip"] = ip
        self.cfg["auto_connect"] = bool(self.auto_var.get())
        save_config(self.cfg)

    def _update_ip_state(self) -> None:
        self.ip_entry.configure(state="normal" if self.transport_var.get() == "wifi" else "disabled")

    def _update_cheatsheet(self) -> None:
        self.cheat_label.configure(text=MODE_CHEATSHEET[self.mode_var.get()])

    def _on_mode_change(self) -> None:
        self._update_cheatsheet()
        self._save_prefs()
        self.backend.set_mode(self.mode_var.get())

    def _on_transport_change(self) -> None:
        self._update_ip_state()
        self._save_prefs()
        if self.running:
            self._connect()

    def _toggle_connect(self) -> None:
        if self.running:
            self._disconnect()
        else:
            self._connect()

    def _connect(self) -> None:
        self._save_prefs()
        self.running = True
        self.toggle_btn.configure(text="Ngắt kết nối")
        self.backend.start(self.transport_var.get(), self.ip_var.get().strip())

    def _disconnect(self) -> None:
        self.running = False
        self.toggle_btn.configure(text="Kết nối")
        self.backend.stop()

    def _set_status_ui(self, text: str, kind: str) -> None:
        self.status_var.set(text)
        self.dot.itemconfigure(self.dot_id, fill=self.STATUS_COLORS.get(kind, "#6b7280"))

    def _handle_status(self, text: str, kind: str) -> None:
        self.root.after(0, self._set_status_ui, text, kind)

    def _handle_ip_found(self, ip: str) -> None:
        def _apply() -> None:
            if self.ip_var.get().strip() != ip:
                self.ip_var.set(ip)
                self._save_prefs()
        self.root.after(0, _apply)

    def _handle_pps(self, pps: int) -> None:
        self.root.after(0, self.pps_var.set, f"{pps} gói/giây")

    def _on_close(self) -> None:
        self._save_prefs()
        self.backend.shutdown()
        self.root.destroy()


def main() -> None:
    companion.enable_low_latency_mode()
    root = tk.Tk()
    PS5PadApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
