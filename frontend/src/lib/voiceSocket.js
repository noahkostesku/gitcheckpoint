/**
 * Voice WebSocket client — handles bidirectional audio streaming
 * with the /ws/voice endpoint. Manages recording, playback, and
 * automatic silence detection to end recording.
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
    onSilenceDetected,
  } = callbacks;

  const apiUrl = import.meta.env.VITE_API_URL || "";
  let wsUrl;
  if (apiUrl) {
    wsUrl = apiUrl.replace(/^http/, "ws") + "/ws/voice";
  } else {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    wsUrl = `${protocol}//${window.location.host}/ws/voice`;
  }
  const ws = new WebSocket(wsUrl);

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

  // Silence detection state
  let silenceAnalyser = null;
  let silenceInterval = null;
  let speechDetected = false;
  let silenceStart = 0;
  const SILENCE_THRESHOLD = 12;   // amplitude level below which = silence
  const SILENCE_DURATION = 1500;  // ms of silence before auto-stop
  const SPEECH_THRESHOLD = 15;    // amplitude level above which = speech

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

  // ---- Silence detection ----
  function startSilenceDetection() {
    if (!mediaStream || !audioContext) return;

    try {
      const source = audioContext.createMediaStreamSource(mediaStream);
      silenceAnalyser = audioContext.createAnalyser();
      silenceAnalyser.fftSize = 256;
      source.connect(silenceAnalyser);
    } catch {
      return;
    }

    speechDetected = false;
    silenceStart = 0;
    const dataArray = new Uint8Array(silenceAnalyser.frequencyBinCount);

    silenceInterval = setInterval(() => {
      if (!silenceAnalyser) return;
      silenceAnalyser.getByteFrequencyData(dataArray);
      const avg = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;

      if (avg > SPEECH_THRESHOLD) {
        speechDetected = true;
        silenceStart = 0;
      } else if (speechDetected && avg < SILENCE_THRESHOLD) {
        if (!silenceStart) {
          silenceStart = Date.now();
        } else if (Date.now() - silenceStart > SILENCE_DURATION) {
          // Silence detected after speech — auto-stop
          stopSilenceDetection();
          stopRecording();
          if (onSilenceDetected) onSilenceDetected();
        }
      }
    }, 100);
  }

  function stopSilenceDetection() {
    if (silenceInterval) {
      clearInterval(silenceInterval);
      silenceInterval = null;
    }
    silenceAnalyser = null;
    speechDetected = false;
    silenceStart = 0;
  }

  // WebSocket handlers
  ws.onopen = () => {
    clearTimeout(wsTimeout);
    if (onOpen) onOpen();
  };

  ws.onclose = () => {
    clearTimeout(wsTimeout);
    stopSilenceDetection();
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
          onPlaybackComplete = () => {
            onPlaybackComplete = null;
            if (onPlaybackFinished) onPlaybackFinished();
          };
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
        stopSilenceDetection();
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "stop_recording" }));
        }
        if (mediaStream) {
          mediaStream.getTracks().forEach((t) => t.stop());
          mediaStream = null;
        }
      };

      mediaRecorder.start(250);

      // Start monitoring for silence after recording begins
      ensureAudioContext();
      startSilenceDetection();
    } catch (err) {
      if (onError) onError("Microphone access denied");
    }
  }

  function stopRecording() {
    stopSilenceDetection();
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
      mediaRecorder = null;
    }
  }

  function stopPlayback() {
    audioQueue = [];
    isPlaying = false;
    onPlaybackComplete = null;
  }

  function sendUiCommand(action, params = {}) {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "ui_command", action, params }));
    }
  }

  function sendTranscriptDirect(text) {
    console.log("[voiceSocket] sendTranscriptDirect, readyState:", ws.readyState, "OPEN:", WebSocket.OPEN);
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "transcript_direct", text }));
      console.log("[voiceSocket] sent transcript_direct:", text);
    } else {
      console.warn("[voiceSocket] WS not open, cannot send transcript");
    }
  }

  function getPlaybackAnalyser() {
    ensureAudioContext();
    return playbackAnalyser;
  }

  function getSilenceAnalyser() {
    return silenceAnalyser;
  }

  function close() {
    stopSilenceDetection();
    stopRecording();
    if (audioContext) audioContext.close();
    ws.close();
  }

  return {
    startRecording,
    stopRecording,
    stopPlayback,
    sendUiCommand,
    sendTranscriptDirect,
    getPlaybackAnalyser,
    getSilenceAnalyser,
    ensureAudioContext,
    close,
    get readyState() { return ws.readyState; },
    get isRecording() { return mediaRecorder?.state === "recording"; },
    get mediaStream() { return mediaStream; },
  };
}
