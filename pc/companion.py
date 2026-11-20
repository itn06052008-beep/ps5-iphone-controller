"""
PS5 Pad – PC companion (Windows)

Receives input from the iPhone app and exposes it to Windows as a virtual
PlayStation controller (DualShock 4 via ViGEmBus – recognised by Steam,
DS4Windows-aware games and most PlayStation-layout games).

Usage:
  python companion.py ble                     # Bluetooth LE
  python companion.py usb                     # USB cable (usbmuxd port-forward)
  python companion.py wifi 192.168.1.23       # Wi-Fi, iPhone IP shown in the app
  python companion.py wifi 192.168.1.23 --lol       # League of Legends (Tốc Chiến style)
  python companion.py wifi 192.168.1.23 --lol-wasd  # League of Legends (official WASD mode)
"""
from __future__ import annotations

import argparse
import asyncio
import atexit
import ctypes
from ctypes import wintypes
import math
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import time

try:
    import vgamepad as vg
except Exception as e:  # pragma: no cover
    sys.exit(f"Không import được vgamepad ({e}). Chạy: pip install -r requirements.txt")

PORT = 7777
INPUT_MAGIC = 0xD5
RUMBLE_MAGIC = 0xD6
PACKET = struct.Struct("<BBIBBBBBB")  # magic, seq, buttons, lx, ly, rx, ry, l2, r2  (12 bytes)

SERVICE_UUID = "8e5a0001-5d35-4c52-9e3f-50535050ad01"
INPUT_UUID = "8e5a0002-5d35-4c52-9e3f-50535050ad01"
RUMBLE_UUID = "8e5a0003-5d35-4c52-9e3f-50535050ad01"

B = vg.DS4_BUTTONS
BUTTON_MAP = [
    (0, B.DS4_BUTTON_CROSS),
    (1, B.DS4_BUTTON_CIRCLE),
    (2, B.DS4_BUTTON_SQUARE),
    (3, B.DS4_BUTTON_TRIANGLE),
    (4, B.DS4_BUTTON_SHOULDER_LEFT),
    (5, B.DS4_BUTTON_SHOULDER_RIGHT),
    (6, B.DS4_BUTTON_THUMB_LEFT),
    (7, B.DS4_BUTTON_THUMB_RIGHT),
    (8, B.DS4_BUTTON_SHARE),
    (9, B.DS4_BUTTON_OPTIONS),
    (16, B.DS4_BUTTON_TRIGGER_LEFT),
    (17, B.DS4_BUTTON_TRIGGER_RIGHT),
]
SPECIAL_MAP = [
    (10, vg.DS4_SPECIAL_BUTTONS.DS4_SPECIAL_BUTTON_PS),
    (11, vg.DS4_SPECIAL_BUTTONS.DS4_SPECIAL_BUTTON_TOUCHPAD),
]
D = vg.DS4_DPAD_DIRECTIONS
DPAD_MAP = {  # (up, down, left, right) -> direction
    (1, 0, 0, 0): D.DS4_BUTTON_DPAD_NORTH,
    (0, 1, 0, 0): D.DS4_BUTTON_DPAD_SOUTH,
    (0, 0, 1, 0): D.DS4_BUTTON_DPAD_WEST,
    (0, 0, 0, 1): D.DS4_BUTTON_DPAD_EAST,
    (1, 0, 1, 0): D.DS4_BUTTON_DPAD_NORTHWEST,
    (1, 0, 0, 1): D.DS4_BUTTON_DPAD_NORTHEAST,
    (0, 1, 1, 0): D.DS4_BUTTON_DPAD_SOUTHWEST,
    (0, 1, 0, 1): D.DS4_BUTTON_DPAD_SOUTHEAST,
}


class VirtualPad:
    """Wraps a ViGEm DS4 gamepad and forwards rumble back to the phone."""

    def __init__(self) -> None:
        self.pad = vg.VDS4Gamepad()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.rumble_sink = None  # async callable(bytes)
        self._last_rumble = (0, 0)
        self._packets = 0
        self._t0 = time.monotonic()
        self.pad.register_notification(callback_function=self._on_notification)
        print("✔ Đã tạo tay cầm ảo (DualShock 4 / PlayStation) trên Windows")

    # Called from a ViGEm thread
    def _on_notification(self, client, target, large_motor, small_motor, led, user_data):
        rumble = (int(large_motor), int(small_motor))
        if rumble == self._last_rumble or not self.loop or not self.rumble_sink:
            return
        self._last_rumble = rumble
        data = bytes([RUMBLE_MAGIC, *rumble])
        asyncio.run_coroutine_threadsafe(self._safe_sink(data), self.loop)

    async def _safe_sink(self, data: bytes) -> None:
        try:
            await self.rumble_sink(data)
        except Exception:
            pass

    def apply(self, pkt: bytes) -> None:
        if len(pkt) < PACKET.size or pkt[0] != INPUT_MAGIC:
            return
        _, _seq, btn, lx, ly, rx, ry, l2, r2 = PACKET.unpack_from(pkt)
        p = self.pad
        p.reset()
        for bit, b in BUTTON_MAP:
            if btn & (1 << bit):
                p.press_button(button=b)
        for bit, s in SPECIAL_MAP:
            if btn & (1 << bit):
                p.press_special_button(special_button=s)
        key = tuple(1 if btn & (1 << i) else 0 for i in (12, 13, 14, 15))
        p.directional_pad(direction=DPAD_MAP.get(key, D.DS4_BUTTON_DPAD_NONE))
        p.left_joystick(x_value=lx, y_value=ly)
        p.right_joystick(x_value=rx, y_value=ry)
        p.left_trigger(value=l2)
        p.right_trigger(value=r2)
        p.update()

        self._packets += 1
        now = time.monotonic()
        if now - self._t0 >= 5:
            print(f"  … {self._packets / (now - self._t0):.0f} gói/giây")
            self._packets, self._t0 = 0, now

    def neutral(self) -> None:
        self.pad.reset()
        self.pad.update()


# ---------------------------------------------------------------- League of Legends mapper

class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUT_UNION)]


LOL_KEY_MAP = [
    (2, 0x51),   # □  -> Q
    (3, 0x57),   # △  -> W
    (1, 0x45),   # ○  -> E
    (17, 0x52),  # R2 -> R
    (0, 0x41),   # ✕  -> A (Attack Move Click)
    (4, 0x44),   # L1 -> D (Summoner Spell 1)
    (16, 0x46),  # L2 -> F (Summoner Spell 2)
    (6, 0x11),   # L3 -> Ctrl (hold L3 + Q/W/E/R to level up)
    (12, 0x34),  # ↑  -> 4 (Ward / Trinket)
    (14, 0x31),  # ←  -> 1 (Item 1)
    (15, 0x32),  # →  -> 2 (Item 2)
    (13, 0x33),  # ↓  -> 3 (Item 3)
    (10, 0x42),  # PS -> B (Recall)
    (11, 0x59),  # Touchpad -> Y (Camera Lock)
    (9, 0x50),   # Options -> P (Shop)
    (8, 0x09),   # Create -> Tab (Scoreboard)
]

LOL_WASD_KEY_MAP = [
    (3, 0xA0),   # △  -> Left Shift (Ability 2 in LoL WASD default)
    (1, 0x45),   # ○  -> E (Ability 3)
    (17, 0x52),  # R2 -> R (Ultimate)
    (4, 0x51),   # L1 -> Q (Summoner Spell 1 in LoL WASD default)
    (16, 0x46),  # L2 -> F (Summoner Spell 2)
    (7, 0x43),   # R3 -> C (Cancel Cast)
    (6, 0xA2),   # L3 -> Left Ctrl (hold to level up abilities)
    (12, 0x34),  # ↑  -> 4 (Ward / Trinket)
    (14, 0x31),  # ←  -> 1 (Item 1)
    (15, 0x32),  # →  -> 2 (Item 2)
    (13, 0x33),  # ↓  -> 3 (Item 3)
    (10, 0x42),  # PS -> B (Recall)
    (11, 0x59),  # Touchpad -> Y (Camera Lock)
    (9, 0x50),   # Options -> P (Shop)
    (8, 0x09),   # Create -> Tab (Scoreboard)
]

WASD_STICK_KEYS = (
    (0x57, lambda lx, ly: ly < -0.14),  # W (Up)
    (0x53, lambda lx, ly: ly > 0.14),   # S (Down)
    (0x41, lambda lx, ly: lx < -0.14),  # A (Left)
    (0x44, lambda lx, ly: lx > 0.14),   # D (Right)
)

_TIMER_PERIOD_SET = False


def enable_low_latency_mode() -> None:
    """Request 1 ms Windows timer resolution and above-normal process priority."""
    global _TIMER_PERIOD_SET
    if not _TIMER_PERIOD_SET:
        try:
            if ctypes.windll.winmm.timeBeginPeriod(1) == 0:
                _TIMER_PERIOD_SET = True
                atexit.register(lambda: ctypes.windll.winmm.timeEndPeriod(1))
        except Exception:
            pass
    try:
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.kernel32.SetPriorityClass(handle, 0x00008000)  # ABOVE_NORMAL_PRIORITY_CLASS
    except Exception:
        pass


class _Win32InputMapper:
    """Shared Windows SendInput / cursor plumbing for LoL controller mappers."""

    INPUT_MOUSE = 0
    INPUT_KEYBOARD = 1
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_SCANCODE = 0x0008
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010

    def __init__(self, banner: str) -> None:
        self.user32 = ctypes.windll.user32
        try:
            self.user32.SetProcessDPIAware()
        except Exception:
            pass
        self.screen_w = max(1, int(self.user32.GetSystemMetrics(0)))
        self.screen_h = max(1, int(self.user32.GetSystemMetrics(1)))
        self.loop: asyncio.AbstractEventLoop | None = None
        self.rumble_sink = None
        self._prev_btn = 0
        self._held_vks: set[int] = set()
        self._lmb_down = False
        self._rmb_down = False
        self._lx = 0.0
        self._ly = 0.0
        self._rx = 0.0
        self._ry = 0.0
        self._packets = 0
        self._t0 = time.monotonic()
        print(f"✔ {banner} [{self.screen_w}x{self.screen_h}]")

    def _build_key_input(self, vk: int, down: bool) -> _INPUT:
        scan_ex = self.user32.MapVirtualKeyW(vk, 4)
        flags = self.KEYEVENTF_SCANCODE
        if (scan_ex & 0xFF00) == 0xE000:
            flags |= self.KEYEVENTF_EXTENDEDKEY
        if not down:
            flags |= self.KEYEVENTF_KEYUP
        scan = scan_ex & 0xFF
        if scan == 0:
            scan = self.user32.MapVirtualKeyW(vk, 0)
        inp = _INPUT(type=self.INPUT_KEYBOARD)
        inp.union.ki = _KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
        return inp

    def _build_mouse_input(self, flags: int, dx: int = 0, dy: int = 0) -> _INPUT:
        inp = _INPUT(type=self.INPUT_MOUSE)
        inp.union.mi = _MOUSEINPUT(dx=dx, dy=dy, mouseData=0, dwFlags=flags, time=0, dwExtraInfo=0)
        return inp

    def _flush_inputs(self, events: list[_INPUT]) -> None:
        n = len(events)
        if n == 0:
            return
        if n == 1:
            self.user32.SendInput(1, ctypes.byref(events[0]), ctypes.sizeof(_INPUT))
            return
        arr = (_INPUT * n)(*events)
        self.user32.SendInput(n, arr, ctypes.sizeof(_INPUT))

    def _send_key(self, vk: int, down: bool) -> None:
        inp = self._build_key_input(vk, down)
        self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

    def _send_mouse(self, flags: int, dx: int = 0, dy: int = 0) -> None:
        inp = self._build_mouse_input(flags, dx=dx, dy=dy)
        self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

    def _set_cursor(self, x: int, y: int) -> None:
        cx = max(0, min(self.screen_w - 1, x))
        cy = max(0, min(self.screen_h - 1, y))
        self.user32.SetCursorPos(cx, cy)

    def _set_key_state(self, vk: int, down: bool, batch: list[_INPUT] | None = None) -> None:
        was_down = vk in self._held_vks
        if down != was_down:
            inp = self._build_key_input(vk, down)
            if batch is not None:
                batch.append(inp)
            else:
                self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
            if down:
                self._held_vks.add(vk)
            else:
                self._held_vks.discard(vk)

    def _sync_key_map(self, btn: int, key_map: list[tuple[int, int]], batch: list[_INPUT] | None = None) -> None:
        for bit, vk in key_map:
            self._set_key_state(vk, bool(btn & (1 << bit)), batch)

    def _set_lmb(self, down: bool, batch: list[_INPUT] | None = None) -> None:
        if down != self._lmb_down:
            inp = self._build_mouse_input(self.MOUSEEVENTF_LEFTDOWN if down else self.MOUSEEVENTF_LEFTUP)
            if batch is not None:
                batch.append(inp)
            else:
                self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
            self._lmb_down = down

    def _set_rmb(self, down: bool, batch: list[_INPUT] | None = None) -> None:
        if down != self._rmb_down:
            inp = self._build_mouse_input(self.MOUSEEVENTF_RIGHTDOWN if down else self.MOUSEEVENTF_RIGHTUP)
            if batch is not None:
                batch.append(inp)
            else:
                self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
            self._rmb_down = down

    def _unpack_packet(self, pkt: bytes) -> int | None:
        if len(pkt) < PACKET.size or pkt[0] != INPUT_MAGIC:
            return None
        _, _seq, btn, lx, ly, rx, ry, _l2, _r2 = PACKET.unpack_from(pkt)
        self._lx = (lx - 127.5) / 127.5
        self._ly = (ly - 127.5) / 127.5
        self._rx = (rx - 127.5) / 127.5
        self._ry = (ry - 127.5) / 127.5
        self._packets += 1
        now = time.monotonic()
        if now - self._t0 >= 5:
            print(f"  … {self._packets / (now - self._t0):.0f} gói/giây")
            self._packets, self._t0 = 0, now
        return btn

    def neutral(self) -> None:
        batch: list[_INPUT] = []
        for vk in list(self._held_vks):
            batch.append(self._build_key_input(vk, False))
        self._held_vks.clear()
        self._set_lmb(False, batch)
        self._set_rmb(False, batch)
        self._flush_inputs(batch)
        self._prev_btn = 0
        self._lx = self._ly = self._rx = self._ry = 0.0


class LolMapper(_Win32InputMapper):
    """Translates iPhone PS5 controller input into classic LoL (Tốc Chiến style)."""

    def __init__(self) -> None:
        super().__init__("Đã bật chế độ Liên Minh Huyền Thoại (LoL)")
        self._last_move_click = 0.0
        self._last_dir: tuple[float, float] | None = None
        self._fx = 0.0
        self._fy = 0.0

    def apply(self, pkt: bytes) -> None:
        btn = self._unpack_packet(pkt)
        if btn is None:
            return
        batch: list[_INPUT] = []
        self._sync_key_map(btn, LOL_KEY_MAP, batch)
        self._set_lmb(bool(btn & (1 << 5)), batch)
        self._set_rmb(bool(btn & (1 << 7)), batch)
        self._flush_inputs(batch)
        self._prev_btn = btn

    def neutral(self) -> None:
        super().neutral()
        self._last_dir = None
        self._fx = 0.0
        self._fy = 0.0

    async def tick_loop(self) -> None:
        pt = wintypes.POINT()
        center_x = self.screen_w * 0.5
        center_y = self.screen_h * 0.48
        radius = min(self.screen_w, self.screen_h) * 0.22
        last = time.perf_counter()
        while True:
            await asyncio.sleep(1.0 / 240.0)
            now_perf = time.perf_counter()
            dt = min(0.05, max(0.0, now_perf - last))
            last = now_perf
            rmag = math.hypot(self._rx, self._ry)
            lmag = math.hypot(self._lx, self._ly)
            if rmag > 0.12:
                if self.user32.GetCursorPos(ctypes.byref(pt)):
                    scale = 22.0 * (min(1.0, rmag) ** 0.6) * (dt * 60.0)
                    self._fx += self._rx * scale
                    self._fy += self._ry * scale
                    dx = int(self._fx)
                    dy = int(self._fy)
                    if dx or dy:
                        self._fx -= dx
                        self._fy -= dy
                        self._set_cursor(pt.x + dx, pt.y + dy)
            else:
                self._fx = 0.0
                self._fy = 0.0
                if lmag > 0.18:
                    nx, ny = self._lx / lmag, self._ly / lmag
                    now_mono = time.monotonic()
                    dir_changed = self._last_dir is None or (nx * self._last_dir[0] + ny * self._last_dir[1]) < 0.94
                    if dir_changed or now_mono - self._last_move_click >= 0.065:
                        tx = int(round(center_x + nx * radius))
                        ty = int(round(center_y + ny * radius))
                        self._set_cursor(tx, ty)
                        self._flush_inputs([
                            self._build_mouse_input(self.MOUSEEVENTF_RIGHTDOWN),
                            self._build_mouse_input(self.MOUSEEVENTF_RIGHTUP),
                        ])
                        self._last_dir = (nx, ny)
                        self._last_move_click = now_mono
                else:
                    self._last_dir = None


class LolWasdMapper(_Win32InputMapper):
    """Translates iPhone PS5 controller into LoL official Keyboard (WASD) mode."""

    def __init__(self) -> None:
        super().__init__("Đã bật chế độ LMHT Keyboard (WASD)")
        self._fx = 0.0
        self._fy = 0.0

    def apply(self, pkt: bytes) -> None:
        btn = self._unpack_packet(pkt)
        if btn is None:
            return
        batch: list[_INPUT] = []
        for vk, active in WASD_STICK_KEYS:
            self._set_key_state(vk, active(self._lx, self._ly), batch)
        self._sync_key_map(btn, LOL_WASD_KEY_MAP, batch)
        self._set_rmb(bool(btn & (1 << 2)), batch)               # □ -> Right-Click (Chiêu 1)
        self._set_lmb(bool(btn & ((1 << 0) | (1 << 5))), batch)  # ✕ hoặc R1 -> Left-Click
        self._flush_inputs(batch)
        self._prev_btn = btn

    def neutral(self) -> None:
        super().neutral()
        self._fx = 0.0
        self._fy = 0.0

    async def tick_loop(self) -> None:
        last = time.perf_counter()
        while True:
            await asyncio.sleep(1.0 / 240.0)
            now = time.perf_counter()
            dt = min(0.05, max(0.0, now - last))
            last = now
            rmag = math.hypot(self._rx, self._ry)
            if rmag > 0.10:
                scale = 24.0 * (min(1.0, rmag) ** 0.7) * (dt * 60.0)
                self._fx += self._rx * scale
                self._fy += self._ry * scale
                dx = int(self._fx)
                dy = int(self._fy)
                if dx or dy:
                    self._fx -= dx
                    self._fy -= dy
                    self._send_mouse(self.MOUSEEVENTF_MOVE, dx=dx, dy=dy)
            else:
                self._fx = 0.0
                self._fy = 0.0


# ---------------------------------------------------------------- TCP (USB / Wi-Fi)

def drain_packets(buf: bytearray, mapper) -> int:
    """Drain all complete packets from buf; keep button changes and latest sticks."""
    packets: list[bytes] = []
    size = PACKET.size
    while len(buf) >= size:
        if buf[0] != INPUT_MAGIC:
            idx = buf.find(bytes((INPUT_MAGIC,)))
            if idx < 0:
                buf.clear()
                break
            del buf[:idx]
            continue
        packets.append(bytes(buf[:size]))
        del buf[:size]

    if not packets:
        return 0

    last_btn = getattr(mapper, "_last_drained_btn", None)
    for pkt in packets[:-1]:
        btn = int.from_bytes(pkt[2:6], "little")
        if btn != last_btn:
            mapper.apply(pkt)
            last_btn = btn

    latest = packets[-1]
    mapper.apply(latest)
    mapper._last_drained_btn = int.from_bytes(latest[2:6], "little")
    return len(packets)


PID_FILE = Path(__file__).resolve().parent / "instance.pid"


def _is_controller_process(pid: int) -> bool:
    try:
        import psutil
        p = psutil.Process(pid)
        if "python" not in p.name().lower():
            return False
        return any(Path(arg).name in ("gui.py", "companion.py") for arg in p.cmdline())
    except Exception:
        return False


def _stop_pid(pid: int) -> None:
    try:
        import psutil
        p = psutil.Process(pid)
        p.terminate()
        try:
            p.wait(timeout=1.5)
        except psutil.TimeoutExpired:
            p.kill()
            p.wait(timeout=1.0)
    except Exception:
        pass


def ensure_single_instance() -> None:
    """Stop any older gui.py / companion.py instance so only one client talks to the iPhone."""
    my_pid = os.getpid()
    killed: set[int] = set()

    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text(encoding="utf-8").strip())
            if old_pid != my_pid and _is_controller_process(old_pid):
                _stop_pid(old_pid)
                killed.add(old_pid)
        except Exception:
            pass

    try:
        import psutil
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            pid = proc.info.get("pid")
            if not pid or pid == my_pid or pid in killed:
                continue
            name = (proc.info.get("name") or "").lower()
            if "python" not in name:
                continue
            cmdline = proc.info.get("cmdline") or []
            if any(Path(arg).name in ("gui.py", "companion.py") for arg in cmdline):
                _stop_pid(pid)
                killed.add(pid)
    except Exception:
        pass

    try:
        PID_FILE.write_text(str(my_pid), encoding="utf-8")
    except Exception:
        pass

    def _remove_pid() -> None:
        try:
            if PID_FILE.exists() and PID_FILE.read_text(encoding="utf-8").strip() == str(my_pid):
                PID_FILE.unlink()
        except Exception:
            pass

    atexit.register(_remove_pid)


def configure_tcp_socket(sock: socket.socket | None) -> None:
    """Enable TCP_NODELAY and aggressive Windows keep-alive probes for dead Wi-Fi sockets."""
    if sock is None:
        return
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except (OSError, AttributeError):
        pass
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except (OSError, AttributeError):
        pass
    raw = getattr(sock, "_sock", sock)
    if hasattr(raw, "ioctl") and hasattr(socket, "SIO_KEEPALIVE_VALS"):
        try:
            raw.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 1000, 500))
        except (OSError, AttributeError):
            pass


async def open_direct_usb_stream(port: int = PORT):
    """Connect directly to iPhone via usbmuxd without a proxy subprocess hop."""
    try:
        from pymobiledevice3 import usbmux
        dev = await usbmux.select_device(connection_type="USB")
        if dev is None:
            return None
        sock = await dev.connect(port)
    except Exception:
        return None
    try:
        configure_tcp_socket(sock)
        sock.setblocking(False)
        return await asyncio.open_connection(sock=sock)
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        return None


async def run_tcp(vpad: VirtualPad, host: str, direct_usb: bool = False) -> None:
    while True:
        reader = writer = None
        if direct_usb:
            stream = await open_direct_usb_stream(PORT)
            if stream is not None:
                reader, writer = stream
            else:
                print("… chưa thấy iPhone qua cáp USB (mở app, chọn 'Cáp USB / Wi-Fi')")
                await asyncio.sleep(1.0)
                continue
        else:
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(host, PORT), timeout=2.0)
            except (OSError, asyncio.TimeoutError):
                print(f"… chưa kết nối được {host}:{PORT}, thử lại (mở app, chọn 'Cáp USB / Wi-Fi')")
                await asyncio.sleep(1.0)
                continue

        configure_tcp_socket(writer.get_extra_info("socket"))

        async def sink(data: bytes) -> None:
            writer.write(data)
            await writer.drain()

        vpad.rumble_sink = sink
        label = "cáp USB trực tiếp" if direct_usb else f"{host}:{PORT}"
        print(f"✔ Đã kết nối iPhone qua TCP ({label})")
        buf = bytearray()
        try:
            while True:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=1.5)
                if not chunk:
                    raise ConnectionResetError("EOF")
                buf.extend(chunk)
                drain_packets(buf, vpad)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError, OSError):
            print("✖ Mất kết nối, đang thử lại…")
        finally:
            vpad.rumble_sink = None
            vpad.neutral()
            try:
                writer.close()
            except Exception:
                pass
        await asyncio.sleep(0.3)


def start_usb_forward() -> subprocess.Popen | None:
    """Forward localhost:7777 -> iPhone:7777 over the USB cable (usbmuxd)."""
    if shutil.which("iproxy"):
        cmd = ["iproxy", str(PORT), str(PORT)]
    else:
        cmd = [sys.executable, "-m", "pymobiledevice3", "usbmux", "forward", str(PORT), str(PORT)]
    print("→ Chuyển tiếp cổng qua USB:", " ".join(cmd))
    try:
        return subprocess.Popen(cmd)
    except FileNotFoundError:
        print("✖ Không tìm thấy iproxy hoặc pymobiledevice3. Xem README.")
        return None


# ---------------------------------------------------------------- Bluetooth LE

async def run_ble(vpad: VirtualPad) -> None:
    try:
        from bleak import BleakClient, BleakScanner
    except ImportError:
        sys.exit("Thiếu thư viện bleak. Chạy: pip install -r requirements.txt")

    def match(device, adv) -> bool:
        uuids = [u.lower() for u in (adv.service_uuids or [])]
        return SERVICE_UUID in uuids or (adv.local_name or device.name) == "PS5Pad"

    while True:
        print("… đang tìm iPhone (mở app, chọn 'Bluetooth')")
        device = await BleakScanner.find_device_by_filter(match, timeout=10)
        if device is None:
            continue

        disconnected = asyncio.Event()
        try:
            async with BleakClient(device, disconnected_callback=lambda _c: disconnected.set()) as client:
                async def sink(data: bytes) -> None:
                    await client.write_gatt_char(RUMBLE_UUID, data, response=False)

                vpad.rumble_sink = sink
                await client.start_notify(INPUT_UUID, lambda _h, data: vpad.apply(bytes(data)))
                print(f"✔ Đã kết nối iPhone qua Bluetooth ({device.address})")
                await disconnected.wait()
        except Exception as e:
            print(f"✖ Lỗi BLE: {e}")
        finally:
            vpad.rumble_sink = None
            vpad.neutral()
        print("✖ Mất kết nối Bluetooth, đang tìm lại…")
        await asyncio.sleep(1)


# ---------------------------------------------------------------- main

async def main() -> None:
    ap = argparse.ArgumentParser(description="PS5 Pad – companion cho Windows")
    ap.add_argument("mode", choices=["ble", "usb", "wifi"])
    ap.add_argument("host", nargs="?", help="IP của iPhone (chế độ wifi)")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--lol", action="store_true", help="Chế độ chơi LMHT kiểu Tốc Chiến (phím + chuột)")
    grp.add_argument("--lol-wasd", action="store_true", help="Chế độ chơi LMHT Keyboard (WASD) chính thức")
    args = ap.parse_args()

    ensure_single_instance()
    enable_low_latency_mode()

    if args.lol_wasd:
        vpad = LolWasdMapper()
    elif args.lol:
        vpad = LolMapper()
    else:
        vpad = VirtualPad()
    vpad.loop = asyncio.get_running_loop()
    tick_task = asyncio.create_task(vpad.tick_loop()) if isinstance(vpad, _Win32InputMapper) else None

    try:
        if args.mode == "ble":
            await run_ble(vpad)
        elif args.mode == "usb":
            try:
                import pymobiledevice3.usbmux  # noqa: F401
                has_usbmux = True
            except ImportError:
                has_usbmux = False
            if has_usbmux:
                await run_tcp(vpad, "127.0.0.1", direct_usb=True)
            else:
                proc = start_usb_forward()
                try:
                    await asyncio.sleep(1.5)
                    await run_tcp(vpad, "127.0.0.1")
                finally:
                    if proc:
                        proc.terminate()
        else:
            if not args.host:
                sys.exit("Cần nhập IP iPhone, ví dụ: python companion.py wifi 192.168.1.23")
            await run_tcp(vpad, args.host)
    finally:
        if tick_task:
            tick_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nĐã thoát.")
