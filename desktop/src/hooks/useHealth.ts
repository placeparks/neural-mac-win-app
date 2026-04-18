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
        const runtimeConflict = runtime?.process_state === 'conflict';
        const runtimeRecovering = Boolean(
          runtime?.start_in_progress
          || runtime?.process_state === 'starting'
          || runtime?.readiness_phase === 'recovering'
          || runtime?.readiness_phase === 'spawning',
        );
        const runtimeDegradedButOnline = Boolean(
          runtime?.dashboard_bound
          && (
            runtime?.process_state === 'degraded'
            || runtime?.provider_degraded
            || health?.readiness === 'degraded'
          ),
        );

        if (backendReady || runtimeDegradedButOnline) {
          failCountRef.current = 0;
          setConnectionStatus('connected');
          setBackendInfo(health?.version || '1.0.0', 0);
          const degradedMessage = runtime?.provider_detail || runtime?.last_error;
          if (degradedMessage && degradedMessage !== lastRuntimeErrorRef.current && (runtime?.provider_degraded || runtimeDegradedButOnline)) {
            lastRuntimeErrorRef.current = degradedMessage;
            pushToast({
              title: 'Backend Online With Degraded Dependencies',
              description: runtime?.desktop_log_path
                ? `${degradedMessage}. Runtime log: ${runtime.desktop_log_path}`
                : degradedMessage,
              level: 'warning',
            });
          } else if (!runtime?.provider_degraded) {
            lastRuntimeErrorRef.current = null;
          }
        } else if (
          runtimeRecovering
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
        } else if (runtimeConflict) {
          failCountRef.current = 0;
          setConnectionStatus('disconnected');
          const owner = runtime?.port_owner;
          const conflictMessage = owner
            ? `Port ${owner.port} is occupied by ${owner.process_name || 'another process'}${owner.process_path ? ` (${owner.process_path})` : ''}.`
            : runtime?.last_error || 'Backend startup is blocked by a port conflict.';
          if (conflictMessage !== lastRuntimeErrorRef.current) {
            lastRuntimeErrorRef.current = conflictMessage;
            pushToast({
              title: 'Backend Startup Conflict',
              description: runtime?.desktop_log_path
                ? `${conflictMessage} Runtime log: ${runtime.desktop_log_path}`
                : conflictMessage,
              level: 'error',
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
        const runtimeConflict = runtime?.process_state === 'conflict';

        if (runtimeAlive || wsManager.connected) {
          failCountRef.current = 0;
          setConnectionStatus('connecting');
        } else if (runtimeConflict) {
          failCountRef.current = 0;
          setConnectionStatus('disconnected');
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
