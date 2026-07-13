import { useEffect, useRef, useState } from "react";

// Single auto-reconnecting WebSocket shared by all subscribers.
let socket = null;
const listeners = new Set();

function ensureSocket() {
  if (socket && socket.readyState <= WebSocket.OPEN) return;
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${window.location.host}/ws/events`);
  socket.onmessage = (message) => {
    try {
      const event = JSON.parse(message.data);
      listeners.forEach((fn) => fn(event));
    } catch {
      /* ignore malformed frames */
    }
  };
  socket.onclose = () => {
    socket = null;
    setTimeout(() => listeners.size && ensureSocket(), 2000);
  };
}

/**
 * Subscribe to pipeline events.
 * @param {string} type - event type: "stats" | "live_status" | "face_captured"
 * @param {(data: object) => void} handler
 */
export function useEvent(type, handler) {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(() => {
    const listener = (event) => {
      if (event.type === type) handlerRef.current(event.data);
    };
    listeners.add(listener);
    ensureSocket();
    return () => listeners.delete(listener);
  }, [type]);
}

/** Convenience: keep the latest payload of an event type in state. */
export function useEventState(type, initial = null) {
  const [data, setData] = useState(initial);
  useEvent(type, setData);
  return data;
}
