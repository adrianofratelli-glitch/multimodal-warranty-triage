import { lazy, Suspense, useEffect, useState } from 'react';
import { api } from './api.js';

const Portal = lazy(() => import('./tabs/Portal.jsx'));
const Revisao = lazy(() => import('./tabs/Revisao.jsx'));

const TABS = ['Abrir chamado', 'Revisar'];

export default function App() {
  const [selected, setSelected] = useState(0);
  const [visited, setVisited] = useState(() => new Set([0]));

  // estado elevado: trocar de aba não apaga o resultado da análise nem a revisão.
  const [portalState, setPortalState] = useState({ resultado: null, step: 0 });
  const [revisaoState, setRevisaoState] = useState({
    pendentes: [],
    selecionado: null,
    nextCursor: null,
    hasMore: false,
    totalPendentes: null,
  });

  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState(false);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      if (document.visibilityState !== 'visible') return;
      try {
        const h = await api.health();
        if (alive) {
          setHealth(h);
          setHealthError(false);
        }
      } catch {
        if (alive) setHealthError(true);
      }
    };
    tick();
    const id = setInterval(tick, 10_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const panes = [
    <Portal state={portalState} setState={setPortalState} goRevisar={() => selectTab(1)} />,
    <Revisao state={revisaoState} setState={setRevisaoState} active={selected === 1} />,
  ];

  const selectTab = (index) => {
    setVisited((current) => new Set(current).add(index));
    setSelected(index);
  };

  const counts = health?.counts ?? {};

  return (
    <div data-pov-shell>
      <a className="pov-skip-link" href="#conteudo-principal">Pular para o conteúdo</a>
      <nav className="top-nav">
        <div className="nav-inner">
          <span className="nav-logo">
            <span className="leaf">●</span> Análise de Garantia Multimodal
          </span>
          <div className="nav-pills">
            {TABS.map((name, i) => (
              <button
                key={name}
                className={`nav-pill ${i === selected ? 'active' : ''}`}
                aria-current={i === selected ? 'page' : undefined}
                onClick={() => selectTab(i)}
              >
                {name}
              </button>
            ))}
          </div>
          <span className="status-pill">
            <span className={`status-dot ${healthError || !health ? 'err' : 'ok'}`} />
            {healthError ? 'sem conexão' : health ? 'Atlas · ping ok' : 'conectando…'}
          </span>
        </div>
      </nav>

      <main id="conteudo-principal" tabIndex={-1} className="content">
        <header className="stage-heading">
          <h1 className="page-title">Da foto ao <span>precedente</span></h1>
          <p>{counts.resolvido ?? '—'} precedentes · {counts.em_analise ?? '—'} em análise</p>
        </header>

        {panes.map((pane, i) => visited.has(i) && (
          <div key={i} style={{ display: i === selected ? 'block' : 'none' }}>
            <Suspense fallback={<div className="card">Carregando etapa…</div>}>
              <div className={i === selected ? 'fade-in' : ''}>{pane}</div>
            </Suspense>
          </div>
        ))}
      </main>

    </div>
  );
}
