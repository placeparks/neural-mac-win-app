// NeuralClaw Desktop — Tool Call Card

import { useState } from 'react';
import type { ToolCall } from '../../lib/api';

interface Props {
  toolCall: ToolCall;
}

export default function ToolCallCard({ toolCall }: Props) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="tool-card">
      <div className="tool-card-header" onClick={() => setExpanded(!expanded)}>
        <span>🔧</span>
        <span>Tool: {toolCall.name}</span>
        <span style={{ marginLeft: 'auto', fontSize: 10, opacity: 0.6 }}>
          {expanded ? '▼' : '▶'}
        </span>
      </div>
      {expanded && (
        <div className="tool-card-body">
          {JSON.stringify(toolCall.arguments, null, 2)}
        </div>
      )}
      {toolCall.status && (
        <div className={`tool-card-status ${toolCall.status}`}>
          {toolCall.status === 'success' ? '✅' : toolCall.status === 'error' ? '❌' : '⏳'}
          <span>{toolCall.status === 'success' ? 'Completed' : toolCall.status === 'error' ? 'Failed' : 'Running...'}</span>
        </div>
      )}
      {toolCall.result && expanded && (
        <div className="tool-card-body" style={{ borderTop: '1px solid var(--border)' }}>
          {toolCall.result}
        </div>
      )}
    </div>
  );
}
