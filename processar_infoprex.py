import pandas as pd
import io

MESES_PT = {
    1: 'JAN', 2: 'FEV', 3: 'MAR', 4: 'ABR', 5: 'MAI', 6: 'JUN',
    7: 'JUL', 8: 'AGO', 9: 'SET', 10: 'OUT', 11: 'NOV', 12: 'DEZ'
}

def filtrar_localizacao(df):
    """
    Converte a coluna DUV para data, identifica a localização da venda
    mais recente e filtra a dataframe por essa localização.
    """
    # 1. Converter DUV para datetime.
    # errors='coerce' transforma valores vazios ou inválidos em NaT (Not a Time)
    df['DUV'] = pd.to_datetime(df['DUV'], format='%d/%m/%Y', errors='coerce')

    # 2. Encontrar a data mais recente (max ignora NaT automaticamente)
    data_mais_recente = df['DUV'].max()

    if pd.isna(data_mais_recente):
        print("Aviso: Não foram encontradas datas de venda (DUV) na dataframe.")
        return df, pd.NaT

    # 3. Localizar o valor da coluna LOCALIZACAO para essa data
    # Usamos .iloc[0] para pegar a primeira ocorrência caso existam várias linhas com a mesma data max
    localizacao_alvo = df.loc[df['DUV'] == data_mais_recente, 'LOCALIZACAO'].iloc[0]

    print(f"Data mais recente: {data_mais_recente.strftime('%d/%m/%Y')}")
    print(f"Localização encontrada: {localizacao_alvo}")

    # 4. Filtrar a dataframe pela localização encontrada
    df_filtrada = df[df['LOCALIZACAO'] == localizacao_alvo].copy()

    return df_filtrada, data_mais_recente

def extrair_codigos_txt(file):
    """
    Lê um ficheiro de texto carregado (Streamlit UploadedFile ou objeto de ficheiro) 
    e extrai uma lista de códigos (um por linha).
    Ignora linhas em branco ou cabeçalhos em texto.
    """
    try:
        # Tenta descodificar o conteúdo (suporta bytes do Streamlit ou strings)
        if hasattr(file, 'getvalue'):
            content = file.getvalue().decode("utf-8")
        else:
            with open(file, 'r', encoding='utf-8') as f:
                content = f.read()
        
        stringio = io.StringIO(content)
        codigos = []
        for linha in stringio.readlines():
            linha_limpa = linha.strip()
            # Fica apenas com linhas que contenham unicamente dígitos (exclui cabeçalhos como "CNP")
            if linha_limpa and linha_limpa.isdigit():
                codigos.append(linha_limpa)
        return codigos
    except Exception as e:
        print(f"Erro ao ler ficheiro de códigos: {e}")
        return []

def ler_ficheiro_infoprex(filepath, lista_cla=None, lista_codigos=None):
    """
    Lê o ficheiro txt do Infoprex para uma dataframe do pandas e aplica o filtro inicial.
    Tenta várias codificações, começando por utf-16 que é comum nestes exports.
    Permite filtrar por uma lista de códigos (CPR) ou uma lista de classes (CLA) para poupar memória.
    """
    # -------------------------------------------------------------
    # OTIMIZAÇÃO DE MEMÓRIA (usecols)
    # Definir exatamente quais colunas queremos carregar do disco
    # -------------------------------------------------------------
    colunas_vendas_esperadas = [f'V{i}' for i in range(15)]
    colunas_alvo = ['CPR', 'NOM', 'LOCALIZACAO', 'SAC', 'PVP', 'PCU', 'DUC', 'DTVAL', 'CLA', 'DUV'] + colunas_vendas_esperadas

    # Função lambda para ler apenas as colunas se elas existirem no ficheiro (previne KeyError)
    usecols_func = lambda x: x in colunas_alvo

    try:
        # Tenta ler com utf-16 (comum em exports de texto do Windows/Infoprex)
        df = pd.read_csv(filepath, sep='\t', encoding='utf-16', usecols=usecols_func)
    except Exception:
        try:
            # Tenta ler com utf-8
            df = pd.read_csv(filepath, sep='\t', encoding='utf-8', usecols=usecols_func)
        except Exception:
            try:
                # Se falhar, tenta com latin1
                df = pd.read_csv(filepath, sep='\t', encoding='latin1', usecols=usecols_func)
            except Exception:
                raise ValueError("Codificação não suportada ou ficheiro corrompido.")

    # Validação estrutural: garantir que é de facto um ficheiro Infoprex verificando a presença de colunas chave
    if 'CPR' not in df.columns or 'DUV' not in df.columns:
        raise ValueError("O ficheiro não contém as colunas estruturais esperadas (CPR, DUV). Verifique se não carregou o ficheiro errado no local do Infoprex.")
    
    # Aplica o filtro de localização baseado na DUV e recebe a data máxima
    df, data_max = filtrar_localizacao(df)

    # -------------------------------------------------------------
    # APLICAÇÃO DE FILTROS (REDUÇÃO DE MEMÓRIA)
    # -------------------------------------------------------------
    # Se uma lista de códigos foi carregada, ela tem prioridade
    if lista_codigos is not None and len(lista_codigos) > 0:
        lista_codigos_str = [str(c).strip().lower() for c in lista_codigos]
        df = df[df['CPR'].astype(str).str.strip().str.lower().isin(lista_codigos_str)]
    # Senão, usamos a lista de laboratórios (CLA) se existir
    elif lista_cla is not None and len(lista_cla) > 0:
        lista_cla_str = [str(c).strip().lower() for c in lista_cla]
        df = df[df['CLA'].astype(str).str.strip().str.lower().isin(lista_cla_str)]
    # -------------------------------------------------------------

    # Definir colunas de vendas (V0 a V14 = 15 meses)
    colunas_vendas = [f'V{i}' for i in range(15)]
    
    # Colunas base solicitadas e necessárias para a lógica
    colunas_base = ['CPR', 'NOM', 'LOCALIZACAO', 'PVP', 'PCU', 'DUC', 'DTVAL', 'SAC', 'CLA']
    colunas_manter = colunas_base + colunas_vendas
    
    # Filtrar a dataframe apenas com as colunas que existem no ficheiro (evitar erros)
    colunas_finais = [col for col in colunas_manter if col in df.columns]
    df_filtrada = df[colunas_finais].copy()
    
    # Inverter a ordem das colunas de vendas para ficar [Mais Antigo ... Mais Recente]
    vendas_presentes = [col for col in colunas_vendas if col in df_filtrada.columns]
    vendas_invertidas = vendas_presentes[::-1] # Inverte a lista (V14, V13 ... V0)
    
    # Reordenar a dataframe (Base + Vendas)
    base_presentes = [col for col in colunas_base if col in df_filtrada.columns]
    df_filtrada = df_filtrada[base_presentes + vendas_invertidas]
    
    # Calcular T Uni (Soma de todas as vendas V0 a V14)
    df_filtrada['T Uni'] = df_filtrada[vendas_presentes].sum(axis=1)

    # Renomear colunas base para os nomes do sistema antigo
    rename_base = {
        'CPR': 'CÓDIGO',
        'NOM': 'DESIGNAÇÃO',
        'SAC': 'STOCK',
        'PCU': 'P.CUSTO'
    }
    df_filtrada.rename(columns=rename_base, inplace=True)

    # Renomear as colunas V0 a V14 de forma dinâmica baseada no mês mais recente
    if pd.notna(data_max):
        rename_dict = {}
        meses_vistos = {}
        
        # Iteramos da coluna de vendas mais antiga (V14) para a mais recente (V0)
        # para garantir que a primeira ocorrência fica normal e as seguintes levam sufixo.
        for col_v in vendas_invertidas:
            if col_v in df_filtrada.columns:
                # Extrai o índice a partir do nome da coluna (ex: V14 -> 14)
                i = int(col_v.replace('V', ''))
                
                # Subtrai i meses da data mais recente
                mes_alvo = data_max - pd.DateOffset(months=i)
                nome_mes = MESES_PT[mes_alvo.month]
                
                # Se o mês já existe, adicionamos um sufixo (.1, .2, etc.) igual ao pandas nativo
                if nome_mes in meses_vistos:
                    meses_vistos[nome_mes] += 1
                    novo_nome = f"{nome_mes}.{meses_vistos[nome_mes]}"
                else:
                    meses_vistos[nome_mes] = 0
                    novo_nome = nome_mes
                
                rename_dict[col_v] = novo_nome
                
        df_filtrada.rename(columns=rename_dict, inplace=True)
    
    return df_filtrada
