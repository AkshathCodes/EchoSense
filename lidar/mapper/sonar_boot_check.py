"""Unplug the sonar board, run this, plug it back in: prints the firmware's first lines (which pins it uses)."""
import glob, time, serial
print("Unplug the board now if it is plugged in, then plug it back in (waiting 40 s)...")
seen = set(glob.glob("/dev/cu.usbmodem*")); end = time.time() + 40
while time.time() < end:
    now = set(glob.glob("/dev/cu.usbmodem*"))
    new = now - seen
    seen &= now
    if new:
        port = new.pop(); print("found", port)
        for _ in range(40):
            try:
                s = serial.Serial(port, 115200, timeout=1); break
            except Exception:
                time.sleep(0.05)
        for _ in range(8):
            print(repr(s.readline().decode("ascii", "replace").strip()))
        s.close(); break
    time.sleep(0.05)
else:
    print("no board appeared")
