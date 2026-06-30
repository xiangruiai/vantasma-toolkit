/**
 * WebCodecs Recorder - Records canvas directly to MP4
 *
 * Uses the WebCodecs API for fast, native video encoding
 * and mp4-muxer to write directly to MP4 format.
 *
 * This is 10x faster than MediaRecorder + FFmpeg conversion.
 */

import { Muxer, ArrayBufferTarget } from 'mp4-muxer';

// Check if WebCodecs is supported
export function isWebCodecsSupported(): boolean {
  return typeof VideoEncoder !== 'undefined' && typeof AudioEncoder !== 'undefined';
}

export interface WebCodecsRecorderOptions {
  width: number;
  height: number;
  frameRate?: number;
  videoBitrate?: number;
  audioBitrate?: number;
  audioStream?: MediaStream; // For webcam audio
}

export class WebCodecsRecorder {
  private muxer: Muxer<ArrayBufferTarget> | null = null;
  private videoEncoder: VideoEncoder | null = null;
  private audioEncoder: AudioEncoder | null = null;
  private audioContext: AudioContext | null = null;
  private mediaStreamSource: MediaStreamAudioSourceNode | null = null;

  private width: number;
  private height: number;
  private frameRate: number;
  private videoBitrate: number;
  private audioBitrate: number;
  private audioStream: MediaStream | null;

  private frameCount: number = 0;
  private droppedFrameCount: number = 0;
  private isRecording: boolean = false;
  private isPaused: boolean = false;
  private audioSampleRate: number = 48000;
  private audioTimestamp: number = 0;
  private frameIntervalUs: number;
  private timelineStartedAtMs: number | null = null;
  private pausedAtMs: number | null = null;
  private totalPausedMs: number = 0;
  private lastVideoTimestampUs: number = -1;

  constructor(options: WebCodecsRecorderOptions) {
    this.width = options.width;
    this.height = options.height;
    this.frameRate = options.frameRate || 30;
    this.frameIntervalUs = 1_000_000 / this.frameRate;
    this.videoBitrate = options.videoBitrate || 5_000_000; // 5 Mbps
    this.audioBitrate = options.audioBitrate || 128_000; // 128 kbps
    this.audioStream = options.audioStream || null;
  }

  async start(): Promise<void> {
    // Create the MP4 muxer
    this.muxer = new Muxer({
      target: new ArrayBufferTarget(),
      video: {
        codec: 'avc',
        width: this.width,
        height: this.height,
      },
      audio: this.audioStream ? {
        codec: 'aac',
        numberOfChannels: 1,
        sampleRate: this.audioSampleRate,
      } : undefined,
      fastStart: 'in-memory',
      firstTimestampBehavior: 'offset',
    });

    // Create video encoder
    this.videoEncoder = new VideoEncoder({
      output: (chunk, meta) => {
        this.muxer?.addVideoChunk(chunk, meta);
      },
      error: (e) => console.error('VideoEncoder error:', e),
    });

    // Configure video encoder with H.264
    // Use High Profile Level 4.0 for 1080p support
    // Level 4.0 supports up to 1920x1080 @ 30fps
    this.videoEncoder.configure({
      codec: 'avc1.640028', // H.264 High Profile Level 4.0
      width: this.width,
      height: this.height,
      bitrate: this.videoBitrate,
      framerate: this.frameRate,
      latencyMode: 'realtime', // Optimize for live recording
    });

    // Wait for encoder to be ready
    await this.videoEncoder.flush();

    // Set up audio encoding if we have an audio stream
    if (this.audioStream) {
      await this.setupAudioEncoder();
    }

    this.frameCount = 0;
    this.droppedFrameCount = 0;
    this.audioTimestamp = 0;
    this.timelineStartedAtMs = null;
    this.pausedAtMs = null;
    this.totalPausedMs = 0;
    this.lastVideoTimestampUs = -1;
    this.isRecording = true;
    this.isPaused = false;

    console.log('[WebCodecsRecorder] Started recording', this.width, 'x', this.height);
  }

  private async setupAudioEncoder(): Promise<void> {
    if (!this.audioStream) return;

    // Create audio encoder
    this.audioEncoder = new AudioEncoder({
      output: (chunk, meta) => {
        this.muxer?.addAudioChunk(chunk, meta);
      },
      error: (e) => console.error('AudioEncoder error:', e),
    });

    this.audioEncoder.configure({
      codec: 'mp4a.40.2', // AAC-LC
      numberOfChannels: 1,
      sampleRate: this.audioSampleRate,
      bitrate: this.audioBitrate,
    });

    // Set up audio capture using AudioContext
    this.audioContext = new AudioContext({ sampleRate: this.audioSampleRate });

    // Get audio track from stream
    const audioTrack = this.audioStream.getAudioTracks()[0];
    if (!audioTrack) {
      console.warn('[WebCodecsRecorder] No audio track found');
      return;
    }

    // Create media stream source
    const audioOnlyStream = new MediaStream([audioTrack]);
    this.mediaStreamSource = this.audioContext.createMediaStreamSource(audioOnlyStream);

    // Use ScriptProcessorNode for audio capture (simpler than AudioWorklet)
    const bufferSize = 4096;
    const scriptNode = this.audioContext.createScriptProcessor(bufferSize, 1, 1);

    scriptNode.onaudioprocess = (event) => {
      if (!this.isRecording || this.isPaused || !this.audioEncoder || this.timelineStartedAtMs === null) return;

      const inputData = event.inputBuffer.getChannelData(0);

      // Convert Float32 to Int16
      const int16Data = new Int16Array(inputData.length);
      for (let i = 0; i < inputData.length; i++) {
        const s = Math.max(-1, Math.min(1, inputData[i]));
        int16Data[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      }

      // Create AudioData
      const audioData = new AudioData({
        format: 's16',
        sampleRate: this.audioSampleRate,
        numberOfFrames: int16Data.length,
        numberOfChannels: 1,
        timestamp: this.audioTimestamp,
        data: int16Data,
      });

      this.audioTimestamp += (int16Data.length / this.audioSampleRate) * 1_000_000;

      try {
        this.audioEncoder.encode(audioData);
      } catch (e) {
        console.error('Audio encode error:', e);
      }

      audioData.close();
    };

    this.mediaStreamSource.connect(scriptNode);
    scriptNode.connect(this.audioContext.destination);
  }

  private getVideoTimestampUs(nowMs: number): number {
    if (this.timelineStartedAtMs === null) {
      this.timelineStartedAtMs = nowMs;
      return 0;
    }

    return Math.max(0, Math.round((nowMs - this.timelineStartedAtMs - this.totalPausedMs) * 1000));
  }

  // Call this for each rendered frame with the canvas.
  // requestAnimationFrame can run at 60/120Hz, so timestamps must come from the
  // real recording clock instead of a synthetic frame counter.
  addFrame(canvas: HTMLCanvasElement | OffscreenCanvas): void {
    if (!this.isRecording || this.isPaused || !this.videoEncoder) return;

    const nowMs = performance.now();
    const timestamp = this.getVideoTimestampUs(nowMs);

    if (
      this.lastVideoTimestampUs >= 0 &&
      timestamp - this.lastVideoTimestampUs < this.frameIntervalUs * 0.85
    ) {
      this.droppedFrameCount++;
      return;
    }

    const safeTimestamp = Math.max(timestamp, this.lastVideoTimestampUs + 1);

    // Create VideoFrame from canvas
    const frame = new VideoFrame(canvas, {
      timestamp: safeTimestamp,
      duration: Math.round(this.frameIntervalUs),
    });

    // Encode the frame
    // First frame and every 2 seconds should be keyframes
    const keyFrame = this.frameCount === 0 || this.frameCount % (this.frameRate * 2) === 0;
    this.videoEncoder.encode(frame, { keyFrame });

    frame.close();
    this.lastVideoTimestampUs = safeTimestamp;
    this.frameCount++;
  }

  pause(): void {
    if (!this.isRecording || this.isPaused) return;
    this.isPaused = true;
    this.pausedAtMs = performance.now();
    console.log('[WebCodecsRecorder] Paused');
  }

  resume(): void {
    if (!this.isRecording || !this.isPaused) return;
    if (this.pausedAtMs !== null) {
      this.totalPausedMs += performance.now() - this.pausedAtMs;
      this.pausedAtMs = null;
    }
    this.isPaused = false;
    console.log('[WebCodecsRecorder] Resumed');
  }

  async stop(): Promise<Blob> {
    if (!this.isRecording) {
      throw new Error('Not recording');
    }

    this.isRecording = false;
    console.log('[WebCodecsRecorder] Stopping, frames:', this.frameCount, 'dropped:', this.droppedFrameCount);

    // Flush encoders
    if (this.videoEncoder) {
      await this.videoEncoder.flush();
      this.videoEncoder.close();
    }

    if (this.audioEncoder) {
      await this.audioEncoder.flush();
      this.audioEncoder.close();
    }

    // Clean up audio
    if (this.audioContext) {
      await this.audioContext.close();
    }

    // Finalize the muxer
    if (!this.muxer) {
      throw new Error('Muxer not initialized');
    }

    this.muxer.finalize();

    // Get the MP4 data
    const { buffer } = this.muxer.target;
    const blob = new Blob([buffer], { type: 'video/mp4' });

    console.log('[WebCodecsRecorder] Finished, size:', (blob.size / 1024 / 1024).toFixed(2), 'MB');

    return blob;
  }

  get recording(): boolean {
    return this.isRecording;
  }

  get paused(): boolean {
    return this.isPaused;
  }
}
