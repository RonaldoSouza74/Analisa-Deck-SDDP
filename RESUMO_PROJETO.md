# Resumo do projeto: vertimento (curtailment) renovável por estado a partir do SDDP

Documento para dar continuidade ao trabalho em um novo projeto do Claude, sem perder contexto.
Atualizado em 15/11/2026.

---

## 1. Contexto

- **Quem:** Ronaldo Souza (EPE). Estudo de **curtailment / vertimento de geração renovável** no SIN.
- **Ferramenta:** SDDP (PSR), versão **18.0.11rc**, com representação da rede elétrica (barras, linhas,
  transformadores, elos CC) e resolução **horária**.
- **Caso (deck):** `estudo_perdas_2025` (pasta no Windows: `C:\Estudo Curtailment SDDP\estudo_perdas_2025`).
  Deck do PDE (log aponta `X:\SGE-Projetos\02-Estudos\09-Diversos\Est PDE 2035 e 2036\estudo_perdas_2025`).
- **Rodada analisada (2030):** início **dez/2029**, **13 estágios mensais** (9.504 horas), **10 cenários**.
  Estágio 1 = dez/2029; **estágios 2 a 13 = jan a dez de 2030**. Futuramente o usuário quer analisar outros
  anos (ex.: 2032) com novas rodadas, trazendo os .hdr/.bin daquele ano (o deck já tem carga 2025–2040 e
  alterações de rede até 2039).
- **Objetivo geral:** quantificar o vertimento por estado (UF), entender quando/onde ocorre, e separar
  **vertimento por gargalo de transmissão** de **vertimento por excesso no sistema (falta de demanda)**,
  relacionando com injeção nas barras, CMO, fluxos e limites físicos de linhas/trafos, e com o balanço de
  geração (renovável, hidro, térmica) e carga de cada estado.

## 2. Repositório, arquivos e forma de trabalho

- **GitHub:** https://github.com/RonaldoSouza74/Analisa-Deck-SDDP — branch de trabalho
  **`claude/nice-newton-23r08d`** (o `main` tem os uploads iniciais).
- **Pacote para rodar no Windows:**
  https://github.com/RonaldoSouza74/Analisa-Deck-SDDP/raw/claude/nice-newton-23r08d/downloads/agregacao_uf.zip
  (scripts .py + .bat + tabelas + `LEIAME.txt` com passo a passo).
- **Estrutura do repositório:**
  - `scripts/` — todos os scripts Python e .bat (fonte do pacote).
  - `resultados/estudo_perdas_2025/` — tabelas de UF (barras, usinas, cargas, conexões), limites de rede
    2030, gráficos 2030 e análise de dias úteis x fins de semana (com dados reais de 2030).
  - `downloads/` — zips para baixar (pacote, gráficos, limites, metodologia).
  - Raiz: partes `estudo_perdas_2025.zip.001` a `.013` (deck + saídas de uma rodada anterior, 2025), `.hdr`
    da rodada 2030 (gergnd, vergnd, businj/bus_inj, cmgbus, acline_flow, transformer_flow, envetu, envehd,
    gerhid, gerter, demxba, cmgsuc, sumcir, lscsup, usedcl) e `.bin` pequenos (cmgsuc, sumcir, lscsup,
    usedcl). `methodology/` (manual de metodologia do SDDP, HTML) e `interface_guide.zip` (guia da interface;
    não descreve os arquivos de barras).
- **Como os arquivos chegam ao Claude:** o usuário sobe pelo GitHub (navegador). Limites: 100 arquivos por
  upload e 25 MB por arquivo no navegador; para pastas grandes, compactar com 7‑Zip em volumes de 24 MB
  (formato zip). Os `.bin` grandes (vários GB) **não** vão para o GitHub: os scripts rodam no computador do
  usuário e só os resultados (CSV/PNG pequenos) são enviados para análise.
- **Execução:** o usuário roda os `.bat` no Windows (Python 3 + numpy + matplotlib). Resultados em
  `<pasta do caso>\resultados_uf`. O `rodar_tudo.bat` grava tudo o que aparece na janela em
  `resultados_uf\log_rodar_tudo.txt`.

## 3. Preferências e regras combinadas com o usuário

- Responder em **português**, de forma didática; explicar termos (CMO, mediana, faixa 5–95%, etc.).
- Instruções sempre **passo a passo para Windows** (o usuário não programa em Python).
- **Usar apenas dados de entrada e saída do SDDP** — **sem estimativas ou hipóteses próprias** (ex.: foi
  descartada uma estimativa de fim de semana com redução de carga suposta, a pedido do usuário).
- **CSV:** vírgula como separador e **ponto decimal** (o Excel do usuário usa esse padrão). Os CSV horários
  seguem o formato dos CSV exportados pelo SDDP/Graf (3 linhas de cabeçalho + colunas `Mês,Cenários,Hora`).
- **Gráficos:** hora do dia **1 a 24** no eixo x (hora 1 = 00h–01h); **box plot dos 10 cenários**; quando há
  eixo secundário (pedido do usuário), separar visualmente (carga na faixa de cima, caixas embaixo).
- Perguntar quando houver ambiguidade; testar scripts antes de entregar (testes com dados sintéticos de
  resposta conhecida) e deixar claro que gráficos de teste **não** são resultados reais.
- Commits no branch `claude/nice-newton-23r08d`; pacote `downloads/agregacao_uf.zip` sempre atualizado.

## 4. Formatos de dados do SDDP (descobertos e validados)

- **Saídas binárias `.hdr` + `.bin` (formato PSR/Graf):**
  - `.hdr` com registros estilo Fortran (4 bytes de tamanho antes e depois de cada registro):
    registro 1 = versão; registro 2 = 10 inteiros (estágio inicial, nº de estágios, nº de cenários,
    nº de agentes, varia por cenário, varia por bloco, discretização horária, tipo de estágio (2 = mensal),
    mês inicial, ano inicial) + unidade (7 caracteres) + tamanho do nome; registro 3 (saídas horárias) =
    horas acumuladas por estágio (ex.: 0, 744, 1488, 2160, …); depois um registro por agente com o nome.
  - `.bin`: float32, ordem **estágio → cenário → hora → agente**, sem cabeçalho. Tamanho = horas × cenários ×
    agentes × 4 (os scripts conferem).
  - Energia em GWh por hora (×1000 = MWh na hora = MW médio). `demxba` não varia por cenário.
  - Alguns `.hdr` são por bloco (ex.: `lscsup`, 4 blocos/mês, sem cenário) — não usados.
- **Convenção de horas:** dentro de cada mês, hora 1 a 744; cada bloco de 24 h é um dia (hora 1 = 00h–01h);
  o SDDP não usa 29/02. Validado pelo perfil de carga (mínima ~hora 5, ponta ~hora 20).
- **CSV exportado pelo SDDP** (exemplo `vergnd_Distribuicao`): linhas `Varies per block?`, `Varies per
  sequence?`, `# of agents`, depois `Mês,Cenários,Hora,<agentes>`; ordem estágio → cenário → hora.
- **Validação cruzada:** a soma por UF do `vergnd` calculada pelos scripts bateu hora a hora com o CSV do
  SDDP por subsistema (diferença máxima 0,09 MW em 87.600 horas).

## 5. O que se sabe do deck

- **Barras:** 13.188 barras CA (`dbus.dat`) + 64 barras CC (`ddcbus.dat`, numeração própria que se repete
  com a das CA). Nomes no padrão ANAREDE `NOMEXX-UFkkk` (ex.: `S.BONF-BA138`).
- **UF de cada barra** (`scripts/barras_uf.py`): pelo nome (81,7%), pelo nome das usinas renováveis ligadas
  (10,1%, ex.: `EOLRN031759`), pela rede (vizinhos, 8,2%); barras CC pela barra CA do conversor. Acertos
  nos testes: rede 98,9%, usina 98,8%. 100% das barras com UF.
- **Usinas:** 9.398 renováveis (`cgnd??.dat`; tecnologias Eólica, Solar, GD Solar (MMGD), Outras GD (OMGD),
  Biomassa (PCT/PBI/PRS), PCH), 176 hidrelétricas, 255 térmicas. Ligação à barra por `busconnection.dat`;
  hidrelétricas grandes e 55 térmicas ligam pelas **unidades geradoras** (`hydrounit??.dat`,
  `thermunit??.dat`). 146 renováveis estão em barra de UF diferente da UF do nome (divisa).
- **Renováveis — dados de entrada:** `hgndhr.dat` = histórico horário 1981–2022 de 75 estações (eólicas,
  solares, GD) usado para gerar cenários (`gndforh.dat`: 10 cenários × 8.760 h × 75 estações);
  `hrrenw.dat` = perfis horários fixos (um cenário, 2025–2039) de 228 estações (PCH, biomassa, GD, etc.).
  Ligação usina → estação em `gndsite??.dat` (coluna Datasource), `cgnd??.dat` (Stat.) e `gndrps.dat`.
- **Carga (`hrload??.dat`):** 2025–2040, por subsistema. **Padrão semanal do deck:** em todo mês, **domingos
  = dias 1, 8, 15, 22, 29** e **sábados = dias 7, 14, 21, 28** (não segue o calendário real); domingo ~10,5%
  e sábado ~4,2% abaixo da média do mês; feriados de data fixa (1/1, 1/5, 25/12) com carga menor.
  Não segue os dias da semana do calendário de 2030 (análise por calendário real foi descartada).
- **Rede:** todas as alterações (`mcirc`, `mtrans`, `circstatus`…) ocorrem em 1º de janeiro → rede
  constante no ano. **Circuitos monitorados** (limite imposto pelo SDDP): 2.540 de 10.836 linhas e 3.165 de
  7.365 transformadores (FlagMonitored). Limite 99999 = sem limite. Linhas: `Rating` (normal) e
  `EmergencyRating`; trafos: `Rn` e `Re`.
- **Restrições de intercâmbio (`csumcirc.dat`):** EXPN CA, NNSE→SE, RECNE, EXPNE, RSUL CA, RSE,
  FNS+Bip GAranha, XI→SE, XI←SE, XI→MAN, NE→N, NE→SE, TP→SE, AC/RO↔SE, MAD→SE (+ Itaipu, Madeira, Graça
  Aranha, Xingu). Limites 2030 (`lscsup`): EXPNE 19,5–21,5 GW; NE→SE 13,2–14 GW; NNSE→SE 20,5–25 GW;
  NE→N 7,5 GW; RECNE 11 GW.
- **Elos CC 2030:** Itaipu (PR→SP, 4×1.566 MW), Madeira (RO→SP, 4×1.575 MW), Xingu (PA→MG e PA→RJ),
  Graça Aranha–Silvânia (MA↔GO, novo em 2030).
- **Capacidade de divisa por estado** (soma dos limites dos circuitos que cruzam a divisa — limite
  teórico, muito acima da capacidade real de transferência): ex. MG ~140 GW, SP ~116/128 GW, BA ~94 GW,
  AC 1,6 GW. Em `resultados/estudo_perdas_2025/limites_rede_2030/`.

## 6. Resultados já obtidos com dados reais (2030, estágios 2–13, média dos 10 cenários)

- **Vertimento renovável Brasil:** **43.254 GWh**. Por estado: BA 12.094; RN 7.385; MG 5.885; PB 4.644;
  PI 3.813; CE 2.506; PE 1.888; SP 1.575; GO 1.433; MS 791 GWh.
- **% vertido** [vertimento/(geração+vertimento)]: PB 26,7%; BA 15,2%; MG 14,7%; PI 12,0%; RN 11,9%;
  PE 11,9%; GO 11,0%; CE 10,1%.
- **Perfil:** vertimento concentrado das 8h às 16h; no NE e em MG/GO/MS mais em jul–out.
- **Injeção líquida (businj):** soma de todas as barras = 0 em todas as horas (rede sem perdas) → injeção do
  estado = saldo de intercâmbio. businj = geração de todas as fontes da barra − carga da barra.
  Ex.: MG às 13h: renovável 8,6 GW, injeção 2,4 GW (carga local consome parte).
- **Correlações horárias:** vertimento × carga líquida do SIN (carga − renovável disponível) = −0,83 (BR);
  vertimento × carga = −0,34; no NE, injeção × geração renovável ≈ 0,95–1,00.
- **Dias úteis × fins de semana** (fim de semana = 2 dias de menor carga de cada semana do mês, pelo deck):
  carga 104,0 GW × 92,2 GW (−11,4%); vertimento BR **95 × 175 GWh/dia (+84%)**; BA 28→45, RN 16→29,
  MG 12→26, PB 11→16, PI 8→16, CE 5→11 GWh/dia.
- **Restrições de intercâmbio (cmgsuc ≠ 0 = no limite):** EXPNE 0,6% das horas; NE→SE 5,4%; NNSE→SE 5,3%;
  NE→N 0,9%; FNS+Bip GAranha 11,4%; AC/RO↔SE ~30%. Só **7,9%** do vertimento do NE ocorre com alguma
  restrição do NE no limite (SE/CO 1,9%; Sul 0,6%) → a maior parte do vertimento **não** coincide com
  limites de intercâmbio entre regiões (falta separar excesso sistêmico × gargalos internos via cmgbus).
- **Margem por barra (businj × circuitos monitorados):** todas as barras deram "com margem" — esperado,
  porque o SDDP impõe os limites dos circuitos monitorados no despacho; levou à abordagem por CMO e fluxos.

## 7. Pacote de scripts (`scripts/`, etapas do `rodar_tudo.bat`)

| Etapa | .bat | Script | O que faz |
|---|---|---|---|
| 1 | `rodar_agregacao.bat` | `agrega_saidas_uf.py` | Lê gergnd, vergnd, businj (ou bus_inj), bus_losses (.hdr/.bin) e soma por UF: `<var>_uf_horario.csv` (formato SDDP), `_uf_mensal.csv`, `_agente_mensal.csv`, `checagem.txt` |
| 2 | `rodar_limites.bat` | `limites_uf.py` | Capacidade dos circuitos de divisa por UF (CA, trafos, elos CC) e restrições de intercâmbio: `limites_uf.csv`, `limites_pares_uf.csv`, `circuitos_fronteira_uf.csv`, `restricoes_intercambio.csv` |
| 3 | `rodar_graficos.bat` | `graficos_uf.py` | Box plots por hora (geração, vertimento, injeção) com linhas de limite de exportação/importação, painel dos 27 estados, mapas de calor mês×hora, injeção×vertimento, ranking, vertimento por tecnologia e UF da usina×UF da barra |
| 4 | `rodar_analise_semana.bat` | `analise_semana_carga.py` | Dias úteis × fins de semana (2 dias de menor carga por semana): gráficos diários mês a mês e perfil horário médio mensal com carga no eixo secundário, resumo, correlações, carga líquida×vertimento |
| 5 | `rodar_margem.bat` | `margem_barras.py` | Classifica barras com/sem margem (businj × soma dos circuitos monitorados) e agrega por UF |
| 6 | `rodar_gargalo.bat` | `gargalo_cmo.py` | **Gargalo pelo CMO:** usina com vertimento cuja barra tem CMO > 1 $/MWh abaixo da mediana do SIN = gargalo; senão excesso. **A GD (MMGD/OMGD) fica fora** (no deck CurtCos = 11 $/MWh, contra 10 das centralizadas, e o SDDP a corta; na operação real ela não é cortada). Usa cmgbus, vergnd, envetu, cmgsuc, cmglnk. Gera `gargalo_mensal_<UF>.png` (vertimento por causa mês a mês), resumo, restrições ativas, CSVs horários (vertimento gargalo/excesso, CMO e diferença de CMO por UF) e `perfil_horario_uf.csv` (por UF e hora do dia: vertimento por causa, CMO do estado, do SIN, das barras das usinas que verteram, ponderado pelo MW vertido, e dos 3 vizinhos de maior capacidade de divisa) |
| 7 | `rodar_gargalo_linhas.bat` (etapas 6+7+8) | `gargalo_linhas.py` | **Gargalo pelas linhas:** fluxos (acline_flow, transformer_flow) × limites do deck; circuitos monitorados no limite (≥99%) com lado preso e vertimento coincidente; não monitorados em sobrecarga (>100%); **gráfico padronizado por UF** `por_estado\estado_<UF>.png` (todos os painéis com hora 1–24 alinhada: vertimento renovável e hidro por causa; CMO estado × SIN × 3 vizinhos; CMO das barras das renováveis e, em outro painel, das hidrelétricas no momento em que verteram × SIN e vizinhos nesses momentos; carregamento % das 4 linhas monitoradas que mais limitam; não monitoradas >100%) e dispersão injeção×vertimento por causa |
| 8 | (no rodar_tudo / rodar_gargalo_linhas) | `relacao_gargalo.py` | Por UF, 3 colunas (horas com gargalo / só excesso / sem vertimento): nº de ocorrências, vertimento, injeção, CMO do estado/SIN/vizinhos e fluxo real × limite físico (Rating e emergência) das linhas que mais limitam; `ocorrencias_estados.png`; `relacao_por_hora.csv` |
| 9 | `rodar_balanco.bat` | `balanco_uf.py` | Balanço por UF: renovável + hidro (gerhid) + térmica (gerter) − carga (demxba) = injeção; consumido no estado / exportado (contorno roxo) / vertido (hachurado), separado por situação da hora |
| 10 | `rodar_gargalo_subsistema.bat` | `gargalo_subsistema.py` | **Gargalo entre subsistemas:** CMO do subsistema (mediana das barras CA do subsistema, 14 do sistem.dat) × SIN; vertimento (vergnd sem GD, envetu) em gargalo entre subsistemas / dentro do subsistema (barra < subsistema) / excesso. Intercâmbio = fluxo nos 425 circuitos de fronteira da saída `interc` (com rede DC o SDDP não usa os limites do interc.dat), somado por par e comparado com Rating/Rn e conversores CC. Gera resumo, mensal, `subsistema_<ID>.png`, `intercambios_subsistemas.png/.csv` e CSVs |
| — | `rodar_apresentacao.bat` | `apresentacao.py` | Monta `resultados_uf\apresentacao\apresentacao_vertimento_<ano>.pptx` (python-pptx) com os PNGs das etapas e títulos calculados dos CSVs; gera `mapa_vertimento_uf.png` (mapa do Brasil por UF, contorno IBGE em `mapa_uf.json`) e `tecnologia_uf.png` (ano, sem GD); divide figuras altas em 2–3 slides |
| — | `rodar_tudo.bat` | `com_log.py` | Roda as 10 etapas (pode pular a etapa 1 com S, se os resultados dela existirem) e grava o log |
| — | (sem .bat) | `barras_uf.py` | Refaz as tabelas de UF a partir do deck |

**Tabelas do pacote:** `barras_uf.csv`, `usinas_renovaveis_uf.csv`, `conexoes_usinas_uf.csv`, `limites_uf.csv`.

**Arquivos necessários na pasta do caso:**
- `.hdr` + `.bin` obrigatórios: gergnd, vergnd, businj (ou bus_inj), cmgbus, acline_flow, transformer_flow,
  gerhid, gerter, demxba. Opcionais: envetu, cmgsuc, cmglnk, bus_losses. (~25 GB no total.)
- `.dat` do deck: hrload??, dcirc, mcirc, circstatus_b004m, dtrans, mtrans, transtatus_b004m, ddcline,
  mdcline, dclinestatus_b004m, dcnvlcc, mcnvlcc, csumcirc, sumcircub_b004m, chidro??, hydrounit??,
  ctermi??, thermunit??.

**Detalhes de uso:** estágios para 2030 = `2 13` (o .bat aproveita só os dois primeiros números digitados);
ano = 2030; para outro ano, os estágios dependem do início da rodada (rodada iniciando em dez/(A−1):
`2 13`; iniciando em jan/A: `1 12`).

## 8. Conceitos e explicações já dadas ao usuário

- **Gargalo pelo CMO:** sem limite de rede ativo, o CMO é igual em todas as barras; quando uma linha chega
  ao limite os preços se separam — atrás do gargalo o CMO cai (energia presa). CMO da barra da usina abaixo
  do SIN → gargalo; igual → excesso no sistema (falta de demanda). Diz **se** há gargalo.
- **Gargalo pelas linhas:** fluxo do SDDP ≥ 99% do limite em circuito monitorado → no limite (lado preso =
  barra de menor CMO); não monitorado > 100% → sobrecarga que o SDDP não limita. Diz **onde** está.
- **MW médio** (vertimento): média sobre as ocorrências (dias × cenários) daquela hora naquela situação.
  **Mediana e faixa 5–95%**: valor do meio e intervalo que contém 90% das ocorrências.
- **Térmicas não têm "vertimento"**: são reduzidas até o mínimo.
- Capacidade de divisa somada ≠ capacidade de transferência (N‑1, distribuição de fluxo).

## 9. Situação atual e próximos passos

- **Pendente do usuário:** rodar o `rodar_tudo.bat` (pacote mais recente) com os dados reais de 2030 e
  enviar: `resultados_uf\log_rodar_tudo.txt`, `gargalo_linhas\por_estado\estado_<UF>.png`, `gargalo_cmo\gargalo_resumo.png` e
  `vertimento_causa_uf_mensal.csv`, `gargalo_linhas\circuitos_no_limite.csv`, `gargalos_por_uf.csv` e PNGs,
  `relacao_gargalo\relacao_<UF>.png` (BA, RN, MG, PB, PI), `ocorrencias_estados.png`,
  `relacao_por_hora.csv`, `balanco_uf\balanco_resumo.png`, `balanco_situacao_uf.csv` e `balanco_<UF>.png`.
- Último erro relatado: etapa 3 sem `*_uf_horario.csv` (etapa 1 pulada sem ter rodado na pasta) — corrigido:
  o .bat agora roda a etapa 1 se os resultados dela não existirem.
- **Ideias/próximos passos discutidos:**
  - Interpretar os resultados reais: quanto do vertimento é gargalo × excesso por estado, quais linhas.
  - Opção de os .bat perguntarem só o **ano** e calcularem os estágios a partir do `.hdr` (não implementado).
  - Incluir baterias (`gerbat`) no balanço se a parcela "outros" ficar grande.
  - Analisar 2032 (ou outros anos) com novas rodadas (mesmos scripts; informar o ano e os estágios).
  - Se surgirem barras/usinas novas em outro deck: rodar `barras_uf.py` para refazer as tabelas.

## 10. Lições práticas

- O Excel do usuário separa colunas por vírgula (CSV com `;` não abre direito).
- Upload no GitHub pelo navegador: até 100 arquivos e 25 MB por arquivo; usar 7‑Zip com volumes de 24 MB.
- `.bat`: o usuário pode digitar o exemplo inteiro ("2 13 para o ano de 2030") — os scripts aproveitam só
  os números; `echo texto>> arquivo` com texto terminando em dígito é interpretado como redirecionamento
  (usar `>> arquivo echo texto`).
- Rodar as etapas em ordem: 3, 4, 8 e 9 usam CSVs criados pelas etapas 1, 6 e 7.
