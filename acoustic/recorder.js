class EchoRecorder extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0][0];
    if (input) this.port.postMessage({ start: currentFrame, samples: input });
    return true;
  }
}

registerProcessor("echo-recorder", EchoRecorder);
