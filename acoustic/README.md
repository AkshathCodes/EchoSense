# Acoustic scan with a distance sensor

The acoustic viewer accepts individual ranges from a laptop microphone or an external ultrasonic module. For the external module, **Enter ultrasonic sensor readings** accepts five readings at one scanner position and aim. Enter one distance in meters per line, or `timeout` for a missed return. Take all five pings before moving the sensor. See the [project README](../README.md#acoustic-scan-and-databricks) for server and notebook setup.

The 3D view uses the median when at least three readings are usable, a majority of trials are usable, and their spread is at most 0.35 m. **Download scan CSV** includes the pose and missed returns so Databricks can reproduce that decision. Use the optional tape distance to calculate error. It does not affect the estimate.

## Rehearse the judging demo

1. Open **Try sample scan** to rehearse with the simulated room. Select **Panel at 1 m**, **Panel at 2 m**, and **Panel removed** to see how the scan quality summary reports estimates and withheld positions.
2. For the live demo, leave the sensor stationary. In **Capture a scan**, choose each panel setup, enter the actual tape distance, and capture five pings. Take the third set with the panel out of the beam. A return in that set may be a background surface.
3. Upload the exported CSV and run the Databricks notebook. Show the usable trial count, mapped positions, and tape error table. Open the exported room map on the iPhone and move the You marker.
4. Save the measured CSV and JSON and record the judge's view of the panel and phone. Keep the JSON in Files on the iPhone so it can be reopened in the loaded demo page if the live capture fails. Rehearse the complete sequence in 90 seconds.

For the judging pitch, keep the scope to the test you can show:

- **0–15 seconds.** “EchoSense estimates distance from reflected sound. We’re testing whether it can map a few surfaces in a room when visibility is limited.”
- **15–55 seconds.** Have a judge move the panel between the two tape marks. Show the scan reading for each position and then open the room map on the iPhone. Move the You marker and point out the change in distance.
- **55–90 seconds.** Show Databricks coverage, tape error, and the missing-return count. If you're demonstrating the sample workflow, leave the simulated data label visible.

## USB capture

On the scanner laptop, use desktop Chrome at `http://127.0.0.1:4173/acoustic/`. Close the serial monitor, select the board's baud rate, and click **Read 5 from USB**. Select the board's port and hold the scanner still. The board should stream one positive decimal distance in meters or the word `timeout` per line, at a steady rate. EchoSense opens the port for each batch and reads five newline-terminated records within ten seconds. Configure the board to emit plain readings after opening the port. The paste field accepts the same format.

## Remaining hardware and demo work

1. Identify the exact distance module and microcontroller. Check their power, signal voltages, units, and timing requirements before wiring. Verify that the controller prints each measured distance or an explicit timeout to its serial monitor.
2. Fix the sensor in place and measure a flat panel at 1 m and again at 2 m. Record five pings each time, put the tape distance in the reference field, and compare the results. Repeat with the panel moved out of the beam to check for returns from other surfaces.
3. For the first 3D demo, use one scene name and take readings at several marked positions and two heights. Record the sensor pose for each batch. A single range module reports one distance within its beam per ping. EchoSense places it along the entered aim, so the plotted point is an estimate.
4. Upload the measured CSV to Databricks and run the notebook. Open its exported JSON on an actual iPhone. Save the CSV and video of the panel moving for the demo.
5. Verify USB capture with the selected board and the same panel test. The separate [SonarFrame pipeline](../sonar-ml/docs/interfaces/sonar-frame.md) still needs its hardware driver and real captures for the live WebGL headset route.

The laptop timing window covers a roughly 192 ms delay observed during a live check. That retry returned 0.66 m five times, close to the lower end of the laptop detector's range. A known-distance panel test is still needed to identify the reflector and verify ranging accuracy.

## Train and replay the sonar classifier

From the repository root, use Python 3.11 or later in a project virtual environment:

```sh
python -m pip install -e ./sonar-ml/perception -e "./websocket-bridge[recorded]"
python acoustic/train_demo_model.py ./sonar-ml/data/judge-model --train-scenes 240 --validation-scenes 80 --test-scenes 120
python -m sonar_bridge --origin http://127.0.0.1:4173 --manifest ./sonar-ml/data/judge-model/replay/manifest.jsonl --fps 2
```

Open the room viewer and connect to `ws://127.0.0.1:8765/ws`. The viewer labels the stream as simulated replay. The training script saves a random-forest checkpoint, test metrics, and the paired frames and detections consumed by the bridge. It chooses forest parameters using validation macro F1 and tunes the person class weight using object-level F2 on a separate validation set. The held-out metrics in `model-evaluation.json` include recall and precision, plus the results for the current forest with its documented person weight of 2.

Use the laptop or USB panel test for measured distances. The classifier scores and replay come from the sonar simulator.

In the documented 120-scene held-out simulation, the tuned model found 79 of 127 person-sized objects and raised 51 false alarms. The current forest with its documented person weight of 2 found 77 of 127 and raised 34 false alarms. The extra false alarms outweighed the recall gain on F2, so keep the current forest as the default. The tuned replay remains available for comparison.
