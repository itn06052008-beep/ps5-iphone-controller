import Foundation
import Combine

final class ConnectionManager: ObservableObject {
    enum Mode: String, CaseIterable, Identifiable {
        case bluetooth = "Bluetooth"
        case cable = "Cáp USB / Wi-Fi"
        var id: String { rawValue }
    }

    @Published var mode: Mode = .cable {
        didSet { if oldValue != mode { restart() } }
    }
    @Published private(set) var status = "Đang khởi tạo…"
    @Published private(set) var connected = false
    @Published private(set) var ipAddress: String?
    @Published var hapticsOnPress = true

    let state = ControllerState()
    private let ble = BLETransport()
    private let tcp = TCPTransport()
    private var timer: Timer?
    private var seq: UInt8 = 0
    private var lastPayload = Data()
    private var lastSent = Date.distantPast

    init() {
        let statusHandler: (String, Bool) -> Void = { [weak self] text, ok in
            DispatchQueue.main.async {
                self?.status = text
                self?.connected = ok
            }
        }
        let rumbleHandler: (UInt8, UInt8) -> Void = { large, small in
            DispatchQueue.main.async { Haptics.shared.rumble(large: large, small: small) }
        }
        ble.onStatus = statusHandler
        tcp.onStatus = statusHandler
        ble.onRumble = rumbleHandler
        tcp.onRumble = rumbleHandler

        restart()
        let t = Timer(timeInterval: 1.0 / 120.0, repeats: true) { [weak self] _ in self?.tick() }
        RunLoop.main.add(t, forMode: .common)
        timer = t
    }

    private func restart() {
        connected = false
        Haptics.shared.rumble(large: 0, small: 0)
        switch mode {
        case .bluetooth:
            tcp.stop()
            ble.start()
            ipAddress = nil
        case .cable:
            ble.stop()
            tcp.start()
            ipAddress = TCPTransport.localIPAddress()
        }
    }

    /// Send on change, plus a 10 Hz keep-alive.
    private func tick() {
        let packet = state.packet(seq: 0)
        let now = Date()
        guard packet != lastPayload || now.timeIntervalSince(lastSent) > 0.1 else { return }
        lastPayload = packet
        lastSent = now
        seq &+= 1
        var out = packet
        out[1] = seq
        switch mode {
        case .bluetooth: ble.send(out)
        case .cable: tcp.send(out)
        }
    }

    // MARK: Input API used by the UI

    func press(_ b: Buttons, _ down: Bool) {
        if down {
            state.buttons.insert(b)
            if hapticsOnPress { Haptics.shared.tap() }
        } else {
            state.buttons.remove(b)
        }
        if b == .l2 { state.l2 = down ? 1 : 0 }
        if b == .r2 { state.r2 = down ? 1 : 0 }
        tick()
    }

    func setStick(left: Bool, x: Float, y: Float) {
        // small radial dead zone
        let mag = (x * x + y * y).squareRoot()
        let (fx, fy): (Float, Float) = mag < 0.04 ? (0, 0) : (x, y)
        if left { state.lx = fx; state.ly = fy } else { state.rx = fx; state.ry = fy }
        tick()
    }
}
