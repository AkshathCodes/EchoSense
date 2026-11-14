# Acoustic scan with a distance sensor

The acoustic viewer accepts individual ranges from a laptop microphone or an external ultrasonic module. For the external module, **Enter ultrasonic sensor readings** accepts five readings at one scanner position and aim. Enter one distance in meters per line, or `timeout` for a missed return. Take all five pings before moving the sensor. See the [project README](../README.md#acoustic-scan-and-databricks) for server and notebook setup.

The 3D view uses the median when at least three readings are usable, a majority of trials are usable, and their spread is at most 0.35 m. **Download scan CSV** includes the pose and missed returns so Databricks can reproduce that decision. Use the optional tape distance to calculate error. It does not affect the estimate.

## Remaining hardware and demo work

1. Identify the exact distance module and microcontroller. Check their power, signal voltages, units, and timing requirements before wiring. Verify that the controller prints each measured distance or an explicit timeout to its serial monitor.
2. Fix the sensor in place and measure a flat panel at 1 m and again at 2 m. Record five pings each time, put the tape distance in the reference field, and compare the results. Repeat with the panel moved out of the beam to check for returns from other surfaces.
3. For the first 3D demo, use one scene name and take readings at several marked positions and two heights. Record the sensor pose for each batch. A single range module reports one distance within its beam per ping. EchoSense places it along the entered aim, so the plotted point is an estimate.
4. Upload the measured CSV to Databricks and run the notebook. Open its exported JSON on an actual iPhone. Save the CSV and video of the panel moving for the demo.
5. Once the board is known, connect its serial output to the app and verify it with the same panel test. The separate [SonarFrame pipeline](../sonar-ml/docs/interfaces/sonar-frame.md) still needs its hardware driver and real captures for the live WebGL headset route.

The laptop timing window covers a roughly 192 ms delay observed during a live check. That retry returned 0.66 m five times, close to the lower end of the laptop detector's range. A known-distance panel test is still needed to identify the reflector and verify ranging accuracy.
