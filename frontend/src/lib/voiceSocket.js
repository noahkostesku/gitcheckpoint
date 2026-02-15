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
    onPlaybackFinished,
    onStateUpdate,
    onUiCommand,
    onReady,
    onError,
    onOpen,
    onClose,
  } = callbacks;

  const apiUrl = import.meta.env.VITE_API_URL || "";
  let wsUrl;
  if (apiUrl) {
    // External backend — derive WebSocket URL from API URL
    wsUrl = apiUrl.replace(/^http/, "ws") + "/ws/voice";
  } else {
    // Same origin (local dev)
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    wsUrl = `${protocol}//${window.location.host}/ws/voice`;
  }
  const ws = new WebSocket(wsUrl);

  // Close if connection doesn't open within 10s
  const wsTimeout = setTimeout(() => {
    if (ws.readyState !== WebSocket.OPEN) {
      ws.close();
      if (onError) onError("Voice connection timed out");
    }
  }, 10000);

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
    clearTimeout(wsTimeout);
    if (onOpen) onOpen();
  };

  ws.onclose = () => {
    clearTimeout(wsTimeout);
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
          // Wait for all queued audio to finish playing before notifying
          onPlaybackComplete = () => {
            onPlaybackComplete = null;
            if (onPlaybackFinished) onPlaybackFinished();
            if (continuous) {
              setTimeout(() => startRecording(), 300);
            }
          };
          // If nothing is queued/playing, fire immediately
          if (!isPlaying) {
            onPlaybackComplete();
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
