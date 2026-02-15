import { useState, useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ToggleLeft, ToggleRight, Mic } from "lucide-react";
import { createVoiceSocket } from "../lib/voiceSocket";

const WAKE_PHRASES = ["hey git", "hey gitcheckpoint", "hey git checkpoint"];
const DEACTIVATE_PHRASES = [
  "thanks git", "thank you git", "goodbye git",
  "that's all git", "thats all git", "go to sleep",
];

/**
 * Voice orb — always-visible animated sphere in the center of the page.
 * Named "Git". Supports passive wake word detection ("Hey Git") and
 * active voice conversation.
 *
 * States: passive | idle | listening | processing | speaking
 *  - passive: small, dimmed, listening for wake word only (client-side)
 *  - idle: full size, waiting for click or wake word activation
 *  - listening: actively recording audio for STT
 *  - processing: waiting for LLM response
 *  - speaking: playing TTS audio
 */
export default function VoiceOrb({
  threadId,
  onTranscript,
  onUiCommand,
  onStateUpdate,
  onMessage,
  onDeactivate,
  alwaysListening = false,
}) {
  // passive | idle | listening | processing | speaking
  const [status, setStatus] = useState(alwaysListening ? "passive" : "idle");
  const [continuous, setContinuous] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [responseText, setResponseText] = useState("");
  const [error, setError] = useState(null);
  const [wsConnected, setWsConnected] = useState(false);

  const socketRef = useRef(null);
  const canvasRef = useRef(null);
  const animFrameRef = useRef(null);
  const analyserRef = useRef(null);
  const micAnalyserRef = useRef(null);
  const recognitionRef = useRef(null);
  const statusRef = useRef(status);

  // Keep statusRef in sync for use in callbacks
  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  // ---- Activation chime via Web Audio API ----
  const playActivationChime = useCallback(() => {
    try {
      const ctx = new AudioContext();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(440, ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(880, ctx.currentTime + 0.05);
      gain.gain.setValueAtTime(0.15, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.1);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.1);
    } catch {}
  }, []);

  // ---- Wake word detection via Web Speech API ----
  const startPassiveListening = useCallback(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return null;

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    recognition.onresult = (event) => {
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const text = event.results[i][0].transcript.toLowerCase().trim();

        const isWakeWord = WAKE_PHRASES.some((phrase) => text.includes(phrase));
        if (isWakeWord) {
          recognition.stop();
          playActivationChime();

          // Extract command after wake phrase
          let command = text;
          for (const phrase of WAKE_PHRASES) {
            command = command.replace(phrase, "").trim();
          }
          // Remove leading comma/period from "hey git, ..."
          command = command.replace(/^[,.\s]+/, "").trim();

          // Activate orb
          setStatus("listening");
          setTranscript("");
          setResponseText("");

          if (command.length > 3 && socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
            // User said a command inline — send it directly as text
            socketRef.current.sendTranscriptDirect(command);
            setTranscript(command);
            setStatus("processing");
            if (onTranscript) onTranscript(command);
          } else if (socketRef.current) {
            // No command — start recording
            socketRef.current.startRecording();
          }
          return;
        }
      }
    };

    recognition.onend = () => {
      // Restart if still in passive mode
      if (statusRef.current === "passive") {
        try { recognition.start(); } catch {}
      }
    };

    recognition.onerror = () => {
      // Restart on error if still passive
      if (statusRef.current === "passive") {
        setTimeout(() => {
          try { recognition.start(); } catch {}
        }, 1000);
      }
    };

    try { recognition.start(); } catch {}
    return recognition;
  }, [playActivationChime, onTranscript]);

  // ---- Manage passive listening lifecycle ----
  useEffect(() => {
    if (status === "passive" && alwaysListening) {
      const rec = startPassiveListening();
      recognitionRef.current = rec;
      return () => {
        if (rec) {
          try { rec.stop(); } catch {}
        }
        recognitionRef.current = null;
      };
    }
  }, [status, alwaysListening, startPassiveListening]);

  // When alwaysListening changes, update status
  useEffect(() => {
    if (alwaysListening && status === "idle") {
      setStatus("passive");
    } else if (!alwaysListening && status === "passive") {
      setStatus("idle");
      if (recognitionRef.current) {
        try { recognitionRef.current.stop(); } catch {}
        recognitionRef.current = null;
      }
    }
  }, [alwaysListening]);

  // ---- Connect voice WebSocket on mount ----
  useEffect(() => {
    const socket = createVoiceSocket(threadId, {
      onOpen: () => setWsConnected(true),
      onClose: () => setWsConnected(false),
      onTranscript: (text) => {
        // Check for deactivation phrases
        const lower = text.toLowerCase().trim();
        const isDeactivate = DEACTIVATE_PHRASES.some((p) => lower.includes(p));

        setTranscript(text);
        setStatus("processing");
        if (onTranscript) onTranscript(text);

        if (isDeactivate) {
          // Will be handled by server returning deactivate response,
          // but we can flag it here
          socket._deactivateRequested = true;
        }
      },
      onRouting: (agent, message) => {
        setResponseText(message);
      },
      onResponseText: (content, done) => {
        if (content) {
          setResponseText((prev) => prev + content);
          setStatus("speaking");
        }
        if (done) {
          setResponseText((prev) => {
            if (prev && onMessage) {
              onMessage({ role: "assistant", content: prev });
            }
            return "";
          });
        }
      },
      onAudioChunk: () => {
        setStatus("speaking");
        if (socket && !analyserRef.current) {
          analyserRef.current = socket.getPlaybackAnalyser();
        }
      },
      onAudioDone: () => {
        // Check if deactivation was requested
        if (socket._deactivateRequested) {
          socket._deactivateRequested = false;
          if (alwaysListening) {
            setStatus("passive");
          } else {
            setStatus("idle");
          }
          analyserRef.current = null;
          return;
        }

        if (continuous) {
          setStatus("listening");
        } else if (alwaysListening) {
          setStatus("passive");
        } else {
          setStatus("idle");
        }
        analyserRef.current = null;
      },
      onStateUpdate: (kind, data) => {
        if (onStateUpdate) onStateUpdate(kind, data);
      },
      onUiCommand: (action, params) => {
        if (onUiCommand) onUiCommand(action, params);
      },
      onReady: () => {
        if (continuous) return;
        if (alwaysListening) {
          setStatus("passive");
        } else {
          setStatus("idle");
        }
      },
      onError: (msg) => {
        setError(msg);
        if (alwaysListening) {
          setStatus("passive");
        } else {
          setStatus("idle");
        }
        setTimeout(() => setError(null), 3000);
      },
    });

    socketRef.current = socket;
    return () => {
      socket.close();
      socketRef.current = null;
    };
  }, [threadId]);

  // ---- Canvas animation ----
  useEffect(() => {
    if (!canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    const isPassive = status === "passive";
    const size = isPassive ? 160 : 220;
    canvas.width = size * 2;
    canvas.height = size * 2;
    canvas.style.width = `${size}px`;
    canvas.style.height = `${size}px`;
    ctx.scale(2, 2);

    let time = 0;

    function draw() {
      time += 0.016;
      ctx.clearRect(0, 0, size, size);

      const cx = size / 2;
      const cy = size / 2;
      const baseRadius = isPassive ? 50 : 75;

      // Get audio amplitude
      let amplitude = 0;
      const analyser =
        status === "listening" ? micAnalyserRef.current :
        status === "speaking" ? analyserRef.current : null;

      if (analyser) {
        const data = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteFrequencyData(data);
        const avg = data.reduce((a, b) => a + b, 0) / data.length;
        amplitude = avg / 255;
      }

      const idlePulse = Math.sin(time * (isPassive ? 0.4 : 0.6)) * (isPassive ? 1.5 : 2.5);
      const audioScale = amplitude * 18;
      const radius = baseRadius + idlePulse + audioScale;

      // Colors based on status
      let c1, c2, c3;
      switch (status) {
        case "passive":
          c1 = "rgba(191, 219, 254, 0.35)";
          c2 = "rgba(219, 234, 254, 0.25)";
          c3 = "rgba(255, 255, 255, 0.15)";
          break;
        case "listening":
          c1 = `rgba(59, 130, 246, ${0.85 + amplitude * 0.15})`;
          c2 = `rgba(147, 197, 253, ${0.65 + amplitude * 0.35})`;
          c3 = `rgba(219, 234, 254, ${0.5 + amplitude * 0.4})`;
          break;
        case "processing":
          c1 = "rgba(156, 163, 175, 0.7)";
          c2 = "rgba(209, 213, 219, 0.5)";
          c3 = "rgba(243, 244, 246, 0.35)";
          break;
        case "speaking":
          c1 = `rgba(37, 99, 235, ${0.8 + amplitude * 0.2})`;
          c2 = `rgba(96, 165, 250, ${0.6 + amplitude * 0.4})`;
          c3 = `rgba(255, 255, 255, ${0.5 + amplitude * 0.5})`;
          break;
        default: // idle
          c1 = "rgba(147, 197, 253, 0.6)";
          c2 = "rgba(219, 234, 254, 0.4)";
          c3 = "rgba(255, 255, 255, 0.25)";
      }

      // Radial gradient
      const grad = ctx.createRadialGradient(
        cx - radius * 0.2, cy - radius * 0.3, radius * 0.1,
        cx, cy, radius
      );
      grad.addColorStop(0, c3);
      grad.addColorStop(0.5, c2);
      grad.addColorStop(1, c1);

      // Organic distortion (less in passive mode)
      ctx.beginPath();
      const points = 64;
      const distortScale = isPassive ? 0.4 : 1;
      for (let i = 0; i <= points; i++) {
        const angle = (i / points) * Math.PI * 2;
        const distort = (
          Math.sin(angle * 3 + time * 1.8) * (1.5 + amplitude * 7) +
          Math.sin(angle * 5 + time * 1.3) * (0.8 + amplitude * 3.5) +
          Math.cos(angle * 2 + time * 2.5) * (1.2 + amplitude * 5)
        ) * distortScale;
        const r = radius + distort;
        const x = cx + Math.cos(angle) * r;
        const y = cy + Math.sin(angle) * r;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.fillStyle = grad;
      ctx.fill();

      // Inner glow
      const innerGrad = ctx.createRadialGradient(
        cx - radius * 0.15, cy - radius * 0.2, 0,
        cx, cy, radius * 0.65
      );
      innerGrad.addColorStop(0, `rgba(255, 255, 255, ${(isPassive ? 0.15 : 0.35) + amplitude * 0.3})`);
      innerGrad.addColorStop(1, "rgba(255, 255, 255, 0)");
      ctx.fillStyle = innerGrad;
      ctx.fill();

      // Standby LED dot in passive mode
      if (isPassive) {
        const dotAlpha = 0.4 + Math.sin(time * 2) * 0.3;
        ctx.beginPath();
        ctx.arc(cx, cy + baseRadius + 16, 3, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(59, 130, 246, ${dotAlpha})`;
        ctx.fill();
      }

      animFrameRef.current = requestAnimationFrame(draw);
    }

    draw();
    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [status]);

  // ---- Mic analyser ----
  useEffect(() => {
    if (status === "listening" && socketRef.current) {
      const timer = setTimeout(() => {
        if (socketRef.current) {
          socketRef.current.ensureAudioContext();
          const stream = socketRef.current.mediaStream;
          if (stream) {
            try {
              const ctx = new AudioContext();
              const source = ctx.createMediaStreamSource(stream);
              const analyser = ctx.createAnalyser();
              analyser.fftSize = 256;
              source.connect(analyser);
              micAnalyserRef.current = analyser;
            } catch {}
          }
        }
      }, 200);
      return () => clearTimeout(timer);
    } else {
      micAnalyserRef.current = null;
    }
  }, [status]);

  // ---- Click handler ----
  const handleOrbClick = useCallback(() => {
    if (!socketRef.current || !wsConnected) return;

    if (status === "passive") {
      // Activate from passive
      playActivationChime();
      setTranscript("");
      setResponseText("");
      socketRef.current.startRecording();
      setStatus("listening");
    } else if (status === "listening") {
      socketRef.current.stopRecording();
      setStatus("processing");
    } else if (status === "idle" || status === "speaking") {
      setTranscript("");
      setResponseText("");
      socketRef.current.startRecording();
      setStatus("listening");
    }
  }, [status, wsConnected, playActivationChime]);

  const toggleContinuous = useCallback(() => {
    const next = !continuous;
    setContinuous(next);
    if (socketRef.current) socketRef.current.setContinuousMode(next);
  }, [continuous]);

  // ---- Labels ----
  const isActive = status !== "passive" && status !== "idle";

  return (
    <div className="flex flex-col items-center justify-center gap-4">
      {/* The Orb */}
      <motion.div
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{
          scale: status === "passive" ? 0.7 : 1,
          opacity: status === "passive" ? 0.7 : 1,
        }}
        transition={{ type: "spring", damping: 20, stiffness: 200 }}
        className="cursor-pointer"
        onClick={handleOrbClick}
      >
        <canvas
          ref={canvasRef}
          className="drop-shadow-lg"
          style={{
            filter: status === "speaking"
              ? "drop-shadow(0 0 20px rgba(37,99,235,0.3))"
              : status === "passive"
                ? "drop-shadow(0 0 6px rgba(147,197,253,0.1))"
                : "drop-shadow(0 0 10px rgba(147,197,253,0.2))",
          }}
        />
      </motion.div>

      {/* Name + status area */}
      <div className="text-center max-w-md px-4 min-h-[70px]">
        <AnimatePresence mode="wait">
          {/* Response text while speaking */}
          {responseText && (
            <motion.div
              key="response"
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
            >
              <p className="text-lg font-semibold text-text-primary mb-1" style={{ fontWeight: 600 }}>
                Git
              </p>
              <p className="text-sm text-text-primary leading-relaxed">
                {responseText}
              </p>
            </motion.div>
          )}

          {/* Transcript while processing */}
          {!responseText && transcript && status === "processing" && (
            <motion.div
              key="transcript"
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
            >
              <p className="text-lg font-semibold text-text-primary mb-1" style={{ fontWeight: 600 }}>
                Thinking...
              </p>
              <p className="text-sm text-text-secondary italic">
                &ldquo;{transcript}&rdquo;
              </p>
            </motion.div>
          )}

          {/* Status labels when no response/transcript */}
          {!responseText && !(transcript && status === "processing") && (
            <motion.div
              key="status"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              {!wsConnected ? (
                <p className="text-sm text-text-muted">Connecting...</p>
              ) : status === "passive" ? (
                <>
                  <div className="flex items-center justify-center gap-1.5 mb-1">
                    <p className="text-lg font-semibold" style={{ color: "#111827", fontWeight: 600 }}>
                      Git
                    </p>
                    <Mic size={12} className="text-text-muted" />
                  </div>
                  <p className="text-xs" style={{ color: "#9ca3af" }}>
                    Say &ldquo;Hey Git&rdquo; to start
                  </p>
                </>
              ) : status === "listening" ? (
                <p className="text-lg font-semibold" style={{ color: "#111827", fontWeight: 600 }}>
                  Listening...
                </p>
              ) : status === "speaking" ? (
                <p className="text-lg font-semibold" style={{ color: "#111827", fontWeight: 600 }}>
                  Git
                </p>
              ) : (
                /* idle */
                <>
                  <p className="text-lg font-semibold" style={{ color: "#111827", fontWeight: 600 }}>
                    Git
                  </p>
                  <p className="text-xs" style={{ color: "#9ca3af" }}>
                    your conversation copilot
                  </p>
                </>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {error && (
          <p className="mt-2 text-xs text-error">{error}</p>
        )}
      </div>

      {/* Continuous mode toggle */}
      {status !== "passive" && (
        <button
          onClick={toggleContinuous}
          className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium transition-all"
          style={{
            color: continuous ? "#2563eb" : "#9ca3af",
            backgroundColor: continuous ? "#eff6ff" : "#f9fafb",
          }}
        >
          {continuous ? <ToggleRight size={14} /> : <ToggleLeft size={14} />}
          Continuous
        </button>
      )}
    </div>
  );
}
