# Interview Cases

Notas para entrevistas. Usar somente metricas sanitizadas, projetos clean-room e explicacoes que possam ser defendidas sem expor clientes, dados privados, endpoints, logs reais ou codigo proprietario.

## 1. Automacao de Capacidade >80x

SITUACAO: uma rotina de relatorios exigia consolidacao repetitiva de dados em muitas contas.

PROBLEMA: o processo manual era lento, sujeito a inconsistencia e dificil de auditar depois.

DECISAO: automatizar a coleta, consolidacao e geracao de evidencias com Python, mantendo entradas e saidas rastreaveis.

IMPLEMENTACAO: estruturei a rotina por contas, arquivos e resultados verificaveis, com tratamento de dados e saidas consolidadas.

RESULTADO: 41 contas/relatorios, >1,1 milhao de registros processados em 30min16s, com ganho estimado >80x frente a rotina manual.

TRADE-OFF: a automacao precisou preservar rastreabilidade e validacao humana para evitar que velocidade virasse falta de controle.

O QUE EU FARIA EM PRODUCAO: adicionaria observabilidade, historico de execucoes, alertas de falha, versionamento de schema e testes de regressao sobre amostras controladas.

## 2. Decisao Automatizada de Manutencao

SITUACAO: analises de equipamentos exigiam leitura de grandes volumes de registros operacionais.

PROBLEMA: a decisao entre manutencao, atencao, OK ou inconclusivo dependia de interpretar muitos sinais de forma consistente.

DECISAO: transformar a investigacao em fluxo reproduzivel de classificacao e evidencia.

IMPLEMENTACAO: processei dados operacionais sanitizados, organizei status e comparei tempo de execucao contra baseline manual.

RESULTADO: 41 equipamentos, >1,2 milhao de registros, 1h14m15s de execucao e ganho estimado entre 16x e 22x.

TRADE-OFF: algumas decisoes continuam exigindo revisao humana quando o dado e inconclusivo.

O QUE EU FARIA EM PRODUCAO: criaria regras versionadas, explicabilidade por decisao, fila de revisao manual e metricas de falso positivo/falso negativo.

## 3. Incidentes Em Escala

SITUACAO: bases operacionais grandes geram muitos eventos, acoes e incidentes que precisam ser priorizados.

PROBLEMA: sem regras, estados e metricas, a operacao vira uma lista de sintomas sem confiabilidade.

DECISAO: modelar eventos, incidentes, acoes, cooldown, auditoria e metricas em um projeto clean-room.

IMPLEMENTACAO: criei uma plataforma sintetica com Python/FastAPI, SQLAlchemy, SQLite, regras e testes automatizados.

RESULTADO: o case publico demonstra padroes usados para raciocinar sobre bases com >66 mil incidentes e >2,7 milhoes de acoes analisadas em contexto profissional sanitizado.

TRADE-OFF: o repositorio publico nao contem regras reais; ele demonstra arquitetura e metodo com dominio ficticio.

O QUE EU FARIA EM PRODUCAO: usaria PostgreSQL, filas externas, outbox, tracing, dashboards de SLO e governanca de regras.

## 4. Python x .NET no Support

SITUACAO: eu queria provar capacidade de arquitetura e decisao de stack sem transformar portfolio em colecao de cursos.

PROBLEMA: comparar linguagens sem equivalencia funcional gera conclusoes fracas.

DECISAO: definir contrato comportamental compartilhado antes de medir performance.

IMPLEMENTACAO: implementei o mesmo fluxo sintetico em Python/FastAPI e .NET/ASP.NET Core, com workloads JSONL deterministas, SQLite, testes Python e xUnit.

RESULTADO: equivalencia canonica validada para workloads de 100 e 1.000 eventos; benchmark engine, HTTP, concorrencia e soak documentados.

TRADE-OFF: os detalhes de acesso ao banco diferem entre stacks, entao a leitura correta e sobre arquitetura, gargalos e metodo, nao sobre uma verdade universal de linguagem.

O QUE EU FARIA EM PRODUCAO: repetiria com PostgreSQL, filas reais, carga maior, telemetria de CPU/memoria por processo e ambiente isolado.

## 5. Python x .NET no Extractor

SITUACAO: extracoes batch precisam sobreviver a falhas, rate limit, interrupcoes e retomadas.

PROBLEMA: um benchmark de extractor so e justo se comparar checkpoint, sink idempotente, retry e falhas com o mesmo contrato.

DECISAO: preservar a implementacao Python e adicionar um Worker Service .NET clean-room pequeno, com testes de retomada e duplicidade.

IMPLEMENTACAO: Python usa `httpx.MockTransport`, SQLite checkpoint e NDJSON idempotente; .NET Worker usa SQLite checkpoint, sink NDJSON e xUnit para recovery.

RESULTADO: Python ficou com 93% de coverage; .NET passou com 4 testes. A rodada local 10k/100k teve corretude verdadeira nos dois stacks, mas foi marcada como smoke benchmark porque o transporte ainda nao esta alinhado.

TRADE-OFF: nao afirmar que .NET resolveu performance do extractor enquanto o caminho de transporte nao for equivalente.

O QUE EU FARIA EM PRODUCAO: alinhar transporte HTTP/JSON nos dois lados, adicionar matriz completa 429/500/timeout/reset/payload invalido e rodar 5+ medicoes por perfil.

## 6. Race Condition e Idempotencia

SITUACAO: workloads concorrentes podem tentar criar a mesma entidade logica ou reprocessar uma mesma pagina.

PROBLEMA: pre-check em aplicacao nao basta; duas requisicoes podem passar na verificacao antes do commit.

DECISAO: usar restricoes do banco como fonte de verdade e tratar conflitos no nivel da API.

IMPLEMENTACAO: na plataforma de operacoes, `external_id` e `event_id` sao unicos; a API captura `IntegrityError` e retorna 409. No extractor, o sink carrega IDs ja escritos e pula duplicados no resume.

RESULTADO: teste concorrente confirma uma entidade logica criada e uma resposta 409; testes de crash/resume confirmam output sem duplicidade.

TRADE-OFF: consistencia forte pode reduzir throughput se o gargalo for escrita sincronizada.

O QUE EU FARIA EM PRODUCAO: avaliar isolation level, optimistic concurrency, locks por chave logica, outbox e desenho de filas por particao.

## 7. SQLite WAL e Persistencia Como Gargalo

SITUACAO: o benchmark do support mostrou que o banco local influencia fortemente o resultado.

PROBLEMA: se o gargalo e escrita SQLite, comparar so linguagem vira simplificacao errada.

DECISAO: separar resultados historicos, WAL e rodada canonica, documentando configuracao e trade-off.

IMPLEMENTACAO: rodei benchmarks default SQLite e uma rodada com WAL + synchronous NORMAL, mantendo arquivos de raw/summary separados.

RESULTADO: foi possivel explicar throughput, erros, latencia de cauda e contencao de escrita sem esconder o bug/race condition descoberto no processo.

TRADE-OFF: WAL melhora concorrencia em certos cenarios, mas muda caracteristicas de durabilidade e nao substitui validacao em PostgreSQL.

O QUE EU FARIA EM PRODUCAO: migrar o benchmark para PostgreSQL, medir lock contention, conexoes, pool, filas e tempos de transacao.

## 8. Escolha de Stack Baseada em Requisito

SITUACAO: meu objetivo nao e vender "sei varias linguagens", e sim mostrar que escolho stack por requisito.

PROBLEMA: portfolio tecnico pode virar exibicao superficial se nao houver problema, regra, teste e medicao.

DECISAO: limitar a estrategia multi-stack a poucos cases fortes e documentar o motivo de cada stack.

IMPLEMENTACAO: support usa Python/FastAPI vs .NET/ASP.NET Core para regras/API/concorrencia; extractor usa Python/httpx vs .NET Worker para batch/recovery; USB pode receber C# apenas se agregar integracao Windows.

RESULTADO: a narrativa fica demonstravel: problema -> regra -> arquitetura -> implementacao -> teste -> medicao -> decisao.

TRADE-OFF: alguns projetos permanecem Python-only porque converter por converter reduziria clareza.

O QUE EU FARIA EM PRODUCAO: criar matriz de decisao por requisito, custo operacional, time, ecossistema, deploy, observabilidade e manutencao.
