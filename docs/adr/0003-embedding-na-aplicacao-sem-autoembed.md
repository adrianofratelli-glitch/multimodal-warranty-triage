# 0003 — Embedding multimodal calculado na aplicação (sem autoEmbed)

- **Status:** aceita (registrada em 2026-11-12)
- **Onde:** `backend/voyage.py` (`embed_multimodal`, `embed_imagem`), `backend/rag.py` (`queryVector` pré-computado), `backend/setup_indexes.py` (`VECTOR_DEF`, `CATALOGO_FOTOS_VECTOR_DEF`)

## Contexto

O Atlas Vector Search tem autoEmbed (o índice gera e mantém o vetor). Em 2026-11-12 a definição de autoEmbed aceita modalidade `text` e modelos Voyage de texto (voyage-4, -4-large, -4-lite, voyage-code-*); em self-managed é Preview. Esta PoV precisa de vetor de **imagem + texto** (`voyage-multimodal-3.5`, 1024d) e de vetor só de imagem (ADR 0002).

## Decisão

A aplicação chama a Voyage (`voyage-multimodal-3.5`, `input_type` `document` no seed e `query` na consulta), grava o vetor no documento e passa `queryVector` pronto ao `$vectorSearch` ("Caminho B"). Modelo e dimensão vêm do `.env` (`EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS`).

## Consequências

- Os mesmos bytes JPEG normalizados vão para storage, Voyage e Claude.
- Trocar de modelo ou dimensão exige reseed de `chamados` e `catalogo_fotos` e novo validador; não misturar modelos no mesmo campo (espaços incompatíveis).
- Revisar quando o autoEmbed aceitar imagem: aí o índice pode assumir o vetor de `catalogo_fotos`, mantendo a regra de identidade só-imagem.
