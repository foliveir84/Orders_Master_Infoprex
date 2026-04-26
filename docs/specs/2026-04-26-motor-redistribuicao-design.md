# Documento de Especificação Lógica e Funcional — Motor de Redistribuição de Inventário

**Data:** 2026-04-26
**Versão:** 2.0 (refeita a partir do doc original v1.0 + análise do `Sell_Out_GRUPO_mylan.xlsx` + código existente em `stockreorder.py`/`app.py`)
**Estado:** Especificação validada com o utilizador, pronta para implementação.

---

## 0. Contexto e Objetivo

Sistema autónomo de redistribuição de stock entre farmácias do mesmo grupo. Otimiza a **cobertura de prateleira**, previne **ruturas** e **escoa stock antes da caducidade**, ignorando custos logísticos.

A redistribuição obedece a duas fases sequenciais e dependentes:
1. **Fase 1 — Apagar Fogos**: prevenir ruturas iminentes usando excessos de outras lojas.
2. **Fase 2 — Evacuação de Zombies**: limpar peso morto crónico para lojas com escoamento provado.

A avaliação é **dinâmica**: cada transferência atualiza o stock do doador (↓) e do recetor (↑) em tempo real, e os limiares são re-avaliados antes do próximo emparelhamento.

---

## 1. Estrutura do Dataframe de Entrada

O motor recebe um `DataFrame` (`df_input`) já filtrado e agregado pelo pipeline `app.py`. Cada linha representa um par único **(produto, loja)**.

### 1.1. Colunas obrigatórias

| Coluna | Tipo | Descrição |
|---|---|---|
| `CÓDIGO` | int | CNP/CPR do produto. |
| `DESIGNAÇÃO` | str | Nome do produto (já normalizado em title case). |
| `LOCALIZACAO` | str | Nome da farmácia (e.g. `Colmeias`, `Guia`, `Ilha`, `Souto`). |
| `STOCK` | int | Stock atual em unidades. |
| `PVP_Médio` | float | Preço de venda médio (informativo, não usado pelo motor). |
| `P.CUSTO` | float | Preço de custo (informativo, não usado pelo motor). |
| `DUC` | str (`DD/MM/YYYY`) | Data da Última Compra. **Pode ser nula.** |
| `DTVAL` | str (`MM/YYYY`) | Data de Validade do lote. **Pode ser nula.** |
| `<colunas mensais>` | int | Vendas por mês (nº variável, ordenadas cronologicamente da esquerda para a direita). |
| `T Uni` | int | Total acumulado (sentinela de fim das colunas mensais). |

### 1.2. Convenções de leitura

- **`T Uni` é sempre a última coluna** do dataframe. As `N` colunas imediatamente à esquerda são meses cronológicos crescentes (a coluna mais à direita antes de `T Uni` é o mês mais recente).
- O `DataFrame` chega ao motor com **as últimas 6 colunas mensais** disponíveis (necessárias para janela de Failsafe). As últimas 4 são usadas para Run Rate.
- **Pressuposto de lote único**: cada linha tem **1 STOCK + 1 DTVAL**. Assume-se que toda a quantidade da linha partilha a mesma DTVAL. O motor não trata multi-lote.

### 1.3. Pré-filtros aplicados a montante (em `app.py`)

Estes filtros já estão aplicados quando o DF chega ao motor; o motor não os repete:
- Linhas sem stock e sem vendas removidas (`STOCK == 0 AND T Uni == 0`).
- Códigos locais (começados por `1`) removidos.
- Códigos não-numéricos removidos.

### 1.4. Pré-filtros aplicados pelo motor

- **Filtro institucional**: remover linhas em que `LOCALIZACAO.str.contains('Zgrupo', case=False)`. Captura `Zgrupo_Total` e variantes (consolidados que não são pontos de venda finais).

---

## 2. Variáveis Calculadas

### 2.1. Run Rate (média ponderada de 4 meses)

Janela: **4 meses**, pesos `[0.40, 0.30, 0.20, 0.10]` (mais recente → mais antigo).

O comportamento depende do **Toggle Operacional** definido pelo utilizador (`anterior` em `app.py`):

#### Cenário A — Toggle Fechado / "Mês Anterior" (`anterior = True`, início do mês)
Ignora a coluna mais recente (assumida parcial e potencialmente enganosa).
Janela usada: `[idx-2, idx-3, idx-4, idx-5]` relativas a `T Uni`.

```
Run Rate = M(-2)*0.40 + M(-3)*0.30 + M(-4)*0.20 + M(-5)*0.10
```

#### Cenário B — Toggle Aberto / "Fim do Mês" (`anterior = False`, default)
Inclui a coluna mais recente, mas com **normalização obrigatória a 30 dias** se for o mês corrente em curso.
Janela usada: `[idx-1, idx-2, idx-3, idx-4]`.

```
M_atual_normalizado = (Vendas_M_Atual / DiaAtualDoMês) * 30
Run Rate = M_atual_normalizado*0.40 + M(-2)*0.30 + M(-3)*0.20 + M(-4)*0.10
```

> **Nota operacional**: a normalização a 30 dias só deve ser aplicada se a coluna mais recente for de facto o mês corrente em curso (verificar `DiaAtualDoMês > 0` e a coluna corresponder ao mês de `datetime.now()`). Caso o ficheiro tenha sido extraído com o último mês já fechado (caso real do exemplo `Sell_Out_GRUPO_mylan.xlsx` — última coluna `MAR.1` referente a Março/2026, hoje é Abril/2026), a normalização não se aplica e a coluna entra crua com peso 0.40.

### 2.2. DLV — Data Limite de Venda

```
DLV = DTVAL_parsed − margem_dias
```

- `DTVAL_parsed` = último dia do mês indicado em `DTVAL` (ex.: `09/2026` → `2026-09-30`).
- `margem_dias` é **configurável via slider** (default `60`, range `0–180`).
- Se `DTVAL` for nulo, **DLV é considerada longa/segura** (não bloqueia transferências).

A DLV substitui DTVAL como referência temporal em **toda a matemática de validade** (`Meses_Para_DLV`, `Recall`, Bloqueador de Validade).

### 2.3. Cobertura Atual (meses de stock)

```
Cobertura = STOCK / Run Rate              se Run Rate > 0
Cobertura = +∞                            se Run Rate == 0 e STOCK > 0
Cobertura = 0                             se Run Rate == 0 e STOCK == 0
```

Nas operações de ordenação, `+∞` deve ser tratado com `np.inf` (não com sentinela como `999`).

### 2.4. Capacidade Máxima de Receção

Espaço livre no recetor até atingir o cap de cobertura `2.0`:

```
Capacidade_Recepção = (Run Rate × 2.0) − STOCK
```

Se ≤ 0, o recetor está cheio.

### 2.5. Meses até DLV

```
Meses_Para_DLV = (DLV − hoje) / 30.0
```

Se DTVAL for nulo, `Meses_Para_DLV = +∞` (validade longa).

### 2.6. Capacidade Real de Escoamento (Bloqueador de Validade)

Limite máximo que um recetor pode aceitar dado o tempo até DLV do lote do doador:

```
Capacidade_Escoamento = (Run Rate_recetor × Meses_Para_DLV_doador) − STOCK_recetor
```

A quantidade efetivamente transferível é `min(Capacidade_Escoamento, Capacidade_Recepção)`.

### 2.7. Sinalizadores derivados

| Variável | Definição |
|---|---|
| `Is_Novo` | `True` se `(hoje − DUC) < 60 dias`. Se DUC for nulo, `False` (imunidade perdida). |
| `Recall` | `True` se `DLV < hoje`. Produto não-transferível (ver §3.1). Substitui o conceito anterior de "Validade_Curta": como a margem (default 60 dias) está embebida na DLV, qualquer produto não-Recall é, por construção, transferível do ponto de vista de validade. O Bloqueador de Validade (§4.2) garante a matemática de escoamento. |
| `Teve_Vendas_6m` | `True` se a soma das 6 colunas mensais mais recentes > 0. |
| `Meses_Com_Vendas_4m` | nº de colunas (entre as 4 do Run Rate) com vendas > 0. |
| `Vendeu_Mes_Corrente` | `True` se a primeira coluna da janela do Run Rate > 0. |
| `Vendeu_Mes_Anterior` | `True` se a segunda coluna da janela do Run Rate > 0. |

---

## 3. Condições de Exclusão e Gatekeepers

### 3.1. Bloqueio de Recall (DLV no passado)

Se `DLV < hoje`, o produto é **excluído completamente** do plano (não doa, não recebe, não aparece no output). É tratamento operacional separado.

### 3.2. Período de Imunidade (Novidades)

Produtos com `Is_Novo = True` (DUC < 60 dias) **não são classificáveis como Zombie**, mesmo com 0 vendas. Protege novidades acabadas de chegar à prateleira que ainda não tiveram tempo de rodar.

> Não impede o produto de ser considerado **excesso normal** se tiver Run Rate > 0 e cobertura > 2.5.

### 3.3. Filtro Institucional

`LOCALIZACAO.str.contains('Zgrupo', case=False)` removido antes de qualquer cálculo.

---

## 4. Regras Obrigatórias de Negócio

### 4.1. Failsafe Clínico (Reserva de Serviço)

Para garantir que doentes crónicos não ficam sem resposta, o doador retém **obrigatoriamente 1 unidade de segurança** sempre que o produto teve **≥ 1 venda nos últimos 6 meses** (`Teve_Vendas_6m == True`).

Janela: 6 colunas mensais mais recentes da disponibilidade, **independente do toggle**.

Excepção — **Zombie Puro**: se `Run Rate == 0 AND Teve_Vendas_6m == False`, o Failsafe é desativado e 100% do stock é transferível.

### 4.2. Bloqueador de Validade

Um recetor nunca aceita uma quantidade que demore mais a vender do que a vida útil do lote do doador:

```
Qtd_Final = min(
    Necessidade_Recetor,
    Excesso_Líquido_Doador,
    Capacidade_Escoamento (definida em §2.6)
)
```

Se `Capacidade_Escoamento ≤ 0`, a transferência é cancelada para esse par.

### 4.3. Critério "Destino Forte"

Uma loja só é elegível para receber stock (Fase 1 ou Fase 2) se:

```
Destino_Forte = (Run Rate > 0)
                AND (
                    Vendeu_Mes_Corrente
                    OR (Vendeu_Mes_Anterior AND Meses_Com_Vendas_4m >= 2)
                )
```

Aplica-se igualmente em Fase 1 e Fase 2 para evitar alimentar lojas com picos isolados (falsas ruturas).

### 4.4. Quantidade Mínima de Transferência

Mínimo de **1 unidade** em ambas as fases. Transferências de 0 não são geradas.

---

## 5. Tabela de Categorização (Run Rate × Histórico de 6 meses)

| # | Run Rate (4m) | Vendas 6m | Classificação | Quantidade Transferível |
|---|---|---|---|---|
| 1 | `> 0` | `> 0` | Excesso Normal | `STOCK − ⌈Run Rate × 2.0⌉ − 1` (Failsafe ativo) |
| 2 | `= 0` | `> 0` | Zombie com Failsafe | `STOCK − 1` (Failsafe ativo) |
| 3 | `= 0` | `= 0` | Zombie Puro | `STOCK` total (Failsafe desativado) |
| 4 | `> 0` | `= 0` | (Impossível por construção) | n/a |

Linhas com `Is_Novo == True` não entram nas categorias 2 ou 3 (protegidas).
Linhas com `Recall == True` não entram em nenhuma categoria.
A linha do excesso normal (1) também aplica `−1` apenas se `Teve_Vendas_6m == True` (Failsafe ativo); caso contrário cede `STOCK − ⌈Run Rate × 2.0⌉` integral.

---

## 6. Algoritmo Lógico Passo-a-Passo

### 6.1. Pseudocódigo de alto nível

```
df = receber_dataframe()
df = aplicar_filtro_zgrupo(df)
df = excluir_recall(df)
df = calcular_variaveis(df)            # §2

# === FASE 1: Apagar Fogos ===
df = identificar_recetores_fase1(df)   # cobertura < 1.5 AND Destino_Forte
df = identificar_doadores_fase1(df)    # cobertura > 2.5
df = aplicar_failsafe(df)
sugestoes_f1 = emparelhar_fase1(df)    # ordenação γ + dinâmica completa
df = atualizar_stock_virtual(df, sugestoes_f1)
df = recalcular_variaveis(df)          # loop de recálculo entre fases

# === FASE 2: Evacuação de Zombies ===
df = identificar_doadores_fase2(df)    # Zombie ou Zombie Puro
df = identificar_recetores_fase2(df)   # Destino_Forte (mesmo critério da Fase 1)
sugestoes_f2 = emparelhar_fase2(df)    # ordenação γ + dinâmica completa

plano_final = consolidar(sugestoes_f1, sugestoes_f2)
return plano_final
```

### 6.2. Fase 1 — Apagar Fogos

**Objetivo:** garantir nível de serviço em lojas em risco de rutura.

**Identificação de Recetores:**
- `Destino_Forte == True` (§4.3)
- `Cobertura < 1.5` meses
- `Recall == False`

**Necessidade do Recetor:**
```
Necessidade = ⌈(Run Rate × 2.0) − STOCK⌉
```
(arredondamento para cima — preferimos pedir um pouco mais a ficar curto).

**Identificação de Doadores:**
- `Cobertura > 2.5` meses
- `Recall == False` (já filtrado a montante em §3.1, mantido aqui por clareza)

**Excesso Bruto do Doador:**
```
Excesso_Bruto = ⌊STOCK − (Run Rate × 2.0)⌋
```
(arredondamento para baixo — só cedemos o que sobra com folga; cap em 2.0 = alvo).

**Aplicação do Failsafe (§4.1):**
```
Excesso_Líquido = min(Excesso_Bruto, STOCK − 1)   se Teve_Vendas_6m
Excesso_Líquido = Excesso_Bruto                    caso contrário
```

**Ordenação (γ):**
- **Recetores**: `Cobertura` ascendente (maior risco primeiro). Em empate: maior `Run Rate` primeiro.
- **Doadores**: `Meses_Para_DLV` ascendente (limpa validade enquanto resolve rutura). Em empate: `Cobertura` descendente (maior excesso primeiro).

**Emparelhamento:** para cada produto (`groupby('CÓDIGO')`), iterar:

```python
for recetor in recetores_ordenados:
    if recetor.Necessidade <= 0: continue
    for doador in doadores_ordenados:
        if doador.Excesso_Líquido <= 0: continue
        capacidade_escoamento = floor(recetor.RunRate × doador.Meses_Para_DLV) − recetor.STOCK
        if capacidade_escoamento <= 0: continue
        qtd = min(recetor.Necessidade, doador.Excesso_Líquido, capacidade_escoamento)
        qtd = floor(qtd)
        if qtd < 1: continue
        registar_transferencia(doador, recetor, qtd, fase=1)
        # atualização dinâmica completa
        doador.STOCK -= qtd
        doador.Excesso_Líquido -= qtd
        recetor.STOCK += qtd
        recetor.Necessidade = ceil((recetor.RunRate × 2.0) − recetor.STOCK)
        recetor.Cobertura = recetor.STOCK / recetor.RunRate
        if recetor.Necessidade <= 0: break
```

### 6.3. Loop de Recálculo (entre fases)

Após Fase 1:
- Re-aplicar §2 (Run Rate não muda; mas Cobertura, Capacidade_Recepção, Capacidade_Escoamento mudam).
- **Não** iterar Fase 1 mais que uma vez (`p`: 1 passagem por fase).

### 6.4. Fase 2 — Evacuação de Zombies

**Objetivo:** mover dead-stock crónico para onde tem saída validada.

**Identificação de Doadores:**
- `Run Rate == 0 AND STOCK > 0 AND Is_Novo == False AND Recall == False`
- Categorias 2 ou 3 da tabela em §5.
- Quantidade transferível conforme Failsafe (categoria 2: `STOCK − 1`; categoria 3: `STOCK` total).

**Identificação de Recetores:**
- `Destino_Forte == True`
- `Cobertura < 2.0` (têm capacidade de receber até ao cap).

**Capacidade do Recetor:**
- Limitada dinamicamente pela `Capacidade_Escoamento` (§2.6) calculada contra a DLV do doador no momento do emparelhamento. A `Necessidade` "lógica" é tratada como ilimitada (sentinela alto), mas o cap real é o de escoamento.

**Ordenação (γ):**
- **Doadores**: `Meses_Para_DLV` ascendente (escoar primeiro o que está mais perto de caducar). Em empate: `STOCK` descendente (atacar maior foco de estagnação primeiro).
- **Recetores**: `Run Rate` descendente (priorizar destino com maior tração).

**Emparelhamento:** análogo a Fase 1, mas com:
- `qtd = min(Excesso_Líquido_Doador, Capacidade_Escoamento, Capacidade_Recepção_Atual)`
- Critério de paragem do recetor: `Cobertura ≥ 2.0`.

### 6.5. Consolidação

- Concatenar `sugestoes_f1` e `sugestoes_f2`.
- Ordenar por `Origem, Destino, DESIGNAÇÃO`.
- Output conforme §7.

---

## 7. Output do Plano Final

### 7.1. Esquema fixo (DataFrame)

| Coluna | Tipo | Descrição |
|---|---|---|
| `CÓDIGO` | int | Código do produto. |
| `DESIGNAÇÃO` | str | Nome do produto. |
| `Origem` | str | Loja doadora. |
| `Motivo Saída` | str | Ver §7.2. |
| `Stock_Origem` | int | Stock do doador **antes** da transferência. |
| `Validade` | str | DTVAL crua do lote. |
| `Qtd Transferir` | int | Unidades. |
| `Destino` | str | Loja recetora. |
| `Motivo Entrada` | str | Ver §7.2. |
| `Stock_Destino` | int | Stock do recetor **após** a transferência. |
| `Tempo_Escoamento_Previsto` | str | `f"{Stock_Destino_pós / Run Rate_recetor:.1f} meses"` ou `"N/A"`. |
| `Fase` | int | `1` ou `2`. |

Ordenação final: `Origem ↑, Destino ↑, DESIGNAÇÃO ↑`.

### 7.2. Vocabulário dos motivos

**Motivo Saída:**
- `Excesso (Cob: Xm)` — Fase 1, doador com cobertura > 2.5.
- `Evacuação Zombie` — Fase 2, categoria 2 (com Failsafe).
- `Evacuação Zombie Puro` — Fase 2, categoria 3 (sem Failsafe).

**Motivo Entrada:**
- `Risco Rutura (Cob: Xm)` — Fase 1.
- `Forte Escoamento (Média: X)` — Fase 2.

---

## 8. Parâmetros Configuráveis (UI)

| Parâmetro | Default | Range | Localização |
|---|---|---|---|
| Toggle "Mês Anterior" | OFF | bool | `app.py` (já existe) |
| Margem DLV (dias) | 60 | 0–180 | Slider no painel Redistribuição (substitui o atual "Meses Mínimos de Validade", agora em dias e com default mais permissivo) |
| Dias Imunidade | 60 | 0–180 | Slider já existente (default a alterar de 90 para 60 para alinhar com §3.2) |
| Filtro Marcas | (todas) | multi-select | Já existente |

Os limiares **1.5 / 2.5 / 2.0** ficam **fixos no código** (não expostos como sliders) para garantir comportamento previsível.

---

## 9. Pressupostos e Limitações Declaradas

1. **Lote único por linha**: o motor não trata multi-lote. Se a TI consolidar múltiplos lotes numa só linha, assume-se a DTVAL que vier no campo (responsabilidade do pipeline a montante decidir se reporta o pior, melhor ou dominante).
2. **Vida útil ≤ 12 meses na Fase 2**: o cálculo de `Capacidade_Escoamento` na Fase 2 deve fazer `Meses_Para_DLV = min(Meses_Para_DLV, 12)` para evitar caps de escoamento irrealistas em lotes com 5+ anos de validade.
3. **Granularidade temporal mensal**: todas as projeções assumem mês de 30 dias. Não há ajuste para meses de 28/29/31.
4. **Custos logísticos ignorados**: por desenho. Versões futuras podem incorporar matriz de custos por par origem-destino.
5. **Toggle Aberto + ficheiro fechado**: se o utilizador ativa o Toggle Aberto mas o ficheiro foi extraído já com o último mês fechado (sem coluna parcial corrente), a normalização a 30 dias **não se aplica** — a coluna entra crua. Detetável comparando o nome da coluna mais recente com o mês de `datetime.now()`.

---

## 10. Resumo das Decisões de Design

| # | Decisão | Escolha |
|---|---|---|
| 1 | Janela Run Rate | 4 meses, pesos `0.40/0.30/0.20/0.10`, normalização do mês corrente quando toggle aberto |
| 2 | DTVAL | parseado como último dia do mês; nulo = validade longa |
| 3 | DUC | nulo = imunidade perdida (`Is_Novo = False`) |
| 4 | Janela Failsafe | 6 meses fixos |
| 5 | Destino Forte | `(RR>0) AND (vendeu_corrente OR vendeu_anterior) AND (≥2/4)` em ambas as fases |
| 6 | DLV | `DTVAL − margem`, slider default 60 dias |
| 7 | Mecânica | Recetores cobertura ↑, doadores DLV ↑/cobertura ↓; 1 passagem por fase + recálculo entre fases; atualização dinâmica completa |
| 8 | Lote / quantidade mínima | Lote único declarado; mínimo 1 unidade ambas as fases |
| 9 | Limiares | Recetor cobertura `<1.5`, doador `>2.5`, alvo/cap `2.0`; filtro `contains('Zgrupo')`; sem tiebreaker financeiro |
| 10 | Recall / output | Recall excluído do plano; categorização zombie/excesso conforme tabela §5; output schema fixado |
