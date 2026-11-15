import Foundation

/// Pushes frames to the laptop bridge at ws://<host>:8765/lidar/publish.
/// Sends at most one message at a time and drops frames while one is in flight,
/// so a slow network shows up as a lower frame rate instead of a growing backlog.
final class BridgeClient: NSObject, ObservableObject, URLSessionWebSocketDelegate {
    enum Status: Equatable {
        case off
        case connecting
        case connected
        case failed(String)
    }

    @Published private(set) var status: Status = .off
    @Published private(set) var framesSent = 0

    private lazy var session = URLSession(configuration: .default, delegate: self, delegateQueue: nil)
    private let lock = NSLock()
    private var task: URLSessionWebSocketTask?
    private var isOpen = false
    private var busy = false
    private var wanted: URL?

    /// Accepts "192.168.1.20", "192.168.1.20:8765" or a full ws:// URL.
    static func url(for entry: String) -> URL? {
        let trimmed = entry.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        if trimmed.hasPrefix("ws://") || trimmed.hasPrefix("wss://") { return URL(string: trimmed) }
        let host = trimmed.contains(":") ? trimmed : trimmed + ":8765"
        return URL(string: "ws://" + host + "/lidar/publish")
    }

    func connect(to entry: String) {
        guard let url = BridgeClient.url(for: entry) else {
            publish(.failed("Enter the laptop's IP address"))
            return
        }
        lock.lock()
        wanted = url
        lock.unlock()
        openSocket()
    }

    func disconnect() {
        lock.lock()
        wanted = nil
        let current = task
        task = nil
        isOpen = false
        busy = false
        lock.unlock()
        current?.cancel(with: .goingAway, reason: nil)
        publish(.off)
    }

    /// True when a frame handed to `send` right now would go out.
    var readyForFrame: Bool {
        lock.lock()
        defer { lock.unlock() }
        return isOpen && !busy
    }

    func send(_ text: String) {
        lock.lock()
        guard isOpen, !busy, let current = task else {
            lock.unlock()
            return
        }
        busy = true
        lock.unlock()
        current.send(.string(text)) { [weak self] error in
            guard let self else { return }
            self.lock.lock()
            self.busy = false
            self.lock.unlock()
            if error == nil {
                DispatchQueue.main.async { self.framesSent += 1 }
            }
        }
    }

    private func openSocket() {
        lock.lock()
        guard let url = wanted else {
            lock.unlock()
            return
        }
        let previous = task
        let next = session.webSocketTask(with: url)
        task = next
        isOpen = false
        busy = false
        lock.unlock()
        previous?.cancel(with: .goingAway, reason: nil)
        publish(.connecting)
        next.resume()
        listen(on: next)
    }

    /// The bridge sends nothing, but a pending receive is how a dropped link is noticed.
    private func listen(on socket: URLSessionWebSocketTask) {
        socket.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .success:
                self.listen(on: socket)
            case .failure(let error):
                self.dropped(socket, reason: error.localizedDescription)
            }
        }
    }

    private func dropped(_ socket: URLSessionWebSocketTask, reason: String) {
        lock.lock()
        guard task === socket else {
            lock.unlock()
            return
        }
        task = nil
        isOpen = false
        busy = false
        let retry = wanted != nil
        lock.unlock()
        guard retry else { return }
        publish(.failed(reason))
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
            guard let self else { return }
            self.lock.lock()
            let idle = self.task == nil && self.wanted != nil
            self.lock.unlock()
            if idle { self.openSocket() }
        }
    }

    private func publish(_ next: Status) {
        DispatchQueue.main.async { self.status = next }
    }

    // MARK: URLSessionWebSocketDelegate

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                    didOpenWithProtocol `protocol`: String?) {
        lock.lock()
        let current = task === webSocketTask
        if current { isOpen = true }
        lock.unlock()
        if current { publish(.connected) }
    }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                    didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        let text = reason.flatMap { String(data: $0, encoding: .utf8) } ?? "Bridge closed the connection"
        dropped(webSocketTask, reason: text.isEmpty ? "Bridge closed the connection" : text)
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let socket = task as? URLSessionWebSocketTask else { return }
        dropped(socket, reason: error?.localizedDescription ?? "Connection ended")
    }
}
