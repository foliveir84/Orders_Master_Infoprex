# PRD — Motor de Redistribuição de Inventário Inter-Farmácias

| Campo | Valor |
|---|---|
| **Documento** | Product Requirement Document (PRD) |
| **Versão** | 1.0 |
| **Data** | 26 de abril de 2026 |
| **Estado** | Aprovado para desenvolvimento |
| **Autor** | Filipe (Owner / Gestor do Grupo) |
| **Referência técnica** | `2026-04-26-motor-redistribuicao-design.md` (v2.0) |
| **Idioma do produto** | Português europeu (PT-PT) |
| **Stack** | Python 3.11+, `pandas`, `numpy`, `python-dateutil` |

---

## 1. Sumário Executivo

### 1.1 O quê
Um módulo Python autocontido (`motor_redistribuicao.py`) que, dado um *snapshot* agregado de stock e vendas das farmácias do grupo, gera um **plano operacional de transferências de inventário** entre lojas. O output é um `DataFrame` determinístico com a lista de movimentos sugeridos, prontos para execução logística.

### 1.2 Porquê
O grupo opera múltiplas farmácias na zona da Figueira da Foz com stocks heterogéneos: lojas em **risco de rutura** convivem com lojas em **excesso crónico** ou com **lotes a aproximar-se da validade**. Hoje, o rebalanceamento é feito por intuição humana, com três falhas recorrentes:

1. **Risco de rutura clínica** em medicação para doentes crónicos (impacto direto em nível de serviço e fidelização).
2. **Quebra por validade** (DLV) — produto a expirar numa loja sem rotação enquanto outra teria escoamento.
3. **Capital empatado em "zombies"** — produto sem rotação local que poderia ser vendido noutra loja.

### 1.3 Para quem
- **Utilizador primário**: o gestor do grupo (Filipe) que executa o motor mensalmente (e potencialmente quinzenalmente) e despacha o plano para as lojas.
- **Beneficiários indiretos**: equipas de balcão (recebem stock no sítio certo), clientes finais (menor rutura), gestão financeira (menor capital empatado e menor quebra por validade).

### 1.4 Princípios de desenho
1. **Determinismo absoluto** — mesmo input ⇒ mesmo output, byte-a-byte.
2. **Atualização dinâmica de estado** — cada transferência altera o estado e os candidatos seguintes são reavaliados.
3. **Failsafe clínico inegociável** — nenhuma transferência pode deixar uma loja sem capacidade mínima de servir um doente crónico.
4. **Custos logísticos ignorados por desenho** — assumido como não-fator dentro do grupo.
5. **Sem hardcoding de lojas** — o motor é agnóstico ao número e nome de farmácias do grupo.

---

## 2. Contexto e Enquadramento

### 2.1 Domínio
Grupo de farmácias comunitárias em Portugal, sujeitas à Lei do Medicamento e ao INFARMED. A redistribuição **intra-grupo** entre estabelecimentos do mesmo titular não cria fricção regulamentar adicional — o motor não precisa de modelar interações com circuitos de distribuição grossista (Cooprofar, Alliance, OCP, etc.).

### 2.2 Pipeline existente
O motor é uma **etapa nova** num pipeline já em produção:

```
Sifarma (export)
  → app.py / stockreorder.py (limpeza, agregação, filtros)
       └── remove linhas sem stock e sem vendas
       └── remove códigos locais (começados por '1')
       └── remove códigos não-numéricos
  → motor_redistribuicao.py (NOVO — este PRD)
  → output: plano de transferências (DataFrame)
  → consumo manual ou via Streamlit dashboard
```

O motor **não** repete os filtros do `app.py`. Confia que o input chega já limpo, exceto pelo **filtro institucional Zgrupo** que aplica internamente.

### 2.3 Pressupostos arquiteturais
- **1 linha = 1 lote**. Multi-lote está fora de âmbito (ver §11).
- **Custos de transporte = 0**. Decisão de gestão.
- **Output é sugestão, não execução automática**. A operação física é manual.
- **Cadência de execução**: mensal (default) ou quinzenal (toggle "anterior").

---

## 3. Objetivos e Métricas de Sucesso

### 3.1 Objetivos primários (P0)
| ID | Objetivo |
|---|---|
| OBJ-1 | Reduzir incidência de **rutura** em produtos com Run Rate sustentado e múltiplos meses de vendas. |
| OBJ-2 | Reduzir **quebra por validade** evacuando lotes próximos da DLV para lojas com escoamento real. |
| OBJ-3 | Libertar **capital empatado** em produtos zombie (sem rotação local). |
| OBJ-4 | Garantir **failsafe clínico**: nenhuma loja com histórico recente de venda fica a zero. |

### 3.2 Métricas de sucesso (medidas após 3 ciclos)
| KPI | Direção | Fonte |
|---|---|---|
| Nº de produtos em rutura/mês | ↓ | Sifarma |
| Valor (€) de quebra por validade trimestral | ↓ | Quebra de stock |
| Valor (€) de stock parado > 6 meses | ↓ | Snapshot mensal |
| % do plano efetivamente executado | ≥ 80% | Auditoria pós-ciclo |
| Tempo (min) para gerar plano | ≤ 30s para 30k linhas | `pytest --benchmark` |

### 3.3 Critérios de aceitação técnicos
- 100% dos itens da `<self_validation>` da spec marcados ✅.
- 100% dos 15 edge cases cobertos por testes unitários.
- Determinismo demonstrado por teste (2 execuções idênticas → output idêntico).
- Imutabilidade do input demonstrada por teste.

---

## 4. Personas e Cenários de Uso

### 4.1 Persona principal — Gestor do Grupo
- Fluência técnica média/alta (Python, dashboards, automação).
- Trabalha em PT-PT.
- Executa o motor a partir do `app.py` ou de um *notebook*.
- Inspeciona o output em tabela e despacha por WhatsApp/folha de transferência.

### 4.2 Cenários canónicos

**Cenário 1 — Início de mês (toggle fechado)**
> "Estou a 3 do mês. Quero ver o que devo movimentar com base em 4 meses fechados (sem o mês corrente, ainda inestável)."
> Aciona `anterior=True`. Run Rate = pesos `[0.40, 0.30, 0.20, 0.10]` em `M-2..M-5`.

**Cenário 2 — Meio do mês (toggle aberto, ficheiro com mês em curso)**
> "Estou a 18 do mês. Quero incluir o mês corrente, normalizado a 30 dias."
> Aciona `anterior=False`. Última coluna é o mês de hoje. Sistema normaliza: `(M_atual / 18) × 30`.

**Cenário 3 — Meio do mês, mas ficheiro com mês fechado**
> "Estou a 26/04, mas o ficheiro foi extraído com a última coluna `MAR.1` (março fechado). Não quero normalização."
> Sistema deteta automaticamente: `M[idx-1]` ≠ mês corrente → entra **crua** com peso 0.40.

**Cenário 4 — Lote em fim de validade**
> Lote com DTVAL `09/2026`. Margem = 60 dias ⇒ DLV = 31/jul/2026. A 26/abr são ≈ 3 meses até DLV. Recetor com RR=10/mês ⇒ `Capacidade_Escoamento = (10 × 3) − STOCK_recetor`. Se = 8 e o stock do recetor for 5, escoa até 25 unidades.

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

**Validações obrigatórias da função pública** (levantam `ValueError`):
- Colunas obrigatórias presentes (ver §5.2).
- `T Uni` é a última coluna do DataFrame.
- `margem_dlv_dias ∈ [0, 180]`.
- `dias_imunidade ∈ [0, 180]`.

### 5.2 Schema do input

| Coluna | Tipo | Notas |
|---|---|---|
| `CÓDIGO` | int | Chave primária do produto. |
| `DESIGNAÇÃO` | str | Nome comercial. |
| `LOCALIZACAO` | str | Loja. Pode conter "Zgrupo" → filtrado. |
| `STOCK` | int | ≥ 0. |
| `PVP_Médio` | float | Informativo. |
| `P.CUSTO` | float | Informativo. |
| `DUC` | str ou null | `DD/MM/YYYY`. |
| `DTVAL` | str ou null | `MM/YYYY`. |
| `<colunas mensais>` | int | N colunas, cronológicas crescentes. |
| `T Uni` | int | **Sempre a última**. Sentinela. |

### 5.3 Fórmulas de cálculo (todas com referência §)

#### 5.3.1 Run Rate (§2.1)
Pesos fixos `[0.40, 0.30, 0.20, 0.10]` do mais recente para o mais antigo.

**Cenário A — `anterior=True`:**
$$\text{RR} = M_{idx-2} \cdot 0.40 + M_{idx-3} \cdot 0.30 + M_{idx-4} \cdot 0.20 + M_{idx-5} \cdot 0.10$$

**Cenário B — `anterior=False`, com deteção automática de mês fechado:**
- Se `nome_coluna(M[idx-1]) == mês_corrente(hoje)`:
  $$M_\text{atual\_norm} = \frac{M[idx-1]}{\text{dia\_de\_hoje}} \times 30$$
- Caso contrário (mês fechado): `M_atual_norm = M[idx-1]` cru.

$$\text{RR} = M_\text{atual\_norm} \cdot 0.40 + M_{idx-2} \cdot 0.30 + M_{idx-3} \cdot 0.20 + M_{idx-4} \cdot 0.10$$

#### 5.3.2 Datas e Validade (§2.2, §2.5)
- `DTVAL_parsed = último_dia_do_mês(DTVAL)`.
- `DLV = DTVAL_parsed − margem_dlv_dias`.
- `Meses_Para_DLV = (DLV − hoje).days / 30.0`.
- `DTVAL` nulo ⇒ `Meses_Para_DLV = np.inf`.

#### 5.3.3 Cobertura (§2.3)
| Condição | Resultado |
|---|---|
| `RR > 0` | `STOCK / RR` |
| `RR == 0 ∧ STOCK > 0` | `np.inf` |
| `RR == 0 ∧ STOCK == 0` | `0` |

> **Proibido** usar sentinelas (`999`, `9999`).

#### 5.3.4 Capacidades (§2.4, §2.6)
- `Capacidade_Recepção = (RR × 2.0) − STOCK`. Se ≤ 0, recetor cheio.
- `Capacidade_Escoamento = (RR_recetor × Meses_Para_DLV_doador) − STOCK_recetor`.
- **Cap Fase 2**: `Meses_Para_DLV = min(Meses_Para_DLV, 12)`.

#### 5.3.5 Sinalizadores (§2.7)
| Variável | Definição |
|---|---|
| `Is_Novo` | `(hoje − DUC).days < dias_imunidade`; DUC nulo ⇒ `False`. |
| `Recall` | `DLV < hoje`. |
| `Teve_Vendas_6m` | Soma das 6 colunas mensais mais recentes > 0. |
| `Meses_Com_Vendas_4m` | Nº de colunas (entre as 4 da janela RR) > 0. |
| `Vendeu_Mes_Corrente` | Primeira coluna da janela RR > 0. |
| `Vendeu_Mes_Anterior` | Segunda coluna da janela RR > 0. |

### 5.4 Categorização de doadores (§5)

| # | RR (4m) | Vendas 6m | Classificação | Quantidade transferível |
|---|---|---|---|---|
| 1 | `> 0` | `> 0` | Excesso Normal | `STOCK − ⌈RR × 2.0⌉ − 1` (Failsafe ON) |
| 2 | `= 0` | `> 0` | Zombie c/ Failsafe | `STOCK − 1` |
| 3 | `= 0` | `= 0` | Zombie Puro | `STOCK` total |
| 4 | `> 0` | `= 0` | Impossível por construção | n/a |

- **Excesso Normal**: o `−1` final só aplica se `Teve_Vendas_6m == True`.
- **`Is_Novo == True`** ⇒ não pode ser zombie (cat. 2 ou 3).
- **`Recall == True`** ⇒ excluído totalmente do plano.

### 5.5 Regras de negócio críticas

#### RB-1: Failsafe Clínico (§4.1)
Doador retém **≥ 1 unidade** sempre que `Teve_Vendas_6m == True`. Janela de 6 meses, **independente** do toggle. **Única exceção**: Zombie Puro (cat. 3).

#### RB-2: Bloqueador de Validade (§4.2)
$$\text{Qtd\_Final} = \min(\text{Necessidade}_\text{recetor}, \text{Excesso\_Líquido}_\text{doador}, \text{Cap\_Escoamento})$$
Se `Cap_Escoamento ≤ 0` ⇒ par cancelado.

#### RB-3: Destino Forte (§4.3) — aplicável em ambas as fases
$$\text{Destino\_Forte} = (\text{RR} > 0) \land (\text{Vendeu\_Mes\_Corrente} \lor (\text{Vendeu\_Mes\_Anterior} \land \text{Meses\_Com\_Vendas\_4m} \geq 2))$$

#### RB-4: Quantidade mínima
≥ 1 unidade. Transferências de 0 nunca são geradas.

#### RB-5: Atualização dinâmica obrigatória (§6.2 e Diretiva 3)
Após cada transferência:
- `STOCK_doador ↓`, `STOCK_recetor ↑`.
- Recálculo de `Cobertura`, `Necessidade`, `Excesso_Líquido` **antes** do próximo emparelhamento.
- Emparelhamento estático **proibido**.

#### RB-6: Loop de recálculo entre Fase 1 e Fase 2 (Diretiva 4)
Antes de iniciar Fase 2, recalcular `Cobertura`, `Capacidade_Recepção` e `Capacidade_Escoamento` com stocks pós-Fase 1.

### 5.6 Algoritmo (resumo executável)

#### Fase 1 — Apagar Fogos
- **Recetores**: `Destino_Forte == True ∧ Cobertura < 1.5`.
- **Doadores**: `Cobertura > 2.5`.
- Iteração por `groupby('CÓDIGO')`, ordenação determinística:
  - Recetores: `Cobertura ↑`, tiebreak `RR ↓`.
  - Doadores: `Meses_Para_DLV ↑`, tiebreak `Cobertura ↓`.
- 1 passagem (`p = 1`).

#### Fase 2 — Evacuação de Zombies
- **Doadores**: `RR == 0 ∧ STOCK > 0 ∧ ¬Is_Novo ∧ ¬Recall` (cat. 2 ou 3).
- **Recetores**: `Destino_Forte ∧ Cobertura < 2.0`.
- Cap recetor: `Capacidade_Escoamento` com `min(Meses_Para_DLV, 12)`.
- Ordenação:
  - Doadores: `Meses_Para_DLV ↑`, tiebreak `STOCK ↓`.
  - Recetores: `RR ↓`.
- Paragem: `Cobertura recetor ≥ 2.0`.

### 5.7 Schema do output (contratual)

`pd.DataFrame` com **exatamente** estas 12 colunas, nesta ordem:

| # | Coluna | Tipo | Descrição |
|---|---|---|---|
| 1 | `CÓDIGO` | int | |
| 2 | `DESIGNAÇÃO` | str | |
| 3 | `Origem` | str | Loja doadora. |
| 4 | `Motivo Saída` | str | Vocabulário §5.7.1. |
| 5 | `Stock_Origem` | int | Stock do doador **antes** da transferência. |
| 6 | `Validade` | str | DTVAL crua do lote. |
| 7 | `Qtd Transferir` | int | |
| 8 | `Destino` | str | |
| 9 | `Motivo Entrada` | str | Vocabulário §5.7.1. |
| 10 | `Stock_Destino` | int | Stock do recetor **após** a transferência. |
| 11 | `Tempo_Escoamento_Previsto` | str | `f"{Stock_Destino_pós / RR_recetor:.1f} meses"` ou `"N/A"`. |
| 12 | `Fase` | int | `1` ou `2`. |

**Ordenação final**: `Origem ↑, Destino ↑, DESIGNAÇÃO ↑`.

#### 5.7.1 Vocabulário dos motivos
- **Motivo Saída**: `"Excesso (Cob: Xm)"` | `"Evacuação Zombie"` | `"Evacuação Zombie Puro"`.
- **Motivo Entrada**: `"Risco Rutura (Cob: Xm)"` | `"Forte Escoamento (Média: X)"`.

### 5.8 Constantes (não-configuráveis)

```python
COBERTURA_RECETOR_MAX = 1.5   # Fase 1
COBERTURA_DOADOR_MIN  = 2.5   # Fase 1
COBERTURA_ALVO        = 2.0   # Fase 2 e cap de receção
JANELA_FAILSAFE_MESES = 6
PESOS_RUN_RATE        = (0.40, 0.30, 0.20, 0.10)
CAP_DLV_FASE2_MESES   = 12
```

> **Proibido** expor estas constantes como argumentos, sliders ou variáveis de ambiente.

---

## 6. Requisitos Não-Funcionais

### 6.1 Determinismo
Mesmo `(df_input, anterior, margem_dlv_dias, dias_imunidade, hoje)` ⇒ output **bit-a-bit idêntico**. Sem `set` em pipelines, sem `dict` order surprises, sem `random`.

### 6.2 Imutabilidade do input
`df_input` nunca é mutado. O motor opera sobre cópia interna.

### 6.3 Performance
- Alvo: ≤ 30s para 30k linhas (~5k produtos × 6 lojas) num laptop moderno.
- Vetorização permitida **desde que não destrua a atualização dinâmica entre pares**. Correção lógica > performance.

### 6.4 Manutenibilidade
- Type hints em todas as funções públicas e privadas.
- Docstrings PEP 257 com `Args:`, `Returns:`, `Raises:` e referência à secção da spec (`§2.1`, `§4.3`...).
- Constantes nomeadas (sem números mágicos).
- Linhas ≤ 100 chars, `ruff`-compatível.

### 6.5 Testabilidade
- `hoje` injetável (default `date.today()`).
- Cada fórmula numa função pura testável isoladamente.
- Suite `pytest` com cobertura mínima dos blocos exigidos no §8.

### 6.6 Logging
- `logging` (não `print`).
- Logger ao nível do módulo: `logger = logging.getLogger(__name__)`.
- `INFO` para marcos (início Fase 1, transferências geradas, fim).
- `DEBUG` para detalhe de cada par avaliado.

### 6.7 Tratamento de erros
- `ValueError` na função pública para: faltarem colunas, `T Uni` mal posicionada, parâmetros fora de range.
- Mensagens em português, claras e acionáveis.

---

## 7. Edge Cases (cobertura obrigatória por testes)

| # | Caso | Comportamento esperado |
|---|---|---|
| 1 | `df_input` vazio | DataFrame vazio com schema fixo. |
| 2 | Apenas 1 loja após filtro Zgrupo | DataFrame vazio. |
| 3 | Produto presente em 1 só loja | Não gera transferência. |
| 4 | `DTVAL` nulo no doador | `Meses_Para_DLV = np.inf`; não bloqueia. |
| 5 | `DUC` nulo | `Is_Novo = False`. |
| 6 | RR = 0 em todas as lojas para um produto | Sem destino possível; doadores sem linha. |
| 7 | `STOCK = 0` no candidato a doador | Não doa. |
| 8 | Última coluna = mês fechado, `anterior=False` | NÃO normalizar; entra crua. |
| 9 | Última coluna = mês corrente, `anterior=False` | Normalizar a 30 dias. |
| 10 | Empates de ordenação | Resolvidos por tiebreaker; resultado determinístico. |
| 11 | Doador F1 deixa de o ser na F2 | Recálculo deteta; não doa. |
| 12 | Recetor F1 atinge cobertura ≥ 2.0 | Não recebe na F2. |
| 13 | Arredondamentos `floor`/`ceil` | Exatos conforme spec. |
| 14 | Lote com validade > 5 anos na F2 | Cap `min(Meses_Para_DLV, 12)`. |
| 15 | Mesmo produto F1 + F2 | Output mantém ambas as linhas; não deduplica. |

---

## 8. Plano de Testes (`pytest`)

### 8.1 Cobertura mínima exigida

| Bloco | Testes |
|---|---|
| Run Rate Cenário A | 1+ |
| Run Rate Cenário B com normalização | 1+ |
| Run Rate Cenário B sem normalização (mês fechado) | 1+ |
| Parsing de `DTVAL` → último dia do mês | 1+ |
| DLV com diferentes margens | 2+ |
| `Is_Novo` (DUC nulo, < imunidade, > imunidade) | 3 |
| `Recall` true/false | 2 |
| `Destino_Forte` em todos os branches | 3+ |
| Categorias 1, 2, 3 | 3 |
| Failsafe ON/OFF | 2 |
| Bloqueador de Validade cancelando par | 1+ |
| Atualização dinâmica entre pares (mesma fase) | 1+ |
| Loop de recálculo F1→F2 | 1+ |
| Schema do output | 1 |
| Determinismo (2 execuções) | 1 |
| Imutabilidade do input | 1 |
| Edge cases 1–15 | 15 |

### 8.2 Estrutura recomendada
```
tests/
  conftest.py                 # fixtures partilhadas (DataFrames sintéticos, hoje fixo)
  test_run_rate.py
  test_dlv_parsing.py
  test_sinalizadores.py
  test_categorias.py
  test_failsafe.py
  test_bloqueador_validade.py
  test_emparelhamento_dinamico.py
  test_recalculo_entre_fases.py
  test_output_schema.py
  test_determinismo.py
  test_imutabilidade.py
  test_edge_cases.py
```

### 8.3 Comando de execução
```bash
pytest test_motor_redistribuicao.py -v
pytest tests/ -v --tb=short                       # se modular
pytest tests/ --cov=motor_redistribuicao -v       # com cobertura
```

---

## 9. Plano de Implementação

### 9.1 Fases de desenvolvimento

| Fase | Entregável | Critério de saída |
|---|---|---|
| **0 — Plano** | Markdown com estrutura de funções, assinaturas, lista de testes | Aprovação explícita do owner. |
| **1 — Funções puras** | Run Rate, DLV, Cobertura, sinalizadores | Testes unitários verdes. |
| **2 — Categorização** | Tabela §5 implementada | Testes cat. 1/2/3 verdes. |
| **3 — Fase 1** | Emparelhador "Apagar Fogos" com atualização dinâmica | Teste de atualização sequencial verde. |
| **4 — Loop de recálculo** | Recalc completo entre fases | Teste de doador-que-deixa-de-o-ser verde. |
| **5 — Fase 2** | Emparelhador "Evacuação Zombie" | Testes F2 verdes. |
| **6 — Output** | Consolidação e schema fixo | Teste de schema verde. |
| **7 — Edge cases** | 15 cenários cobertos | 15 testes verdes. |
| **8 — Validação** | Checklist `<self_validation>` toda ✅ | Aprovação final. |
| **9 — Integração** | Hook em `app.py` + secção no Streamlit | Plano corre fim-a-fim. |

### 9.2 Estrutura de ficheiros
```
projeto/
  motor_redistribuicao.py          # módulo principal
  test_motor_redistribuicao.py     # ou pasta tests/
  README_motor.md                  # instruções de uso e integração
  app.py                           # existente — recebe hook
```

### 9.3 Estrutura interna do módulo (proposta)
```
motor_redistribuicao.py
├── Constantes (§5.8)
├── Logger
├── Tipos / TypedDicts auxiliares
├── --- Funções puras de cálculo ---
│   ├── _calcular_run_rate()
│   ├── _parse_dtval()
│   ├── _calcular_dlv()
│   ├── _calcular_meses_para_dlv()
│   ├── _calcular_cobertura()
│   ├── _calcular_sinalizadores()
│   └── _classificar_categoria()
├── --- Pipeline de preparação ---
│   ├── _validar_input()
│   ├── _aplicar_filtro_zgrupo()
│   ├── _excluir_recall()
│   └── _enriquecer_dataframe()
├── --- Emparelhamento ---
│   ├── _emparelhar_fase1()
│   ├── _recalcular_apos_fase1()
│   └── _emparelhar_fase2()
├── --- Output ---
│   ├── _consolidar_sugestoes()
│   └── _ordenar_e_validar_output()
└── gerar_plano_redistribuicao()  # função pública
```

### 9.4 Integração com `app.py`
```python
from motor_redistribuicao import gerar_plano_redistribuicao

# após o pipeline de limpeza existente
df_agregado = stockreorder.preparar(df_raw)         # já existente
plano = gerar_plano_redistribuicao(
    df_agregado,
    anterior=toggle_anterior,                       # vindo do Streamlit
    margem_dlv_dias=margem_slider,
    dias_imunidade=imunidade_slider,
)
st.dataframe(plano)
```

---

## 10. Riscos e Mitigações

| ID | Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|---|
| R-1 | Cálculo errado de mês corrente vs. fechado em ficheiros antigos | M | A | Função pura `_detetar_normalizacao()` com testes para vários *snapshots*. |
| R-2 | Atualização dinâmica perdida por refactor de "performance" | M | A | Teste sequencial que falha imediatamente se houver staleness. |
| R-3 | Failsafe Clínico violado em casos limítrofes | B | A | Asserção explícita em `_emparelhar_fase1` antes de registar; teste dedicado por categoria. |
| R-4 | Output schema alterado inadvertidamente | M | M | Teste de schema com tuplo de colunas hard-coded. |
| R-5 | Lote com validade gigante a "absorver" stock excessivo na F2 | B | M | Cap `min(Meses_Para_DLV, 12)` testado. |
| R-6 | Multi-lote acidentalmente "ajudado" pelo desenvolvedor | B | A | Diretiva explícita; revisão de PR. |
| R-7 | Loja nova adicionada e motor falha por hardcoding | M | A | Teste com 1, 2, 5 lojas dinâmicas. |
| R-8 | Não-determinismo por `groupby` em colunas com NaN | B | M | Tiebreakers explícitos + teste de 2 execuções. |

---

## 11. Limitações Conhecidas / Out of Scope

### 11.1 Fora de âmbito (explicitamente excluído)
- **Multi-lote**. 1 linha = 1 lote.
- **Custos logísticos**. Ignorados por desenho.
- **Otimização global** (programação linear, *min-cost flow*). O algoritmo é guloso por desenho — atualização dinâmica + ordenação determinística.
- **Previsão estatística avançada** (ARIMA, Prophet). Run Rate é média ponderada simples.
- **Execução automática de transferências**. Output é sugestão.
- **Integração com sistemas grossistas** (Cooprofar, Alliance, OCP).
- **Otimização fiscal/contabilística** das transferências entre estabelecimentos.

### 11.2 Limitações declaradas
- O motor assume que `T Uni` é a última coluna e que as N colunas imediatamente à esquerda são meses cronológicos crescentes. Inputs que violem este pressuposto levantam `ValueError`.
- Lojas com nome contendo "Zgrupo" são **sempre** filtradas — não há mecanismo para incluí-las.
- O peso do mês corrente normalizado pode introduzir ruído em produtos com sazonalidade extrema (decisão consciente).

---

## 12. Glossário

| Termo | Definição |
|---|---|
| **DUC** | Data da última compra do produto na loja. |
| **DTVAL** | Data de validade do lote (`MM/YYYY`). |
| **DLV** | Data Limite de Venda = `DTVAL − margem_dlv_dias`. |
| **Run Rate (RR)** | Média ponderada de vendas mensais, pesos `[0.40, 0.30, 0.20, 0.10]`. |
| **Cobertura** | `STOCK / RR`, em meses. |
| **Necessidade** | `⌈RR × 2.0⌉ − STOCK`. |
| **Excesso Bruto** | `⌊STOCK − RR × 2.0⌋`. |
| **Excesso Líquido** | Excesso Bruto ajustado pelo Failsafe Clínico. |
| **Capacidade de Receção** | Quanto stock o recetor ainda comporta até `RR × 2.0`. |
| **Capacidade de Escoamento** | Quanto stock o recetor consegue *vender* até à DLV do doador. |
| **Failsafe Clínico** | Reserva mínima de 1 unidade quando `Teve_Vendas_6m == True`. |
| **Bloqueador de Validade** | Cap de transferência por capacidade de escoamento. |
| **Destino Forte** | Recetor com vendas recentes consistentes (RB-3). |
| **Zombie c/ Failsafe** | RR=0 mas teve vendas em 6m (cat. 2). |
| **Zombie Puro** | RR=0 e sem vendas em 6m (cat. 3). |
| **Toggle "anterior"** | `True` ⇒ janela `M-2..M-5`; `False` ⇒ janela inclui mês corrente. |

---

## 13. Anexos e Referências

- **Spec técnica detalhada**: `2026-04-26-motor-redistribuicao-design.md` (v2.0).
- **Pipeline a montante**: `app.py`, `stockreorder.py` (existentes).
- **Standards de código**: PEP 8, PEP 257, `ruff`.
- **Stack**: Python 3.11+, `pandas ≥ 2.0`, `numpy ≥ 1.24`, `python-dateutil ≥ 2.8`, `pytest ≥ 7.0`.

---

## 14. Aprovação

| Papel | Nome | Estado | Data |
|---|---|---|---|
| Owner / Sponsor | Filipe | ☐ Pendente | — |
| Implementação | — | ☐ Pendente | — |
| Validação técnica | — | ☐ Pendente | — |

---

## 15. Histórico de Versões

| Versão | Data | Alteração |
|---|---|---|
| 1.0 | 2026-04-26 | Versão inicial baseada na spec técnica v2.0. |
