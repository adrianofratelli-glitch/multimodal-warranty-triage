import Badge from '@leafygreen-ui/badge';

const ROTULO = {
  defeito_fabrica: { txt: 'Defeito de fábrica', variant: 'red' },
  defeito_transporte: { txt: 'Defeito de transporte', variant: 'yellow' },
  mau_uso: { txt: 'Mau uso', variant: 'lightgray' },
  inconclusivo: { txt: 'Inconclusivo', variant: 'blue' },
};

// Graus de confiança — a classificacao (defeito_fabrica/mau_uso/...) já vem do
// veredito, mas o numero de 0 a 1 sozinho nao diz se é uma confiança forte ou
// fraca. Faixas: <40% baixa (pouca evidencia visual sustentando a causa),
// 40-70% moderada (hipotese plausivel mas nao conclusiva), >=70% alta.
const grauConfianca = (pct) => {
  if (pct >= 70) return { txt: 'confiança alta', variant: 'green' };
  if (pct >= 40) return { txt: 'confiança moderada', variant: 'yellow' };
  return { txt: 'confiança baixa', variant: 'red' };
};

/** Card de veredito: classificação + barra de confiança + aviso de revisão humana. */
export default function VeredictoCard({ veredito }) {
  if (!veredito) return null;
  const r = ROTULO[veredito.classificacao] || { txt: veredito.classificacao, variant: 'darkgray' };
  const pct = Math.round((veredito.confianca ?? 0) * 100);
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

      {veredito.sinais_observados?.length > 0 && (
        <div className="row" style={{ marginTop: 10 }}>
          {veredito.sinais_observados.map((s, i) => (
            <Badge key={i} variant="darkgray">{s}</Badge>
          ))}
        </div>
      )}

      <div className="aviso-humano">
        ⚠ Sujeito a revisão humana — não é decisão final (risco CDC).
      </div>

      {veredito._meta && (
        <div className="dim mono" style={{ marginTop: 8, fontSize: 11 }}>
          {veredito._meta.precedentes_usados} precedentes recuperados via $rankFusion ·
          {' '}{veredito._meta.latency_ms}ms de triagem
        </div>
      )}
    </div>
  );
}
