# PS5 Pad – Dùng iPhone làm tay cầm PS5 cho máy tính

```
┌──────────── iPhone (app SwiftUI) ────────────┐        ┌──────── PC Windows ────────┐
│ Giao diện DualSense: D-pad, △○✕□, L1/L2,     │  BLE   │ companion.py               │
│ R1/R2, 2 cần analog, L3/R3, Touchpad, PS,    │ ─────► │  ├─ nhận gói 12 byte       │
│ Create, Options + rung (CoreHaptics)         │  USB   │  └─ ViGEmBus → tay cầm ảo  │
│                                              │ ◄───── │     PlayStation (DS4)      │
└──────────────────────────────────────────────┘  rung  └────────────────────────────┘
```

> **Vì sao cần app trên PC?** iOS không cho app tự nhận mình là tay cầm Bluetooth (HID)
> hay thiết bị USB. Vì vậy iPhone gửi dữ liệu qua Bluetooth LE / cáp USB, còn
> `companion.py` trên PC tạo ra một tay cầm PlayStation ảo mà game và Steam đều nhận.

## 1. Cài app lên iPhone

**Có máy Mac:**
```bash
brew install xcodegen
cd ios && xcodegen generate && open PS5Pad.xcodeproj
```
Trong Xcode: Signing & Capabilities → chọn Team (Apple ID miễn phí cũng được) → Run lên iPhone.

**Chỉ có Windows:** đẩy thư mục này lên GitHub → tab *Actions* → chạy **Build unsigned IPA** →
tải `PS5Pad-unsigned.ipa` → cài bằng **Sideloadly** hoặc **AltStore** (đăng nhập Apple ID).

## 2. Cài trên PC (Windows 10/11)

```powershell
cd pc
pip install -r requirements.txt    # vgamepad sẽ cài driver ViGEmBus (đồng ý khi được hỏi)
```
Với cáp USB cần thêm **Apple Devices** (Microsoft Store) hoặc iTunes để Windows nhận iPhone.

## 3. Kết nối

| Cách | Trên iPhone | Trên PC |
|---|---|---|
| Bluetooth | Chọn **Bluetooth** | `python companion.py ble` |
| Cáp USB | Chọn **Cáp USB / Wi-Fi**, cắm cáp, bấm "Tin cậy" | `python companion.py usb` |
| Wi-Fi (dự phòng) | Chọn **Cáp USB / Wi-Fi**, xem IP trên màn hình | `python companion.py wifi <IP>` |

- Bluetooth: **không cần ghép đôi** trong cài đặt Windows, companion tự tìm iPhone tên `PS5Pad`.
- Cáp USB: companion tự chạy `iproxy` (nếu có) hoặc `pymobiledevice3 usbmux forward 7777 7777`.
- Kiểm tra: mở `joy.cpl` hoặc https://hardwaretester.com/gamepad. Trong Steam bật
  *PlayStation Controller Support*.
- Để app ở màn hình chính (iOS hạn chế BLE khi app chạy nền).

## Giao thức (để tự mở rộng)

Gói input 12 byte: `D5 seq btn(u32 LE) LX LY RX RY L2 R2` · gói rung PC→iPhone: `D6 large small`.
Bit nút: 0 ✕, 1 ○, 2 □, 3 △, 4 L1, 5 R1, 6 L3, 7 R3, 8 Create, 9 Options, 10 PS, 11 Touchpad,
12–15 ↑↓←→, 16 L2, 17 R2.

## Giới hạn
- Windows nhận là DualShock 4 (ViGEm không có DualSense) – vẫn là tay cầm PlayStation, đúng
  ký hiệu nút. Không có cò thích ứng / con quay / loa.
- Độ trễ: USB ~5–10 ms, BLE ~15–30 ms.
