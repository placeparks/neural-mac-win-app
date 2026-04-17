// NeuralClaw Desktop - Backend Health Hook
// Polls the dashboard and the local runtime state so startup does not get
// mislabeled as a hard disconnect.

import { useEffect, useRef } from 'react';
import { useAppStore } from '../store/appStore';
import { getBackendRuntimeStatus, getHealth } from '../lib/api';
import { wsManager } from '../lib/ws';
import { HEALTH_POLL_INTERVAL } from '../lib/constants';

const MAX_BACKOFF = 30000;

export function useHealth() {
  const { setConnectionStatus, setBackendInfo, pushToast } = useAppStore();
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const failCountRef = useRef<number>(0);
  const stoppedRef = useRef<boolean>(false);
  const lastRuntimeErrorRef = useRef<string | null>(null);

  useEffect(() => {
    stoppedRef.current = false;

    const schedule = (delay: number) => {
      if (stoppedRef.current) return;
      timeoutRef.current = setTimeout(poll, delay);
    };

    const poll = async () => {
      try {
        const [runtime, health] = await Promise.all([
          getBackendRuntimeStatus().catch(() => null),
          getHealth().catch(() => null),
        ]);

        const healthReady = health?.status === 'healthy';
        const runtimeReady = Boolean(
          runtime?.healthy
          || (
            runtime?.running
            && runtime?.dashboard_bound
            && runtime?.operator_api_ready
            && runtime?.process_state === 'running'
          ),
        );
        const backendReady = Boolean(
          healthReady
          || runtimeReady
          || health?.runtime?.operator_api_ready
          || health?.runtime?.adaptive_ready,
        );

        if (backendReady) {
          failCountRef.current = 0;
          setConnectionStatus('connected');
          setBackendInfo(health?.version || '1.0.0', 0);
          lastRuntimeErrorRef.current = null;
        } else if (
          runtime?.start_in_progress
          || runtime?.process_state === 'starting'
          || runtime?.process_state === 'degraded'
          || runtime?.readiness_phase === 'binding_dashboard'
          || runtime?.readiness_phase === 'warming_operator_surface'
          || health?.readiness === 'starting'
        ) {
          failCountRef.current = 0;
          setConnectionStatus('connecting');
          if (runtime?.last_error && runtime.last_error !== lastRuntimeErrorRef.current) {
            lastRuntimeErrorRef.current = runtime.last_error;
            pushToast({
              title: 'Backend Recovering',
              description: runtime.desktop_log_path
                ? `${runtime.last_error}. Runtime log: ${runtime.desktop_log_path}`
                : runtime.last_error,
              level: 'warning',
            });
          }
        } else {
          throw new Error(`unhealthy: ${health?.status || runtime?.process_state || 'unknown'}`);
        }
      } catch {
        const runtime = await getBackendRuntimeStatus().catch(() => null);
        const runtimeAlive = Boolean(
          runtime?.healthy
          || runtime?.running
          || runtime?.start_in_progress
          || runtime?.attached_to_existing,
        );

        if (runtimeAlive || wsManager.connected) {
          failCountRef.current = 0;
          setConnectionStatus('connecting');
        } else {
          failCountRef.current += 1;
          setConnectionStatus('disconnected');
          if (runtime?.last_error && runtime.last_error !== lastRuntimeErrorRef.current) {
            lastRuntimeErrorRef.current = runtime.last_error;
            pushToast({
              title: 'Backend Offline',
              description: runtime.desktop_log_path
                ? `${runtime.last_error}. Runtime log: ${runtime.desktop_log_path}`
                : runtime.last_error,
              level: 'error',
            });
          }
        }
      } finally {
        const fails = failCountRef.current;
        const delay = fails === 0
          ? HEALTH_POLL_INTERVAL
          : Math.min(HEALTH_POLL_INTERVAL * Math.pow(2, Math.min(fails, 5)), MAX_BACKOFF);
        schedule(delay);
      }
    };

    void poll();

    return () => {
      stoppedRef.current = true;
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
    };
  }, [setConnectionStatus, setBackendInfo, pushToast]);
}
