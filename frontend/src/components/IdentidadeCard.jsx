import Badge from '@leafygreen-ui/badge';
import Banner from '@leafygreen-ui/banner';

/** Verificação de identidade: a foto do cliente bate com as fotos de referência
 * do SKU (catalogo_fotos, $vectorSearch)? Sinal de produto certo/errado — não
 * de defeito, que continua sendo decisão do Claude via VeredictoCard. */
export default function IdentidadeCard({ identidade }) {
  if (!identidade) return null;
  const { sku, score, top_sku, top_score, fotos_comparadas, abaixo_threshold } = identidade;

  if (score === null) {
    return (
      <div className="card neutral">
        <div className="card-header">
          <span className="card-title">Verificação de identidade do produto</span>
          <Badge variant="lightgray">sem fotos de referência</Badge>
        </div>
        <p className="dim" style={{ marginTop: 8 }}>
          Catálogo ainda não tem fotos seedadas em catalogo_fotos — etapa pulada.
        </p>
      </div>
    );
  }

  const pct = Math.round(score * 100);
  const disputa = top_sku && top_sku !== sku;

  return (
    <div className="card neutral">
      <div className="card-header">
        <span className="card-title">Verificação de identidade do produto</span>
        <Badge variant={abaixo_threshold ? 'red' : 'green'}>{pct}% de similaridade</Badge>
      </div>
      <p className="dim" style={{ marginTop: 8 }}>
        Comparado ($vectorSearch) com {fotos_comparadas} foto(s) de referência do catálogo inteiro —
        o SKU do pedido precisa ser o melhor match entre todos, não só "parecido o bastante" sozinho.
        Embedding multimodal Voyage AI mede semelhança semântica, não detecta o defeito em si.
      </p>
      {abaixo_threshold && disputa && (
        <Banner variant="warning" darkMode style={{ marginTop: 10 }}>
          Essa foto parece mais com <b>{top_sku}</b> ({Math.round(top_score * 100)}%) do que com o
          produto do pedido ({sku}, {pct}%) — pode ser upload errado. Confirmar manualmente antes de aprovar.
        </Banner>
      )}
      {abaixo_threshold && !disputa && (
        <Banner variant="warning" darkMode style={{ marginTop: 10 }}>
          Similaridade baixa mesmo sendo o melhor match do catálogo — a foto pode não ser de
          nenhum produto conhecido. Confirmar manualmente antes de aprovar.
        </Banner>
      )}
    </div>
  );
}
