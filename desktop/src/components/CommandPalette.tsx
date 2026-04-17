import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

interface CommandItem {
  id: string;
  label: string;
  description?: string;
  category: string;
  icon?: string;
  action: () => void;
  keywords?: string[];
}

interface Props {
  open: boolean;
  onClose: () => void;
  onNavigate: (view: string) => void;
}

export default function CommandPalette({ open, onClose, onNavigate }: Props) {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const commands = useMemo<CommandItem[]>(() => [
    // Navigation
    { id: 'nav-chat', label: 'Go to Chat', category: 'Navigation', action: () => { onNavigate('chat'); onClose(); }, keywords: ['message', 'conversation'] },
    { id: 'nav-tasks', label: 'Go to Tasks', category: 'Navigation', action: () => { onNavigate('tasks'); onClose(); }, keywords: ['todo', 'inbox'] },
    { id: 'nav-memory', label: 'Go to Memory', category: 'Navigation', action: () => { onNavigate('memory'); onClose(); }, keywords: ['episodic', 'semantic'] },
    { id: 'nav-knowledge', label: 'Go to Knowledge Base', category: 'Navigation', action: () => { onNavigate('knowledge'); onClose(); }, keywords: ['docs', 'rag'] },
    { id: 'nav-database', label: 'Go to Database BI', category: 'Navigation', action: () => { onNavigate('database'); onClose(); }, keywords: ['sql', 'query', 'analytics'] },
    { id: 'nav-workflows', label: 'Go to Workflows', category: 'Navigation', action: () => { onNavigate('workflows'); onClose(); }, keywords: ['pipeline', 'dag'] },
    { id: 'nav-agents', label: 'Go to Agents', category: 'Navigation', action: () => { onNavigate('agents'); onClose(); }, keywords: ['swarm', 'delegate'] },
    { id: 'nav-connections', label: 'Go to Connections', category: 'Navigation', action: () => { onNavigate('connections'); onClose(); }, keywords: ['integrations', 'github', 'slack', 'jira', 'google'] },
    { id: 'nav-dashboard', label: 'Go to Dashboard', category: 'Navigation', action: () => { onNavigate('dashboard'); onClose(); }, keywords: ['stats', 'traces'] },
    { id: 'nav-settings', label: 'Go to Settings', category: 'Navigation', action: () => { onNavigate('settings'); onClose(); }, keywords: ['config', 'provider'] },
    // Quick Actions
    { id: 'action-new-chat', label: 'New Chat Session', category: 'Actions', description: 'Start a fresh conversation', action: () => { onNavigate('chat'); onClose(); window.dispatchEvent(new CustomEvent('neuralclaw:new-chat')); }, keywords: ['fresh', 'start'] },
    { id: 'action-connect-db', label: 'Connect Database', category: 'Actions', description: 'Add a new database connection', action: () => { onNavigate('database'); onClose(); }, keywords: ['sql', 'postgres', 'mysql'] },
    { id: 'action-open-connections', label: 'Open Connection Hub', category: 'Actions', description: 'Connect GitHub, Slack, Jira, Google, and more', action: () => { onNavigate('connections'); onClose(); }, keywords: ['integrations', 'oauth', 'api', 'channels'] },
    { id: 'action-morning', label: 'Morning Briefing', category: 'Actions', description: 'Get your morning digest', action: () => { onNavigate('chat'); onClose(); window.dispatchEvent(new CustomEvent('neuralclaw:send-message', { detail: 'Give me a morning briefing with my recent activity, pending tasks, and any KPI alerts.' })); }, keywords: ['digest', 'summary', 'briefing'] },
    { id: 'action-clipboard', label: 'Analyze Clipboard', category: 'Actions', description: 'Detect and analyze clipboard content', action: () => { onNavigate('chat'); onClose(); window.dispatchEvent(new CustomEvent('neuralclaw:send-message', { detail: 'Analyze my current clipboard content and suggest actions.' })); }, keywords: ['paste', 'copy'] },
    { id: 'action-context', label: 'Context Suggestions', category: 'Actions', description: 'Get suggestions based on active app', action: () => { onNavigate('chat'); onClose(); window.dispatchEvent(new CustomEvent('neuralclaw:send-message', { detail: 'Detect my active window and suggest relevant actions.' })); }, keywords: ['window', 'app', 'detect'] },
    // Skills
    { id: 'skill-web-search', label: 'Web Search', category: 'Skills', description: 'Search the web', action: () => { onNavigate('chat'); onClose(); }, keywords: ['google', 'browse', 'find'] },
    { id: 'skill-code-exec', label: 'Execute Python', category: 'Skills', description: 'Run Python code in sandbox', action: () => { onNavigate('chat'); onClose(); }, keywords: ['run', 'python', 'script'] },
    { id: 'skill-db-query', label: 'Natural Language Query', category: 'Skills', description: 'Ask questions about your databases', action: () => { onNavigate('database'); onClose(); }, keywords: ['sql', 'data', 'analytics'] },
    { id: 'skill-chart', label: 'Generate Chart', category: 'Skills', description: 'Create visualizations from data', action: () => { onNavigate('database'); onClose(); }, keywords: ['bar', 'line', 'pie', 'graph'] },
    { id: 'skill-kpi', label: 'Create KPI Monitor', category: 'Skills', description: 'Set up a metric watcher with alerts', action: () => { onNavigate('chat'); onClose(); window.dispatchEvent(new CustomEvent('neuralclaw:send-message', { detail: 'Help me create a KPI monitor for tracking a metric.' })); }, keywords: ['metric', 'alert', 'threshold'] },
    { id: 'skill-schedule', label: 'Create Schedule', category: 'Skills', description: 'Set up a cron-based scheduled task', action: () => { onNavigate('chat'); onClose(); window.dispatchEvent(new CustomEvent('neuralclaw:send-message', { detail: 'Help me create a scheduled task.' })); }, keywords: ['cron', 'timer', 'recurring'] },
    { id: 'skill-browse-skills', label: 'Browse All Skills', category: 'Skills', description: 'View all registered agent skills', action: () => { onNavigate('workspace'); onClose(); }, keywords: ['list', 'available', 'registry'] },
    // Workspace
    { id: 'nav-workspace', label: 'Go to Workspace', category: 'Navigation', action: () => { onNavigate('workspace'); onClose(); }, keywords: ['projects', 'scaffold', 'skills', 'claims'] },
    { id: 'workspace-scaffold', label: 'Scaffold New Project', category: 'Workspace', description: 'Create a project from a template', action: () => { onNavigate('workspace'); onClose(); setTimeout(() => window.dispatchEvent(new CustomEvent('neuralclaw:scaffold-project')), 150); }, keywords: ['new', 'create', 'fastapi', 'python', 'template'] },
    { id: 'workspace-claims', label: 'View Workspace Claims', category: 'Workspace', description: 'See which agents own which directories', action: () => { onNavigate('workspace'); onClose(); setTimeout(() => window.dispatchEvent(new CustomEvent('neuralclaw:workspace-tab', { detail: 'claims' })), 150); }, keywords: ['lock', 'directory', 'agent', 'coordination'] },
    { id: 'workspace-write-skill', label: 'Write a New Skill', category: 'Workspace', description: 'Ask the agent to create a custom skill', action: () => { onNavigate('chat'); onClose(); window.dispatchEvent(new CustomEvent('neuralclaw:send-message', { detail: 'Help me write a new NeuralClaw skill. Show me the template and guide me through it.' })); }, keywords: ['plugin', 'extend', 'custom', 'tool'] },
  ], [onNavigate, onClose]);

  const filtered = useMemo(() => {
    if (!query.trim()) return commands;
    const q = query.toLowerCase();
    return commands.filter(cmd => {
      const searchable = [cmd.label, cmd.description || '', cmd.category, ...(cmd.keywords || [])].join(' ').toLowerCase();
      return searchable.includes(q);
    });
  }, [query, commands]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  useEffect(() => {
    if (open) {
      setQuery('');
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  const executeSelected = useCallback(() => {
    if (filtered[selectedIndex]) {
      filtered[selectedIndex].action();
    }
  }, [filtered, selectedIndex]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(i => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(i => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      executeSelected();
    } else if (e.key === 'Escape') {
      onClose();
    }
  }, [filtered.length, executeSelected, onClose]);

  // Scroll selected item into view
  useEffect(() => {
    const listEl = listRef.current;
    if (!listEl) return;
    const selected = listEl.querySelector('[data-selected="true"]');
    if (selected) {
      selected.scrollIntoView({ block: 'nearest' });
    }
  }, [selectedIndex]);

  // Global keyboard shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        if (open) onClose();
        else window.dispatchEvent(new CustomEvent('neuralclaw:command-palette'));
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  let lastCategory = '';

  return (
    <div className="command-palette-overlay" onClick={onClose}>
      <div className="command-palette" onClick={e => e.stopPropagation()}>
        <div className="command-palette-input-wrapper">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="2">
            <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
          </svg>
          <input
            ref={inputRef}
            className="command-palette-input"
            type="text"
            placeholder="Type a command or search..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <kbd className="command-palette-kbd">Esc</kbd>
        </div>

        <div className="command-palette-list" ref={listRef}>
          {filtered.length === 0 && (
            <div className="command-palette-empty">No matching commands</div>
          )}
          {filtered.map((cmd, i) => {
            const showCategory = cmd.category !== lastCategory;
            lastCategory = cmd.category;
            return (
              <div key={cmd.id}>
                {showCategory && (
                  <div className="command-palette-category">{cmd.category}</div>
                )}
                <div
                  className={`command-palette-item ${i === selectedIndex ? 'selected' : ''}`}
                  data-selected={i === selectedIndex}
                  onClick={() => cmd.action()}
                  onMouseEnter={() => setSelectedIndex(i)}
                >
                  <div className="command-palette-item-content">
                    <span className="command-palette-item-label">{cmd.label}</span>
                    {cmd.description && (
                      <span className="command-palette-item-desc">{cmd.description}</span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div className="command-palette-footer">
          <span><kbd>Up</kbd><kbd>Down</kbd> navigate</span>
          <span><kbd>Enter</kbd> select</span>
          <span><kbd>Esc</kbd> close</span>
        </div>
      </div>
    </div>
  );
}
