/**
 * AudioWorklet Processor – captures microphone audio, down-samples to 16 kHz,
 * posts PCM buffers + RMS energy back to the main thread.
 *
 * Messages to main thread:
 *   { type: "audio",  buffer: Float32Array }
 *   { type: "vad",    rms: number }
 */

class AudioCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();

    // Target 16 kHz regardless of the hardware sample rate
    this.targetRate = 16000;
    this.sourceRate = sampleRate;                    // global in AudioWorklet scope
    this.ratio      = Math.max(1, Math.round(this.sourceRate / this.targetRate));

    // Accumulate ~4096 down-sampled samples before posting (≈ 256 ms at 16 kHz)
    // this.chunkSize    = 4096;

    // Accumulate ~1024 down-sampled samples before posting (≈ 64 ms at 16 kHz) for lower latency
    this.chunkSize    = 1024;
    this.buffer       = new Float32Array(this.chunkSize);
    this.bytesWritten = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;

    const channelData = input[0]; // mono
    if (!channelData) return true;

    // RMS for VAD (computed on full-rate data)
    let sum = 0;
    for (let i = 0; i < channelData.length; i++) {
      sum += channelData[i] * channelData[i];
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

    // Always send RMS so the main thread can run VAD immediately
    this.port.postMessage({ type: 'vad', rms });

    return true;
  }
}

registerProcessor('audio-capture-processor', AudioCaptureProcessor);
