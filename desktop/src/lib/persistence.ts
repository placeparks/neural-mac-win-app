import { invoke } from '@tauri-apps/api/core';

export async function getPersistedValue<T>(key: string, fallback: T): Promise<T> {
  try {
    const value = await invoke<unknown>('store_get', { key });
    if (value === null || value === undefined) return fallback;
    return value as T;
  } catch {
    return fallback;
  }
}

export async function setPersistedValue<T>(key: string, value: T): Promise<void> {
  try {
    await invoke('store_set', { key, value });
  } catch {
    // ignore desktop store write failures; callers may still proceed in-memory
  }
}

export async function deletePersistedValue(key: string): Promise<void> {
  try {
    await invoke('store_delete', { key });
  } catch {
    // ignore delete failures
  }
}

export async function clearPersistedStore(): Promise<void> {
  try {
    await invoke('store_clear');
  } catch {
    // ignore clear failures
  }
}
