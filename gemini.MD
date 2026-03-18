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

## Próximos Passos
1.  Manter a estabilidade das fórmulas matemáticas.
2.  Garantir que novos mapeamentos em `localizacoes.json` refletem instantaneamente em todos os merges.
3.  Implementar novas métricas de performance conforme necessidade de negócio.
