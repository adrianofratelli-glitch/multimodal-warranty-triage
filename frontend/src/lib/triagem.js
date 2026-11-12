// Regras puras de apresentação da triagem (sem React), testadas em
// frontend/tests/triagem.test.mjs. Os componentes só desenham o que sai daqui.

/** Graus de confiança do veredito: <40% baixa, 40-70% moderada, >=70% alta. */
export function grauConfianca(pct) {
  if (pct >= 70) return { txt: 'confiança alta', variant: 'green' };
  if (pct >= 40) return { txt: 'confiança moderada', variant: 'yellow' };
  return { txt: 'confiança baixa', variant: 'red' };
}

/** Confiança 0..1 (ou ausente) -> inteiro 0..100, limitado. */
export function confiancaPct(confianca) {
  const v = Number(confianca);
  if (!Number.isFinite(v)) return 0;
  return Math.min(100, Math.max(0, Math.round(v * 100)));
}

/**
 * Grau de match de um precedente, RELATIVO ao melhor score da mesma busca.
 * Com $rerank o score é a relevância do reranker; sem ele, o do $rankFusion é RRF (soma de peso/(60+posição)), sempre ~0,01-0,02
 * por construção: o número cru não diz se o match é fraco. A lista já vem
 * ordenada desc, então o primeiro é o 100%.
 */
export function grauMatch(score, maxScore) {
  const max = Number(maxScore) > 0 ? Number(maxScore) : 1;
  const rel = Math.round((Number(score) / max) * 100);
  if (rel >= 70) return { txt: 'match forte', variant: 'green', rel };
  if (rel >= 40) return { txt: 'match moderado', variant: 'yellow', rel };
  return { txt: 'match fraco', variant: 'lightgray', rel };
}

/** Rótulo do estágio de recuperação conforme o modo que o backend de fato usou. */
export function rotuloBusca(modo) {
  if (modo === 'hybrid') return '$rankFusion';
  if (modo === 'vector_fallback') return '$vectorSearch — fallback';
  return '$vectorSearch';
}

export const STATUS_IDENTIDADE = ['aprovado', 'inconclusivo', 'divergente', 'sem_referencia'];

/**
 * Status de identidade a exibir. Preferência: status do chamado (pior entre foto
 * principal e extras) > status da foto principal > booleano legado de chamados
 * antigos (abaixo_threshold). Status desconhecido vira "inconclusivo" (revisar),
 * nunca "aprovado".
 */
export function statusIdentidade(identidade) {
  if (!identidade) return null;
  const s = identidade.status_chamado || identidade.status
    || (identidade.abaixo_threshold === undefined ? null : (identidade.abaixo_threshold ? 'divergente' : 'aprovado'));
  return STATUS_IDENTIDADE.includes(s) ? s : 'inconclusivo';
}

/**
 * Badge do $rerank a partir de funnel.rerank (backend/rag.py::_executar):
 * aplicado -> "reordenado por $rerank (<modelo>)"; falhou -> aviso com o motivo;
 * desligado ou chamado antigo sem o campo -> nada.
 */
export function rotuloRerank(rerank) {
  if (!rerank) return null;
  if (rerank.aplicado) return { txt: `reordenado por $rerank (${rerank.modelo})`, variant: 'blue', falhou: false };
  if (rerank.motivo && rerank.motivo !== 'desligado') {
    return { txt: '$rerank indisponível — ordem da busca', variant: 'yellow', falhou: true, motivo: rerank.motivo };
  }
  return null;
}

/**
 * Título do passo "Busca de precedentes" a partir do que o backend devolveu
 * (funnel.modo e funnel.rerank). Antes da resposta, descreve o caminho pedido
 * com o $rerank padrão; depois, só o que de fato rodou.
 */
export function rotuloPassoBusca(funnel, modoPedido = 'hybrid') {
  if (!funnel) {
    return `Busca de precedentes (Atlas ${modoPedido === 'hybrid' ? '$rankFusion' : '$vectorSearch'} + $rerank)`;
  }
  if (funnel.modo === 'idempotent_replay') return 'Busca de precedentes (não repetida: envio idêntico)';
  const rerank = funnel.rerank?.aplicado ? ' + $rerank' : '';
  return `Busca de precedentes (Atlas ${rotuloBusca(funnel.modo)}${rerank})`;
}
