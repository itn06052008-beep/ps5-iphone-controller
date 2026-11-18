import Foundation

/// Bit layout must match pc/companion.py
struct Buttons: OptionSet, Hashable {
    let rawValue: UInt32
    static let cross    = Buttons(rawValue: 1 << 0)
    static let circle   = Buttons(rawValue: 1 << 1)
    static let square   = Buttons(rawValue: 1 << 2)
    static let triangle = Buttons(rawValue: 1 << 3)
    static let l1       = Buttons(rawValue: 1 << 4)
    static let r1       = Buttons(rawValue: 1 << 5)
    static let l3       = Buttons(rawValue: 1 << 6)
    static let r3       = Buttons(rawValue: 1 << 7)
    static let create   = Buttons(rawValue: 1 << 8)
    static let options  = Buttons(rawValue: 1 << 9)
    static let ps       = Buttons(rawValue: 1 << 10)
    static let touchpad = Buttons(rawValue: 1 << 11)
    static let up       = Buttons(rawValue: 1 << 12)
    static let down     = Buttons(rawValue: 1 << 13)
    static let left     = Buttons(rawValue: 1 << 14)
    static let right    = Buttons(rawValue: 1 << 15)
    static let l2       = Buttons(rawValue: 1 << 16)
    static let r2       = Buttons(rawValue: 1 << 17)
}

/// Packet (12 bytes, little endian):
/// [0]=0xD5 magic, [1]=seq, [2..5]=buttons u32, [6]=LX, [7]=LY, [8]=RX, [9]=RY, [10]=L2, [11]=R2
/// Axes 0..255 (128 = center, LY/RY: 0 = up). Rumble feedback PC -> phone: [0xD6, large, small]
final class ControllerState {
    static let inputMagic: UInt8 = 0xD5
    static let rumbleMagic: UInt8 = 0xD6
    static let packetSize = 12

    var buttons: Buttons = []
    var lx: Float = 0, ly: Float = 0, rx: Float = 0, ry: Float = 0
    var l2: Float = 0, r2: Float = 0

    func packet(seq: UInt8) -> Data {
        var b = [UInt8](repeating: 0, count: Self.packetSize)
        b[0] = Self.inputMagic
        b[1] = seq
        let v = buttons.rawValue
        b[2] = UInt8(v & 0xFF)
        b[3] = UInt8((v >> 8) & 0xFF)
        b[4] = UInt8((v >> 16) & 0xFF)
        b[5] = UInt8((v >> 24) & 0xFF)
        b[6] = Self.axis(lx)
        b[7] = Self.axis(ly)
        b[8] = Self.axis(rx)
        b[9] = Self.axis(ry)
        b[10] = UInt8(clamping: Int((max(0, min(1, l2)) * 255).rounded()))
        b[11] = UInt8(clamping: Int((max(0, min(1, r2)) * 255).rounded()))
        return Data(b)
    }

    static func axis(_ v: Float) -> UInt8 {
        let c = max(-1, min(1, v))
        return UInt8(clamping: Int((c * 127.5 + 127.5).rounded()))
    }
}
