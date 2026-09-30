#!/usr/bin/env bash
# Boots the whole app: FastAPI (8100) in the background + Vite (5190) in the foreground.
set -e
cd "$(dirname "$0")"

for port in 8100 "${PORT:-5190}"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port $port is already in use; no process was stopped."
    exit 1
  fi
done

echo "▶ backend FastAPI :8100"
# --workers 1 explícito: métricas em processo e o change stream SSE assumem
# processo único; múltiplos workers dividiriam contadores e duplicariam streams.
(cd backend && .venv/bin/uvicorn main:app --port 8100 --workers 1 &)
# Espera readiness real em vez de sleep fixo: a conexão com o Atlas leva mais de
# 2s em rede fria, e o Vite subindo antes disso faz o proxy devolver 500
# (ECONNREFUSED) para as primeiras chamadas da página -> banner "Erro HTTP 500".
printf "  aguardando backend"
for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8100/api/health >/dev/null 2>&1; then
    echo " ok"
    break
  fi
  printf "."
  sleep 1
done
if ! curl -fsS http://127.0.0.1:8100/api/health >/dev/null 2>&1; then
  echo ""
  echo "⚠ backend não respondeu em 60s — seguindo mesmo assim; veja os logs do uvicorn."
fi

echo "▶ frontend Vite :5190"
cd frontend
# instala deps na primeira vez (LeafyGreen tem conflito de peer dep -> legacy-peer-deps)
[ -x node_modules/.bin/vite ] || npm install --legacy-peer-deps
if [ "${POV_DEV:-0}" != "1" ] && {
  [ ! -f dist/index.html ] ||
  [ -n "$(find src -type f -newer dist/index.html -print -quit)" ] ||
  [ package-lock.json -nt dist/index.html ] ||
  [ vite.config.js -nt dist/index.html ];
}; then
  echo "▶ gerando frontend otimizado"
  npm run build
fi
# Preview não mantém watcher/HMR em uma demo normal; POV_DEV=1 preserva o fluxo de edição.
if [ "${POV_DEV:-0}" = "1" ]; then
  exec node_modules/.bin/vite --host 127.0.0.1 --port "${PORT:-5190}" --strictPort
fi
exec node_modules/.bin/vite preview --host 127.0.0.1 --port "${PORT:-5190}" --strictPort
