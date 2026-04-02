import { useEffect } from 'react';
import { useAppStore } from '../../store/appStore';

export default function ToastViewport() {
  const { toasts, removeToast } = useAppStore();

  useEffect(() => {
    if (!toasts.length) return;
    const timers = toasts.map((toast) =>
      window.setTimeout(() => removeToast(toast.id), 4200),
    );
    return () => {
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [removeToast, toasts]);

  return (
    <div className="toast-viewport" aria-live="polite" aria-atomic="true">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast-card ${toast.level}`}>
          <div className="toast-card-title">{toast.title}</div>
          <div className="toast-card-body">{toast.description}</div>
        </div>
      ))}
    </div>
  );
}
