export function createChatSocket(threadId, { onToken, onDone, onError }) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${protocol}//${window.location.host}/ws/chat`);

  ws.onopen = () => {
    ws.send(threadId);
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === "token" && onToken) onToken(data.content);
      if (data.type === "done" && onDone) onDone();
      if (data.type === "error" && onError) onError(data.content);
    } catch {
      // non-JSON message, ignore
    }
  };

  ws.onerror = () => {
    if (onError) onError("WebSocket connection error");
  };

  return {
    send: (message) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(message);
    },
    close: () => ws.close(),
    get readyState() { return ws.readyState; },
  };
}
