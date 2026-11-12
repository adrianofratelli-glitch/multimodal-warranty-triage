import Badge from '@leafygreen-ui/badge';
import { confiancaPct, grauConfianca } from '../lib/triagem.js';

const ROTULO = {
  defeito_fabrica: { txt: 'Defeito de fábrica', variant: 'red' },
  defeito_transporte: { txt: 'Defeito de transporte', variant: 'yellow' },
  mau_uso: { txt: 'Mau uso', variant: 'lightgray' },
  inconclusivo: { txt: 'Inconclusivo', variant: 'blue' },
};

/** Card de veredito: classificação + barra de confiança + aviso de revisão humana. */
export default function VeredictoCard({ veredito, modoBusca }) {
  if (!veredito) return null;
  const r = ROTULO[veredito.classificacao] || { txt: veredito.classificacao, variant: 'darkgray' };
  const pct = confiancaPct(veredito.confianca);
  const grau = grauConfianca(pct);

  return (
    <div className="card neutral">
      <div className="card-header">
        <span className="card-title">Veredito da triagem</span>
        <Badge variant={r.variant}>{r.txt}</Badge>
        <Badge variant={grau.variant}>{grau.txt}</Badge>
      </div>

      <div className="conf-row">
        <span className="conf-label">confiança</span>
        <div className="conf-track">
          <div className="conf-fill" style={{ width: `${pct}%` }} />
        </div>
        <span className="conf-pct mono">{pct}%</span>
      </div>

      <p style={{ marginTop: 12, color: 'var(--text-sec)' }}>{veredito.racional}</p>

      {veredito.alerta_manipulacao && (
        <div className="alerta-manipulacao" role="alert">
          <strong>⚠ Possível tentativa de manipulação</strong> — confiança limitada a 50%.
          Revise o relato e as fotos antes de decidir.
          {veredito.alertas?.length > 0 && (
            <ul>{veredito.alertas.map((a, i) => <li key={i}>{a}</li>)}</ul>
          )}
        </div>
      )}

      {veredito.sinais_observados?.length > 0 && (
        <ul className="sinais" aria-label="Sinais observados na foto">
          {veredito.sinais_observados.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      )}

      <div className="aviso-humano">
        ⚠ Sujeito a revisão humana — não é decisão final (risco CDC).
      </div>

      {veredito._meta && (
        <div className="dim mono" style={{ marginTop: 8, fontSize: 11 }}>
          {veredito._meta.mode === 'manual_review_fallback'
            ? 'triagem automática indisponível · caso preservado para revisão manual · '
            : ''}
          {veredito._meta.precedentes_usados} precedentes recuperados
          {modoBusca === 'idempotent_replay' ? ' no envio original' : modoBusca ? ` via ${modoBusca === 'hybrid' ? '$rankFusion' : '$vectorSearch'}` : ''} ·
          {' '}{veredito._meta.latency_ms}ms de triagem
        </div>
      )}
    </div>
  );
}
