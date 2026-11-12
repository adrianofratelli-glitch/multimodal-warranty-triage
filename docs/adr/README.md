# Decisões de arquitetura (ADRs)

Registro curto das decisões que mudam como a PoV se comporta ou o que ela mede. Cada ADR cita onde a decisão vive no código e como foi medida.

| ADR | Decisão | Status |
|---|---|---|
| [0001](0001-documento-unico-por-chamado.md) | Um documento por chamado (metadados, vetor, identidade, veredito) | aceita |
| [0002](0002-identidade-so-imagem-sinal-relativo.md) | Identidade do produto com vetor só da imagem e sinal relativo ao catálogo | aceita |
| [0003](0003-embedding-na-aplicacao-sem-autoembed.md) | Embedding multimodal calculado na aplicação (sem autoEmbed) | aceita |
| [0004](0004-rerank-precedentes.md) | `$rerank` nativo do Atlas sobre os precedentes; sem quantização de vetor por ora | aceita |
