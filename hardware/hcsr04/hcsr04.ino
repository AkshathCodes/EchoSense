// HC-SR04 ultrasonic range sensor -> USB serial, for the EchoSense LiDAR mapper.
//
// Prints one line per ping at 115200 baud: the distance in meters with three
// decimals ("1.234"), or "timeout" when no echo came back. The mapper reads
// this with --sonar-port (lidar/mapper/src/lidar_mapper/sonar.py), and so does
// the bridge's range adapter in "meters-line" mode.
//
// Wiring and how the sensor works: README.md in this folder.
// Not yet run on hardware.

// The same sketch runs on an ESP32 and on a 5 V Arduino. Pins differ per board.
#if defined(ESP32)
// Classic ESP32 DevKit. ECHO must come through the 1k / 2k divider: the sensor
// drives it at 5 V and ESP32 pins take 3.3 V at most.
const uint8_t TRIG_PIN = 26;
const uint8_t ECHO_PIN = 27;
#else
// Arduino Uno or Nano (5 V): wire ECHO straight to the pin.
const uint8_t TRIG_PIN = 9;
const uint8_t ECHO_PIN = 10;
#endif

// The sensor needs about 60 ms between pings for the last echo to die away.
const unsigned long PING_INTERVAL_MS = 65;
// Give up after 25 ms: sound covers 4.3 m and back in that time, beyond the sensor's range.
const unsigned long ECHO_TIMEOUT_US = 25000;
// Sound travels 343 m/s in air at 20 C. The echo time covers the distance twice.
const float METERS_PER_MICROSECOND = 343.0f / 2.0f / 1000000.0f;

void setup() {
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  digitalWrite(TRIG_PIN, LOW);
  Serial.begin(115200);
}

void loop() {
  const unsigned long started = millis();

  // A 10 microsecond HIGH on TRIG makes the sensor send its burst of 40 kHz sound.
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(4);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  // ECHO stays HIGH for as long as the sound took to go out and come back.
  const unsigned long echoMicros = pulseIn(ECHO_PIN, HIGH, ECHO_TIMEOUT_US);

  if (echoMicros == 0) {
    Serial.println(F("timeout"));
  } else {
    Serial.println(echoMicros * METERS_PER_MICROSECOND, 3);
  }

  while (millis() - started < PING_INTERVAL_MS) {
    // Wait out the rest of the interval so pings are evenly spaced.
  }
}
