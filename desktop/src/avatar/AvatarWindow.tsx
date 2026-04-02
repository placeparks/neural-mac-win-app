import { MouseEvent as ReactMouseEvent, useEffect, useMemo, useRef, useState } from 'react';
import AvatarScene from './AvatarScene';
import AvatarChatOverlay from './AvatarChatOverlay';
import { useAvatarState, type AvatarAnchor } from './useAvatarState';
import { createSharedTask, delegateTask, getAgentActivity, getRunningAgents, type AgentActivityEvent, type RunningAgent } from '../lib/api';

const PRESET_LABELS: Array<{ anchor: AvatarAnchor; label: string }> = [
  { anchor: 'bottom-right', label: 'Bottom Right' },
  { anchor: 'bottom-left', label: 'Bottom Left' },
  { anchor: 'top-right', label: 'Top Right' },
  { anchor: 'top-left', label: 'Top Left' },
  { anchor: 'taskbar', label: 'Taskbar' },
];

export default function AvatarWindow() {
  const {
    hydrate,
    modelPath,
    scale,
    emotion,
    isSpeaking,
    position,
    inputOpen,
    setInputOpen,
    setPosition,
    setAnchor,
    openMainApp,
    hide,
    collaborationPulse,
    setCollaborationPulse,
    setEmotion,
    setLatestResponse,
  } = useAvatarState();
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);
  const [runningCount, setRunningCount] = useState(0);
  const [runningAgents, setRunningAgents] = useState<RunningAgent[]>([]);
  const [recentActivity, setRecentActivity] = useState<AgentActivityEvent[]>([]);
  const [deckOpen, setDeckOpen] = useState(false);
  const [delegateTaskText, setDelegateTaskText] = useState('');
  const [selectedAgents, setSelectedAgents] = useState<string[]>([]);
  const [delegateBusy, setDelegateBusy] = useState(false);
  const [delegateStatus, setDelegateStatus] = useState<string | null>(null);
  const dragStart = useRef<{ mouseX: number; mouseY: number; originX: number; originY: number } | null>(null);

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  useEffect(() => {
    const previousBody = document.body.style.background;
    const previousRoot = document.documentElement.style.background;
    document.body.style.background = 'transparent';
    document.documentElement.style.background = 'transparent';
    return () => {
      document.body.style.background = previousBody;
      document.documentElement.style.background = previousRoot;
    };
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === 'k' && event.ctrlKey) {
        event.preventDefault();
        setInputOpen(true);
      }
      if (event.key === 'Escape') {
        setContextMenu(null);
        setDeckOpen(false);
        if (inputOpen) setInputOpen(false);
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [inputOpen, setInputOpen]);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const [running, activity] = await Promise.all([
          getRunningAgents(),
          getAgentActivity(4),
        ]);

        if (cancelled) return;
        setRunningAgents(running);
        setRunningCount(running.length);
        setRecentActivity(activity.slice().reverse());
        setSelectedAgents((current) => {
          if (current.length) {
            return current.filter((name) => running.some((agent) => agent.name === name));
          }
          return running[0]?.name ? [running[0].name] : [];
        });
        const mostRecent = activity[activity.length - 1];
        setCollaborationPulse(Boolean(
          mostRecent &&
          mostRecent.from_agent !== mostRecent.to_agent &&
          Date.now() - (mostRecent.timestamp * 1000) < 12000,
        ));
      } catch {
        if (!cancelled) {
          setRunningCount(0);
          setRunningAgents([]);
          setRecentActivity([]);
          setSelectedAgents([]);
          setCollaborationPulse(false);
        }
      }
    };

    poll();
    const timer = window.setInterval(poll, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [setCollaborationPulse]);

  useEffect(() => {
    if (!dragStart.current) return;

    const onMove = (event: MouseEvent) => {
      const start = dragStart.current;
      if (!start) return;
      const nextX = start.originX + (event.screenX - start.mouseX);
      const nextY = start.originY + (event.screenY - start.mouseY);
      void setPosition(nextX, nextY);
    };

    const onUp = () => {
      dragStart.current = null;
    };

    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [setPosition]);

  const onPointerDown = (event: ReactMouseEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (event.button !== 0) return;
    if (target.closest('button') || target.closest('input') || target.closest('form')) return;
    dragStart.current = {
      mouseX: event.screenX,
      mouseY: event.screenY,
      originX: position.x,
      originY: position.y,
    };
  };

  const avatarClassName = useMemo(
    () => `avatar-window-shell${collaborationPulse ? ' collaborating' : ''}`,
    [collaborationPulse],
  );

  const toggleAgent = (agentName: string) => {
    setSelectedAgents((current) =>
      current.includes(agentName)
        ? current.filter((name) => name !== agentName)
        : [...current, agentName],
    );
  };

  const handleDelegate = async () => {
    if (!delegateTaskText.trim() || selectedAgents.length === 0) return;

    setDelegateBusy(true);
    setDelegateStatus(null);
    setEmotion('thinking');

    try {
      let sharedTaskId: string | undefined;
      if (selectedAgents.length > 1) {
        const sharedTask = await createSharedTask(selectedAgents);
        if (sharedTask.ok && sharedTask.task_id) {
          sharedTaskId = sharedTask.task_id;
        }
      }

      const response = await delegateTask(selectedAgents[0], delegateTaskText.trim(), {
        agentNames: selectedAgents,
        sharedTaskId,
      });

      if (!response.ok) {
        throw new Error(response.error || 'Delegation failed');
      }

      const summary = response.results?.length
        ? response.results
          .map((entry) => `[${entry.agent}] ${entry.result || entry.status}`)
          .join('\n\n')
        : (response.result || 'Delegation completed');

      setDelegateStatus(summary);
      setLatestResponse(summary);
      setEmotion('happy');
      setDelegateTaskText('');
      setDeckOpen(true);
    } catch (error: any) {
      const message = error?.message || 'Delegation failed';
      setDelegateStatus(message);
      setLatestResponse(message);
      setEmotion('surprised');
    } finally {
      setDelegateBusy(false);
      window.setTimeout(() => {
        useAvatarState.getState().setEmotion('neutral');
      }, 1500);
    }
  };

  return (
    <div
      className={avatarClassName}
      onMouseDown={onPointerDown}
      onClick={() => setContextMenu(null)}
      onContextMenu={(event) => {
        event.preventDefault();
        setContextMenu({ x: event.clientX, y: event.clientY });
      }}
    >
      <div className="avatar-stage" onDoubleClick={() => setInputOpen(true)}>
        <AvatarScene
          modelPath={modelPath}
          scale={scale}
          emotion={emotion}
          isSpeaking={isSpeaking}
        />
      </div>

      <div className="avatar-status-pill">
        <span className={`status-dot ${collaborationPulse ? 'online' : 'connecting'}`} />
        <span>{runningCount} agent{runningCount === 1 ? '' : 's'}</span>
      </div>

      <div className="avatar-action-strip">
        <button type="button" className="avatar-chip-btn" onClick={() => setInputOpen(true)}>
          Ask
        </button>
        <button
          type="button"
          className="avatar-chip-btn"
          onClick={() => setDeckOpen((open) => !open)}
        >
          {deckOpen ? 'Hide' : 'Agentic'}
        </button>
        <button type="button" className="avatar-chip-btn" onClick={() => { void openMainApp('agents'); }}>
          Agents
        </button>
        <button type="button" className="avatar-chip-btn" onClick={() => { void hide(); }}>
          Min
        </button>
      </div>

      {deckOpen && (
        <div className="avatar-agent-panel" onClick={(event) => event.stopPropagation()}>
          <div className="avatar-panel-title">Agent Desk</div>

          {runningAgents.length === 0 ? (
            <div className="avatar-panel-empty">
              No running agents yet. Start an agent from the main app to delegate work here.
            </div>
          ) : (
            <>
              <div className="avatar-agent-chip-row">
                {runningAgents.map((agent) => {
                  const selected = selectedAgents.includes(agent.name);
                  return (
                    <button
                      key={agent.name}
                      type="button"
                      className={`avatar-agent-chip${selected ? ' selected' : ''}`}
                      onClick={() => toggleAgent(agent.name)}
                    >
                      {agent.name}
                    </button>
                  );
                })}
              </div>

              <textarea
                className="avatar-delegate-input"
                value={delegateTaskText}
                onChange={(event) => setDelegateTaskText(event.target.value)}
                placeholder="Delegate a task to the selected agents..."
                rows={3}
              />

              <div className="avatar-agent-actions">
                <button
                  type="button"
                  className="avatar-chip-btn primary"
                  disabled={delegateBusy || selectedAgents.length === 0 || !delegateTaskText.trim()}
                  onClick={() => { void handleDelegate(); }}
                >
                  {delegateBusy ? 'Working...' : 'Delegate'}
                </button>
                <button
                  type="button"
                  className="avatar-chip-btn"
                  onClick={() => { void openMainApp('agents'); }}
                >
                  Full Control
                </button>
              </div>
            </>
          )}

          {delegateStatus && (
            <div className="avatar-panel-status">
              {delegateStatus}
            </div>
          )}

          {recentActivity.length > 0 && (
            <div className="avatar-activity-list">
              {recentActivity.slice(0, 3).map((event) => (
                <div key={event.id} className="avatar-activity-item">
                  <strong>{event.from_agent}</strong>
                  <span>{event.content}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <AvatarChatOverlay />

      {contextMenu && (
        <div
          className="avatar-context-menu"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={(event) => event.stopPropagation()}
        >
          {PRESET_LABELS.map((preset) => (
            <button
              key={preset.anchor}
              type="button"
              className="avatar-context-item"
              onClick={async () => {
                await setAnchor(preset.anchor);
                setContextMenu(null);
              }}
            >
              {preset.label}
            </button>
          ))}
          <button
            type="button"
            className="avatar-context-item"
            onClick={async () => {
              await openMainApp();
              setContextMenu(null);
            }}
          >
            Open Main App
          </button>
          <button
            type="button"
            className="avatar-context-item"
            onClick={async () => {
              await openMainApp('agents');
              setContextMenu(null);
            }}
          >
            Open Agents
          </button>
          <button
            type="button"
            className="avatar-context-item"
            onClick={async () => {
              await hide();
              setContextMenu(null);
            }}
          >
            Minimize Avatar
          </button>
          <button
            type="button"
            className="avatar-context-item"
            onClick={async () => {
              await openMainApp('settings');
              setContextMenu(null);
            }}
          >
            Open Settings
          </button>
        </div>
      )}
    </div>
  );
}
