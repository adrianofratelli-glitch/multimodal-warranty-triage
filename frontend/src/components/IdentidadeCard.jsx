import Badge from '@leafygreen-ui/badge';
import Banner from '@leafygreen-ui/banner';
import { statusIdentidade } from '../lib/triagem.js';

/** Verificação de identidade: a foto do cliente bate com as fotos de referência
 * do SKU (catalogo_fotos, $vectorSearch só com o vetor da imagem)? Sinal de
 * produto certo/errado — não de defeito, que continua sendo decisão do Claude
 * via VeredictoCard. Estados (backend/rag.py::decidir_identidade): aprovado,
 * inconclusivo (revisar), divergente, sem_referencia (SKU sem foto no catálogo). */
const ROTULO = {
  aprovado: { badge: 'green', texto: 'confere' },
  inconclusivo: { badge: 'yellow', texto: 'inconclusivo — revisar' },
  divergente: { badge: 'red', texto: 'divergente' },
  sem_referencia: { badge: 'lightgray', texto: 'sem referência no catálogo' },
};

const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`);

export default function IdentidadeCard({ identidade }) {
  if (!identidade) return null;
  const { sku, score, concorrente_sku, concorrente_score, fotos_comparadas } = identidade;
  // Chamados antigos não têm `status`: derivado do booleano legado (lib/triagem.js).
  const status = statusIdentidade(identidade);
  const motivo = identidade.motivo_chamado || identidade.motivo;
  const rotulo = ROTULO[status] || ROTULO.inconclusivo;

  return (
    <div className="card neutral">
      <div className="card-header">
        <span className="card-title">Verificação de identidade do produto</span>
        <Badge variant={rotulo.badge}>
          {rotulo.texto}{score != null ? ` · ${pct(score)}` : ''}
        </Badge>
      </div>
      <p className="dim" style={{ marginTop: 8 }}>
        Foto comparada ($vectorSearch, só a imagem) com {fotos_comparadas} foto(s) de referência do catálogo inteiro.
        O SKU do pedido ({sku}) precisa vencer o produto mais parecido seguinte
        {concorrente_sku ? <> ({concorrente_sku}, {pct(concorrente_score)})</> : null} por margem mínima; empate
        entre variantes vai para revisão. Embedding multimodal Voyage AI mede semelhança, não detecta o defeito.
      </p>
      {status !== 'aprovado' && motivo && (
        <Banner variant={status === 'divergente' ? 'danger' : 'warning'} darkMode style={{ marginTop: 10 }}>
          {motivo} Confirmar manualmente antes de aprovar.
        </Banner>
      )}
    </div>
  );
}
