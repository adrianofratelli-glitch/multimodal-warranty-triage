import test from 'node:test'
import assert from 'node:assert/strict'
import { confiancaPct, grauConfianca, grauMatch, rotuloBusca, rotuloPassoBusca, rotuloRerank, statusIdentidade } from '../src/lib/triagem.js'

test('grauConfianca: faixas <40 baixa, 40-69 moderada, >=70 alta', () => {
  assert.equal(grauConfianca(0).txt, 'confiança baixa')
  assert.equal(grauConfianca(39).txt, 'confiança baixa')
  assert.equal(grauConfianca(40).txt, 'confiança moderada')
  assert.equal(grauConfianca(69).txt, 'confiança moderada')
  assert.equal(grauConfianca(70).txt, 'confiança alta')
})

test('confiancaPct limita a 0..100 e trata ausente/inválido como 0', () => {
  assert.equal(confiancaPct(0.35), 35)
  assert.equal(confiancaPct(undefined), 0)
  assert.equal(confiancaPct('x'), 0)
  assert.equal(confiancaPct(1.7), 100)
  assert.equal(confiancaPct(-0.2), 0)
})

test('grauMatch é relativo ao melhor score da busca (RRF tem número cru baixo)', () => {
  // scores reais de $rankFusion medidos ao vivo: ~0,016 no topo
  assert.deepEqual(grauMatch(0.0164, 0.0164), { txt: 'match forte', variant: 'green', rel: 100 })
  assert.equal(grauMatch(0.0155, 0.0164).txt, 'match forte')
  assert.equal(grauMatch(0.5, 1).txt, 'match moderado')
  assert.equal(grauMatch(0.1, 1).txt, 'match fraco')
  // sem maxScore válido não divide por zero
  assert.equal(grauMatch(0.9, 0).rel, 90)
})

test('rotuloBusca reflete o modo que o backend usou, inclusive o fallback', () => {
  assert.equal(rotuloBusca('hybrid'), '$rankFusion')
  assert.equal(rotuloBusca('vector_fallback'), '$vectorSearch — fallback')
  assert.equal(rotuloBusca('vector'), '$vectorSearch')
  assert.equal(rotuloBusca(undefined), '$vectorSearch')
})

test('statusIdentidade: chamado > foto principal > legado; desconhecido nunca vira aprovado', () => {
  assert.equal(statusIdentidade(null), null)
  assert.equal(statusIdentidade({ status: 'aprovado', status_chamado: 'divergente' }), 'divergente')
  assert.equal(statusIdentidade({ status: 'sem_referencia' }), 'sem_referencia')
  assert.equal(statusIdentidade({ abaixo_threshold: true }), 'divergente')
  assert.equal(statusIdentidade({ abaixo_threshold: false }), 'aprovado')
  assert.equal(statusIdentidade({}), 'inconclusivo')
  assert.equal(statusIdentidade({ status: 'qualquer' }), 'inconclusivo')
})

test('rotuloRerank: aplicado mostra o modelo; falha avisa; desligado/antigo não mostra nada', () => {
  assert.equal(rotuloRerank({ aplicado: true, modelo: 'rerank-2.5-lite' }).txt, 'reordenado por $rerank (rerank-2.5-lite)')
  const falha = rotuloRerank({ aplicado: false, motivo: "Unrecognized pipeline stage name: '$rerank'" })
  assert.equal(falha.falhou, true)
  assert.equal(falha.variant, 'yellow')
  assert.equal(rotuloRerank({ aplicado: false, motivo: 'desligado' }), null)
  assert.equal(rotuloRerank(undefined), null)
})

test('rotuloPassoBusca: título do passo segue funnel.modo e funnel.rerank', () => {
  assert.equal(rotuloPassoBusca(undefined, 'hybrid'), 'Busca de precedentes (Atlas $rankFusion + $rerank)')
  assert.equal(rotuloPassoBusca({ modo: 'hybrid', rerank: { aplicado: true } }), 'Busca de precedentes (Atlas $rankFusion + $rerank)')
  assert.equal(rotuloPassoBusca({ modo: 'hybrid', rerank: { aplicado: false, motivo: 'x' } }), 'Busca de precedentes (Atlas $rankFusion)')
  assert.equal(rotuloPassoBusca({ modo: 'vector_fallback', rerank: { aplicado: true } }), 'Busca de precedentes (Atlas $vectorSearch — fallback + $rerank)')
  assert.equal(rotuloPassoBusca({ modo: 'idempotent_replay' }), 'Busca de precedentes (não repetida: envio idêntico)')
})
