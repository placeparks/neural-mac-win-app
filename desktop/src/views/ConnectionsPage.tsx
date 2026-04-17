import { useEffect, useMemo, useState } from 'react';
import { openUrl } from '@tauri-apps/plugin-opener';
import Header from '../components/layout/Header';
import {
  connectIntegration,
  disconnectIntegration,
  getChannels,
  getConfig,
  getDBConnections,
  getDesktopIntegrations,
  testIntegration,
  testChannel,
  updateChannel,
  updateDashboardConfig,
  type ChannelSnapshot,
  type DBConnection,
  type DesktopIntegration,
} from '../lib/api';

type AppConfig = Record<string, any>;
type AgentAccessMode = 'enabled' | 'read_only' | 'disabled';

function asRecord(value: unknown): Record<string, any> {
  return value && typeof value === 'object' ? value as Record<string, any> : {};
}

function navigateTo(view: string) {
  window.dispatchEvent(new CustomEvent('neuralclaw:navigate', { detail: view }));
}

function statusTone(connected: boolean, configured = false) {
  if (connected) return 'green';
  if (configured) return 'orange';
  return 'blue';
}

function statusLabel(connected: boolean, configured = false) {
  if (connected) return 'Connected';
  if (configured) return 'Configured';
  return 'Idle';
}

function SectionTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="connection-section-title">
      <h2>{title}</h2>
      <p>{subtitle}</p>
    </div>
  );
}

function StatusBadge({ connected, configured = false }: { connected: boolean; configured?: boolean }) {
  const tone = statusTone(connected, configured);
  return <span className={`badge badge-${tone}`}>{statusLabel(connected, configured)}</span>;
}

function CapabilityList({ items }: { items: string[] }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
      {items.map((item) => (
        <span key={item} className="badge">{item}</span>
      ))}
    </div>
  );
}

function ConnectionCard({
  title,
  category,
  summary,
  status,
  actions,
  children,
}: {
  title: string;
  category: string;
  summary: string;
  status: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="card connection-card" style={{ marginBottom: 16 }}>
      <div className="card-header connection-card-header">
        <div>
          <div className="connection-card-headline">
            <span className="card-title">{title}</span>
            <span className="badge">{category}</span>
            {status}
          </div>
          <div className="connection-card-summary">{summary}</div>
        </div>
        {actions}
      </div>
      <div className="connection-card-body">
        {children}
      </div>
    </div>
  );
}

function IntegrationApiCard({
  title,
  apiName,
  defaultBaseUrl,
  defaultAuthType = 'bearer',
  capabilities,
  config,
  integrations,
  onSave,
}: {
  title: string;
  apiName: string;
  defaultBaseUrl: string;
  defaultAuthType?: 'bearer' | 'api_key_header' | 'api_key_query' | 'basic';
  capabilities: string[];
  config: AppConfig;
  integrations: DesktopIntegration[];
  onSave: (payload: Record<string, unknown>) => Promise<void>;
}) {
  const apiConfig = asRecord(asRecord(config.apis)[apiName]);
  const inventory = integrations.find((item) => item.id === apiName);
  const [baseUrl, setBaseUrl] = useState(String(apiConfig.base_url || defaultBaseUrl));
  const [authType, setAuthType] = useState<String>(String(apiConfig.auth_type || defaultAuthType));
  const [secret, setSecret] = useState('');
  const [agentAccess, setAgentAccess] = useState<AgentAccessMode>((String(apiConfig.agent_access || 'enabled') as AgentAccessMode));
  const [requiresConfirmation, setRequiresConfirmation] = useState(Boolean(apiConfig.requires_confirmation ?? true));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    setBaseUrl(String(apiConfig.base_url || defaultBaseUrl));
    setAuthType(String(apiConfig.auth_type || defaultAuthType));
    setSecret('');
    setAgentAccess(String(apiConfig.agent_access || 'enabled') as AgentAccessMode);
    setRequiresConfirmation(Boolean(apiConfig.requires_confirmation ?? true));
    setMessage(null);
  }, [apiConfig.base_url, apiConfig.auth_type, apiConfig.agent_access, apiConfig.requires_confirmation, defaultAuthType, defaultBaseUrl]);

  const connected = Boolean(inventory?.connected);
  const configured = Boolean(apiConfig.base_url || inventory?.enabled);

  return (
    <ConnectionCard
      title={title}
      category="API"
      summary={`Expose ${title} as an agent-ready surface with saved auth and reusable actions.`}
      status={<StatusBadge connected={connected} configured={configured} />}
      actions={
        <div className="connection-actions">
          <button
            className="btn btn-secondary btn-sm"
            onClick={async () => {
              setBusy(true);
              setMessage(null);
              try {
                const result = await testIntegration(apiName, {
                  base_url: baseUrl.trim(),
                  secret: secret.trim(),
                });
                setMessage(result.ok ? (result.message || `${title} connection succeeded.`) : (result.error || `${title} connection failed.`));
              } finally {
                setBusy(false);
              }
            }}
            disabled={busy || !baseUrl.trim()}
          >
            Test
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={async () => {
              setBusy(true);
              setMessage(null);
              try {
                const apis = asRecord(config.apis);
                await onSave({
                  apis: {
                    ...apis,
                    [apiName]: {
                      ...asRecord(apis[apiName]),
                      base_url: baseUrl.trim(),
                      auth_type: String(authType),
                      agent_access: agentAccess,
                      requires_confirmation: requiresConfirmation,
                    },
                  },
                  ...(secret.trim() ? { provider_secrets: { [apiName]: secret.trim() } } : {}),
                });
                setSecret('');
              } finally {
                setBusy(false);
              }
            }}
            disabled={busy || !baseUrl.trim()}
          >
            {busy ? 'Saving…' : 'Save Connection'}
          </button>
        </div>
      }
    >
      <CapabilityList items={capabilities} />
      <div className="settings-row">
        <div>
          <div className="settings-row-label">Base URL</div>
          <div className="settings-row-desc">Saved in config and reused by agent tools.</div>
        </div>
        <input className="input-field" style={{ width: 320 }} value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
      </div>
      <div className="settings-row">
        <div>
          <div className="settings-row-label">Auth Type</div>
          <div className="settings-row-desc">How the saved secret should be attached to requests.</div>
        </div>
        <select className="input-field" style={{ width: 220 }} value={String(authType)} onChange={(e) => setAuthType(e.target.value)}>
          <option value="bearer">Bearer</option>
          <option value="api_key_header">API key header</option>
          <option value="api_key_query">API key query</option>
          <option value="basic">Basic</option>
        </select>
      </div>
      <div className="settings-row">
        <div>
          <div className="settings-row-label">Secret</div>
          <div className="settings-row-desc">
            Saved securely in the OS keychain. Leave blank to keep the existing secret.
          </div>
        </div>
        <input
          className="input-field"
          style={{ width: 320 }}
          type="password"
          placeholder={`Update ${title} token`}
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
        />
      </div>
      <div className="settings-row">
        <div>
          <div className="settings-row-label">Agent access</div>
          <div className="settings-row-desc">Set whether agents can use this connection freely, in read-only workflows, or not at all.</div>
        </div>
        <select className="input-field" style={{ width: 220 }} value={agentAccess} onChange={(e) => setAgentAccess(e.target.value as AgentAccessMode)}>
          <option value="enabled">Read and write</option>
          <option value="read_only">Read only</option>
          <option value="disabled">Disabled</option>
        </select>
      </div>
      <label style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}>
        <input
          type="checkbox"
          checked={requiresConfirmation}
          onChange={(e) => setRequiresConfirmation(e.target.checked)}
        />
        Require confirmation before mutating actions
      </label>
      {message ? <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{message}</div> : null}
    </ConnectionCard>
  );
}

async function pollUntil(
  check: () => Promise<boolean>,
  timeoutMs = 90000,
  intervalMs = 2000,
): Promise<boolean> {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await check()) return true;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  return false;
}

function GitHubOAuthCard({
  config,
  integrations,
  onSave,
  onRefresh,
}: {
  config: AppConfig;
  integrations: DesktopIntegration[];
  onSave: (payload: Record<string, unknown>) => Promise<void>;
  onRefresh: () => Promise<void>;
}) {
  const githubConfig = asRecord(asRecord(config.apis).github);
  const details = asRecord(integrations.find((item) => item.id === 'github')?.details);
  const identity = asRecord(details.identity);
  const [baseUrl, setBaseUrl] = useState(String(githubConfig.base_url || 'https://api.github.com'));
  const [clientId, setClientId] = useState(String(githubConfig.client_id || ''));
  const [clientSecret, setClientSecret] = useState('');
  const [agentAccess, setAgentAccess] = useState<AgentAccessMode>((String(githubConfig.agent_access || 'enabled') as AgentAccessMode));
  const [requiresConfirmation, setRequiresConfirmation] = useState(Boolean(githubConfig.requires_confirmation ?? true));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    setBaseUrl(String(githubConfig.base_url || 'https://api.github.com'));
    setClientId(String(githubConfig.client_id || ''));
    setAgentAccess(String(githubConfig.agent_access || 'enabled') as AgentAccessMode);
    setRequiresConfirmation(Boolean(githubConfig.requires_confirmation ?? true));
    setMessage(null);
  }, [githubConfig.base_url, githubConfig.client_id, githubConfig.agent_access, githubConfig.requires_confirmation]);

  const connected = Boolean(integrations.find((item) => item.id === 'github')?.connected);
  const configured = Boolean(baseUrl.trim() || clientId.trim());
  const connectReady = Boolean(details.connect_ready);
  const login = String(identity.login || '');

  const saveSettings = async () => {
    await onSave({
      apis: {
        ...asRecord(config.apis),
        github: {
          ...githubConfig,
          base_url: baseUrl.trim(),
          client_id: clientId.trim(),
          auth_type: 'bearer',
          agent_access: agentAccess,
          requires_confirmation: requiresConfirmation,
        },
      },
    });
  };

  return (
    <ConnectionCard
      title="GitHub"
      category="Developer"
      summary="Sign in once, then let agents review PRs, inspect CI, comment on issues, and work against live repository context."
      status={<StatusBadge connected={connected} configured={configured} />}
      actions={
        <div className="connection-actions">
          <button
            className="btn btn-secondary btn-sm"
            onClick={async () => {
              setBusy(true);
              setMessage(null);
              try {
                await saveSettings();
                setMessage('GitHub settings saved.');
              } finally {
                setBusy(false);
              }
            }}
            disabled={busy || !baseUrl.trim()}
          >
            Save
          </button>
          <button
            className="btn btn-primary btn-sm"
            onClick={async () => {
              setBusy(true);
              setMessage(null);
              try {
                await saveSettings();
                const result = await connectIntegration('github', {
                  client_id: clientId.trim(),
                  client_secret: clientSecret.trim(),
                });
                if (!result.ok || !result.auth_url) {
                  setMessage(result.error || 'Failed to start GitHub sign-in.');
                  return;
                }
                await openUrl(result.auth_url);
                setMessage('GitHub sign-in opened in your browser. Waiting for completion…');
                const connectedNow = await pollUntil(async () => {
                  const snapshot = await getDesktopIntegrations().catch(() => ({ integrations: [], count: 0 }));
                  return Boolean(snapshot.integrations.find((item) => item.id === 'github')?.connected);
                });
                await onRefresh();
                setClientSecret('');
                setMessage(connectedNow ? 'GitHub connected successfully.' : 'Browser flow opened. If you completed sign-in, press Refresh.');
              } finally {
                setBusy(false);
              }
            }}
            disabled={busy || (!connectReady && (!clientId.trim() || !clientSecret.trim()))}
          >
            Sign in with GitHub
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={async () => {
              setBusy(true);
              setMessage(null);
              try {
                const result = await testIntegration('github', { base_url: baseUrl.trim() });
                setMessage(result.ok ? (result.message || 'GitHub test succeeded.') : (result.error || 'GitHub test failed.'));
              } finally {
                setBusy(false);
              }
            }}
            disabled={busy || !connected}
          >
            Test
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={async () => {
              setBusy(true);
              setMessage(null);
              try {
                const result = await disconnectIntegration('github');
                setMessage(result.ok ? (result.message || 'GitHub disconnected.') : (result.error || 'Failed to disconnect GitHub.'));
                if (result.ok) await onRefresh();
              } finally {
                setBusy(false);
              }
            }}
            disabled={busy || !connected}
          >
            Disconnect
          </button>
        </div>
      }
    >
      <CapabilityList items={['PR review', 'Issue workflows', 'CI status', 'Repository context']} />
      <div className="connection-inline-note">
        {connectReady
          ? 'GitHub sign-in is ready in this build. Use the primary button to connect your account.'
          : 'If you are packaging your own build, add OAuth app credentials once and end users can just sign in.'}
      </div>
      {login ? (
        <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
          Connected account: <strong>{login}</strong>
        </div>
      ) : null}
      <details className="connection-advanced-details">
        <summary>Advanced GitHub app settings</summary>
        <div className="connection-advanced-body">
          <div className="settings-row">
            <div>
              <div className="settings-row-label">Base URL</div>
              <div className="settings-row-desc">Use the default GitHub API unless you are connecting GitHub Enterprise.</div>
            </div>
            <input className="input-field" style={{ width: 320 }} value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          </div>
          <div className="settings-row">
            <div>
              <div className="settings-row-label">OAuth Client ID</div>
              <div className="settings-row-desc">Optional override if you are using your own GitHub OAuth app.</div>
            </div>
            <input className="input-field" style={{ width: 320 }} value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="GitHub OAuth app client ID" />
          </div>
          <div className="settings-row">
            <div>
              <div className="settings-row-label">OAuth Client Secret</div>
              <div className="settings-row-desc">Optional override for custom GitHub OAuth apps.</div>
            </div>
            <input className="input-field" style={{ width: 320 }} type="password" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} placeholder={connectReady ? 'Stored securely already' : 'GitHub OAuth app client secret'} />
          </div>
        </div>
      </details>
      <div className="settings-row">
        <div>
          <div className="settings-row-label">Agent access</div>
          <div className="settings-row-desc">Control whether agents can use GitHub directly, in read-only mode, or not at all.</div>
        </div>
        <select className="input-field" style={{ width: 220 }} value={agentAccess} onChange={(e) => setAgentAccess(e.target.value as AgentAccessMode)}>
          <option value="enabled">Read and write</option>
          <option value="read_only">Read only</option>
          <option value="disabled">Disabled</option>
        </select>
      </div>
      <label style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}>
        <input type="checkbox" checked={requiresConfirmation} onChange={(e) => setRequiresConfirmation(e.target.checked)} />
        Require confirmation before mutating actions
      </label>
      {message ? <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{message}</div> : null}
    </ConnectionCard>
  );
}

function GoogleWorkspaceCard({
  config,
  integrations,
  onSave,
  onRefresh,
}: {
  config: AppConfig;
  integrations: DesktopIntegration[];
  onSave: (payload: Record<string, unknown>) => Promise<void>;
  onRefresh: () => Promise<void>;
}) {
  const google = asRecord(config.google_workspace);
  const integration = integrations.find((item) => item.id === 'google_workspace');
  const details = asRecord(integration?.details);
  const identity = asRecord(details.identity);
  const scopes = Array.isArray(details.scopes)
    ? details.scopes.map((item) => String(item))
    : (Array.isArray(google.scopes) ? google.scopes.slice(0, 5) : []);
  const googlePolicy = asRecord(asRecord(config.apis).google_workspace);
  const [clientId, setClientId] = useState(String(googlePolicy.client_id || ''));
  const [clientSecret, setClientSecret] = useState('');
  const [agentAccess, setAgentAccess] = useState<AgentAccessMode>((String(googlePolicy.agent_access || 'enabled') as AgentAccessMode));
  const [requiresConfirmation, setRequiresConfirmation] = useState(Boolean(googlePolicy.requires_confirmation ?? true));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    setClientId(String(googlePolicy.client_id || ''));
    setAgentAccess(String(googlePolicy.agent_access || 'enabled') as AgentAccessMode);
    setRequiresConfirmation(Boolean(googlePolicy.requires_confirmation ?? true));
    setMessage(null);
  }, [googlePolicy.client_id, googlePolicy.agent_access, googlePolicy.requires_confirmation]);

  const connected = Boolean(integration?.connected);
  const configured = Boolean(clientId.trim() || integration?.enabled);
  const connectReady = Boolean(details.connect_ready);
  const email = String(identity.email || '');

  const saveSettings = async () => {
    const apis = asRecord(config.apis);
    await onSave({
      google_workspace: {
        ...google,
        enabled: Boolean(google.enabled),
      },
      apis: {
        ...apis,
        google_workspace: {
          ...asRecord(apis.google_workspace),
          client_id: clientId.trim(),
          agent_access: agentAccess,
          requires_confirmation: requiresConfirmation,
        },
      },
    });
  };

  return (
    <ConnectionCard
      title="Google Workspace"
      category="Productivity"
      summary="Search Drive, summarize Docs, draft email flows, and coordinate meetings from one connected workspace."
      status={<StatusBadge connected={connected} configured={configured} />}
      actions={
        <div className="connection-actions">
          <button
            className="btn btn-secondary btn-sm"
            onClick={async () => {
              setBusy(true);
              setMessage(null);
              try {
                await saveSettings();
                setMessage('Google Workspace settings saved.');
              } finally {
                setBusy(false);
              }
            }}
            disabled={busy || !clientId.trim()}
          >
            Save
          </button>
          <button
            className="btn btn-primary btn-sm"
            onClick={async () => {
              setBusy(true);
              setMessage(null);
              try {
                await saveSettings();
                const result = await connectIntegration('google_workspace', {
                  client_id: clientId.trim(),
                  client_secret: clientSecret.trim(),
                });
                if (!result.ok || !result.auth_url) {
                  setMessage(result.error || 'Failed to start Google sign-in.');
                  return;
                }
                await openUrl(result.auth_url);
                setMessage('Google sign-in opened in your browser. Waiting for completion...');
                const connectedNow = await pollUntil(async () => {
                  const snapshot = await getDesktopIntegrations().catch(() => ({ integrations: [], count: 0 }));
                  return Boolean(snapshot.integrations.find((item) => item.id === 'google_workspace')?.connected);
                });
                await onRefresh();
                setClientSecret('');
                setMessage(connectedNow ? 'Google Workspace connected successfully.' : 'Browser flow opened. If you completed sign-in, press Refresh.');
              } finally {
                setBusy(false);
              }
            }}
            disabled={busy || (!connectReady && (!clientId.trim() || !clientSecret.trim()))}
          >
            Sign in with Google
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={async () => {
              setBusy(true);
              setMessage(null);
              try {
                const result = await testIntegration('google_workspace');
                setMessage(result.ok ? (result.message || 'Google Workspace connection succeeded.') : (result.error || 'Google Workspace connection failed.'));
              } finally {
                setBusy(false);
              }
            }}
            disabled={busy || !connected}
          >
            Test
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={async () => {
              setBusy(true);
              try {
                const result = await disconnectIntegration('google_workspace');
                setMessage(result.ok ? (result.message || 'Google Workspace disconnected.') : (result.error || 'Failed to disconnect Google Workspace.'));
                if (result.ok) await onRefresh();
              } finally {
                setBusy(false);
              }
            }}
            disabled={busy || !connected}
          >
            Disconnect
          </button>
        </div>
      }
    >
      <CapabilityList items={['Gmail triage', 'Calendar actions', 'Drive search', 'Docs and Sheets context']} />
      <div className="connection-inline-note">
        {connectReady
          ? 'Google Workspace sign-in is ready in this build. Users can connect directly without handling console credentials.'
          : 'Package OAuth credentials once and this becomes a one-click Sign in with Google flow for end users.'}
      </div>
      {email ? (
        <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
          Connected account: <strong>{email}</strong>
        </div>
      ) : null}
      <details className="connection-advanced-details">
        <summary>Advanced Google OAuth settings</summary>
        <div className="connection-advanced-body">
          <div className="settings-row">
            <div>
              <div className="settings-row-label">OAuth Client ID</div>
              <div className="settings-row-desc">Optional override if you are using your own Google OAuth app.</div>
            </div>
            <input className="input-field" style={{ width: 320 }} value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="Google OAuth client ID" />
          </div>
          <div className="settings-row">
            <div>
              <div className="settings-row-label">OAuth Client Secret</div>
              <div className="settings-row-desc">Optional override for custom Google OAuth apps.</div>
            </div>
            <input className="input-field" style={{ width: 320 }} type="password" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} placeholder={connectReady ? 'Stored securely already' : 'Google OAuth client secret'} />
          </div>
        </div>
      </details>
      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
        Browser OAuth enables the Google tools already present in the backend and stores access and refresh tokens securely.
      </div>
      <div style={{ display: 'grid', gap: 8 }}>
        <div className="settings-row-label">Scopes</div>
        <CapabilityList items={scopes.length > 0 ? scopes : ['No scopes configured']} />
      </div>
      <div className="settings-row">
        <div>
          <div className="settings-row-label">Agent access</div>
          <div className="settings-row-desc">Control how agents are allowed to use connected Google data.</div>
        </div>
        <select className="input-field" style={{ width: 220 }} value={agentAccess} onChange={(e) => setAgentAccess(e.target.value as AgentAccessMode)}>
          <option value="enabled">Read and write</option>
          <option value="read_only">Read only</option>
          <option value="disabled">Disabled</option>
        </select>
      </div>
      <label style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}>
        <input type="checkbox" checked={requiresConfirmation} onChange={(e) => setRequiresConfirmation(e.target.checked)} />
        Require confirmation before mutating actions
      </label>
      {message ? <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{message}</div> : null}
    </ConnectionCard>
  );
}

function SlackConnectionCard({
  config,
  integrations,
  channel,
  onRefresh,
  onSave,
}: {
  config: AppConfig;
  integrations: DesktopIntegration[];
  channel: ChannelSnapshot | null;
  onRefresh: () => Promise<void>;
  onSave: (payload: Record<string, unknown>) => Promise<void>;
}) {
  const slackConfig = asRecord(asRecord(config.apis).slack);
  const integration = integrations.find((item) => item.id === 'channel:slack');
  const details = asRecord(integration?.details);
  const [botToken, setBotToken] = useState('');
  const [appToken, setAppToken] = useState('');
  const [clientId, setClientId] = useState(String(slackConfig.client_id || ''));
  const [clientSecret, setClientSecret] = useState('');
  const [agentAccess, setAgentAccess] = useState<AgentAccessMode>((String(slackConfig.agent_access || 'enabled') as AgentAccessMode));
  const [requiresConfirmation, setRequiresConfirmation] = useState(Boolean(slackConfig.requires_confirmation ?? true));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const connected = Boolean(channel?.ready || channel?.running);
  const configured = Boolean(channel?.configured || channel?.token_present);
  const channelExtra = asRecord(channel?.extra);
  const workspace = String(channelExtra.workspace || asRecord(details.identity).team || '');
  const connectReady = Boolean(channelExtra.connect_ready || details.connect_ready);
  const appTokenPresent = Boolean(channelExtra.app_token_present);
  const slackModeMessage = connected
    ? 'Slack Socket Mode is live.'
    : configured
      ? (appTokenPresent ? 'Workspace is connected. Enable the channel to go live.' : 'Workspace is connected, but Slack still needs the app token for Socket Mode.')
      : 'Connect the workspace first, then add the app token for inbound Slack events.';

  useEffect(() => {
    setClientId(String(slackConfig.client_id || ''));
    setAgentAccess(String(slackConfig.agent_access || 'enabled') as AgentAccessMode);
    setRequiresConfirmation(Boolean(slackConfig.requires_confirmation ?? true));
  }, [slackConfig.client_id, slackConfig.agent_access, slackConfig.requires_confirmation]);

  return (
    <ConnectionCard
      title="Slack"
      category="Channels"
      summary="Let agents post updates, summarize threads, and report task completions back into Slack."
      status={<StatusBadge connected={connected} configured={configured} />}
      actions={
        <div className="connection-actions">
          <button
            className="btn btn-primary btn-sm"
            onClick={async () => {
              setBusy(true);
              setMessage(null);
              try {
                await onSave({
                  apis: {
                    ...asRecord(config.apis),
                    slack: {
                      ...slackConfig,
                      client_id: clientId.trim(),
                      agent_access: agentAccess,
                      requires_confirmation: requiresConfirmation,
                    },
                  },
                });
                const result = await connectIntegration('slack', {
                  client_id: clientId.trim(),
                  client_secret: clientSecret.trim(),
                });
                if (!result.ok || !result.auth_url) {
                  setMessage(result.error || 'Failed to start Slack connect.');
                  return;
                }
                await openUrl(result.auth_url);
                setMessage('Slack install opened in your browser. Waiting for completion…');
                const connectedNow = await pollUntil(async () => {
                  const snapshot = await getChannels().catch(() => []);
                  return Boolean(snapshot.find((item) => item.name === 'slack')?.token_present);
                });
                await onRefresh();
                setClientSecret('');
                setMessage(connectedNow ? 'Slack workspace connected successfully.' : 'Browser flow opened. If you completed install, press Refresh.');
              } finally {
                setBusy(false);
              }
            }}
            disabled={busy || (!connectReady && (!clientId.trim() || !clientSecret.trim()))}
          >
            Install to Slack
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={async () => {
              setBusy(true);
              setMessage(null);
              try {
                const result = await testChannel('slack', {
                  enabled: Boolean(channel?.enabled),
                  trust_mode: String(channel?.trust_mode || ''),
                  secret: botToken.trim(),
                  extra: { slack_app: appToken.trim() },
                });
                setMessage(result.ok ? (result.message || 'Slack test succeeded.') : (result.error || 'Slack test failed.'));
              } finally {
                setBusy(false);
              }
            }}
            disabled={busy || (!botToken.trim() && !configured)}
          >
            Test
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={async () => {
              setBusy(true);
              setMessage(null);
              try {
                await onSave({
                  apis: {
                    ...asRecord(config.apis),
                    slack: {
                      ...slackConfig,
                      client_id: clientId.trim(),
                      agent_access: agentAccess,
                      requires_confirmation: requiresConfirmation,
                    },
                  },
                });
                const result = await updateChannel('slack', {
                  enabled: Boolean(channel?.enabled),
                  trust_mode: String(channel?.trust_mode || ''),
                  secret: botToken.trim(),
                  extra: { slack_app: appToken.trim() },
                });
                setMessage(result.ok ? 'Slack credentials saved.' : (result.error || 'Failed to save Slack credentials.'));
                if (result.ok) {
                  setBotToken('');
                  setAppToken('');
                  await onRefresh();
                }
              } finally {
                setBusy(false);
              }
            }}
            disabled={busy || (!botToken.trim() && !appToken.trim() && !clientId.trim())}
          >
            Save
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={async () => {
              setBusy(true);
              setMessage(null);
              try {
                await onSave({
                  apis: {
                    ...asRecord(config.apis),
                    slack: {
                      ...slackConfig,
                      client_id: clientId.trim(),
                      agent_access: agentAccess,
                      requires_confirmation: requiresConfirmation,
                    },
                  },
                });
                const result = await updateChannel('slack', {
                  enabled: !Boolean(channel?.enabled),
                  trust_mode: String(channel?.trust_mode || ''),
                  extra: {},
                });
                setMessage(result.ok ? (!Boolean(channel?.enabled) ? 'Slack enabled.' : 'Slack disabled.') : (result.error || 'Failed to toggle Slack.'));
                if (result.ok) await onRefresh();
              } finally {
                setBusy(false);
              }
            }}
            disabled={busy}
          >
            {channel?.enabled ? 'Disable' : 'Enable'}
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={async () => {
              setBusy(true);
              setMessage(null);
              try {
                const result = await disconnectIntegration('slack');
                setMessage(result.ok ? (result.message || 'Slack disconnected.') : (result.error || 'Failed to disconnect Slack.'));
                if (result.ok) await onRefresh();
              } finally {
                setBusy(false);
              }
            }}
            disabled={busy || !configured}
          >
            Disconnect
          </button>
        </div>
      }
    >
      <CapabilityList items={['Post task updates', 'Send alerts', 'Summarize channels', 'Respond to team workflows']} />
      <div className="connection-inline-note">
        {connectReady
          ? 'Slack workspace install is ready. Install first, then add the Socket Mode app token to go fully live.'
          : 'Use a packaged Slack app configuration for one-click install; Socket Mode still needs the app token from Slack app settings.'}
      </div>
      {workspace ? (
        <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
          Connected workspace: <strong>{workspace}</strong>
        </div>
      ) : null}
      <details className="connection-advanced-details">
        <summary>Advanced Slack app settings</summary>
        <div className="connection-advanced-body">
          <div className="settings-row">
            <div>
              <div className="settings-row-label">Slack OAuth Client ID</div>
              <div className="settings-row-desc">Optional override for your own Slack app install flow.</div>
            </div>
            <input className="input-field" style={{ width: 320 }} value={clientId} placeholder="Slack app client ID" onChange={(e) => setClientId(e.target.value)} />
          </div>
          <div className="settings-row">
            <div>
              <div className="settings-row-label">Slack OAuth Client Secret</div>
              <div className="settings-row-desc">Optional override for your own Slack app install flow.</div>
            </div>
            <input className="input-field" style={{ width: 320 }} type="password" value={clientSecret} placeholder={connectReady ? 'Stored securely already' : 'Slack app client secret'} onChange={(e) => setClientSecret(e.target.value)} />
          </div>
        </div>
      </details>
      <div className="settings-row">
        <div>
          <div className="settings-row-label">Bot Token</div>
          <div className="settings-row-desc">Slack bot token for workspace access.</div>
        </div>
        <input className="input-field" style={{ width: 320 }} type="password" value={botToken} placeholder="xoxb-..." onChange={(e) => setBotToken(e.target.value)} />
      </div>
      <div className="settings-row">
        <div>
          <div className="settings-row-label">App Token</div>
          <div className="settings-row-desc">App-level token for Socket Mode.</div>
        </div>
        <input className="input-field" style={{ width: 320 }} type="password" value={appToken} placeholder="xapp-..." onChange={(e) => setAppToken(e.target.value)} />
      </div>
      <div className="settings-row">
        <div>
          <div className="settings-row-label">Agent access</div>
          <div className="settings-row-desc">Control whether agents can use Slack workflows freely, read-only, or not at all.</div>
        </div>
        <select className="input-field" style={{ width: 220 }} value={agentAccess} onChange={(e) => setAgentAccess(e.target.value as AgentAccessMode)}>
          <option value="enabled">Read and write</option>
          <option value="read_only">Read only</option>
          <option value="disabled">Disabled</option>
        </select>
      </div>
      <label style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}>
        <input type="checkbox" checked={requiresConfirmation} onChange={(e) => setRequiresConfirmation(e.target.checked)} />
        Require confirmation before mutating actions
      </label>
      {channel?.status_detail ? (
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{channel.status_detail}</div>
      ) : null}
      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{slackModeMessage}</div>
      {message ? <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{message}</div> : null}
    </ConnectionCard>
  );
}

function DatabaseConnectionCard({ connections }: { connections: DBConnection[] }) {
  const connected = connections.some((conn) => conn.connected);
  const summary = connected
    ? `${connections.filter((conn) => conn.connected).length} live database connection${connections.filter((conn) => conn.connected).length === 1 ? '' : 's'}`
    : 'No live database connections yet';

  return (
    <ConnectionCard
      title="Databases"
      category="Data"
      summary="Expose warehouse and operational data to agents through schema-aware, safe query workflows."
      status={<StatusBadge connected={connected} configured={connections.length > 0} />}
      actions={<button className="btn btn-secondary btn-sm" onClick={() => navigateTo('database')}>Open Database BI</button>}
    >
      <CapabilityList items={['Schema inspection', 'Natural-language analytics', 'Charts', 'Read-only operational context']} />
      <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{summary}</div>
      {connections.length > 0 ? (
        <div style={{ display: 'grid', gap: 8 }}>
          {connections.slice(0, 4).map((connection) => (
            <div key={connection.name} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '10px 12px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-tertiary)' }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{connection.name}</div>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                  {connection.driver} · {connection.table_count} tables · {connection.read_only ? 'read-only' : 'read/write'}
                </div>
              </div>
              <StatusBadge connected={connection.connected} configured />
            </div>
          ))}
        </div>
      ) : null}
    </ConnectionCard>
  );
}

function VercelCard({
  config,
  integrations,
  onSave,
}: {
  config: AppConfig;
  integrations: DesktopIntegration[];
  onSave: (payload: Record<string, unknown>) => Promise<void>;
}) {
  const apiConfig = asRecord(asRecord(config.apis).vercel);
  const providerConfig = asRecord(asRecord(config.providers).vercel);
  const integration = integrations.find((item) => item.id === 'vercel');
  const [apiBaseUrl, setApiBaseUrl] = useState(String(apiConfig.base_url || 'https://api.vercel.com'));
  const [gatewayBaseUrl, setGatewayBaseUrl] = useState(String(providerConfig.base_url || 'https://ai-gateway.vercel.sh/v1'));
  const [defaultModel, setDefaultModel] = useState(String(providerConfig.model || 'openai/gpt-5.4'));
  const [secret, setSecret] = useState('');
  const [agentAccess, setAgentAccess] = useState<AgentAccessMode>((String(apiConfig.agent_access || 'enabled') as AgentAccessMode));
  const [requiresConfirmation, setRequiresConfirmation] = useState(Boolean(apiConfig.requires_confirmation ?? true));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    setApiBaseUrl(String(apiConfig.base_url || 'https://api.vercel.com'));
    setGatewayBaseUrl(String(providerConfig.base_url || 'https://ai-gateway.vercel.sh/v1'));
    setDefaultModel(String(providerConfig.model || 'openai/gpt-5.4'));
    setAgentAccess(String(apiConfig.agent_access || 'enabled') as AgentAccessMode);
    setRequiresConfirmation(Boolean(apiConfig.requires_confirmation ?? true));
    setSecret('');
    setMessage(null);
  }, [apiConfig.base_url, apiConfig.agent_access, apiConfig.requires_confirmation, providerConfig.base_url, providerConfig.model]);

  const connected = Boolean(integration?.connected);
  const configured = Boolean(apiBaseUrl.trim() || gatewayBaseUrl.trim());

  return (
    <ConnectionCard
      title="Vercel"
      category="Deploy + AI"
      summary="Wire Vercel into NeuralClaw for deployment workflows and route premium AI work through Vercel AI Gateway instead of hard-dropping DB analysis to local models."
      status={<StatusBadge connected={connected} configured={configured} />}
      actions={
        <div className="connection-actions">
          <button className="btn btn-secondary btn-sm" onClick={() => { void openUrl('https://vercel.com/changelog'); }}>
            View Changelog
          </button>
          <button
            className="btn btn-primary btn-sm"
            onClick={async () => {
              setBusy(true);
              setMessage(null);
              try {
                await onSave({
                  apis: {
                    ...asRecord(config.apis),
                    vercel: {
                      ...apiConfig,
                      base_url: apiBaseUrl.trim(),
                      auth_type: 'bearer',
                      agent_access: agentAccess,
                      requires_confirmation: requiresConfirmation,
                    },
                  },
                  providers: {
                    ...asRecord(config.providers),
                    vercel: {
                      ...providerConfig,
                      base_url: gatewayBaseUrl.trim(),
                      model: defaultModel.trim(),
                    },
                  },
                  ...(secret.trim() ? { provider_secrets: { vercel: secret.trim() } } : {}),
                });
                setSecret('');
                setMessage('Vercel is ready. Use the saved AI Gateway route from the Database workspace or make Vercel a primary provider later in Settings.');
              } finally {
                setBusy(false);
              }
            }}
            disabled={busy || !apiBaseUrl.trim() || !gatewayBaseUrl.trim()}
          >
            {busy ? 'Saving…' : 'Save Vercel'}
          </button>
        </div>
      }
    >
      <CapabilityList items={['Deploy token storage', 'Vercel API base', 'AI Gateway routing', 'DB workspace model routing']} />
      <div className="settings-row">
        <div>
          <div className="settings-row-label">Vercel API Base</div>
          <div className="settings-row-desc">Used for deployment and project-facing service integrations.</div>
        </div>
        <input className="input-field" style={{ width: 320 }} value={apiBaseUrl} onChange={(e) => setApiBaseUrl(e.target.value)} />
      </div>
      <div className="settings-row">
        <div>
          <div className="settings-row-label">AI Gateway Base</div>
          <div className="settings-row-desc">OpenAI-compatible route for premium model access through Vercel AI Gateway.</div>
        </div>
        <input className="input-field" style={{ width: 320 }} value={gatewayBaseUrl} onChange={(e) => setGatewayBaseUrl(e.target.value)} />
      </div>
      <div className="settings-row">
        <div>
          <div className="settings-row-label">Default Gateway Model</div>
          <div className="settings-row-desc">Used as the default Vercel route when a workspace does not pick a narrower model.</div>
        </div>
        <input className="input-field" style={{ width: 320 }} value={defaultModel} onChange={(e) => setDefaultModel(e.target.value)} placeholder="openai/gpt-5.4" />
      </div>
      <div className="settings-row">
        <div>
          <div className="settings-row-label">Token</div>
          <div className="settings-row-desc">Stored in the OS keychain. Leave blank to keep the current token.</div>
        </div>
        <input className="input-field" style={{ width: 320 }} type="password" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder="Update Vercel token" />
      </div>
      <div className="settings-row">
        <div>
          <div className="settings-row-label">Agent access</div>
          <div className="settings-row-desc">Keep deploy actions reviewable, while still letting agents inspect project and gateway state.</div>
        </div>
        <select className="input-field" style={{ width: 220 }} value={agentAccess} onChange={(e) => setAgentAccess(e.target.value as AgentAccessMode)}>
          <option value="enabled">Read and write</option>
          <option value="read_only">Read only</option>
          <option value="disabled">Disabled</option>
        </select>
      </div>
      <label style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}>
        <input type="checkbox" checked={requiresConfirmation} onChange={(e) => setRequiresConfirmation(e.target.checked)} />
        Require confirmation before mutating Vercel actions
      </label>
      {message ? <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{message}</div> : null}
    </ConnectionCard>
  );
}

export default function ConnectionsPage() {
  const [config, setConfig] = useState<AppConfig>({});
  const [integrations, setIntegrations] = useState<DesktopIntegration[]>([]);
  const [channels, setChannels] = useState<ChannelSnapshot[]>([]);
  const [dbConnections, setDbConnections] = useState<DBConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const refresh = async () => {
    const [cfg, integrationSnapshot, channelSnapshot, databaseSnapshot] = await Promise.all([
      getConfig(),
      getDesktopIntegrations().catch(() => ({ integrations: [], count: 0 })),
      getChannels().catch(() => []),
      getDBConnections().catch(() => []),
    ]);
    setConfig(cfg as AppConfig);
    setIntegrations(integrationSnapshot.integrations || []);
    setChannels(channelSnapshot);
    setDbConnections(databaseSnapshot);
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    refresh()
      .catch((error: any) => {
        if (!cancelled) setMessage({ ok: false, text: error?.message || 'Failed to load connections.' });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const save = async (payload: Record<string, unknown>) => {
    setMessage(null);
    const result = await updateDashboardConfig(payload);
    if (!result.ok) {
      setMessage({ ok: false, text: result.error || 'Failed to save connection.' });
      return;
    }
    if (result.config) setConfig(result.config as AppConfig);
    setMessage({
      ok: true,
      text: result.restart_required ? 'Saved. Restart the backend to apply all changes.' : 'Saved.',
    });
    await refresh();
  };

  const slackChannel = useMemo(
    () => channels.find((channel) => channel.name === 'slack') || null,
    [channels],
  );

  const recommended = [
    'GitHub for PR review, CI checks, and issue workflows',
    'Google Workspace for email, docs, drive, and calendar context',
    'Slack for agent notifications and team-facing updates',
    'Jira for work tracking and delivery status',
  ];
  const connectedCount = integrations.filter((item) => item.connected).length;
  const channelCount = channels.filter((channel) => channel.enabled || channel.running || channel.configured).length;
  const dbCount = dbConnections.filter((connection) => connection.connected).length;

  return (
    <div className="view-container">
      <Header
        title="Connections"
        subtitle="Turn external systems into agent-ready capabilities with clear trust boundaries."
      />

      <div className="page-body" style={{ paddingTop: 16 }}>
      <section className="connections-command-deck">
        <div>
          <div className="eyebrow">Connection Hub</div>
          <h2>Wire real systems into the agent surface without losing trust boundaries</h2>
          <p>
            Save credentials once, choose which systems agents may touch, and keep deploy, comms, knowledge, and database routes inside one durable control plane.
          </p>
        </div>
        <div className="connections-command-stats">
          <div className="connections-command-stat">
            <span>Integrations</span>
            <strong>{connectedCount}</strong>
          </div>
          <div className="connections-command-stat">
            <span>Channels</span>
            <strong>{channelCount}</strong>
          </div>
          <div className="connections-command-stat">
            <span>Databases</span>
            <strong>{dbCount}</strong>
          </div>
        </div>
      </section>
      <div className="connections-toolbar">
        <div className="connections-toolbar-copy">
          <div className="connections-toolbar-title">Connection control plane</div>
          <div className="connections-toolbar-subtitle">Sign in once, set trust boundaries, and give agents durable access to your real stack.</div>
        </div>
        <button className="btn btn-secondary" onClick={() => { void refresh(); }}>
          Refresh
        </button>
      </div>

      {message ? (
        <div className={`alert ${message.ok ? 'success' : 'error'}`} style={{ marginBottom: 16 }}>
          {message.text}
        </div>
      ) : null}

      <div className="info-box" style={{ marginBottom: 16 }}>
        <span className="info-icon">i</span>
        <span>
          Connect systems in this order for the smoothest setup: sign in, test the connection, then set agent access and confirmation rules. That sequence gives the assistant real power without making it feel unsafe or over-permissioned.
        </span>
      </div>
      <div className="workspace-guide-grid" style={{ marginBottom: 16 }}>
        <div className="workspace-guide-card">
          <div className="workspace-guide-title">Identity first</div>
          <p>Start with GitHub, Google Workspace, and Slack so the assistant understands your code, docs, calendar, and team context before deeper automation.</p>
        </div>
        <div className="workspace-guide-card">
          <div className="workspace-guide-title">Data next</div>
          <p>Open Database BI after the connection is saved. That workspace gives you schema-aware analysis, persistent drafts, and explicit model routing.</p>
        </div>
        <div className="workspace-guide-card">
          <div className="workspace-guide-title">Guard mutations</div>
          <p>Leave confirmation enabled for deploy, comms, and write paths. Agents stay friendly and fast, but humans still control the high-impact edge.</p>
        </div>
      </div>

      <div className="card connections-hero-card" style={{ marginBottom: 16 }}>
        <div className="connections-hero-body">
          <SectionTitle
            title="Agent Connection Hub"
            subtitle="Connect the systems your agents should understand and act on. Start with fundamentals, then expand into delivery, channels, and data."
          />
          <div className="connections-hero-stats">
            <div className="connections-stat-card">
              <div className="connections-stat-value">{connectedCount}</div>
              <div className="connections-stat-label">Live integrations</div>
            </div>
            <div className="connections-stat-card">
              <div className="connections-stat-value">{channelCount}</div>
              <div className="connections-stat-label">Configured channels</div>
            </div>
            <div className="connections-stat-card">
              <div className="connections-stat-value">{dbCount}</div>
              <div className="connections-stat-label">Live databases</div>
            </div>
          </div>
          <CapabilityList items={recommended} />
        </div>
      </div>

      {loading ? (
        <div className="card">
          <div style={{ padding: '16px 18px', color: 'var(--text-secondary)' }}>Loading connections…</div>
        </div>
      ) : (
        <>
          <SectionTitle
            title="Fundamentals"
            subtitle="These are the highest-leverage connections for agent workflows."
          />

          <GitHubOAuthCard
            config={config}
            integrations={integrations}
            onSave={save}
            onRefresh={refresh}
          />

          <GoogleWorkspaceCard config={config} integrations={integrations} onSave={save} onRefresh={refresh} />

          <SlackConnectionCard
            config={config}
            integrations={integrations}
            channel={slackChannel}
            onRefresh={refresh}
            onSave={save}
          />

          <SectionTitle
            title="Delivery"
            subtitle="Project and knowledge systems that give agents operational context."
          />

          <IntegrationApiCard
            title="Jira"
            apiName="jira"
            defaultBaseUrl="https://your-domain.atlassian.net/rest/api/3"
            defaultAuthType="bearer"
            capabilities={['Read issues', 'Update status', 'Create work items', 'Link agent work to delivery']}
            config={config}
            integrations={integrations}
            onSave={save}
          />

          <IntegrationApiCard
            title="Notion"
            apiName="notion"
            defaultBaseUrl="https://api.notion.com/v1"
            defaultAuthType="bearer"
            capabilities={['Search docs', 'Summarize specs', 'Track decisions', 'Feed agent memory with project context']}
            config={config}
            integrations={integrations}
            onSave={save}
          />

          <VercelCard config={config} integrations={integrations} onSave={save} />

          <SectionTitle
            title="Data"
            subtitle="Operational data sources that let agents answer questions with grounded evidence."
          />

          <IntegrationApiCard
            title="Supabase"
            apiName="supabase"
            defaultBaseUrl="https://your-project.supabase.co"
            defaultAuthType="bearer"
            capabilities={['Auth settings', 'REST API access', 'Storage and edge context', 'Project-backed product data']}
            config={config}
            integrations={integrations}
            onSave={save}
          />

          <DatabaseConnectionCard connections={dbConnections} />
        </>
      )}
      </div>
    </div>
  );
}
