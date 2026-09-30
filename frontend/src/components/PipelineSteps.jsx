/** Pipeline steps: pending (gray) → running (spinner) → done (green check). */
export default function PipelineSteps({ steps }) {
  return (
    <div>
      {steps.map((s) => (
        <div className="pipeline-step" key={s.key}>
          <div className={`step-icon ${s.status}`}>
            {s.status === 'done' ? '✓' : s.status === 'running' ? <div className="spinner" /> : s.index}
          </div>
          <div className="step-body">
            <div className="step-title">{s.title}</div>
            {s.detail && <div className="dim" style={{ fontSize: 11, marginTop: 2 }}>{s.detail}</div>}
            {s.status === 'pending' && <span className="dim">aguardando…</span>}
            {s.status === 'running' && <span className="dim">{s.runningLabel}</span>}
            {s.status === 'done' && s.content}
          </div>
        </div>
      ))}
    </div>
  );
}
