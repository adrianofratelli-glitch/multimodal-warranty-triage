# 0001 — Um documento por chamado

- **Status:** aceita (registrada em 2026-11-12; a decisão vem da 1.1.0)
- **Onde:** `backend/main.py` (`_processar_analise`, `_inserir_chamado_com_retry`), validador em `backend/setup_indexes.py` (`CHAMADOS_SCHEMA`), medição em `scripts/bench_documento_unico.py`

## Contexto

Uma triagem produz metadados do pedido, o vetor de 1024 floats, o resultado da identidade, o veredito do Claude e a referência da foto. Um desenho relacional típico separaria isso em tabelas (ou um vector DB à parte), com joins ou sincronização.

## Decisão

Tudo vive num único documento de `chamados`, gravado com 1 insert (estado `veredito_pronto_aguardando_upload`, para não perder o veredito já pago) e 1 update (promove a `em_analise` depois do upload). O mesmo documento é o precedente que a próxima busca vetorial encontra, filtrado por `{categoria, status: "resolvido"}`. A imagem fica fora do banco (`backend/storage.py`, contrato `(uri, url)`).

## Medição

`scripts/bench_documento_unico.py`, 2026-10-09, N=30, mesmo cluster e driver: escrita p50 386,8 ms (1 documento) contra 854,6 ms (3 coleções, sem atomicidade) e 1075,1 ms (3 coleções em transação); leitura p50 379,2 ms contra 701,8 ms. É comparação de modelagem dentro do MongoDB, não benchmark de outro banco.

## Consequências

- O `$jsonSchema` governa o documento inteiro (enum de status e de classificação, dimensão exata do vetor).
- O documento tem ~15 KB, quase todo vetor; a busca e a fila sempre projetam `embedding: 0`.
- Mudar a dimensão do embedding exige reseed e novo validador (ver ADR 0003).
