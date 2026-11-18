import SwiftUI

// MARK: - Main layout (landscape, DualSense style)

struct ControllerView: View {
    @EnvironmentObject var m: ConnectionManager

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            let h = geo.size.height
            let cluster = min(h * 0.40, w * 0.20)
            let stick = min(h * 0.36, w * 0.19)

            ZStack {
                LinearGradient(colors: [Color(white: 0.96), Color(white: 0.80)],
                               startPoint: .top, endPoint: .bottom)
                    .ignoresSafeArea()

                // Shoulders / triggers
                PadButton(bit: .l2, label: "L2", width: w * 0.13, height: h * 0.10, corner: h * 0.05)
                    .position(x: w * 0.08, y: h * 0.08)
                PadButton(bit: .l1, label: "L1", width: w * 0.12, height: h * 0.08, corner: h * 0.04)
                    .position(x: w * 0.22, y: h * 0.08)
                PadButton(bit: .r1, label: "R1", width: w * 0.12, height: h * 0.08, corner: h * 0.04)
                    .position(x: w * 0.78, y: h * 0.08)
                PadButton(bit: .r2, label: "R2", width: w * 0.13, height: h * 0.10, corner: h * 0.05)
                    .position(x: w * 0.92, y: h * 0.08)

                StatusBar()
                    .position(x: w * 0.5, y: h * 0.07)

                // Center
                PadButton(bit: .touchpad, label: "", width: w * 0.30, height: h * 0.24, corner: 14,
                          fill: Color(white: 0.22))
                    .position(x: w * 0.5, y: h * 0.31)
                PadButton(bit: .create, label: "≡", width: h * 0.07, height: h * 0.11, corner: h * 0.035,
                          fontSize: h * 0.04)
                    .position(x: w * 0.31, y: h * 0.25)
                PadButton(bit: .options, label: "☰", width: h * 0.07, height: h * 0.11, corner: h * 0.035,
                          fontSize: h * 0.035)
                    .position(x: w * 0.69, y: h * 0.25)
                PadButton(bit: .ps, label: "PS", width: h * 0.13, height: h * 0.13, corner: h * 0.065,
                          fontSize: h * 0.045)
                    .position(x: w * 0.5, y: h * 0.56)

                // D-pad & face buttons
                DPad(size: cluster)
                    .position(x: w * 0.13, y: h * 0.44)
                FaceButtons(size: cluster)
                    .position(x: w * 0.87, y: h * 0.44)

                // Sticks
                Joystick(left: true, size: stick)
                    .position(x: w * 0.33, y: h * 0.76)
                Joystick(left: false, size: stick)
                    .position(x: w * 0.67, y: h * 0.76)

                PadButton(bit: .l3, label: "L3", width: h * 0.13, height: h * 0.13, corner: h * 0.065,
                          fontSize: h * 0.04)
                    .position(x: w * 0.13, y: h * 0.82)
                PadButton(bit: .r3, label: "R3", width: h * 0.13, height: h * 0.13, corner: h * 0.065,
                          fontSize: h * 0.04)
                    .position(x: w * 0.87, y: h * 0.82)
            }
        }
        .statusBarHidden()
        .persistentSystemOverlays(.hidden)
        .defersSystemGestures(on: .all)
    }
}

// MARK: - Status / mode picker

struct StatusBar: View {
    @EnvironmentObject var m: ConnectionManager

    var body: some View {
        VStack(spacing: 2) {
            Picker("Kết nối", selection: $m.mode) {
                ForEach(ConnectionManager.Mode.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)
            .frame(width: 240)

            HStack(spacing: 6) {
                Circle()
                    .fill(m.connected ? Color.green : Color.orange)
                    .frame(width: 8, height: 8)
                Text(m.status).font(.caption2).lineLimit(1)
                if m.mode == .cable, let ip = m.ipAddress {
                    Text("• Wi-Fi: \(ip):\(TCPTransport.port)")
                        .font(.caption2.monospacedDigit())
                }
            }
            .foregroundStyle(Color(white: 0.25))
        }
    }
}

// MARK: - Generic press-and-hold button (multi-touch safe)

struct PadButton: View {
    @EnvironmentObject var m: ConnectionManager
    let bit: Buttons
    let label: String
    var width: CGFloat
    var height: CGFloat
    var corner: CGFloat
    var fill: Color = Color(white: 0.15)
    var textColor: Color = .white
    var fontSize: CGFloat = 16

    @State private var pressed = false

    var body: some View {
        RoundedRectangle(cornerRadius: corner, style: .continuous)
            .fill(pressed ? Color(white: 0.45) : fill)
            .shadow(color: .black.opacity(pressed ? 0.1 : 0.35), radius: pressed ? 1 : 3, y: pressed ? 0 : 2)
            .overlay(
                Text(label)
                    .font(.system(size: fontSize, weight: .bold, design: .rounded))
                    .foregroundStyle(textColor)
            )
            .frame(width: width, height: height)
            .scaleEffect(pressed ? 0.93 : 1)
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in
                        if !pressed { pressed = true; m.press(bit, true) }
                    }
                    .onEnded { _ in
                        pressed = false
                        m.press(bit, false)
                    }
            )
            .animation(.easeOut(duration: 0.06), value: pressed)
    }
}

// MARK: - D-pad

struct DPad: View {
    let size: CGFloat
    var body: some View {
        let b = size * 0.34
        let o = size * 0.33
        ZStack {
            Circle().fill(Color.black.opacity(0.06)).frame(width: size, height: size)
            PadButton(bit: .up, label: "▲", width: b, height: b, corner: 8, fontSize: b * 0.4).offset(y: -o)
            PadButton(bit: .down, label: "▼", width: b, height: b, corner: 8, fontSize: b * 0.4).offset(y: o)
            PadButton(bit: .left, label: "◀", width: b, height: b, corner: 8, fontSize: b * 0.4).offset(x: -o)
            PadButton(bit: .right, label: "▶", width: b, height: b, corner: 8, fontSize: b * 0.4).offset(x: o)
        }
        .frame(width: size, height: size)
    }
}

// MARK: - Face buttons

struct FaceButtons: View {
    let size: CGFloat
    var body: some View {
        let b = size * 0.34
        let o = size * 0.33
        ZStack {
            Circle().fill(Color.black.opacity(0.06)).frame(width: size, height: size)
            PadButton(bit: .triangle, label: "△", width: b, height: b, corner: b / 2,
                      textColor: Color(red: 0.25, green: 0.85, blue: 0.7), fontSize: b * 0.5).offset(y: -o)
            PadButton(bit: .cross, label: "✕", width: b, height: b, corner: b / 2,
                      textColor: Color(red: 0.45, green: 0.6, blue: 1.0), fontSize: b * 0.45).offset(y: o)
            PadButton(bit: .square, label: "□", width: b, height: b, corner: b / 2,
                      textColor: Color(red: 1.0, green: 0.5, blue: 0.8), fontSize: b * 0.5).offset(x: -o)
            PadButton(bit: .circle, label: "○", width: b, height: b, corner: b / 2,
                      textColor: Color(red: 1.0, green: 0.35, blue: 0.4), fontSize: b * 0.5).offset(x: o)
        }
        .frame(width: size, height: size)
    }
}

// MARK: - Analog stick (relative: touch anywhere on the base, then drag)

struct Joystick: View {
    @EnvironmentObject var m: ConnectionManager
    let left: Bool
    let size: CGFloat
    @State private var knob: CGSize = .zero
    @State private var active = false

    var body: some View {
        let knobSize = size * 0.46
        let maxD = (size - knobSize) / 2 + knobSize * 0.15

        ZStack {
            Circle()
                .fill(Color(white: 0.18))
                .overlay(Circle().stroke(Color.black.opacity(0.35), lineWidth: 3))
            Circle()
                .fill(RadialGradient(colors: [Color(white: 0.38), Color(white: 0.12)],
                                     center: .init(x: 0.4, y: 0.35),
                                     startRadius: 2, endRadius: knobSize * 0.6))
                .frame(width: knobSize, height: knobSize)
                .shadow(color: .black.opacity(0.5), radius: active ? 2 : 4, y: 2)
                .offset(knob)
        }
        .frame(width: size, height: size)
        .contentShape(Circle())
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { v in
                    active = true
                    var dx = v.translation.width
                    var dy = v.translation.height
                    let d = (dx * dx + dy * dy).squareRoot()
                    if d > maxD { dx *= maxD / d; dy *= maxD / d }
                    knob = CGSize(width: dx, height: dy)
                    m.setStick(left: left, x: Float(dx / maxD), y: Float(dy / maxD))
                }
                .onEnded { _ in
                    active = false
                    withAnimation(.spring(response: 0.18, dampingFraction: 0.6)) { knob = .zero }
                    m.setStick(left: left, x: 0, y: 0)
                }
        )
    }
}
