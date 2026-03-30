// NeuralClaw Desktop — Backend Health Hook
// Polls the Dashboard server at :8080/health

import { useEffect, useRef } from 'react';
import { useAppStore } from '../store/appStore';
import { getHealth } from '../lib/api';
import { HEALTH_POLL_INTERVAL } from '../lib/constants';

export function useHealth() {
  const { setConnectionStatus, setBackendInfo } = useAppStore();
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const poll = async () => {
      try {
        const health = await getHealth();
        if (health.status === 'healthy') {
          setConnectionStatus('connected');
          setBackendInfo(health.version || '1.0.0', 0);
        }
      } catch {
        // Don't override WS-based connection status if WS is connected
        // Only set disconnected if we're not connected via WS either
      }
    };

    poll();
    intervalRef.current = setInterval(poll, HEALTH_POLL_INTERVAL);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [setConnectionStatus, setBackendInfo]);
}
