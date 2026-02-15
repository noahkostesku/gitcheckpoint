import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { createVoiceSocket } from "../lib/voiceSocket";

/**
 * Voice orb — fully hands-free AI voice conversation.
 *
 * One click anywhere to unlock browser audio, then Git auto-greets
 * and the conversation is continuous:
 *   Git speaks → listens → user speaks → silence → Git speaks → ...
 *
 * No tapping, no toggling. Git controls the conversation naturally.
 */
export default function VoiceOrb({
  threadId,
  onTranscript,
  onUiCommand,
  onStateUpdate,
  onMessage,
}) {
  // unlocking | listening | processing | speaking
  const [status, setStatus] = useState("unlocking");
  const [error, setError] = useState(null);
  const [wsConnected, setWsConnected] = useState(false);

  const socketRef = useRef(null);
  const canvasRef = useRef(null);
  const animFrameRef = useRef(null);
  const analyserRef = useRef(null);
  const micAnalyserRef = useRef(null);
  const statusRef = useRef(status);
  const stuckTimerRef = useRef(null);
  const gotAudioRef = useRef(false);
  const greetedRef = useRef(false);
  const audioUnlockedRef = useRef(false);

  useEffect(() => { statusRef.current = status; }, [status]);

  // ---- Stuck state recovery ----
  useEffect(() => {
    if (stuckTimerRef.current) clearTimeout(stuckTimerRef.current);
    if (status === "processing") {
      stuckTimerRef.current = setTimeout(() => {
        if (statusRef.current === "processing") {
          setStatus("listening");
        }
      }, 30000);
    }
    return () => {
      if (stuckTimerRef.current) clearTimeout(stuckTimerRef.current);
    };
  }, [status]);

  // ---- Send greeting to LLM ----
  function sendGreeting(socket) {
    if (greetedRef.current) return;
    greetedRef.current = true;
    socket.ensureAudioContext();
    socket.sendTranscriptDirect("Hey Git");
    setStatus("processing");
  }

  // ---- Unlock audio on first user gesture, then auto-greet ----
  useEffect(() => {
    function unlock() {
      if (audioUnlockedRef.current) return;
      audioUnlockedRef.current = true;

      // Create + resume AudioContext to satisfy browser autoplay policy
      try {
        const ctx = new AudioContext();
        ctx.resume().then(() => ctx.close());
      } catch {}

      // If WS is already connected, greet immediately
      if (socketRef.current && wsConnected) {
        sendGreeting(socketRef.current);
      }

      document.removeEventListener("click", unlock, true);
      document.removeEventListener("touchstart", unlock, true);
      document.removeEventListener("keydown", unlock, true);
    }

    document.addEventListener("click", unlock, true);
    document.addEventListener("touchstart", unlock, true);
    document.addEventListener("keydown", unlock, true);

    return () => {
      document.removeEventListener("click", unlock, true);
      document.removeEventListener("touchstart", unlock, true);
      document.removeEventListener("keydown", unlock, true);
    };
  }, [wsConnected]);

  // ---- Connect voice WebSocket on mount ----
  useEffect(() => {
    const socket = createVoiceSocket(threadId, {
      onOpen: () => {
        setWsConnected(true);
        // If audio already unlocked (user clicked before WS connected), greet now
        if (audioUnlockedRef.current) {
          setTimeout(() => sendGreeting(socket), 300);
        }
      },
      onClose: () => setWsConnected(false),
      onTranscript: (text) => {
        setStatus("processing");
        if (onTranscript) onTranscript(text);
      },
      onRouting: () => {},
      onResponseText: (content, done) => {
        if (content) {
          setStatus("speaking");
        }
        if (done) {
          if (content && onMessage) {
            onMessage({ role: "assistant", content });
          }
          // If no audio arrived, go to listening after a short delay
          if (!gotAudioRef.current) {
            setTimeout(() => {
              if (statusRef.current === "speaking" || statusRef.current === "processing") {
                setStatus("listening");
              }
            }, 2000);
          }
        }
      },
      onAudioChunk: () => {
        gotAudioRef.current = true;
        setStatus("speaking");
        if (socket && !analyserRef.current) {
          analyserRef.current = socket.getPlaybackAnalyser();
        }
      },
      onAudioDone: () => {},
      onPlaybackFinished: () => {
        analyserRef.current = null;
        gotAudioRef.current = false;
        setStatus("listening");
      },
      onSilenceDetected: () => {
        setStatus("processing");
      },
      onStateUpdate: (kind, data) => {
        if (onStateUpdate) onStateUpdate(kind, data);
      },
      onUiCommand: (action, params) => {
        if (onUiCommand) onUiCommand(action, params);
      },
      onReady: () => {},
      onError: (msg) => {
        // Audio conversion / no speech errors → just keep listening
        if (
          msg === "No speech detected" ||
          msg === "No audio received" ||
          msg.includes("Audio conversion failed") ||
          msg.includes("conversion failed")
        ) {
          if (statusRef.current !== "unlocking") {
            setStatus("listening");
          }
          return;
        }
        setError(msg);
        setTimeout(() => setError(null), 3000);
      },
    });

    socketRef.current = socket;
    return () => {
      socket.close();
      socketRef.current = null;
    };
  }, [threadId]);

  // ---- When status transitions to "listening", start recording ----
  useEffect(() => {
    if (status === "listening" && socketRef.current) {
      socketRef.current.startRecording();
    }
  }, [status]);

  // ---- Canvas animation ----
  useEffect(() => {
    if (!canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    const size = 220;
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
      const baseRadius = 75;

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

      const idlePulse = Math.sin(time * 0.6) * 2.5;
      const audioScale = amplitude * 18;
      const radius = baseRadius + idlePulse + audioScale;

      let c1, c2, c3;
      switch (status) {
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
        default: // unlocking
          c1 = "rgba(147, 197, 253, 0.6)";
          c2 = "rgba(219, 234, 254, 0.4)";
          c3 = "rgba(255, 255, 255, 0.25)";
      }

      const grad = ctx.createRadialGradient(
        cx - radius * 0.2, cy - radius * 0.3, radius * 0.1,
        cx, cy, radius
      );
      grad.addColorStop(0, c3);
      grad.addColorStop(0.5, c2);
      grad.addColorStop(1, c1);

      ctx.beginPath();
      const points = 64;
      for (let i = 0; i <= points; i++) {
        const angle = (i / points) * Math.PI * 2;
        const distort = (
          Math.sin(angle * 3 + time * 1.8) * (1.5 + amplitude * 7) +
          Math.sin(angle * 5 + time * 1.3) * (0.8 + amplitude * 3.5) +
          Math.cos(angle * 2 + time * 2.5) * (1.2 + amplitude * 5)
        );
        const r = radius + distort;
        const x = cx + Math.cos(angle) * r;
        const y = cy + Math.sin(angle) * r;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.fillStyle = grad;
      ctx.fill();

      const innerGrad = ctx.createRadialGradient(
        cx - radius * 0.15, cy - radius * 0.2, 0,
        cx, cy, radius * 0.65
      );
      innerGrad.addColorStop(0, `rgba(255, 255, 255, ${0.35 + amplitude * 0.3})`);
      innerGrad.addColorStop(1, "rgba(255, 255, 255, 0)");
      ctx.fillStyle = innerGrad;
      ctx.fill();

      animFrameRef.current = requestAnimationFrame(draw);
    }

    draw();
    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [status]);

  // ---- Mic analyser for orb animation ----
  useEffect(() => {
    if (status === "listening" && socketRef.current) {
      const timer = setTimeout(() => {
        if (socketRef.current) {
          const analyser = socketRef.current.getSilenceAnalyser();
          if (analyser) micAnalyserRef.current = analyser;
        }
      }, 300);
      return () => clearTimeout(timer);
    } else {
      micAnalyserRef.current = null;
    }
  }, [status]);

  return (
    <div className="flex flex-col items-center justify-center gap-4">
      <motion.div
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: "spring", damping: 20, stiffness: 200 }}
      >
        <canvas
          ref={canvasRef}
          className="drop-shadow-lg"
          style={{
            filter: status === "speaking"
              ? "drop-shadow(0 0 20px rgba(37,99,235,0.3))"
              : "drop-shadow(0 0 10px rgba(147,197,253,0.2))",
          }}
        />
      </motion.div>

      <div className="text-center max-w-md px-4 min-h-[50px]">
        <AnimatePresence mode="wait">
          <motion.div
            key={status}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            {!wsConnected ? (
              <p className="text-sm text-text-muted">Connecting...</p>
            ) : status === "unlocking" ? (
              <>
                <p className="text-lg font-semibold" style={{ color: "#111827" }}>Git</p>
                <p className="text-xs" style={{ color: "#9ca3af" }}>click anywhere to start</p>
              </>
            ) : (
              <p className="text-lg font-semibold" style={{ color: "#111827" }}>Git</p>
            )}
          </motion.div>
        </AnimatePresence>
        {error && <p className="mt-2 text-xs text-error">{error}</p>}
      </div>
    </div>
  );
}
