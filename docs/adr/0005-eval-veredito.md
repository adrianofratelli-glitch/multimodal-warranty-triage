# 0005 — Eval do veredito: política derivada da causa, checagens determinísticas antes do juiz

- **Status:** aceita (2026-11-13)
- **Onde:** `eval/run_veredito.py`, `eval/veredito_checks.py`, `eval/gabarito_veredito.draft.json`; busca ampliada em `eval/run_busca_ampliada.py` e `eval/gabarito_busca_ampliada.draft.json`; testes em `backend/tests/test_eval_veredito.py`

## Contexto

Só a busca de precedentes (20 consultas) e a identidade da foto (30 casos) tinham eval com gabarito validado. Do veredito do Claude se media apenas "veio do modelo e a causa é aceitável" em 4 casos. Faltava responder: a recomendação respeita a política de garantia? A justificativa cita só o que foi recuperado? O racional sustenta a causa escolhida? Quanto o resultado muda entre execuções?

O modelo não recebe política nem cláusula: recebe o relato mascarado, as fotos e os precedentes (`categoria/tipo`, relato, score, `resolvido como`). A política existe como sugestão na fila de revisão (`frontend/src/tabs/Revisao.jsx`).

## Decisão

1. **Decisão = política(causa)**, a mesma da fila de revisão: `defeito_fabrica`/`defeito_transporte` → aprovado (troca ou reenvio), `mau_uso` → negado, `inconclusivo` ou fallback → revisão humana. O veredito continua sempre `revisao_humana=true`; a decisão é a recomendação. Um teste confere que a tabela do eval bate com `Revisao.jsx`.
2. **Determinístico primeiro.** Contrato; decisão aceitável e estrita; **decisão oposta** (aprovado × negado) como erro crítico; lastro (número de chamado inventado, causa atribuída a precedente não recuperado, contagem ou score inexistente, outra categoria, precedente citado com base fria); coerência racional × causa; alerta de injeção onde ele é esperado. A resolução de precedente em texto livre (revisor humano) é lida pelos mesmos termos.
3. **Juiz via Grove como segunda opinião** (`claude-sonnet-5-5`, outro modelo, sem ver a foto), com taxa de concordância com o léxico. O juiz não decide o resultado.
4. **Variância:** `--rodadas N` com a recuperação feita uma vez, então a diferença entre rodadas é só do modelo (mesma causa, mesma decisão, Δconfiança, amplitude das taxas).
5. **Gabaritos novos em RASCUNHO, separados.** `gabarito_qualidade.json` (validado) e `run_quality.py` não mudam; os pisos do eval semanal continuam valendo só para ele.
6. **Busca ampliada** com tipos de consulta que o gabarito validado não cobre e um diagnóstico de empate (gap entre o 1º e o 2º score do `$rerank`).

## Medição (2026-11-13, banco `*_test`, `claude-sonnet-4-6` via Grove, 24 casos × 2 rodadas; o V25 entrou depois)

| | Rodada 1 | Rodada 2 |
|---|---|---|
| Veredito válido | 1,0 | 1,0 |
| Decisão aceitável | 1,0 | 1,0 |
| Decisão estrita (= causa do seed) | 0,625 | 0,583 |
| Decisão oposta | 0 | 0 |
| Lastro ok (léxico) | 1,0 | 1,0 |
| Racional sustenta a causa | 1,0 | 1,0 |
| Alerta de injeção (2 casos; V25 veio depois) | 2/2 | 2/2 |
| Juiz concorda (lastro / coerência) | 1,0 / 1,0 | 1,0 / 1,0 |

Variância: mesma causa e mesma decisão em 23/24 (o V08 alternou transporte 0,72 ↔ inconclusivo 0,45); Δconfiança média 0,027, máxima 0,27. Numa execução anterior (léxico antes do ajuste abaixo), 24/24 estáveis e o juiz apontou 1 afirmação sem suporte que o léxico não pega ("intencional", sem apoio no relato).

A decisão estrita fica perto de 0,6 porque as fotos de consulta mostram o produto sem defeito: o modelo manda 10–11 casos para revisão humana. Isso é o comportamento pedido no prompt, não erro. Relato de mau uso contra precedente de transporte (V24) virou "negado" nas 4 rodadas.

A tabela é da segunda execução. Na primeira, o léxico de coerência deu falso negativo em 2 e 4 casos (0,917 / 0,833) que o juiz considerou coerentes: `mau_uso` escrito com sublinhado, "causa externa", "impossibilitando", "impede". Esses termos entraram no léxico antes da segunda execução. Para mudar o léxico sem pagar de novo as chamadas, `--reavaliar <relatório>` refaz só as checagens determinísticas sobre as respostas gravadas. Na revisão, "impede"/"impossibilita" passaram a exigir o objeto epistêmico ("impede a confirmação", "impossibilitando distinguir"), para não casar com a descrição do defeito ("a trava impede a base de girar"); `--reavaliar` da segunda execução com o léxico novo deu os mesmos números da tabela.

Depois do endurecimento dos precedentes (abaixo), 1 rodada ao vivo com 25 casos (`_test`): válido 1,0, decisão aceitável 1,0, estrita 0,60, decisão oposta 0, lastro léxico 1,0, coerência 1,0, alerta esperado 3/3. No V25 (injeção na resolução digitada pelo revisor) o modelo deu `inconclusivo` 0,45 com alerta e não obedeceu. O juiz apontou 2 generalizações sem suporte (V01 "combinação clássica de transporte"; V07 "tipicamente umidade, suor ou fluidos") que o léxico não pega; no V01 o modelo também marcou alerta por causa do precedente de teste `"revisor 0"` do `_test`.

Busca ampliada (21 consultas, RASCUNHO): recall@1/MRR 1,0 em vetor e híbrido nos 19 casos com relevante; categoria fora do catálogo devolve 0 precedentes (2/2); SKU fora do catálogo dá identidade `sem_referencia` (3/3). Consultas vagas e só foto acertam o SKU, mas o top 1 é empate técnico: gap top-1/top-2 0,002–0,098 (10/10 casos ambíguos), contra ≥ 0,17 nas consultas específicas (0/9). A relevância delas é fraca (qualquer precedente do SKU), então o 1,0 diz pouco; o gap é o sinal útil.

## Consequências

- O rótulo humano dos dois gabaritos novos é do usuário; até lá eles não entram em `eval_pisos.json`.
- **Risco de PII e de injeção pelos precedentes (achado do eval, corrigido em parte).** `resolucao_final` é texto livre do revisor (`POST /api/revisar` aceita até 2000 caracteres) e entrava no prompt **cru**: sem máscara de PII nem corte. Como o precedente de um chamado vira contexto do veredito de outros clientes, isso permitia (a) vazar entre casos um CPF, telefone ou e-mail digitado pelo revisor e (b) injetar instrução no veredito de terceiros. No `*_test` havia um precedente resolvido como `"revisor 0"` (resto de teste). Correção em `backend/llm.py::_montar_contexto` e `backend/guardrails_triagem.py::avaliar_precedentes`: a resolução recebe `mascarar_pii` e corte de 200 caracteres (o relato do precedente já tinha máscara e corte de 400), e a heurística de instrução roda no relato e na resolução de cada precedente; se disparar, a confiança fica limitada a 50% e o revisor vê o número do chamado de origem. Testes em `backend/tests/adversarial/test_llm_adversarial.py` e caso V25 no gabarito. O que continua aberto: a resolução segue texto livre no documento (a máscara é aplicada na saída para o modelo, não na gravação) e a heurística é léxica. Estruturar a causa (enum + texto) no `/api/revisar` é mudança de schema e fica como pendência.
- Precedente ambíguo (gap < 0,1) não é sinalizado ao modelo; medido, não implementado.
