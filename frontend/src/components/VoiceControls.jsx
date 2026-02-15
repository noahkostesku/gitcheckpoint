import { useState, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Mic, MicOff, Volume2, Loader2 } from "lucide-react";
import { api } from "../lib/api";

export default function VoiceControls({ threadId, onTranscript }) {
  const [status, setStatus] = useState("idle"); // idle | listening | processing | speaking
  const [error, setError] = useState(null);
  const mediaRef = useRef(null);
  const recorderRef = useRef(null);

  const statusLabels = {
    idle: "",
    listening: "Listening...",
    processing: "Processing...",
    speaking: "Speaking...",
  };

  const statusColors = {
    idle: "text-gray-600",
    listening: "text-red",
    processing: "text-amber",
    speaking: "text-neon",
  };

  async function toggleRecording() {
    if (status === "listening") {
      // Stop recording
      if (recorderRef.current) {
        recorderRef.current.stop();
        recorderRef.current = null;
      }
      if (mediaRef.current) {
        mediaRef.current.getTracks().forEach((t) => t.stop());
        mediaRef.current = null;
      }
      // Don't set idle here — onstop handler will manage state
      return;
    }

    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRef.current = stream;

      const recorder = new MediaRecorder(stream);
      recorderRef.current = recorder;
      const chunks = [];

      recorder.ondataavailable = (e) => chunks.push(e.data);
      recorder.onstop = async () => {
        setStatus("processing");
        try {
          const audioBlob = new Blob(chunks, { type: "audio/webm" });
          const data = await api.transcribe(audioBlob);
          const transcript = data.transcript;
          if (transcript && onTranscript) {
            onTranscript(transcript);
          }
        } catch (err) {
          setError(err.message || "Transcription failed");
        }
        setStatus("idle");
      };

      recorder.start();
      setStatus("listening");
    } catch (err) {
      setError("Microphone access denied");
      setStatus("idle");
    }
  }

  return (
    <div className="flex items-center gap-2">
      {/* Mic button */}
      <motion.button
        onClick={toggleRecording}
        whileTap={{ scale: 0.9 }}
        className={`relative p-2 rounded-full transition-all ${
          status === "listening"
            ? "bg-red/20 text-red"
            : status === "processing"
              ? "bg-amber/20 text-amber"
              : "bg-terminal-border text-gray-500 hover:text-gray-300 hover:bg-terminal-border-light"
        }`}
      >
        {status === "listening" ? <MicOff size={14} /> : <Mic size={14} />}

        {/* Pulsing ring when listening */}
        {status === "listening" && (
          <motion.div
            className="absolute inset-0 rounded-full border-2 border-red"
            animate={{ scale: [1, 1.3, 1], opacity: [0.5, 0, 0.5] }}
            transition={{ duration: 1.5, repeat: Infinity }}
          />
        )}
      </motion.button>

      {/* Status text */}
      <AnimatePresence mode="wait">
        {status !== "idle" && (
          <motion.span
            key={status}
            initial={{ opacity: 0, x: -5 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 5 }}
            className={`text-[10px] font-mono ${statusColors[status]}`}
          >
            {status === "processing" && (
              <Loader2 size={8} className="inline animate-spin mr-1" />
            )}
            {status === "speaking" && (
              <Volume2 size={8} className="inline mr-1" />
            )}
            {statusLabels[status]}
          </motion.span>
        )}
      </AnimatePresence>

      {/* Error */}
      {error && (
        <span className="text-[10px] font-mono text-red">{error}</span>
      )}
    </div>
  );
}
