
# PRD — Motor de Redistribuição de Inventário Inter-Farmácias

| Campo | Valor |
|---|---|
| **Documento** | Product Requirement Document (PRD) |
| **Versão** | 2.0 |
| **Data** | 26 de abril de 2026 |
| **Estado** | Em revisão (1 decisão pendente — ver §16) |
| **Autor** | Filipe (Owner / Gestor do Grupo) |
| **Referência técnica** | `2026-04-26-motor-redistribuicao-design.md` (v2.0, a actualizar) |
| **Idioma do produto** | Português europeu (PT-PT) |
| **Stack** | Python 3.11+, `pandas`, `numpy`, `python-dateutil` |

> ⚠️ **v2.0 introduz alteração estrutural do algoritmo**: passa de 2 fases para **3 camadas de transferência** com critérios de doação relativos (rácio) em vez de absolutos. Spec técnica anexa precisa de actualização correspondente antes da implementação.

---

## 1. Sumário Executivo

### 1.1 O quê
Um módulo Python autocontido (`motor_redistribuicao.py`) que, dado um *snapshot* agregado de stock e vendas das farmácias do grupo, gera um **plano operacional de transferências de inventário** entre lojas, em **3 camadas** com objectivos distintos:

1. **Emergência (F1)** — socorrer lojas em risco de rutura imediata.
2. **Rebalanceamento (F2)** — distribuir concentrações anómalas (warehouse de facto) por lojas com cobertura baixa mas sem emergência.
3. **Evacuação Zombie (F3)** — escoar produto sem rotação local para lojas com escoamento real, antes de validade.

O output é um `DataFrame` determinístico com a lista de movimentos sugeridos.

### 1.2 Porquê
O grupo opera múltiplas farmácias na zona da Figueira da Foz com stocks heterogéneos. A redistribuição manual tem três falhas recorrentes — rutura clínica, quebra por validade, capital empatado — agravadas por um quarto padrão: **concentração de stock em lojas que actuam como warehouse** (compras centralizadas) sem que o circuito grossista corrija, porque essa loja também vende ao público.

A versão anterior do motor (2 fases, critério absoluto `Cob > 2.5m`) tratava bem rutura e validade, mas era **cega à concentração relativa**. v2.0 corrige isto.

### 1.3 Para quem
- **Utilizador primário**: o gestor do grupo (Filipe), que executa o motor **antes de cada ciclo de encomenda mensal aos grossistas** (cadência mensal, eventualmente quinzenal).
- **Beneficiários indiretos**: equipas de balcão, clientes finais, gestão financeira.

### 1.4 Princípios de desenho
1. **Determinismo absoluto** — mesmo input ⇒ mesmo output, byte-a-byte.
2. **Atualização dinâmica de estado** — cada transferência altera o estado e os candidatos seguintes são reavaliados.
3. **Failsafe clínico inegociável** — nenhuma transferência pode deixar uma loja sem capacidade mínima de servir um doente crónico.
4. **Custos logísticos ignorados por desenho** — assumido como não-fator dentro do grupo.
5. **Sem hardcoding de lojas** — o motor é agnóstico ao número, nome ou função (warehouse vs. balcão) das farmácias.
6. **Doador é critério relativo, não absoluto** *(novo em v2.0)* — só doa quem tem **stock anormal** comparado com as outras lojas, não quem tem um número fixo de meses.
7. **Não duplicar com o circuito grossista** *(novo em v2.0)* — o motor corre antes da encomenda mensal; reposição grossista chega em ~7 dias. Transferências cobrem só esse hiato.

---

## 2. Contexto e Enquadramento

### 2.1 Domínio
Grupo de farmácias comunitárias em Portugal, sujeitas à Lei do Medicamento e ao INFARMED. A redistribuição **intra-grupo** entre estabelecimentos do mesmo titular não cria fricção regulamentar adicional.

### 2.2 Pipeline existente
Inalterado face a v1.0:

```
Sifarma (export)
  → app.py / stockreorder.py (limpeza, agregação, filtros)
  → motor_redistribuicao.py (este PRD)
  → output: plano em 3 camadas (DataFrame)
  → Streamlit dashboard / WhatsApp / folha de transferência
```

### 2.3 Pressupostos arquiteturais e operacionais
- **1 linha = 1 lote**. Multi-lote fora de âmbito.
- **Custos de transporte = 0**.
- **Output é sugestão, não execução automática**.
- **Cadência operacional** *(crítica em v2.0)*: a análise corre **antes** da encomenda mensal aos grossistas. Reposição grossista chega em **~7 dias**. Os limiares e alvos da F1 são calibrados para cobrir esta janela sem duplicar a encomenda.
- **Todas as lojas vendem ao público.** Lojas que actuem como hub interno também têm RR > 0 — não há entidades "warehouse puro" no modelo de dados.

---

## 3. Objetivos e Métricas de Sucesso

### 3.1 Objetivos primários (P0)
| ID | Objetivo | Camada que serve |
|---|---|---|
| OBJ-1 | Reduzir rutura em produtos com Run Rate sustentado. | F1 |
| OBJ-2 | Eliminar concentrações anómalas (warehouses de facto) sem ruptura nas outras. | **F2 (novo)** |
| OBJ-3 | Reduzir quebra por validade evacuando lotes próximos da DLV. | F3 |
| OBJ-4 | Libertar capital empatado em zombies. | F3 |
| OBJ-5 | Garantir failsafe clínico em todas as camadas. | F1, F2, F3 |
| OBJ-6 | Não inflar a encomenda grossista. | F1 (alvo `RR × 1.0`) |

### 3.2 Métricas de sucesso (medidas após 3 ciclos)
| KPI | Direção | Fonte |
|---|---|---|
| Nº de produtos em rutura/mês | ↓ | Sifarma |
| Valor (€) de quebra por validade trimestral | ↓ | Quebra de stock |
| Valor (€) de stock parado > 6 meses | ↓ | Snapshot mensal |
| **Coeficiente de variação da cobertura intra-produto** *(novo)* | ↓ | Análise pós-execução |
| % do plano efetivamente executado | ≥ 80% | Auditoria pós-ciclo |
| Tempo (s) para gerar plano | ≤ 30s para 30k linhas | `pytest --benchmark` |

### 3.3 Critérios de aceitação técnicos
- 100% dos itens da `<self_validation>` (§14) marcados ✅.
- 100% dos edge cases cobertos por testes.
- Determinismo demonstrado por teste (2 execuções → output idêntico).
- Imutabilidade do input demonstrada por teste.
- Cenário "warehouse" coberto por teste dedicado.

---

## 4. Personas e Cenários de Uso

### 4.1 Persona principal — Gestor do Grupo
Inalterado face a v1.0.

### 4.2 Cenários canónicos

**Cenário 1 — Início de mês (toggle fechado)**
Inalterado: `anterior=True`, janela `M-2..M-5`, pesos `[0.40, 0.30, 0.20, 0.10]`.

**Cenário 2 — Meio do mês (toggle aberto, ficheiro com mês em curso)**
Inalterado: normalização do mês corrente a 30 dias.

**Cenário 3 — Meio do mês, ficheiro com mês fechado**
Inalterado: deteção automática, mês entra cru com peso 0.40.

**Cenário 4 — Lote em fim de validade**
Inalterado: bloqueador de validade (Capacidade_Escoamento) limita transferência.

**Cenário 5 — Warehouse de facto (NOVO em v2.0)**
> "Centralizei a compra de uma referência numa loja. Vende cerca de 30/mês em cada uma das 4 lojas. Loja A tem 160 unidades, B/C/D têm 5 cada."
>
> - F1 não dispara: `Cob_B,C,D = 5/30 ≈ 0.17m < 0.5m`. Espera — dispara! Estão em emergência. F1 trata-as.
> - Após F1 (assumindo cobre ~7-15d em B/C/D): `Cob_B,C,D ≈ 0.5m`. F1 fecha.
> - F2 dispara: `Cob_A = (160 - X) / 30` continua muito alta; `Cob_média_outras ≈ 0.5m`; rácio ≫ 3.
> - F2 distribui o restante até **igualar cobertura** entre as 4 lojas.

**Cenário 6 — Rebalanceamento sem emergência (NOVO em v2.0)**
> "Loja A tem 90u (cob 3m), B/C/D têm 25u cada (cob 0.83m). Todas vendem 30/mês."
>
> - F1 não dispara: B/C/D estão acima de 0.5m.
> - F2 dispara: `Cob_A = 3m`, `Cob_média_outras ≈ 0.83m`; rácio = 3.6 ≥ 3.
> - F2 redistribui A→B,C,D até igualar.

**Cenário 7 — Equilíbrio natural (NOVO em v2.0)**
> "Loja A tem 80u, B/C/D têm 60u. RR = 30/mês todas. Cob A=2.7m, outras=2.0m. Rácio = 1.35."
>
> - F1 não dispara (todos > 0.5m).
> - F2 não dispara (rácio < 3).
> - Sistema **não move stock**. Diferença pequena — grossista corrige no ciclo normal.

---

## 5. Requisitos Funcionais

### 5.1 Função pública (interface contratual)

```python
def gerar_plano_redistribuicao(
    df_input: pd.DataFrame,
    *,
    anterior: bool = False,
    margem_dlv_dias: int = 60,           # range 0..180
    dias_imunidade: int = 60,            # range 0..180
    hoje: date | None = None,            # injetável para testes
) -> pd.DataFrame: ...
```

Validações obrigatórias inalteradas (`ValueError` se input inválido).

### 5.2 Schema do input
Inalterado face a v1.0. Ver tabela completa no anexo técnico.

### 5.3 Fórmulas de cálculo

#### 5.3.1 Run Rate (§2.1 da spec)
Inalterado: pesos `[0.40, 0.30, 0.20, 0.10]`, com deteção de mês fechado vs corrente no Cenário B.

#### 5.3.2 Datas e Validade (§2.2, §2.5 da spec)
Inalterado: `DLV = último_dia_do_mês(DTVAL) − margem_dlv_dias`.

#### 5.3.3 Cobertura (§2.3 da spec)
Inalterado.

#### 5.3.4 Capacidade de Receção *(refinado em v2.0)*
A capacidade depende da camada — o **alvo** é diferente em cada uma:

| Camada | Alvo de cobertura pós-transferência | Capacidade |
|---|---|---|
| F1 — Emergência | `RR × 1.0` *(decisão B — pendente confirmação §16)* | `(RR × 1.0) − STOCK` |
| F2 — Rebalanceamento | `Cob_alvo_grupo × RR` (ver §5.3.6) | `Stock_alvo − STOCK` |
| F3 — Evacuação Zombie | `RR × 2.0` | `(RR × 2.0) − STOCK` |

Se ≤ 0 ⇒ recetor cheio para essa camada.

#### 5.3.5 Capacidade Real de Escoamento *(válido em F1, F2, F3)*
$$\text{Cap\_Escoamento} = (\text{RR}_\text{recetor} \times \text{Meses\_Para\_DLV}_\text{doador}) - \text{STOCK}_\text{recetor}$$

**Cap em F2 e F3**: `Meses_Para_DLV = min(Meses_Para_DLV, 12)` para evitar caps irrealistas em lotes com 5+ anos.

#### 5.3.6 Cobertura-alvo do grupo *(NOVO em v2.0)*

Aplicável apenas a F2. Calculada **por produto** (groupby `CÓDIGO`) entre as lojas com `RR > 0`:

$$\text{Cob\_alvo\_grupo} = \frac{\sum_\text{lojas elegíveis} \text{STOCK}}{\sum_\text{lojas elegíveis} \text{RR}}$$

Cada loja recebe um `Stock_alvo`:
$$\text{Stock\_alvo}_\text{loja} = \lfloor \text{Cob\_alvo\_grupo} \times \text{RR}_\text{loja} \rfloor$$

**Lojas elegíveis para o cálculo**: `RR > 0 AND ¬Recall AND ¬Is_Novo`.
- Lojas com `RR == 0` não entram no cálculo do alvo (são tratadas pela F3 como zombies).
- Lojas em recall ou imunidade não influenciam o equilíbrio.

#### 5.3.7 Rácio de doação *(NOVO em v2.0)*

Para uma loja candidata a doadora `L` num produto:

$$\text{Rácio}_L = \frac{\text{Cob}_L}{\overline{\text{Cob}}_\text{outras lojas}}$$

Onde `outras lojas` exclui `L` e considera apenas lojas com `RR > 0` no produto. Se não houver outras lojas válidas, `Rácio = ∞` (impede a F2 de disparar — tratado em F3 se aplicável).

A loja `L` é candidata a doadora F2 se `Rácio_L ≥ 3.0`.

#### 5.3.8 Sinalizadores (§2.7 da spec)
Inalterado: `Is_Novo`, `Recall`, `Teve_Vendas_6m`, `Meses_Com_Vendas_4m`, `Vendeu_Mes_Corrente`, `Vendeu_Mes_Anterior`.

### 5.4 Categorização de doadores

Mantém-se a tabela §5 da spec original (cat. 1–4), mas **agora distribuída por camadas**:

| # | RR (4m) | Vendas 6m | Classificação | Camada onde actua |
|---|---|---|---|---|
| 1 | `> 0` | `> 0` | Excesso Normal | **F1** (se cob ≥ alvo F1) e/ou **F2** (se rácio ≥ 3) |
| 2 | `= 0` | `> 0` | Zombie c/ Failsafe | **F3** |
| 3 | `= 0` | `= 0` | Zombie Puro | **F3** |
| 4 | `> 0` | `= 0` | (impossível) | n/a |

### 5.5 Regras de negócio críticas

#### RB-1: Failsafe Clínico
**Inalterado**, aplicável às 3 camadas. Doador retém ≥ 1 unidade se `Teve_Vendas_6m == True`. Exceção única: Zombie Puro.

#### RB-2: Bloqueador de Validade
**Inalterado**, aplicável às 3 camadas. `Cap_Escoamento ≤ 0` ⇒ par cancelado.

#### RB-3: Destino Forte
**Inalterado**, aplicável às 3 camadas. Recetor precisa de vendas consistentes para receber.

#### RB-4: Quantidade mínima
**Inalterado**: ≥ 1 unidade.

#### RB-5: Atualização dinâmica obrigatória
**Inalterado**, aplicável dentro de **cada** camada.

#### RB-6: Loop de recálculo entre camadas *(expandido em v2.0)*
Antes de iniciar cada camada nova, recalcular `Cobertura`, `Capacidade_Recepção`, `Cap_Escoamento` e — para F2 — `Cob_alvo_grupo` e `Rácio` com os stocks pós-camada anterior.

Sequência: **F1 → recálculo → F2 → recálculo → F3**.

#### RB-7: Critério de doação relativo *(NOVO em v2.0)*
Em F2, a elegibilidade do doador depende **exclusivamente** do rácio de cobertura (`≥ 3.0`), não de um valor absoluto. Resulta directamente do princípio §1.4.6 ("doador é critério relativo").

#### RB-8: Alvo F1 alinhado com janela grossista *(NOVO em v2.0)*
A F1 deixa o recetor com **`Cob = RR × 1.0`** (≈30 dias, suficiente para cobrir o hiato até reposição grossista sem inflar a encomenda). *(Decisão pendente — §16)*

### 5.6 Algoritmo (3 camadas)

#### Pseudocódigo de alto nível
```
df = aplicar_filtro_zgrupo(df)
df = excluir_recall(df)
df = calcular_variaveis_base(df)        # RR, DLV, Cobertura, sinalizadores

# === F1: Emergência ===
sugestoes_f1 = emparelhar_f1_emergencia(df)
df = aplicar_transferencias(df, sugestoes_f1)
df = recalcular(df)

# === F2: Rebalanceamento ===
df = calcular_alvos_grupo(df)            # Cob_alvo_grupo, Stock_alvo, Rácio
sugestoes_f2 = emparelhar_f2_rebalanceamento(df)
df = aplicar_transferencias(df, sugestoes_f2)
df = recalcular(df)

# === F3: Evacuação Zombie ===
sugestoes_f3 = emparelhar_f3_zombie(df)

return consolidar(sugestoes_f1, sugestoes_f2, sugestoes_f3)
```

#### F1 — Emergência *(modificado em v2.0)*

| Aspecto | Valor |
|---|---|
| **Recetores** | `Destino_Forte ∧ Cob < 0.5m` (15 dias) |
| **Doadores** | `Cob > Cob_alvo_F1 = 1.0m` *(qualquer loja com excesso ≥ 1u)* |
| **Necessidade do recetor** | `⌈(RR × 1.0) − STOCK⌉` |
| **Excesso bruto do doador** | `⌊STOCK − (RR × 1.0)⌋` |
| **Excesso líquido** | Failsafe aplicado (idem v1.0). |
| **Ordenação recetores** | `Cob ↑`, tiebreak `RR ↓`. |
| **Ordenação doadores** | `Meses_Para_DLV ↑`, tiebreak `Cob ↓`. |

> Nota: o doador **não** precisa de passar o critério de rácio na F1 — em emergência, qualquer um com excesso ≥ 1u serve. O rácio é só um filtro da F2.

#### F2 — Rebalanceamento *(NOVO em v2.0)*

| Aspecto | Valor |
|---|---|
| **Recetores** | `Destino_Forte ∧ Cob < 1.0m ∧ STOCK < Stock_alvo` |
| **Doadores** | `Rácio ≥ 3.0 ∧ STOCK > Stock_alvo` |
| **Necessidade do recetor** | `Stock_alvo − STOCK` |
| **Excesso bruto do doador** | `STOCK − Stock_alvo` |
| **Excesso líquido** | Failsafe aplicado. |
| **Cap escoamento** | Aplicado, com `min(Meses_Para_DLV, 12)`. |
| **Ordenação recetores** | `Cob ↑`, tiebreak `RR ↓`. |
| **Ordenação doadores** | `Rácio ↓` (mais concentrado primeiro), tiebreak `Meses_Para_DLV ↑`. |

#### F3 — Evacuação Zombie *(idêntico à F2 da v1.0)*

| Aspecto | Valor |
|---|---|
| **Recetores** | `Destino_Forte ∧ Cob < 2.0m` |
| **Doadores** | `RR == 0 ∧ STOCK > 0 ∧ ¬Is_Novo ∧ ¬Recall` (cat. 2 ou 3) |
| **Quantidade** | `min(Excesso_Líquido, Cap_Escoamento, Cap_Recepção_F3)` |
| **Cap escoamento** | `min(Meses_Para_DLV, 12)`. |
| **Paragem** | `Cob_recetor ≥ 2.0m`. |
| **Ordenação doadores** | `Meses_Para_DLV ↑`, tiebreak `STOCK ↓`. |
| **Ordenação recetores** | `RR ↓`. |

### 5.7 Schema do output (contratual)

12 colunas, mesma ordem da v1.0. **Única alteração**: a coluna `Fase` aceita agora valores `1`, `2`, `3`.

| # | Coluna | Tipo | Descrição |
|---|---|---|---|
| 1 | `CÓDIGO` | int | |
| 2 | `DESIGNAÇÃO` | str | |
| 3 | `Origem` | str | Loja doadora. |
| 4 | `Motivo Saída` | str | Vocabulário §5.7.1. |
| 5 | `Stock_Origem` | int | Stock do doador antes da transferência. |
| 6 | `Validade` | str | DTVAL crua do lote. |
| 7 | `Qtd Transferir` | int | |
| 8 | `Destino` | str | |
| 9 | `Motivo Entrada` | str | Vocabulário §5.7.1. |
| 10 | `Stock_Destino` | int | Stock do recetor após a transferência. |
| 11 | `Tempo_Escoamento_Previsto` | str | `f"{Stock_Destino_pós / RR_recetor:.1f} meses"` ou `"N/A"`. |
| 12 | `Fase` | int | `1`, `2` ou `3`. |

**Ordenação final**: `Fase ↑, Origem ↑, Destino ↑, DESIGNAÇÃO ↑` *(adicionada `Fase` em v2.0 — facilita revisão).*

#### 5.7.1 Vocabulário dos motivos *(expandido em v2.0)*

**Motivo Saída**:
- `"Excesso (Cob: Xm)"` — F1
- `"Concentração (Rácio: Xx)"` — **F2 (novo)**
- `"Evacuação Zombie"` — F3, cat. 2
- `"Evacuação Zombie Puro"` — F3, cat. 3

**Motivo Entrada**:
- `"Risco Rutura (Cob: Xm)"` — F1
- `"Rebalanceamento (Cob: Xm)"` — **F2 (novo)**
- `"Forte Escoamento (Média: X)"` — F3

### 5.8 Constantes (não-configuráveis) *(actualizadas em v2.0)*

```python
# F1 — Emergência
COBERTURA_EMERGENCIA_MAX = 0.5    # 15 dias — trigger recetor F1
COBERTURA_ALVO_F1        = 1.0    # alvo pós-transferência F1 (decisão B, pendente §16)

# F2 — Rebalanceamento
RACIO_DOADOR_F2          = 3.0    # rácio Cob_doador / Cob_média_outras
COBERTURA_RECETOR_F2_MAX = 1.0    # trigger recetor F2

# F3 — Evacuação Zombie
COBERTURA_RECETOR_F3_MAX = 2.0    # trigger recetor F3 (= alvo)
COBERTURA_ALVO_F3        = 2.0

# Globais
JANELA_FAILSAFE_MESES    = 6
PESOS_RUN_RATE           = (0.40, 0.30, 0.20, 0.10)
CAP_DLV_F2_F3_MESES      = 12
```

> **Removida em v2.0**: a constante `COBERTURA_DOADOR_MIN = 2.5` deixa de existir. O critério de doador F2 é agora relativo (rácio); o critério de doador F1 é apenas "ter excesso ≥ 1u acima de `RR × 1.0`".
>
> **Proibido** expor estas constantes como argumentos, sliders ou variáveis de ambiente.

---

## 6. Requisitos Não-Funcionais

Inalterados face a v1.0: determinismo, imutabilidade do input, performance (≤30s/30k linhas), manutenibilidade (type hints, docstrings com referência §), testabilidade (`hoje` injetável), logging (`logging` ao nível do módulo), tratamento de erros (`ValueError` em PT-PT).

---

## 7. Edge Cases (cobertura obrigatória por testes)

Os 15 da v1.0 mantêm-se. **Adicionados em v2.0**:

| # | Caso | Comportamento esperado |
|---|---|---|
| 16 | Cenário "warehouse" (1 loja com 160u, outras com 5u, RR=30 todas) | F1 socorre primeiro (B,C,D em emergência); F2 distribui o restante até igualar Cob. |
| 17 | Rebalanceamento sem doador elegível (todas as Cob são similares, max rácio < 3) | F2 não gera linhas. |
| 18 | Rebalanceamento sem recetor elegível (todas têm Cob ≥ 1m) | F2 não gera linhas mesmo com doador concentrado. |
| 19 | Doador que era F1 deixa de ser F2 | Recálculo entre camadas deteta; não doa. |
| 20 | Produto onde só 1 loja tem `RR > 0` | F2 não dispara (rácio = ∞ por convenção, mas sem outras lojas elegíveis). F3 pode tratar zombies das outras. |
| 21 | Produto onde todas as lojas têm `RR == 0` | F1 e F2 não disparam; F3 trata se houver zombies. |
| 22 | Cob_alvo_grupo fracionária (ex.: 2.43m) | `Stock_alvo = ⌊Cob_alvo × RR⌋`; arredondamento testado. |
| 23 | Lojas com `RR == 0` não influenciam Cob_alvo_grupo | Excluídas do cálculo de soma. |
| 24 | F2 com cap de validade activo | Doador em concentração mas com lote curto → quantidade limitada por Cap_Escoamento. |

Total: **24 edge cases**.

---

## 8. Plano de Testes (`pytest`)

### 8.1 Cobertura mínima exigida

Mantém-se a tabela da v1.0 e adiciona:

| Bloco *(novo em v2.0)* | Testes |
|---|---|
| Cálculo de `Cob_alvo_grupo` e `Stock_alvo` | 2+ |
| Cálculo de `Rácio` em vários cenários | 3+ |
| F2 — emparelhamento básico | 2+ |
| F2 — atualização dinâmica entre pares | 1+ |
| F2 — failsafe em doador rebalanceado | 1+ |
| Cenário "warehouse" end-to-end (F1+F2) | 1+ |
| Cenário "equilíbrio natural" (não move) | 1+ |
| Loop de recálculo F1→F2→F3 | 1+ |
| Edge cases 16–24 | 9 |

### 8.2 Estrutura recomendada
```
tests/
  conftest.py
  test_run_rate.py
  test_dlv_parsing.py
  test_sinalizadores.py
  test_categorias.py
  test_failsafe.py
  test_bloqueador_validade.py
  test_alvo_grupo.py            # NOVO v2.0
  test_racio_doacao.py          # NOVO v2.0
  test_f1_emergencia.py
  test_f2_rebalanceamento.py    # NOVO v2.0
  test_f3_zombie.py
  test_recalculo_entre_camadas.py
  test_output_schema.py
  test_determinismo.py
  test_imutabilidade.py
  test_edge_cases.py
  test_cenarios_canonicos.py    # NOVO v2.0 — warehouse, equilíbrio natural
```

### 8.3 Comando de execução
```bash
pytest tests/ -v --tb=short
pytest tests/ --cov=motor_redistribuicao -v
```

---

## 9. Plano de Implementação

### 9.1 Fases de desenvolvimento *(ajustadas em v2.0)*

| Fase | Entregável | Critério de saída |
|---|---|---|
| **[x] 0 — Plano** | Markdown com estrutura de funções e assinaturas | Aprovação explícita do owner. |
| **[x] 1 — Funções puras base** | RR, DLV, Cobertura, sinalizadores | Testes unitários verdes. |
| **[x] 2 — Categorização** | Tabela §5.4 implementada | Testes cat. 1/2/3 verdes. |
| **[x] 3 — F1 (Emergência)** | Emparelhador F1 com novo alvo `RR × 1.0` | Testes F1 verdes. |
| **[x] 4 — Cálculos de grupo** *(NOVO)* | `Cob_alvo_grupo`, `Stock_alvo`, `Rácio` | Testes verdes. |
| **[x] 5 — F2 (Rebalanceamento)** *(NOVO)* | Emparelhador F2 com critério rácio | Testes F2 + cenário warehouse verdes. |
| **[x] 6 — Loop de recálculo F1→F2→F3** | Recalc entre as 3 camadas | Teste de doador-que-deixa-de-o-ser verde. |
| **[x] 7 — F3 (Evacuação Zombie)** | Emparelhador F3 (idêntico à F2 v1.0) | Testes F3 verdes. |
| **[x] 8 — Output** | Consolidação 3 camadas, schema fixo | Testes de schema e ordenação verdes. |
| **[x] 9 — Edge cases** | 24 cenários cobertos | 24 testes verdes. |
| **[x] 10 — Validação final** | Checklist `<self_validation>` ✅ | Aprovação final. |
| **[x] 11 — Integração** | Hook em `app.py` + secção no Streamlit | Plano corre fim-a-fim. |

### 9.2 Estrutura interna do módulo *(actualizada em v2.0)*
```
motor_redistribuicao.py
├── Constantes (§5.8)
├── Logger
├── --- Funções puras de cálculo ---
│   ├── _calcular_run_rate()
│   ├── _parse_dtval()
│   ├── _calcular_dlv()
│   ├── _calcular_meses_para_dlv()
│   ├── _calcular_cobertura()
│   ├── _calcular_sinalizadores()
│   ├── _calcular_cob_alvo_grupo()        # NOVO v2.0
│   ├── _calcular_racio_doacao()          # NOVO v2.0
│   └── _classificar_categoria()
├── --- Pipeline de preparação ---
│   ├── _validar_input()
│   ├── _aplicar_filtro_zgrupo()
│   ├── _excluir_recall()
│   └── _enriquecer_dataframe()
├── --- Emparelhamento por camada ---
│   ├── _emparelhar_f1_emergencia()
│   ├── _emparelhar_f2_rebalanceamento() # NOVO v2.0
│   └── _emparelhar_f3_zombie()
├── --- Estado entre camadas ---
│   ├── _aplicar_transferencias()
│   └── _recalcular_estado()
├── --- Output ---
│   ├── _consolidar_sugestoes()
│   └── _ordenar_e_validar_output()
└── gerar_plano_redistribuicao()
```

### 9.3 Integração com `app.py`
Inalterada face a v1.0.

---

## 10. Riscos e Mitigações

| ID | Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|---|
| R-1 | Cálculo errado de mês corrente vs. fechado | M | A | Função pura testável. |
| R-2 | Atualização dinâmica perdida | M | A | Teste sequencial. |
| R-3 | Failsafe Clínico violado | B | A | Asserção explícita por camada. |
| R-4 | Output schema alterado | M | M | Teste de schema. |
| R-5 | Lote longa validade na F2/F3 | B | M | Cap `min(Meses_Para_DLV, 12)`. |
| R-6 | Multi-lote acidentalmente "ajudado" | B | A | Diretiva + revisão de PR. |
| R-7 | Loja nova adicionada — motor falha | M | A | Teste com 1, 2, 5 lojas dinâmicas. |
| R-8 | Não-determinismo por `groupby` com NaN | B | M | Tiebreakers explícitos. |
| **R-9** | **F2 dispara onde não devia (cob_alvo mal calculada)** *(novo)* | **M** | **A** | **Teste cenário "equilíbrio natural" — sistema não move stock.** |
| **R-10** | **Alvo F1 (RR×1.0) desadequado se grossista falhar entrega** *(novo)* | **B** | **M** | **Decisão consciente. Documentar como limitação. Possibilidade futura de override manual.** |
| **R-11** | **F2 inflaciona transferências para alcançar alvo "perfeito"** *(novo)* | **M** | **M** | **Cap pelo rácio (≥3) e por excesso real do doador. Teste com 4 lojas.** |
| **R-12** | **Concorrência entre F1 e F2 sobre mesmo doador** *(novo)* | **B** | **M** | **Recálculo obrigatório entre camadas; doador pós-F1 pode já não ter excesso.** |

---

## 11. Limitações Conhecidas / Out of Scope

### 11.1 Fora de âmbito
Inalterado face a v1.0: multi-lote, custos logísticos, otimização global, previsão estatística, execução automática, integração grossista, otimização fiscal.

### 11.2 Limitações declaradas *(actualizadas em v2.0)*
- Inputs com `T Uni` mal posicionada levantam `ValueError`.
- Lojas "Zgrupo" são sempre filtradas.
- O peso do mês corrente normalizado pode introduzir ruído em sazonalidades extremas.
- **Alvo F1 = `RR × 1.0`** assume que o grossista consegue entregar em ~7 dias. Em caso de rutura no grossista, esta cobertura pode ser insuficiente — situação rara mas possível.
- **F2 não dispara para concentrações moderadas** (rácio < 3). Diferenças pequenas confiam-se ao circuito grossista.
- **F2 ignora lojas com `RR == 0`** no cálculo do `Cob_alvo_grupo` — produtos com RR=0 nessas lojas são tratados pela F3 como zombies. Não há "redistribuição de cobertura" para lojas que não vendem.

---

## 12. Glossário *(expandido em v2.0)*

Termos da v1.0 mantêm-se. Adicionados:

| Termo | Definição |
|---|---|
| **Cob_alvo_grupo** | Cobertura uniforme teórica se todo o stock do grupo fosse redistribuído proporcionalmente ao RR de cada loja, por produto. |
| **Stock_alvo** | `⌊Cob_alvo_grupo × RR_loja⌋`, o stock que cada loja teria com cobertura uniforme. |
| **Rácio de doação** | `Cob_loja / Cob_média_outras_lojas`. ≥ 3 ⇒ candidata a doadora F2. |
| **Camada** | Sinónimo de fase. v2.0 prefere "camada" para enfatizar o carácter sequencial e autocontido de cada uma. |
| **Warehouse de facto** | Loja que centraliza stock por decisão operacional, mas que também vende ao público. Detectada pelo motor via rácio, sem hardcoding. |
| **Equilíbrio natural** | Estado onde nenhuma loja tem rácio ≥ 3 nem cobertura < 0.5m — sistema não move stock. |

---

## 13. Anexos e Referências

- **Spec técnica detalhada**: `2026-04-26-motor-redistribuicao-design.md` (v2.0 — necessita actualização para reflectir 3 camadas).
- **Pipeline a montante**: `app.py`, `stockreorder.py`.
- **Standards de código**: PEP 8, PEP 257, `ruff`.
- **Stack**: Python 3.11+, `pandas ≥ 2.0`, `numpy ≥ 1.24`, `python-dateutil ≥ 2.8`, `pytest ≥ 7.0`.

---

## 14. Self-Validation Checklist

Antes de declarar o trabalho completo:

- [ ] As 24 edge cases estão cobertas por testes?
- [ ] As 3 camadas estão implementadas com recálculo obrigatório entre cada uma?
- [ ] O cálculo de `Cob_alvo_grupo` exclui lojas com `RR == 0`?
- [ ] O rácio de doação considera apenas as outras lojas com `RR > 0`?
- [ ] A F1 deixa o recetor com `Cob = 1.0m` (decisão B, pendente confirmação)?
- [ ] O alvo `Stock_alvo` é `⌊Cob_alvo × RR⌋` (floor, não round)?
- [ ] Failsafe Clínico aplicado nas 3 camadas?
- [ ] Bloqueador de Validade aplicado nas 3 camadas?
- [ ] Cap `min(Meses_Para_DLV, 12)` aplicado em F2 e F3?
- [ ] Output tem 12 colunas, `Fase ∈ {1, 2, 3}`, ordenação `Fase, Origem, Destino, DESIGNAÇÃO`?
- [ ] Vocabulário de motivos cobre os 7 valores possíveis (3 saída + 3 entrada + alguns combinados)?
- [ ] Cenário "warehouse" passa o teste end-to-end?
- [ ] Cenário "equilíbrio natural" não gera transferências?
- [ ] Determinismo demonstrado (2 execuções idênticas)?
- [ ] Imutabilidade do input demonstrada?
- [ ] Sem `print()`, sem nomes de loja hardcoded, sem sentinelas numéricas?
- [ ] Constantes `COBERTURA_EMERGENCIA_MAX`, `RACIO_DOADOR_F2`, etc., não expostas como argumentos?
- [ ] Docstrings referenciam secções do PRD/spec?

---

## 15. Histórico de Versões

| Versão | Data | Alteração |
|---|---|---|
| 1.0 | 2026-04-26 | Versão inicial: 2 fases (Emergência + Evacuação Zombie), critério doador absoluto `Cob > 2.5m`. |
| 2.0 | 2026-04-26 | Reestruturação para **3 camadas** (Emergência F1 / Rebalanceamento F2 / Evacuação Zombie F3). Critério de doação relativo (rácio ≥ 3). Alvo F1 ajustado a `RR × 1.0` (decisão pendente §16). Adicionado conceito `Cob_alvo_grupo` para distribuição proporcional. 9 novos edge cases. Cenários canónicos warehouse e equilíbrio natural. |
| 2.1 | 2026-04-26 | **Atualização do RB-3**: `Destino_Forte` passa a exigir sempre um mínimo de 2 meses de vendas na janela de 4 meses, evitando reabastecimentos baseados em picos isolados de 1 mês corrente. |

---

## 16. Decisões Pendentes

| # | Decisão | Default proposto | Alternativas | Quem decide |
|---|---|---|---|---|
| **D-1** | Alvo de cobertura pós-transferência F1 | **B: `RR × 1.0`** (cobre só o hiato grossista) | A: `RR × 2.0` (manter v1.0; exige ajuste manual da encomenda); C: `RR × 1.5` (meio-termo) | Owner. **(Decidido: Opção B)** |

> Nota: as restantes decisões (rácio K=3, F2 com alvo igualar, todas as lojas vendem ao público) já foram confirmadas pelo owner em sessão de 2026-04-26.

---

## 17. Aprovação

| Papel | Nome | Estado | Data |
|---|---|---|---|
| Owner / Sponsor | Filipe | ☐ Pendente (aguarda D-1) | — |
| Implementação | — | ☐ Pendente | — |
| Validação técnica | — | ☐ Pendente | — |