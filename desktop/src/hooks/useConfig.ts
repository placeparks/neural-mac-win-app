// NeuralClaw Desktop — Config Hook
import { useCallback, useState } from 'react';
import { getConfig } from '../lib/api';

export function useConfig() {
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);

  const loadConfig = useCallback(async () => {
    setLoading(true);
    try {
      const cfg = await getConfig();
      setConfig(cfg);
    } catch { /* backend may not be running */ }
    finally { setLoading(false); }
  }, []);

  return { config, loading, loadConfig };
}
