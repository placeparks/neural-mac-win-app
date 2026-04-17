export type AutonomyModeValue =
  | 'observe-only'
  | 'suggest-first'
  | 'auto-run-low-risk'
  | 'policy-driven-autonomous';

export type AutonomyProfileId =
  | 'hands-off'
  | 'suggest-first'
  | 'guarded-auto-run'
  | 'trusted-workspace-auto-run';

export interface AutonomyProfile {
  id: AutonomyProfileId;
  mode: AutonomyModeValue;
  label: string;
  shortLabel: string;
  description: string;
  executionLabel: string;
}

export const AUTONOMY_PROFILES: AutonomyProfile[] = [
  {
    id: 'hands-off',
    mode: 'observe-only',
    label: 'Hands-off',
    shortLabel: 'Hands-off',
    description: 'The agent observes, explains, and plans, but does not autonomously execute follow-up actions.',
    executionLabel: 'Observation only',
  },
  {
    id: 'suggest-first',
    mode: 'suggest-first',
    label: 'Suggest first',
    shortLabel: 'Suggest first',
    description: 'The agent proposes actions and drafts next steps before acting, which keeps the flow friendly and reviewable.',
    executionLabel: 'Draft before execute',
  },
  {
    id: 'guarded-auto-run',
    mode: 'auto-run-low-risk',
    label: 'Guarded auto-run',
    shortLabel: 'Guarded auto-run',
    description: 'The agent can execute low-risk work automatically while still surfacing risky or high-impact steps for review.',
    executionLabel: 'Auto-run low-risk work',
  },
  {
    id: 'trusted-workspace-auto-run',
    mode: 'policy-driven-autonomous',
    label: 'Trusted workspace auto-run',
    shortLabel: 'Trusted auto-run',
    description: 'The agent can drive trusted local workflows with policy guardrails, receipts, rollback, and visible task tracking.',
    executionLabel: 'Policy-driven autonomy',
  },
];

export function getAutonomyProfileByMode(mode?: string | null): AutonomyProfile {
  return AUTONOMY_PROFILES.find((profile) => profile.mode === mode) || AUTONOMY_PROFILES[1];
}

export function getAutonomyProfileById(id?: string | null): AutonomyProfile {
  return AUTONOMY_PROFILES.find((profile) => profile.id === id) || AUTONOMY_PROFILES[1];
}
