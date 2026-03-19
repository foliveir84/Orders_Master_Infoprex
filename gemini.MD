# Documentação do Sistema de Agrupamento de SellOuts (Orders_Master_Infoprex)

Este documento descreve exaustivamente a arquitetura, regras de negócio e estrutura de dados do sistema atualizado (versão `app.py`). Serve como guia de referência e conjunto de regras estritas para o desenvolvimento assistido por IA.

## 1. Regras Críticas para o Assistente (Gemini)
*   **Perguntar Antes de Alterar:** Não deves realizar alterações arquiteturais ou de ficheiros sem primeiro questionar o utilizador, validar a abordagem e explicar o que será feito.
*   **Alterações Cirúrgicas:** Quando modificares o código, altera APENAS o bloco em discussão. Deves garantir que nenhuma outra funcionalidade (cálculos, formatação, merge de dados) se "perde" ou é esquecida na reescrita.
*   **Preservação da Lógica de Cálculo:** A adição de novas colunas ou atributos não pode impactar ou distorcer a lógica fundamental de cálculo de médias, totais ou propostas.
*   **Trabalho Passo a Passo:** As tarefas complexas devem ser partidas em módulos (ex: primeiro preparar os ficheiros auxiliares, depois a lógica core, por fim a UI).

## 2. Estrutura de Input e Configurações (JSON)
O sistema utiliza ficheiros auxiliares para facilitar a escalabilidade e manutenção:
*   **`laboratorios.json`**: Mapeia o nome do laboratório para uma lista de códigos de classe (`CLA`). Usado para filtrar massivamente os dados logo na leitura.
*   **`localizacoes.json`**: Dicionário de "aliases" para farmácias. Procura termos (ex: "vila") no nome original do Infoprex e substitui por um nome curto e limpo (ex: "Guia"). É aplicado de forma case-insensitive.
*   **`.env`**: Contém os URLs confidenciais para as Google Sheets de Ruturas (`DATABASE_URL`) e Produtos a Não Comprar (`GOOGLE_SHEETS`).

## 3. Lógica de Processamento e Memória (`processar_infoprex.py`)
A leitura dos ficheiros `.txt` do Infoprex (Novo Módulo Sifarma) é otimizada:
*   **Codificação:** Tenta `utf-16` (Little Endian), `utf-8` e `latin1`.
*   **Otimização de Memória (`usecols`):** Apenas as colunas necessárias para o negócio são lidas do disco, ignorando dezenas de colunas pesadas.
*   **Filtragem de Localização:** Identifica a data de venda mais recente (`DUV`) e filtra apenas os registos da farmácia principal presente no ficheiro.
*   **Filtragem de Portefólio:** Filtra por lista de códigos TXT (prioridade máxima) ou por códigos CLA dos laboratórios selecionados antes de carregar os dados para o Streamlit.
*   **Cronologia dos Meses:** Inverte a ordem das colunas de vendas (V14 a V0) para que o passado fique à esquerda e o presente à direita, simulando o formato legado. Trata nomes duplicados de meses (ex: `JAN.1`) para compatibilidade com o PyArrow.

## 4. Lógica de Agrupamento e Negócio (`app.py`)

O sistema opera com uma arquitetura de **desacoplamento de estado**, separando a agregação pesada do cálculo de propostas em tempo real.

### A. Filtro de Base e Agregações
1.  **Eliminação de Códigos Internos:** Todos os produtos com `CÓDIGO` iniciado por "1" são removidos logo após a concatenação inicial.
2.  **Filtro Anti-Zombies:** Apenas produtos com `STOCK != 0` ou `T Uni != 0` são processados.
3.  **Master List de Nomes:** Standardiza as designações para `Title Case`, removendo acentos e asteriscos.
4.  **Vistas Pré-Computadas:** O sistema gera e guarda em sessão tanto a **Vista Agrupada** (1 linha por código para todo o grupo) como a **Vista Detalhada** (linhas por farmácia + linha `Zgrupo_Total`).

### B. Cálculos em Tempo Real
Sempre que o utilizador altera um toggle ou slider, o sistema recalcula instantaneamente:
*   **Média Ponderada:** Pesos `[0.4, 0.3, 0.2, 0.1]` aplicados a 4 meses. O utilizador escolhe se começa no mês atual ou no anterior.
*   **Proposta Base:** `(Média * Meses_Previsão) - Stock`.
*   **Integração de Ruturas (Infarmed):** Se o produto estiver em rutura na Google Sheet, a proposta passa a: `((Média / 30) * TimeDelta) - Stock`.
*   **Lista Não Comprar:** Faz merge por Código e Localização para gerar a coluna `DATA_OBS`.

### C. Ordenação Estrita
As tabelas são rigorosamente ordenadas de forma ascendente por:
1. `DESIGNAÇÃO`
2. `CÓDIGO`
3. `LOCALIZACAO` (Apenas na vista detalhada)

## 5. Interface e Exportação
*   **Sidebar:** Centraliza todos os uploads e filtros iniciais.
*   **Alertas Inteligentes:** Deteta se o utilizador alterou filtros na sidebar sem clicar em "Processar Dados" e avisa que os dados estão obsoletos.
*   **Validação de Erros:** Se o utilizador carregar o ficheiro errado no local errado, o sistema apresenta um erro amigável em vez de crashar.
*   **Destaques Visuais (Web e Excel):**
    *   Linha de Total: Preto com letra branca.
    *   Não Comprar: Roxo claro até à coluna `T Uni`.
    *   Rutura: Célula da `Proposta` a vermelho.
*   **Excel:** A coluna `CLA` é removida automaticamente no momento do download.

## 6. Motor de Redistribuição Inteligente de Stock (`stockreorder.py`)

Esta funcionalidade é um sistema de suporte à decisão logística que visa otimizar o capital imobilizado através de transferências entre farmácias da rede.

### A. Fundamentos e Insights de Negócio Implementados

1.  **Custo Marginal de Transporte Zero:**
    *   **O quê:** Não aplicamos filtros de valor mínimo ou quantidade mínima para gerar uma transferência.
    *   **Porquê:** Como as rotas de transporte interno já existem e circulam para outros fluxos, aproveitar a capacidade ociosa para mover até uma única unidade de baixo valor é rentável e limpa o inventário.
    *   **O que evitamos:** Evitamos deixar "restos" de stock parado apenas por terem baixo valor unitário.

2.  **Proteção de Produto Novo (Imunidade DUC):**
    *   **O quê:** Um produto comprado nos últimos X dias (padrão 90) é imune a ser transferido como "Zombie".
    *   **Porquê:** Novos produtos precisam de tempo na prateleira para que o mercado local reaja. Remover um produto novo precocemente distorce o teste de portfólio.
    *   **Dados Sujos:** Se a Data da Última Compra (`DUC`) for nula, o sistema assume que o produto é antigo e retira-lhe a imunidade.

3.  **Trava de Segurança da Última Unidade (Failsafe):**
    *   **O quê:** Se uma farmácia teve pelo menos uma venda nos últimos meses, o sistema nunca lhe retira a última unidade (`Stock - 1`).
    *   **Porquê:** Evitamos "secar" completamente uma loja que ainda tem procura residual, mantendo a presença mínima no mercado local.
    *   **Exceção:** Só evacuamos a prateleira a 100% se o produto for um **Zombie Absoluto** (0 vendas no período avaliado).

4.  **Histerese de Cobertura (Fase 1):**
    *   **O quê:** Tiramos de quem tem `> 2 meses` para dar a quem tem `< 1 mês`. O destino só é enchido até ao limite de `2 meses`.
    *   **Porquê:** Evitamos o efeito "Ping-Pong". Se enchêssemos o destino até ao mesmo nível da origem, no mês seguinte o sistema poderia sugerir a devolução do produto.

5.  **Evacuação Preditiva para Silos Fortes (Fase 2):**
    *   **O quê:** Atiramos Zombies (0 vendas) para a farmácia com a maior Média de Vendas da rede, **mesmo que ela já tenha stock suficiente**.
    *   **Porquê:** É melhor sobrelotar uma loja que vende bem do que deixar o produto morrer numa loja que não vende nada. O produto tem maior probabilidade estatística de ser escoado antes de caducar.
    *   **Limite de Travagem:** O destino só aceita o Zombie se a sua Média permitir vender o stock atual + o Zombie **antes da Data de Validade (`DTVAL`)** do produto.

### B. O Motor de 2 Fases e Stock Virtual
O sistema processa a lógica de forma sequencial para garantir integridade:
*   **Fase 1 (Apagar Fogos):** Resolve riscos imediatos de rutura usando excessos de cobertura.
*   **Cálculo de Stock Virtual:** Após a Fase 1, o sistema "simula" que as unidades já foram movidas.
*   **Fase 2 (Otimizar Mortos):** Atua sobre o que sobrou após a Fase 1, focando-se em eliminar Zombies.

### C. Colunas de Confiança (Validação Humana)
Para que o utilizador confie no sistema "cego", o output inclui métricas de fundamentação:
*   **`Motivo Saída` / `Motivo Entrada`:** Explica textualmente porque é que a ação está a ser sugerida.
*   **`Tempo Escoamento Previsto`:** Uma prova matemática que demonstra que a loja de destino consegue vender o produto antes de ele caducar.

## Próximos Passos
1.  Manter a estabilidade das fórmulas matemáticas.
2.  Garantir que novos mapeamentos em `localizacoes.json` refletem instantaneamente em todos os merges.
3.  Implementar novas métricas de performance conforme necessidade de negócio.
