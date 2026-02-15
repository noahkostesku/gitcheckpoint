/**
 * Voice WebSocket client — handles bidirectional audio streaming
 * with the /ws/voice endpoint. Manages recording, playback, and
 * continuous conversation mode.
 */

export function createVoiceSocket(threadId, callbacks = {}) {
  const {
    onTranscript,
    onRouting,
    onResponseText,
    onAudioChunk,
    onAudioDone,
    onStateUpdate,
    onUiCommand,
    onReady,
    onError,
    onOpen,
    onClose,
  } = callbacks;

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${protocol}//${window.location.host}/ws/voice`);

  // Audio playback via Web Audio API
  let audioContext = null;
  let audioQueue = [];
  let isPlaying = false;
  let playbackAnalyser = null;
  let onPlaybackComplete = null;

  // Recording state
  let mediaStream = null;
  let mediaRecorder = null;
  let continuous = false;

  function ensureAudioContext() {
    if (!audioContext || audioContext.state === "closed") {
      audioContext = new AudioContext({ sampleRate: 24000 });
    }
    if (audioContext.state === "suspended") {
      audioContext.resume();
    }
    if (!playbackAnalyser) {
      playbackAnalyser = audioContext.createAnalyser();
      playbackAnalyser.fftSize = 256;
      playbackAnalyser.connect(audioContext.destination);
    }
    return audioContext;
  }

  function playNextChunk() {
    if (audioQueue.length === 0) {
      isPlaying = false;
      if (onPlaybackComplete) onPlaybackComplete();
      return;
    }

    isPlaying = true;
    const audioData = audioQueue.shift();
    const ctx = ensureAudioContext();

    // Decode the audio data (WAV bytes from TTS)
    ctx.decodeAudioData(
      audioData.buffer.slice(0),
      (buffer) => {
        const source = ctx.createBufferSource();
        source.buffer = buffer;
        source.connect(playbackAnalyser);
        source.onended = playNextChunk;
        source.start();
      },
      (err) => {
        console.warn("Audio decode failed:", err);
        playNextChunk();
      }
    );
  }

  function queueAudio(base64Data) {
    const binary = atob(base64Data);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    audioQueue.push(bytes);
    if (!isPlaying) playNextChunk();
  }

  // WebSocket message handler
  ws.onopen = () => {
    if (onOpen) onOpen();
  };

  ws.onclose = () => {
    if (onClose) onClose();
  };

  ws.onerror = () => {
    if (onError) onError("Voice WebSocket connection error");
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      switch (data.type) {
        case "transcript":
          if (onTranscript) onTranscript(data.text);
          break;
        case "agent_routing":
          if (onRouting) onRouting(data.agent, data.message);
          break;
        case "response_text":
          if (onResponseText) onResponseText(data.content, data.done);
          break;
        case "audio_chunk":
          queueAudio(data.data);
          if (onAudioChunk) onAudioChunk(data.sequence);
          break;
        case "audio_done":
          if (onAudioDone) onAudioDone();
          // In continuous mode, auto-resume after playback finishes
          if (continuous) {
            onPlaybackComplete = () => {
              onPlaybackComplete = null;
              setTimeout(() => startRecording(), 300);
            };
            // If nothing is playing, trigger immediately
            if (!isPlaying) {
              onPlaybackComplete();
            }
          }
          break;
        case "state_update":
          if (onStateUpdate) onStateUpdate(data.kind, data.data);
          break;
        case "ui_command":
          if (onUiCommand) onUiCommand(data.action, data.params);
          break;
        case "ready_for_input":
          if (onReady) onReady();
          break;
        case "error":
          if (onError) onError(data.message);
          break;
      }
    } catch {
      // non-JSON, ignore
    }
  };

  async function startRecording() {
    if (ws.readyState !== WebSocket.OPEN) return;

    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorder = new MediaRecorder(mediaStream, {
        mimeType: MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
          ? "audio/webm;codecs=opus"
          : "audio/webm",
      });

      // Tell server we're starting
      ws.send(JSON.stringify({
        type: "start_recording",
        thread_id: threadId,
        sample_rate: 16000,
      }));

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0 && ws.readyState === WebSocket.OPEN) {
          e.data.arrayBuffer().then((buf) => ws.send(buf));
        }
      };

      mediaRecorder.onstop = () => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "stop_recording" }));
        }
        // Release mic tracks
        if (mediaStream) {
          mediaStream.getTracks().forEach((t) => t.stop());
          mediaStream = null;
        }
      };

      // Record in 250ms chunks
      mediaRecorder.start(250);
    } catch (err) {
      if (onError) onError("Microphone access denied");
    }
  }

  function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
      mediaRecorder = null;
    }
  }

  function setContinuousMode(enabled) {
    continuous = enabled;
  }

  function sendUiCommand(action, params = {}) {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "ui_command", action, params }));
    }
  }

  function sendTranscriptDirect(text) {
    // Send a pre-transcribed text command (from wake word detection)
    // instead of audio — the server processes it as if STT returned this text
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "transcript_direct", text }));
    }
  }

  function getPlaybackAnalyser() {
    ensureAudioContext();
    return playbackAnalyser;
  }

  function getMicAnalyser() {
    if (!mediaStream || !audioContext) return null;
    const source = audioContext.createMediaStreamSource(mediaStream);
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    return analyser;
  }

  function close() {
    stopRecording();
    if (audioContext) audioContext.close();
    ws.close();
  }

  return {
    startRecording,
    stopRecording,
    setContinuousMode,
    sendUiCommand,
    sendTranscriptDirect,
    getPlaybackAnalyser,
    getMicAnalyser,
    ensureAudioContext,
    close,
    get readyState() { return ws.readyState; },
    get isRecording() { return mediaRecorder?.state === "recording"; },
    get isContinuous() { return continuous; },
    get mediaStream() { return mediaStream; },
  };
}
