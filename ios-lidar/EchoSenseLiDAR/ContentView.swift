import SwiftUI

struct ContentView: View {
    @ObservedObject var scanner: LiDARScanner
    @ObservedObject var bridge: BridgeClient
    @AppStorage("bridgeHost") private var host = ""
    @State private var showSettings = false
    @FocusState private var hostFocused: Bool

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            if let image = scanner.depthImage {
                // The frame keeps the oversized image from widening the layout.
                GeometryReader { proxy in
                    Image(uiImage: image)
                        .resizable()
                        .interpolation(.medium)
                        .scaledToFill()
                        .frame(width: proxy.size.width, height: proxy.size.height)
                        .clipped()
                }
                .ignoresSafeArea()
            }
            VStack(spacing: 12) {
                statusBar
                if let problem = scanner.problem { banner(problem) }
                if scanner.scanning && !scanner.trackingNormal {
                    banner("No points are being sent: \(scanner.trackingText.lowercased()). "
                           + "Move slowly, add light, or turn on the torch.")
                }
                if scanner.scanning && bridge.status != .connected {
                    banner("Scanning, but the laptop is not connected. Tap Laptop.")
                }
                Spacer()
                distanceReadout
                controls
            }
            .padding()
        }
        .sheet(isPresented: $showSettings) { settings }
    }

    private var statusBar: some View {
        HStack {
            pill(scanner.trackingText, good: scanner.trackingNormal)
            Spacer()
            pill(bridgeText, good: bridge.status == .connected)
        }
    }

    private var bridgeText: String {
        switch bridge.status {
        case .off: return "Laptop: off"
        case .connecting: return "Laptop: connecting"
        case .connected: return "Laptop: \(bridge.framesSent) sent"
        case .failed: return "Laptop: retrying"
        }
    }

    private var distanceReadout: some View {
        VStack(spacing: 2) {
            Text(scanner.nearest.map { String(format: "%.2f m", $0) } ?? "No return")
                .font(.system(size: 56, weight: .bold, design: .rounded))
                .monospacedDigit()
            Text(scanner.scanning ? "nearest ahead · sending \(scanner.pointsPerFrame) points a frame"
                 : "nearest obstacle ahead")
                .font(.footnote)
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 20)
        .padding(.vertical, 10)
        .background(.black.opacity(0.55), in: RoundedRectangle(cornerRadius: 18))
    }

    private var controls: some View {
        VStack(spacing: 10) {
            Button {
                scanner.scanning.toggle()
            } label: {
                Label(scanner.scanning ? "Stop scan" : "Start scan",
                      systemImage: scanner.scanning ? "stop.fill" : "dot.radiowaves.left.and.right")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 6)
            }
            .buttonStyle(.borderedProminent)
            .tint(scanner.scanning ? .red : .blue)
            Text("Session \(scanner.sessionLabel)")
                .font(.caption2.monospaced())
                .foregroundStyle(.white.opacity(0.7))
            HStack(spacing: 10) {
                toggleButton("Torch", icon: "flashlight.on.fill", isOn: $scanner.torchOn)
                toggleButton("Pulse", icon: "waveform", isOn: $scanner.hapticsOn)
                Button {
                    scanner.newSession()
                } label: {
                    Label("New", systemImage: "arrow.counterclockwise")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                Button {
                    showSettings = true
                } label: {
                    Label("Laptop", systemImage: "laptopcomputer")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
            }
            .tint(.white)
        }
        .padding(12)
        .background(.black.opacity(0.55), in: RoundedRectangle(cornerRadius: 18))
    }

    private var settings: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("192.168.1.20", text: $host)
                        .keyboardType(.numbersAndPunctuation)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .focused($hostFocused)
                    if bridge.status == .off {
                        Button("Connect") {
                            hostFocused = false
                            bridge.connect(to: host)
                        }
                    } else {
                        Button("Disconnect", role: .destructive) { bridge.disconnect() }
                    }
                } header: {
                    Text("Laptop address")
                } footer: {
                    Text("The bridge prints this address when it starts with --lidar. "
                         + "The phone and laptop must be on the same network.")
                }
                Section("Status") {
                    switch bridge.status {
                    case .off: Text("Not connected")
                    case .connecting: Text("Connecting")
                    case .connected: Text("Connected, \(bridge.framesSent) frames sent")
                    case .failed(let reason): Text("Retrying: \(reason)")
                    }
                }
                Section("Feedback") {
                    Toggle("Vibrate near obstacles", isOn: $scanner.hapticsOn)
                    Toggle("Click near obstacles", isOn: $scanner.soundOn)
                }
            }
            .navigationTitle("Laptop viewer")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { showSettings = false }
                }
            }
        }
    }

    private func pill(_ text: String, good: Bool) -> some View {
        HStack(spacing: 6) {
            Circle()
                .fill(good ? Color.green : Color.orange)
                .frame(width: 8, height: 8)
            Text(text).font(.footnote.weight(.semibold))
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 12)
        .padding(.vertical, 7)
        .background(.black.opacity(0.6), in: Capsule())
    }

    private func banner(_ text: String) -> some View {
        Text(text)
            .font(.footnote.weight(.medium))
            .foregroundStyle(.black)
            .padding(10)
            .frame(maxWidth: .infinity)
            .background(Color.yellow, in: RoundedRectangle(cornerRadius: 12))
    }

    private func toggleButton(_ title: String, icon: String, isOn: Binding<Bool>) -> some View {
        Button {
            isOn.wrappedValue.toggle()
        } label: {
            Label(title, systemImage: icon).frame(maxWidth: .infinity)
        }
        .buttonStyle(.bordered)
        .background(isOn.wrappedValue ? Color.white.opacity(0.3) : Color.clear,
                    in: RoundedRectangle(cornerRadius: 8))
    }
}
