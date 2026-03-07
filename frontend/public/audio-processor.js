/**
 * AudioWorklet Processor – captures microphone audio, down-samples to 16 kHz,
 * posts PCM buffers + RMS energy back to the main thread.
 *
 * Messages to main thread:
 *   { type: "audio",  buffer: Float32Array }
 *   { type: "vad",    rms: number, peak: number }
 *
 * The `peak` value is the max absolute sample in the frame — useful for the
 * main-thread VAD to reject isolated spikes that inflate RMS.
 */

class AudioCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();

    // Target 16 kHz regardless of the hardware sample rate
    this.targetRate = 16000;
    this.sourceRate = sampleRate;                    // global in AudioWorklet scope
    this.ratio      = Math.max(1, Math.round(this.sourceRate / this.targetRate));

    // Accumulate ~4096 down-sampled samples before posting (≈ 256 ms at 16 kHz)
    this.chunkSize    = 4096;
    this.buffer       = new Float32Array(this.chunkSize);
    this.bytesWritten = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;

    const channelData = input[0]; // mono
    if (!channelData) return true;

    // RMS + peak for VAD (computed on full-rate data)
    let sum  = 0;
    let peak = 0;
    for (let i = 0; i < channelData.length; i++) {
      sum += channelData[i] * channelData[i];
      const abs = Math.abs(channelData[i]);
      if (abs > peak) peak = abs;
    }
    const rms = Math.sqrt(sum / channelData.length);

    // Down-sample by simple decimation
    for (let i = 0; i < channelData.length; i += this.ratio) {
      this.buffer[this.bytesWritten++] = channelData[i];

      if (this.bytesWritten >= this.chunkSize) {
        this.port.postMessage({
          type: 'audio',
          buffer: this.buffer.slice(0, this.bytesWritten),
        });
        this.bytesWritten = 0;
      }
    }

    // Always send RMS + peak so the main thread can run VAD immediately
    this.port.postMessage({ type: 'vad', rms, peak });

    return true;
  }
}

registerProcessor('audio-capture-processor', AudioCaptureProcessor);
