"use client";

import { useEffect, useRef, useCallback } from "react";

interface SSEOptions {
  onMessage: (data: unknown) => void;
  onError?: (error: Event) => void;
}

const MAX_RETRIES = 5;
const BASE_RETRY_DELAY_MS = 1_000;

export function useSSE(url: string | null, options: SSEOptions) {
  const esRef = useRef<EventSource | null>(null);
  const retriesRef = useRef(0);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (!url) return;

    esRef.current = new EventSource(url);

    esRef.current.onmessage = (e) => {
      retriesRef.current = 0;
      try {
        options.onMessage(JSON.parse(e.data));
      } catch {
        options.onMessage(e.data);
      }
    };

    esRef.current.onerror = (e) => {
      esRef.current?.close();
      options.onError?.(e);

      if (retriesRef.current < MAX_RETRIES) {
        const delay = BASE_RETRY_DELAY_MS * 2 ** retriesRef.current;
        retriesRef.current++;
        timeoutRef.current = setTimeout(connect, delay);
      }
    };
  }, [url, options]);

  useEffect(() => {
    connect();
    return () => {
      esRef.current?.close();
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [connect]);
}
