"""
PS5 Pad – PC companion (Windows)

Receives input from the iPhone app and exposes it to Windows as a virtual
PlayStation controller (DualShock 4 via ViGEmBus – recognised by Steam,
DS4Windows-aware games and most PlayStation-layout games).

Usage:
  python companion.py ble                 # Bluetooth LE
  python companion.py usb                 # USB cable (usbmuxd port-forward)
  python companion.py wifi 192.168.1.23   # Wi-Fi, iPhone IP shown in the app
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
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


# ---------------------------------------------------------------- TCP (USB / Wi-Fi)

async def run_tcp(vpad: VirtualPad, host: str) -> None:
    while True:
        try:
            reader, writer = await asyncio.open_connection(host, PORT)
        except OSError:
            print(f"… chưa kết nối được {host}:{PORT}, thử lại (mở app, chọn 'Cáp USB / Wi-Fi')")
            await asyncio.sleep(1.5)
            continue

        sock = writer.get_extra_info("socket")
        if sock is not None:
            import socket
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        async def sink(data: bytes) -> None:
            writer.write(data)
            await writer.drain()

        vpad.rumble_sink = sink
        print(f"✔ Đã kết nối iPhone qua TCP ({host}:{PORT})")
        try:
            while True:
                first = await reader.readexactly(1)
                if first[0] != INPUT_MAGIC:
                    continue  # resync
                rest = await reader.readexactly(PACKET.size - 1)
                vpad.apply(first + rest)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            print("✖ Mất kết nối, đang thử lại…")
        finally:
            vpad.rumble_sink = None
            vpad.neutral()
            writer.close()
        await asyncio.sleep(1)


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
    args = ap.parse_args()

    vpad = VirtualPad()
    vpad.loop = asyncio.get_running_loop()

    if args.mode == "ble":
        await run_ble(vpad)
    elif args.mode == "usb":
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


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nĐã thoát.")
