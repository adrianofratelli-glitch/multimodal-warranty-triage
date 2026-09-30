import { useEffect, useState } from 'react';
import Badge from '@leafygreen-ui/badge';
import Banner from '@leafygreen-ui/banner';
import Button from '@leafygreen-ui/button';
import { Option, Select } from '@leafygreen-ui/select';
import TextInput from '@leafygreen-ui/text-input';
import IdentidadeCard from '../components/IdentidadeCard.jsx';
import JsonViewer from '../components/JsonViewer.jsx';
import PipelineSteps from '../components/PipelineSteps.jsx';
import VeredictoCard from '../components/VeredictoCard.jsx';
import QueryDetails from '../components/QueryDetails.jsx';
import { api } from '../api.js';

const STEPS = ['Compor frase', 'Guardar foto (storage)', 'Embed multimodal (Voyage AI)', 'Verificar identidade do produto ($vectorSearch)', 'Busca de precedentes (Atlas $rankFusion)', 'Classificar causa provável', 'Gravar chamado (Atlas)'];

// O que cada etapa faz no MongoDB — mostrado sempre no pipeline (não só quando
// concluída), pra deixar explícito onde o Atlas entra em cada passo, não só no
// resultado final.
const STEP_DETAILS = [
  'Sem escrita ainda — junta categoria + produto + checklist + descrição numa frase única que alimenta o embedding do próximo passo.',
  'Blob fica fora do MongoDB (disco local no PoV, S3 em produção) — o Atlas guarda só a referência (uri), nunca o binário da imagem.',
  'Gera 1 vetor de 1024 dimensões (texto + imagem) — vira o campo `embedding` do documento que será salvo em `chamados`.',
  '$vectorSearch na collection `catalogo_fotos`, sem filtro de SKU — compara contra TODAS as fotos de referência do catálogo (sinal relativo, não limiar isolado).',
  '$rankFusion combina $vectorSearch (semântico) + Atlas Search full-text sobre `chamados`, filtrado por categoria + status=resolvido.',
  'Sem escrita no Mongo — classificação estruturada a partir da imagem + precedentes recuperados na etapa anterior.',
  'insertOne em `chamados`: documento completo (embedding + veredito + identidade) fica pronto pra virar precedente na próxima busca vetorial.',
];

// Cenarios prontos com fotos publicas de catalogo de varejo de moveis
// — um clique carrega pedido + produto + checklist + descricao + foto, sem
// depender de upload manual ao vivo (elimina risco de erro na apresentacao).
const CENARIOS = [
  {
    label: 'Cadeira Gamer X · rodinha solta',
    numero_pedido: 'PED-90001',
    sku: 'CAD-GAMER-X',
    checklist: ['rodinha_solta'],
    descricao: 'Uma das rodinhas soltou depois de poucos dias de uso, a cadeira balanca de um lado.',
    imagem: '/demo/CAD-GAMER-X.jpg',
  },
  {
    label: 'Colchao Molas Queen · afundamento',
    numero_pedido: 'PED-90002',
    sku: 'COL-MOLAS-Q',
    checklist: ['afundamento'],
    descricao: 'O colchao afundou no centro logo nas primeiras semanas, formando uma cova visivel.',
    imagem: '/demo/COL-MOLAS-Q.jpg',
  },
  {
    label: 'Guarda-Roupa 6 Portas · porta desalinhada',
    numero_pedido: 'PED-90003',
    sku: 'GR-6PORTAS',
    checklist: ['porta_desalinhada'],
    descricao: 'Uma das portas ficou desalinhada e nao fecha direito desde a entrega.',
    imagem: '/demo/GR-6PORTAS.jpg',
  },
  {
    label: 'Cadeira Office Pro · base travada',
    numero_pedido: 'PED-90001',
    sku: 'CAD-OFF-PRO',
    checklist: ['base_travada'],
    descricao: 'A base da cadeira trava ao tentar abaixar, nao regula mais a altura.',
    imagem: '/demo/CAD-OFF-PRO.jpg',
  },
  // Pedido multi-categoria (PED-90004: cadeira + colchao + guarda-roupa) — mostra
  // que a troca de produto dentro de um MESMO pedido funciona entre categorias
  // distintas, nao so entre 2 produtos da mesma categoria. So a Cadeira Office Pro
  // vira botao; os outros 2 (oculto=true) sao alcancados clicando o produto em
  // "Produtos do pedido" depois de carregar este cenario — escolher() troca pra
  // eles automaticamente por ja existir um cenario pronto pra aquele pedido+SKU.
  {
    label: 'Pedido multi-categoria · Cadeira Office Pro',
    numero_pedido: 'PED-90004',
    sku: 'CAD-OFF-PRO',
    checklist: ['perna_quebrada'],
    descricao: 'A perna traseira da cadeira trincou, a cadeira balanca ao sentar.',
    imagem: '/demo/CAD-OFF-PRO.jpg',
  },
  {
    oculto: true,
    label: 'Pedido multi-categoria · Colchao Molas Queen',
    numero_pedido: 'PED-90004',
    sku: 'COL-MOLAS-Q',
    checklist: ['molas_salientes'],
    descricao: 'Da pra sentir e ver as molas furando o tecido do colchao.',
    imagem: '/demo/COL-MOLAS-Q.jpg',
  },
  {
    oculto: true,
    label: 'Pedido multi-categoria · Guarda-Roupa 6 Portas',
    numero_pedido: 'PED-90004',
    sku: 'GR-6PORTAS',
    checklist: ['dobradica_quebrada'],
    descricao: 'Uma dobradica quebrou e a porta ficou pendurada torta.',
    imagem: '/demo/GR-6PORTAS.jpg',
  },
  // Cenarios NEGATIVOS — a foto do cliente nao bate com o produto do pedido.
  // Mostram que a verificacao de identidade e relativa ao catalogo inteiro
  // (embedding multimodal Voyage), nao um limiar isolado ingenuo.
  {
    label: '⚠ Armário parecido, mas errado',
    negativo: true,
    numero_pedido: 'PED-90003',
    sku: 'GR-6PORTAS',
    checklist: ['porta_desalinhada'],
    descricao: 'Uma das portas ficou desalinhada e nao fecha direito desde a entrega.',
    imagem: '/demo/GR-3PORTAS.jpg',
    explicacao: 'Pedido é do Guarda-Roupa 6 Portas, mas a foto é de um guarda-roupa diferente (3 Portas) — visualmente parecido. A identidade deve sinalizar como divergente mesmo com alta similaridade absoluta.',
  },
  {
    label: '⚠ Foto de produto totalmente errado',
    negativo: true,
    numero_pedido: 'PED-90002',
    sku: 'COL-MOLAS-Q',
    checklist: ['odor_forte'],
    descricao: 'O colchao chegou com um odor muito forte, dificil de tirar.',
    imagem: '/demo/CAD-GAMER-X.jpg',
    explicacao: 'Pedido é de um colchão, mas o cliente subiu (por engano) a foto de uma cadeira gamer. Similaridade deve cair bem abaixo do threshold.',
  },
];

export default function Portal({ state, setState }) {
  const { resultado } = state;
  const [pedido, setPedido] = useState('');
  const [pedidosDisponiveis, setPedidosDisponiveis] = useState([]);
  const [carregandoPedidos, setCarregandoPedidos] = useState(true);
  const [produtos, setProdutos] = useState([]);
  const [produtoSel, setProdutoSel] = useState(null);
  const [itens, setItens] = useState([]);
  const [marcados, setMarcados] = useState({});
  const [descricao, setDescricao] = useState('');
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [fotosExtras, setFotosExtras] = useState({});
  const [previewsExtras, setPreviewsExtras] = useState({});
  const modo = 'hybrid'; // recuperacao de precedentes sempre via $rankFusion (hibrida) — mais precisa que vector puro isolado
  const [pipe, setPipe] = useState(STEPS.map(() => 'pending'));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [carregandoCenario, setCarregandoCenario] = useState(null);
  const [cenarioAtivo, setCenarioAtivo] = useState(null);

  const setStep = (step) => setState((s) => ({ ...s, step }));

  useEffect(() => {
    api.pedidos()
      .then((r) => setPedidosDisponiveis(r.pedidos))
      .catch((e) => setError(e.message))
      .finally(() => setCarregandoPedidos(false));
  }, []);

  const buscar = async (numero) => {
    setError(null);
    setCenarioAtivo(null);
    try {
      const r = await api.lookup(numero);
      setProdutos(r.produtos);
      setPedido(r.numero_pedido);
      setStep(1);
    } catch (e) { setError(e.message); }
  };

  const escolher = async (p) => {
    setError(null);
    // Se ja existe um cenario pronto pra esse pedido+SKU, troca pra ele direto —
    // sem isso, alternar entre produtos do mesmo pedido (mesmo entre categorias
    // distintas) zerava tudo e exigia upload manual, quebrando a fluidez da demo.
    const cenMatch = CENARIOS.find((c) => !c.negativo && c.numero_pedido === pedido && c.sku === p.sku);
    if (cenMatch) {
      await aplicarCenario(cenMatch);
      return;
    }
    setProdutoSel(p);
    try {
      const r = await api.checklist(p.categoria);
      setItens(r.itens);
      setMarcados({});
      setDescricao('');
      setFotosExtras({});
      setPreviewsExtras({});
      // Troca de produto dentro do mesmo pedido: a foto principal era de outro
      // item, mantê-la seria uma foto errada anexada ao produto novo.
      setFile(null);
      setPreview(null);
      setStep(2);
    } catch (e) { setError(e.message); }
  };

  // Descricao volta a ser livre e opcional (o cliente pode detalhar); marcar um
  // item de checklist só sugere uma frase a mais no fim do texto, sem apagar o
  // que o cliente já escreveu. Vale tanto no fluxo manual quanto em cima de um
  // cenario pronto — marcar um item extra além do default do cenario precisa
  // aparecer na descricao, senão o contexto novo não chega no embedding/veredito
  // (frase_analise = categoria+produto+checklist+descricao_cliente).
  const humanizarItem = (id) => id.replace(/_/g, ' ');

  const toggle = (id) => {
    const novoMarcados = { ...marcados, [id]: !marcados[id] };
    setMarcados(novoMarcados);
    if (novoMarcados[id]) {
      const frase = humanizarItem(id);
      setDescricao((d) => {
        if (d.toLowerCase().includes(frase)) return d;
        return d.trim() ? `${d.trim()}, ${frase}` : frase.charAt(0).toUpperCase() + frase.slice(1);
      });
    }
    if (!novoMarcados[id]) {
      setFotosExtras((f) => { const n = { ...f }; delete n[id]; return n; });
      setPreviewsExtras((p) => { const n = { ...p }; delete n[id]; return n; });
    }
  };

  const onFileExtra = (id, e) => {
    const f = e.target.files?.[0] || null;
    setFotosExtras((fs) => ({ ...fs, [id]: f }));
    setPreviewsExtras((ps) => ({ ...ps, [id]: f ? URL.createObjectURL(f) : null }));
  };

  // Carrega um cenario pronto (pedido + produto + checklist + descricao + foto real
  // de catalogo publico) de uma vez — so falta clicar "Analisar defeito".
  const aplicarCenario = async (cen) => {
    setError(null);
    setCarregandoCenario(cen.label);
    setCenarioAtivo(cen);
    try {
      const r = await api.lookup(cen.numero_pedido);
      setProdutos(r.produtos);
      setPedido(r.numero_pedido);
      const p = r.produtos.find((x) => x.sku === cen.sku);
      if (!p) throw new Error(`Produto ${cen.sku} nao encontrado no pedido ${cen.numero_pedido}`);
      setProdutoSel(p);
      const rc = await api.checklist(p.categoria);
      setItens(rc.itens);
      setMarcados(Object.fromEntries(cen.checklist.map((id) => [id, true])));
      setDescricao(cen.descricao);
      setFotosExtras({});
      setPreviewsExtras({});
      const resp = await fetch(cen.imagem);
      const blob = await resp.blob();
      const nomeArquivo = cen.imagem.split('/').pop();
      setFile(new File([blob], nomeArquivo, { type: blob.type || 'image/jpeg' }));
      setPreview(URL.createObjectURL(blob));
      setStep(3);
    } catch (e) {
      setError(e.message);
    } finally {
      setCarregandoCenario(null);
    }
  };

  const onFile = (e) => {
    const f = e.target.files?.[0] || null;
    setFile(f);
    setPreview(f ? URL.createObjectURL(f) : null);
    setCenarioAtivo(null);
  };

  const analisar = async () => {
    if (!file) { setError('Envie a foto do defeito.'); return; }
    setBusy(true);
    setError(null);
    setPipe(STEPS.map(() => 'pending'));
    // 2s por etapa — em vez de disparar tudo em ~350ms (a analise real demora
    // varios segundos, entao ficava tudo "check" de uma vez e travado na ultima
    // etapa esperando a resposta). Se a resposta real chegar antes de todas as
    // etapas terminarem a animacao, os timers pendentes sao cancelados e tudo
    // vira "done" na hora — nunca mostra passo pendente com resultado pronto.
    const STEP_MS = 2000;
    const timers = STEPS.map((_, i) =>
      setTimeout(() => setPipe((p) => p.map((s, j) => (j < i ? 'done' : j === i ? 'running' : 'pending'))), i * STEP_MS)
    );
    const fd = new FormData();
    fd.append('imagem', file);
    fd.append('numero_pedido', pedido);
    fd.append('sku', produtoSel.sku);
    fd.append('descricao', descricao);
    fd.append('modo', modo);
    Object.entries(marcados).filter(([, v]) => v).forEach(([k]) => fd.append('checklist', k));
    Object.entries(fotosExtras).filter(([, f]) => f).forEach(([itemId, f]) => {
      fd.append('fotos_extra', f);
      fd.append('fotos_extra_itens', itemId);
    });
    try {
      const r = await api.analisar(fd);
      timers.forEach(clearTimeout);
      setPipe(STEPS.map(() => 'done'));
      setState((s) => ({ ...s, resultado: r, step: 4 }));
    } catch (e) {
      timers.forEach(clearTimeout);
      setError(e.message);
      setPipe(STEPS.map(() => 'pending'));
    } finally { setBusy(false); }
  };

  const reiniciar = () => {
    setProdutos([]); setProdutoSel(null); setItens([]); setMarcados({});
    setDescricao(''); setFile(null); setPreview(null); setPedido('');
    setFotosExtras({}); setPreviewsExtras({});
    setPipe(STEPS.map(() => 'pending'));
    setCenarioAtivo(null);
    setState({ resultado: null, step: 0 });
  };

  const steps = STEPS.map((title, i) => ({ key: title, index: i + 1, title, status: pipe[i], runningLabel: 'processando…', detail: STEP_DETAILS[i], content: null }));

  return (
    <div className="stack">
      {error && <Banner variant="warning" darkMode>{error}</Banner>}

      <div className="card">
        <div className="card-title" style={{ marginBottom: 12 }}>Portal do cliente — abrir chamado de garantia</div>

        <div style={{ marginBottom: 16 }}>
          <label className="demo-scenario-select">
            <span>Cenário</span>
            <select value={cenarioAtivo?.label || ''} disabled={busy || !!carregandoCenario} onChange={(event) => {
              const scenario = CENARIOS.find((item) => item.label === event.target.value);
              if (scenario) aplicarCenario(scenario);
            }}>
              <option value="">Escolha um caso pronto…</option>
              {CENARIOS.filter((item) => !item.oculto).map((item) => <option key={item.label} value={item.label}>{item.label}</option>)}
            </select>
          </label>
          {cenarioAtivo?.negativo && (
            <Banner variant="warning" darkMode style={{ marginTop: 10 }}>
              <b>Resultado esperado:</b> {cenarioAtivo.explicacao}
            </Banner>
          )}
        </div>

        <div className="row" style={{ alignItems: 'flex-end', gap: 12 }}>
          <div style={{ minWidth: 280 }}>
            <Select
              darkMode
              label="Número do pedido"
              placeholder={carregandoPedidos ? 'Carregando pedidos…' : 'Selecione um pedido'}
              description={pedido ? "Use \"Novo chamado\" para trocar de pedido." : undefined}
              value={pedido}
              disabled={!!pedido}
              onChange={(numero) => buscar(numero)}
            >
              {pedidosDisponiveis.map((p) => (
                <Option key={p.numero_pedido} value={p.numero_pedido}>
                  {p.numero_pedido} · {p.produtos.map((prod) => prod.nome).join(', ')}
                </Option>
              ))}
            </Select>
          </div>
          {resultado && <Button darkMode onClick={reiniciar}>Novo chamado</Button>}
        </div>

        {produtos.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <div className="dim" style={{ marginBottom: 6 }}>Produtos do pedido — selecione o item com defeito:</div>
            <div className="row">
              {produtos.map((p) => (
                <Button key={p.sku} darkMode size="small"
                  variant={produtoSel?.sku === p.sku ? 'primary' : 'default'}
                  onClick={() => escolher(p)}>{p.nome} · {p.sku}</Button>
              ))}
            </div>
          </div>
        )}

        {itens.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <div className="dim" style={{ marginBottom: 6 }}>Checklist da categoria <b>{produtoSel.categoria}</b>:</div>
            <div className="row" style={{ flexWrap: 'wrap' }}>
              {itens.map((it) => (
                <div key={it.id} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <label className={`check-chip ${marcados[it.id] ? 'on' : ''}`}>
                    <input type="checkbox" checked={!!marcados[it.id]} onChange={() => toggle(it.id)} />
                    {it.id} <Badge variant="lightgray">{it.tipo}</Badge>
                  </label>
                  {marcados[it.id] && (
                    <div className="row" style={{ alignItems: 'center', gap: 6 }}>
                      <input type="file" accept="image/jpeg,image/png,image/jpg,.jpg,.jpeg,.png"
                        onChange={(e) => onFileExtra(it.id, e)} style={{ fontSize: 11 }} />
                      {previewsExtras[it.id] && (
                        <img src={previewsExtras[it.id]} alt={`foto extra ${it.id}`} className="foto-preview" style={{ maxWidth: 40, maxHeight: 40 }} />
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
            <div style={{ marginTop: 12 }}>
              <TextInput darkMode label="Descrição do cliente (opcional)" description="Marcar um item do checklist sugere uma frase — edite ou complemente à vontade."
                placeholder="Conte o que aconteceu…"
                value={descricao} onChange={(e) => setDescricao(e.target.value)} />
            </div>
            <div style={{ marginTop: 12 }}>
              <div className="dim" style={{ marginBottom: 6, fontSize: 12 }}>
                Foto principal — envie uma foto que mostre o defeito marcado no checklist.
                Pra itens extras marcados, use o upload que aparece ao lado de cada um.
              </div>
              <div className="row">
                <input type="file" accept="image/jpeg,image/png,image/jpg,.jpg,.jpeg,.png" onChange={onFile} />
                {preview && <img src={preview} alt="prévia" className="foto-preview" />}
              </div>
            </div>
            <div style={{ marginTop: 12 }}>
              <div className="dim" style={{ marginBottom: 6 }}>Recuperação de precedentes:</div>
              <div className="row" style={{ alignItems: 'center' }}>
                <Badge variant="green">$rankFusion — busca híbrida</Badge>
              </div>
            </div>
            <div style={{ marginTop: 12 }}>
              <Button darkMode variant="primary" onClick={analisar} disabled={busy || !file}>
                {busy ? 'Analisando…' : '▶ Analisar defeito'}
              </Button>
            </div>
          </div>
        )}
      </div>

      {(busy || resultado) && (
        <div className="two-col">
          <div className="card">
            <div className="card-title" style={{ marginBottom: 8 }}>Pipeline (Caminho B)</div>
            <PipelineSteps steps={steps} />
            {resultado && (
              <>
                <div className="dim mono" style={{ marginTop: 10, fontSize: 12 }}>
                  chamado <b>{resultado.numero_chamado}</b> · status em_analise<br />
                  embedding: {resultado.embedding_model} ({resultado.embedding_dim}d)<br />
                  frase: {resultado.frase_analise}
                </div>
                <QueryDetails
                  operation={resultado.funnel?.query_details?.operation}
                  namespace="chamados"
                  query={resultado.funnel?.query_details?.pipeline}
                  label="Ver pipeline de precedentes executado"
                />
                <QueryDetails
                  operation={resultado.identidade?.query_details?.operation}
                  namespace="catalogo_fotos"
                  query={resultado.identidade?.query_details?.pipeline}
                  label="Ver pipeline de identidade executado"
                />
              </>
            )}
          </div>
          <div className="stack">
            {resultado?.identidade && <IdentidadeCard identidade={resultado.identidade} />}
            {resultado?.veredito && <VeredictoCard veredito={resultado.veredito} />}
            {resultado?.imagem_url && (
              <div className="card"><div className="card-title" style={{ marginBottom: 8 }}>Foto do cliente</div>
                <img src={resultado.imagem_url} alt="defeito" className="foto-full" /></div>
            )}
            {resultado?.fotos_extra?.length > 0 && (
              <div className="card">
                <div className="card-title" style={{ marginBottom: 8 }}>Fotos extras por item do checklist</div>
                <div className="row" style={{ flexWrap: 'wrap' }}>
                  {resultado.fotos_extra.map((f) => (
                    <div key={f.url} style={{ textAlign: 'center' }}>
                      <img src={f.url} alt={`foto extra ${f.item}`} className="foto-preview" />
                      <div className="dim" style={{ fontSize: 11 }}>{f.item}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {resultado?.precedentes && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">
              Precedentes recuperados ({resultado.funnel?.modo === 'hybrid' ? '$rankFusion' : resultado.funnel?.modo === 'vector_fallback' ? '$vectorSearch — fallback' : '$vectorSearch'})
            </span>
            <Badge variant="green">
              {resultado.funnel?.retrieved ?? 0}
              {resultado.funnel?.num_candidates ? ` de ${resultado.funnel.num_candidates} candidatos` : ''}
            </Badge>
            {resultado.funnel?.pesos && (
              <Badge variant="blue">
                pesos: {Math.round(resultado.funnel.pesos.vetorial * 100)}% vetorial · {Math.round(resultado.funnel.pesos.textual * 100)}% textual
              </Badge>
            )}
          </div>
          {resultado.funnel?.modo === 'vector_fallback' && (
            <Banner variant="warning" darkMode style={{ marginBottom: 10 }}>
              $rankFusion indisponível neste cluster — degradou para $vectorSearch automaticamente.
            </Banner>
          )}
          {resultado.precedentes.map((p, i) => {
            // Score do $rankFusion é Reciprocal Rank Fusion (1/(60+posição)), não
            // similaridade de cosseno — o número absoluto é sempre baixo (~0.01-0.02)
            // por construção do algoritmo, não indica match fraco. O badge de match
            // é relativo ao melhor score retornado nesta busca (lista já vem ordenada
            // desc), pra dar uma leitura visual sem depender do número cru.
            const maxScore = resultado.precedentes[0]?.score || 1;
            const relPct = Math.round((p.score / maxScore) * 100);
            const matchGrau = relPct >= 70 ? { txt: 'match forte', variant: 'green' }
              : relPct >= 40 ? { txt: 'match moderado', variant: 'yellow' }
              : { txt: 'match fraco', variant: 'lightgray' };
            return (
              <div key={p._id} className="prec-item">
                <div className="row" style={{ justifyContent: 'space-between' }}>
                  <span className="mono">{p.numero_chamado} · {p.categoria}/{p.tipo_defeito}</span>
                  <div className="row" style={{ gap: 6 }}>
                    <Badge variant={matchGrau.variant}>{matchGrau.txt}</Badge>
                    <Badge variant="green">score {Number(p.score).toFixed(3)}</Badge>
                  </div>
                </div>
                <JsonViewer doc={p} />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
