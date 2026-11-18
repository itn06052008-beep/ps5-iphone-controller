import CoreBluetooth

/// iPhone acts as a BLE peripheral exposing a custom GATT service.
/// (iOS does not allow apps to advertise as a real Bluetooth HID gamepad,
///  so the PC companion app subscribes to this service and creates a virtual controller.)
final class BLETransport: NSObject, CBPeripheralManagerDelegate {
    static let serviceUUID = CBUUID(string: "8E5A0001-5D35-4C52-9E3F-50535050AD01")
    static let inputUUID   = CBUUID(string: "8E5A0002-5D35-4C52-9E3F-50535050AD01")
    static let rumbleUUID  = CBUUID(string: "8E5A0003-5D35-4C52-9E3F-50535050AD01")

    var onStatus: ((String, Bool) -> Void)?
    var onRumble: ((UInt8, UInt8) -> Void)?

    private var manager: CBPeripheralManager?
    private var inputChar: CBMutableCharacteristic?
    private var subscribers: [CBCentral] = []
    private var pending: Data?
    private var lastPacket = Data()

    var isConnected: Bool { !subscribers.isEmpty }

    func start() {
        if manager == nil {
            manager = CBPeripheralManager(delegate: self, queue: .main)
        } else if manager?.state == .poweredOn {
            setupService()
        }
    }

    func stop() {
        manager?.stopAdvertising()
        manager?.removeAllServices()
        subscribers.removeAll()
        inputChar = nil
    }

    func send(_ data: Data) {
        lastPacket = data
        guard let manager, let inputChar, !subscribers.isEmpty else { return }
        if !manager.updateValue(data, for: inputChar, onSubscribedCentrals: nil) {
            pending = data // queue full, resend latest when ready
        }
    }

    private func setupService() {
        guard let manager else { return }
        manager.removeAllServices()
        let input = CBMutableCharacteristic(type: Self.inputUUID,
                                            properties: [.notify, .read],
                                            value: nil,
                                            permissions: [.readable])
        let rumble = CBMutableCharacteristic(type: Self.rumbleUUID,
                                             properties: [.write, .writeWithoutResponse],
                                             value: nil,
                                             permissions: [.writeable])
        let service = CBMutableService(type: Self.serviceUUID, primary: true)
        service.characteristics = [input, rumble]
        inputChar = input
        manager.add(service)
    }

    // MARK: CBPeripheralManagerDelegate

    func peripheralManagerDidUpdateState(_ peripheral: CBPeripheralManager) {
        switch peripheral.state {
        case .poweredOn:
            onStatus?("Bluetooth sẵn sàng", false)
            setupService()
        case .poweredOff: onStatus?("Bluetooth đang tắt", false)
        case .unauthorized: onStatus?("Chưa cấp quyền Bluetooth", false)
        case .unsupported: onStatus?("Thiết bị không hỗ trợ BLE", false)
        default: onStatus?("Bluetooth: đang khởi tạo…", false)
        }
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, didAdd service: CBService, error: Error?) {
        if let error {
            onStatus?("Lỗi BLE: \(error.localizedDescription)", false)
            return
        }
        peripheral.startAdvertising([
            CBAdvertisementDataLocalNameKey: "PS5Pad",
            CBAdvertisementDataServiceUUIDsKey: [Self.serviceUUID]
        ])
    }

    func peripheralManagerDidStartAdvertising(_ peripheral: CBPeripheralManager, error: Error?) {
        if let error {
            onStatus?("Lỗi quảng bá: \(error.localizedDescription)", false)
        } else {
            onStatus?("Đang chờ máy tính kết nối (BLE)…", false)
        }
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, central: CBCentral,
                           didSubscribeTo characteristic: CBCharacteristic) {
        if !subscribers.contains(where: { $0.identifier == central.identifier }) {
            subscribers.append(central)
        }
        peripheral.setDesiredConnectionLatency(.low, for: central)
        onStatus?("Đã kết nối Bluetooth", true)
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, central: CBCentral,
                           didUnsubscribeFrom characteristic: CBCharacteristic) {
        subscribers.removeAll { $0.identifier == central.identifier }
        if subscribers.isEmpty {
            onStatus?("Mất kết nối – đang chờ (BLE)…", false)
            onRumble?(0, 0)
        }
    }

    func peripheralManagerIsReady(toUpdateSubscribers peripheral: CBPeripheralManager) {
        if let data = pending, let inputChar {
            if peripheral.updateValue(data, for: inputChar, onSubscribedCentrals: nil) {
                pending = nil
            }
        }
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, didReceiveRead request: CBATTRequest) {
        request.value = lastPacket
        peripheral.respond(to: request, withResult: .success)
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, didReceiveWrite requests: [CBATTRequest]) {
        for r in requests {
            if let v = r.value, v.count >= 3, v[v.startIndex] == ControllerState.rumbleMagic {
                onRumble?(v[v.startIndex + 1], v[v.startIndex + 2])
            }
        }
        if let first = requests.first {
            peripheral.respond(to: first, withResult: .success)
        }
    }
}
