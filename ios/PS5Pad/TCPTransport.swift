import Foundation
import Network

/// TCP server on the iPhone (port 7777).
/// - USB cable: the PC forwards a local port to the phone through usbmuxd
///   (pymobiledevice3 / iproxy), then connects to 127.0.0.1:7777.
/// - Wi-Fi: the PC connects directly to <iPhone IP>:7777.
final class TCPTransport {
    static let port: UInt16 = 7777

    var onStatus: ((String, Bool) -> Void)?
    var onRumble: ((UInt8, UInt8) -> Void)?

    private var listener: NWListener?
    private var connection: NWConnection?
    private var rxBuffer = Data()

    var isConnected: Bool { connection?.state == .ready }

    func start() {
        guard listener == nil else { return }
        let params = NWParameters.tcp
        if let tcp = params.defaultProtocolStack.transportProtocol as? NWProtocolTCP.Options {
            tcp.noDelay = true
        }
        params.allowLocalEndpointReuse = true
        do {
            let l = try NWListener(using: params, on: NWEndpoint.Port(rawValue: Self.port)!)
            l.newConnectionHandler = { [weak self] c in self?.accept(c) }
            l.stateUpdateHandler = { [weak self] state in
                switch state {
                case .ready: self?.onStatus?("Đang chờ máy tính (cổng \(Self.port))…", false)
                case .failed(let e): self?.onStatus?("Lỗi TCP: \(e.localizedDescription)", false)
                default: break
                }
            }
            l.start(queue: .main)
            listener = l
        } catch {
            onStatus?("Không mở được cổng \(Self.port): \(error.localizedDescription)", false)
        }
    }

    func stop() {
        connection?.cancel()
        connection = nil
        listener?.cancel()
        listener = nil
    }

    func send(_ data: Data) {
        guard let c = connection, c.state == .ready else { return }
        c.send(content: data, completion: .contentProcessed { _ in })
    }

    private func accept(_ c: NWConnection) {
        connection?.cancel()
        connection = c
        rxBuffer.removeAll()
        c.stateUpdateHandler = { [weak self, weak c] state in
            guard let self, let c else { return }
            switch state {
            case .ready:
                self.onStatus?("Đã kết nối (cáp / Wi-Fi)", true)
            case .failed, .cancelled:
                if self.connection === c {
                    self.connection = nil
                    self.onRumble?(0, 0)
                    self.onStatus?("Mất kết nối – đang chờ (cổng \(Self.port))…", false)
                }
            default: break
            }
        }
        c.start(queue: .main)
        receive(on: c)
    }

    private func receive(on c: NWConnection) {
        c.receive(minimumIncompleteLength: 1, maximumLength: 256) { [weak self] data, _, done, error in
            guard let self else { return }
            if let data { self.rxBuffer.append(data); self.parse() }
            if done || error != nil {
                c.cancel()
            } else {
                self.receive(on: c)
            }
        }
    }

    private func parse() {
        while rxBuffer.count >= 3 {
            let b = [UInt8](rxBuffer.prefix(3))
            if b[0] == ControllerState.rumbleMagic {
                onRumble?(b[1], b[2])
                rxBuffer.removeFirst(3)
            } else {
                rxBuffer.removeFirst(1) // resync
            }
        }
    }

    /// IPv4 address of Wi-Fi (en0) or Personal Hotspot bridge, for display.
    static func localIPAddress() -> String? {
        var result: String?
        var ifaddr: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&ifaddr) == 0, let first = ifaddr else { return nil }
        defer { freeifaddrs(ifaddr) }
        for ptr in sequence(first: first, next: { $0.pointee.ifa_next }) {
            let iface = ptr.pointee
            guard let sa = iface.ifa_addr, sa.pointee.sa_family == UInt8(AF_INET) else { continue }
            let name = String(cString: iface.ifa_name)
            guard name == "en0" || name.hasPrefix("bridge") else { continue }
            var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            if getnameinfo(sa, socklen_t(sa.pointee.sa_len), &host, socklen_t(host.count),
                           nil, 0, NI_NUMERICHOST) == 0 {
                result = String(cString: host)
                if name == "en0" { break }
            }
        }
        return result
    }
}
