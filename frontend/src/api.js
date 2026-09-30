// O prazo cobre headers, corpo e as tentativas já previstas pelo cliente.
async function boundedRequest(work, timeoutMs = 30000) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try { return await work(controller.signal) }
  finally { clearTimeout(timer) }
}

// HTTP client. Backend errors arrive as {error: {kind, message}} (503) and
// become ApiError — the UI shows them in a yellow Banner, never a stack trace.

export class ApiError extends Error {
  constructor(kind, message) {
    super(message);
    this.kind = kind;
  }
}

// O proxy do Vite devolve 500 quando o backend ainda não está escutando
// (ECONNREFUSED no boot). Sem corpo {error}, isso vira um banner "Erro HTTP 500"
// que não descreve nada. Tratamos 500/502/503/504 sem corpo de domínio como
// indisponibilidade transitória e repetimos algumas vezes antes de desistir.
const RETRY_STATUS = new Set([500, 502, 503, 504]);
const RETRIES = 4;
const RETRY_DELAY_MS = 700;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function send(path, init, attempt) {
  let res;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError('rede', 'Backend não respondeu. O FastAPI está rodando na porta 8100?');
  }
  const body = await res.json().catch(() => {
    if (res.ok) throw new Error('Resposta incompleta ou inválida do backend. Tente novamente.')
    return {}
  });
  if (res.ok) return body;

  const err = body.error || {};
  // Sem {error} no corpo a falha veio do proxy/infra, não do domínio.
  if (!body.error && RETRY_STATUS.has(res.status) && attempt < RETRIES) {
    await sleep(RETRY_DELAY_MS * (attempt + 1));
    return send(path, init, attempt + 1);
  }
  if (!body.error && RETRY_STATUS.has(res.status)) {
    throw new ApiError('indisponivel', 'Backend ainda subindo ou indisponível na porta 8100. Recarregue em instantes.');
  }
  throw new ApiError(err.kind || 'erro', err.message || `Erro HTTP ${res.status}`);
}

async function request(path, options = {}) {
  return boundedRequest(async (signal) => {
    return send(path, { headers: { 'Content-Type': 'application/json' }, ...options, signal }, 0);
  }, 30000)
}

async function upload(path, formData) {
  return boundedRequest(async (signal) => {
    // multipart — sem Content-Type manual (o browser põe o boundary).
    // Sem retry: POST /api/analisar não é idempotente (insere um chamado).
    return send(path, { method: 'POST', body: formData, signal }, RETRIES);
  }, 300000)
}

export const api = {
  health: () => request('/api/health'),
  pedidos: () => request('/api/pedidos'),
  lookup: (numero_pedido) =>
    request('/api/lookup', { method: 'POST', body: JSON.stringify({ numero_pedido }) }),
  checklist: (categoria) => request(`/api/checklist/${categoria}`),
  analisar: (formData) => upload('/api/analisar', formData),
  // cursor: { created_at, id } de um next_cursor anterior — paginação real,
  // sem isso casos com mais de 50 pendentes ficavam invisíveis para sempre.
  pendentes: (cursor) => {
    const params = new URLSearchParams();
    if (cursor?.created_at) params.set('before_created_at', cursor.created_at);
    if (cursor?.id) params.set('before_id', cursor.id);
    const qs = params.toString();
    return request(`/api/chamados/pendentes${qs ? `?${qs}` : ''}`);
  },
  revisar: (numero_chamado, resolucao_final) =>
    request('/api/revisar', {
      method: 'POST',
      body: JSON.stringify({ numero_chamado, resolucao_final }),
    }),
};
