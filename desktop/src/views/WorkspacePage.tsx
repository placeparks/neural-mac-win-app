import { useCallback, useEffect, useState } from 'react';
import Header from '../components/layout/Header';
import {
  getWorkspaceProjects,
  getAvailableSkills,
  getWorkspaceClaims,
  scaffoldProject,
  getProjectInfo,
  getSkillTemplate,
  releaseWorkspaceDir,
  type ProjectInfo,
  type SkillInfo,
  type WorkspaceClaim,
} from '../lib/api';

// ─── helpers ────────────────────────────────────────────────────────────────

const TEMPLATES = [
  { id: 'python-service', label: 'Python Service', desc: 'src/, tests/, Dockerfile, Makefile' },
  { id: 'python-lib', label: 'Python Library', desc: 'Library layout with typed stubs' },
  { id: 'fastapi', label: 'FastAPI App', desc: 'app/routers, models, Dockerfile' },
  { id: 'cli-tool', label: 'CLI Tool', desc: 'Argparse CLI with setup.py' },
  { id: 'data-pipeline', label: 'Data Pipeline', desc: 'src/, data/raw, notebooks/' },
  { id: 'agent-skill', label: 'Agent Skill', desc: 'NeuralClaw skill layout + tests' },
  { id: 'generic', label: 'Generic', desc: 'Flat project structure' },
];

const COMPONENTS = ['dockerfile', 'ci_github', 'ci_gitlab', 'makefile', 'test'];

function ts(epoch: number) {
  return new Date(epoch * 1000).toLocaleString();
}

// ─── sub-components ──────────────────────────────────────────────────────────

function SectionHeader({ title, count }: { title: string; count?: number }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
      <h2 style={{ margin: 0, fontSize: 13, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--text-muted)' }}>
        {title}
      </h2>
      {count !== undefined && (
        <span style={{ fontSize: 11, background: 'var(--accent)', color: '#fff', borderRadius: 10, padding: '1px 7px', fontWeight: 600 }}>
          {count}
        </span>
      )}
    </div>
  );
}

function Card({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{
      background: 'var(--surface)',
      border: '1px solid var(--border)',
      borderRadius: 10,
      padding: 16,
      ...style,
    }}>
      {children}
    </div>
  );
}

// ─── Scaffold Modal ──────────────────────────────────────────────────────────

function ScaffoldModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState('');
  const [template, setTemplate] = useState('python-service');
  const [desc, setDesc] = useState('');
  const [author, setAuthor] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; path?: string; files_created?: string[]; error?: string } | null>(null);

  const submit = async () => {
    if (!name.trim()) return;
    setLoading(true);
    try {
      const r = await scaffoldProject({
        project_name: name.trim(),
        template,
        description: desc,
        author,
        claim_directory: true,
      });
      setResult(r);
      if (r.ok) onDone();
    } catch (e: any) {
      setResult({ ok: false, error: e.message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200,
    }} onClick={onClose}>
      <div style={{
        background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: 12, padding: 24, width: 480, maxHeight: '80vh', overflowY: 'auto',
      }} onClick={e => e.stopPropagation()}>
        <h2 style={{ margin: '0 0 16px', fontSize: 16 }}>Scaffold New Project</h2>

        <label style={{ display: 'block', marginBottom: 12 }}>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>Project Name *</div>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="my-project"
            style={{ width: '100%', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 10px', color: 'inherit', fontSize: 14 }}
          />
        </label>

        <label style={{ display: 'block', marginBottom: 12 }}>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>Template</div>
          <select
            value={template}
            onChange={e => setTemplate(e.target.value)}
            style={{ width: '100%', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 10px', color: 'inherit', fontSize: 14 }}
          >
            {TEMPLATES.map(t => (
              <option key={t.id} value={t.id}>{t.label} — {t.desc}</option>
            ))}
          </select>
        </label>

        <label style={{ display: 'block', marginBottom: 12 }}>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>Description</div>
          <input
            value={desc}
            onChange={e => setDesc(e.target.value)}
            placeholder="Brief description of the project"
            style={{ width: '100%', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 10px', color: 'inherit', fontSize: 14 }}
          />
        </label>

        <label style={{ display: 'block', marginBottom: 16 }}>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>Author</div>
          <input
            value={author}
            onChange={e => setAuthor(e.target.value)}
            placeholder="Your name"
            style={{ width: '100%', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 10px', color: 'inherit', fontSize: 14 }}
          />
        </label>

        {result && (
          <div style={{
            padding: '8px 12px', borderRadius: 6, marginBottom: 12, fontSize: 13,
            background: result.ok ? 'rgba(63,185,80,0.1)' : 'rgba(248,81,73,0.1)',
            border: `1px solid ${result.ok ? 'var(--green)' : 'var(--red)'}`,
            color: result.ok ? 'var(--green)' : 'var(--red)',
          }}>
            {result.ok
              ? `Created at ${result.path} — ${result.files_created?.length ?? 0} files`
              : `Error: ${result.error}`}
          </div>
        )}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ padding: '6px 14px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'inherit', cursor: 'pointer', fontSize: 13 }}>
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={loading || !name.trim()}
            style={{ padding: '6px 14px', borderRadius: 6, border: 'none', background: 'var(--accent)', color: '#fff', cursor: 'pointer', fontSize: 13, opacity: loading || !name.trim() ? 0.6 : 1 }}
          >
            {loading ? 'Creating...' : 'Create Project'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Project Card ────────────────────────────────────────────────────────────

function ProjectCard({ project, onSelect }: { project: ProjectInfo; onSelect: (p: ProjectInfo) => void }) {
  return (
    <div
      onClick={() => onSelect(project)}
      className="workspace-project-card"
    >
      <div className="workspace-project-title">{project.name}</div>
      {project.template && (
        <span className="workspace-project-badge">
          {project.template}
        </span>
      )}
      {project.description && (
        <div className="workspace-project-description">{project.description}</div>
      )}
      {project.created_at && (
        <div className="workspace-project-meta">{project.created_at}</div>
      )}
    </div>
  );
}

// ─── Project Detail Panel ────────────────────────────────────────────────────

function ProjectDetailPanel({ name, onClose }: { name: string; onClose: () => void }) {
  const [info, setInfo] = useState<ProjectInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [component, setComponent] = useState('dockerfile');
  const [adding, setAdding] = useState(false);
  const [addResult, setAddResult] = useState('');

  useEffect(() => {
    setLoading(true);
    getProjectInfo(name).then(r => { setInfo(r); setLoading(false); }).catch(() => setLoading(false));
  }, [name]);

  const addComponent = async () => {
    setAdding(true);
    try {
      const { addToProject } = await import('../lib/api');
      const r = await addToProject(name, component);
      setAddResult(r.ok ? `Added: ${r.added?.join(', ') ?? component}` : `Error: ${r.error}`);
    } catch (e: any) {
      setAddResult(`Error: ${e.message}`);
    } finally {
      setAdding(false);
    }
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200,
    }} onClick={onClose}>
      <div style={{
        background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: 12, padding: 24, width: 560, maxHeight: '80vh', overflowY: 'auto',
      }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>{name}</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 18 }}>✕</button>
        </div>

        {loading && <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Loading...</div>}

        {info && (
          <>
            {info.path && (
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12, fontFamily: 'monospace', background: 'var(--bg)', padding: '4px 8px', borderRadius: 4 }}>
                {info.path}
              </div>
            )}

            {info.description && (
              <div style={{ fontSize: 13, marginBottom: 12 }}>{info.description}</div>
            )}

            {info.agents_md && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>AGENTS.md</div>
                <pre style={{
                  background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6,
                  padding: '10px 12px', fontSize: 11, overflowX: 'auto', whiteSpace: 'pre-wrap',
                  maxHeight: 240, overflowY: 'auto', margin: 0,
                }}>
                  {info.agents_md}
                </pre>
              </div>
            )}

            {info.files && info.files.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>Files ({info.files.length})</div>
                <div style={{ maxHeight: 120, overflowY: 'auto', fontSize: 12, fontFamily: 'monospace', color: 'var(--text-muted)' }}>
                  {info.files.map(f => <div key={f}>{f}</div>)}
                </div>
              </div>
            )}

            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <select
                value={component}
                onChange={e => setComponent(e.target.value)}
                style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6, padding: '5px 8px', color: 'inherit', fontSize: 13 }}
              >
                {COMPONENTS.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
              <button
                onClick={addComponent}
                disabled={adding}
                style={{ padding: '5px 12px', borderRadius: 6, border: 'none', background: 'var(--accent)', color: '#fff', cursor: 'pointer', fontSize: 13 }}
              >
                {adding ? 'Adding...' : 'Add Component'}
              </button>
              {addResult && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{addResult}</span>}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ─── Skills Panel ────────────────────────────────────────────────────────────

function SkillsPanel() {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all');
  const [template, setTemplate] = useState('');
  const [templateType, setTemplateType] = useState('basic');
  const [loadingTemplate, setLoadingTemplate] = useState(false);

  useEffect(() => {
    setLoading(true);
    getAvailableSkills(filter)
      .then(r => { setSkills(r.skills || []); setLoading(false); })
      .catch(() => setLoading(false));
  }, [filter]);

  const loadTemplate = async () => {
    setLoadingTemplate(true);
    try {
      const r = await getSkillTemplate(templateType);
      setTemplate(r.template || '');
    } catch {
      setTemplate('Failed to load template');
    } finally {
      setLoadingTemplate(false);
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        {(['all', 'builtin', 'user'] as const).map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            style={{
              padding: '4px 10px', borderRadius: 20, border: '1px solid var(--border)',
              background: filter === f ? 'var(--accent)' : 'transparent',
              color: filter === f ? '#fff' : 'inherit',
              cursor: 'pointer', fontSize: 12,
            }}
          >
            {f}
          </button>
        ))}
        <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-muted)' }}>
          {loading ? 'Loading...' : `${skills.length} skills`}
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 8, marginBottom: 20 }}>
        {skills.map(s => (
          <div key={s.name} style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 12px' }}>
            <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>{s.name}</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>{s.description}</div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 10, background: 'rgba(88,166,255,0.1)', color: 'var(--accent)', borderRadius: 4, padding: '1px 5px' }}>
                {s.source}
              </span>
              <span style={{ fontSize: 10, background: 'rgba(255,255,255,0.05)', borderRadius: 4, padding: '1px 5px', color: 'var(--text-muted)' }}>
                {s.tool_count} tools
              </span>
            </div>
          </div>
        ))}
      </div>

      <div style={{ borderTop: '1px solid var(--border)', paddingTop: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>Skill Template</div>
        <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
          <select
            value={templateType}
            onChange={e => setTemplateType(e.target.value)}
            style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6, padding: '5px 8px', color: 'inherit', fontSize: 13 }}
          >
            {['basic', 'api', 'filesystem', 'stateful'].map(t => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          <button
            onClick={loadTemplate}
            disabled={loadingTemplate}
            style={{ padding: '5px 12px', borderRadius: 6, border: 'none', background: 'var(--accent)', color: '#fff', cursor: 'pointer', fontSize: 13 }}
          >
            {loadingTemplate ? 'Loading...' : 'Load Template'}
          </button>
        </div>
        {template && (
          <pre style={{
            background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6,
            padding: '12px', fontSize: 11, overflowX: 'auto', whiteSpace: 'pre-wrap',
            maxHeight: 320, overflowY: 'auto', margin: 0,
          }}>
            {template}
          </pre>
        )}
      </div>
    </div>
  );
}

// ─── Claims Panel ────────────────────────────────────────────────────────────

function ClaimsPanel({ claims, onRelease }: { claims: WorkspaceClaim[]; onRelease: (path: string) => void }) {
  if (!claims.length) {
    return <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>No active workspace claims.</div>;
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {claims.map(c => (
        <div key={c.claim_id} style={{
          background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 8,
          padding: '10px 12px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
        }}>
          <div>
            <div style={{ fontWeight: 600, fontSize: 13, fontFamily: 'monospace' }}>{c.path}</div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
              Agent: <b style={{ color: 'var(--accent)' }}>{c.agent_name}</b>
              {c.purpose && ` — ${c.purpose}`}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>Claimed: {ts(c.claimed_at)}</div>
          </div>
          <button
            onClick={() => onRelease(c.path)}
            style={{ padding: '3px 10px', borderRadius: 6, border: '1px solid var(--red)', background: 'transparent', color: 'var(--red)', cursor: 'pointer', fontSize: 11, whiteSpace: 'nowrap' }}
          >
            Release
          </button>
        </div>
      ))}
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

type Tab = 'projects' | 'skills' | 'claims';

export default function WorkspacePage() {
  const [tab, setTab] = useState<Tab>('projects');
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [claims, setClaims] = useState<WorkspaceClaim[]>([]);
  const [skillsCount, setSkillsCount] = useState(0);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [loadingClaims, setLoadingClaims] = useState(false);
  const [scaffoldOpen, setScaffoldOpen] = useState(false);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);

  const loadProjects = useCallback(async () => {
    setLoadingProjects(true);
    try {
      const r = await getWorkspaceProjects();
      setProjects(r.projects || []);
    } catch {
      setProjects([]);
    } finally {
      setLoadingProjects(false);
    }
  }, []);

  const loadClaims = useCallback(async () => {
    setLoadingClaims(true);
    try {
      const c = await getWorkspaceClaims();
      setClaims(Array.isArray(c) ? c : []);
    } catch {
      setClaims([]);
    } finally {
      setLoadingClaims(false);
    }
  }, []);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    getAvailableSkills('all')
      .then((result) => setSkillsCount((result.skills || []).length))
      .catch(() => setSkillsCount(0));
  }, []);

  useEffect(() => {
    if (tab === 'claims') loadClaims();
  }, [tab, loadClaims]);

  const handleRelease = async (path: string) => {
    try {
      await releaseWorkspaceDir(path);
      loadClaims();
    } catch {
      // ignore
    }
  };

  return (
    <div className="view-container">
      <Header title="Workspace" subtitle="Projects, skills, and agent workspace coordination" />
      <div className="page-body">
        <div className="workspace-shell">
          <div className="workspace-topbar">
            <div>
              <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>Workspace</h1>
              <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4 }}>
                Coordinate projects, reusable skills, and active workspace claims.
              </div>
            </div>
            {tab === 'projects' && (
              <button
                className="btn btn-primary"
                onClick={() => setScaffoldOpen(true)}
              >
                + Scaffold Project
              </button>
            )}
          </div>

          <div className="info-box" style={{ marginBottom: 16 }}>
            <span className="info-icon">i</span>
            <span>
              Workspace is where agent work becomes reusable. Projects are scaffolded delivery surfaces, Skills are capability building blocks, and Claims prevent multiple agents from colliding in the same directory.
            </span>
          </div>

          <div className="workspace-tabs">
            {(['projects', 'skills', 'claims'] as Tab[]).map(t => (
              <button
                key={t}
                className={`workspace-tab ${tab === t ? 'active' : ''}`}
                onClick={() => setTab(t)}
              >
                <span>{t}</span>
                <span className="workspace-tab-count">
                  {t === 'projects' ? projects.length : t === 'skills' ? skillsCount : claims.length}
                </span>
              </button>
            ))}
          </div>

          {tab === 'projects' && (
            <div>
              <SectionHeader title="Projects" count={projects.length} />
              <div className="info-box" style={{ marginBottom: 16 }}>
                <span className="info-icon">i</span>
                <span>
                  Start here when you want the system to create a new working area with sensible structure. Each scaffolded project gets its own orientation file so future agents understand the layout immediately.
                </span>
              </div>
              {loadingProjects ? (
                <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Loading projects...</div>
              ) : projects.length === 0 ? (
                <Card>
                  <div style={{ textAlign: 'center', padding: '32px 0', color: 'var(--text-muted)' }}>
                    <div style={{ fontSize: 32, marginBottom: 12 }}>📂</div>
                    <div style={{ fontSize: 14, marginBottom: 8 }}>No projects yet</div>
                    <div style={{ fontSize: 13, marginBottom: 16 }}>Create a project from a template to get started</div>
                    <button
                      className="btn btn-primary"
                      onClick={() => setScaffoldOpen(true)}
                    >
                      Scaffold First Project
                    </button>
                  </div>
                </Card>
              ) : (
                <div className="workspace-grid">
                  {projects.map(p => (
                    <ProjectCard key={p.name} project={p} onSelect={p => setSelectedProject(p.name)} />
                  ))}
                </div>
              )}
            </div>
          )}

          {tab === 'skills' && (
            <div>
              <SectionHeader title="Available Skills" />
              <div className="info-box" style={{ marginBottom: 16 }}>
                <span className="info-icon">i</span>
                <span>
                  Skills are how the agent learns repeatable powers. Use built-ins to inspect what exists, templates to create new skills, and Skill Forge when you want the agent to synthesize a capability from docs, APIs, or libraries.
                </span>
              </div>
              <SkillsPanel />
            </div>
          )}

          {tab === 'claims' && (
            <div>
              <div className="workspace-topbar" style={{ marginBottom: 12 }}>
                <SectionHeader title="Workspace Claims" count={claims.length} />
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={loadClaims}
                  disabled={loadingClaims}
                >
                  {loadingClaims ? 'Refreshing...' : 'Refresh'}
                </button>
              </div>
              <div className="info-box" style={{ marginBottom: 16 }}>
                <span className="info-icon">i</span>
                <span>
                  Claims are coordination locks. If two agents need the same repo or app folder, claim it first, release it when done, and use this view to clear stale ownership when a run was interrupted.
                </span>
              </div>
              <ClaimsPanel claims={claims} onRelease={handleRelease} />
            </div>
          )}
        </div>
      </div>

      {/* Modals */}
      {scaffoldOpen && (
        <ScaffoldModal
          onClose={() => setScaffoldOpen(false)}
          onDone={() => { setScaffoldOpen(false); loadProjects(); }}
        />
      )}
      {selectedProject && (
        <ProjectDetailPanel
          name={selectedProject}
          onClose={() => setSelectedProject(null)}
        />
      )}
    </div>
  );
}
