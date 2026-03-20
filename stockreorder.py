import pandas as pd
import numpy as np
from datetime import datetime

def calcular_estado_stock(df, meses_validade, dias_imunidade, cols_meses_vendas, pesos_vendas):
    """
    Calcula todas as métricas necessárias para a análise de redistribuição.
    """
    df_analise = df.copy()
    hoje = pd.Timestamp(datetime.now().date())

    # 1. Calcular Média Ponderada Exata
    df_analise['Media'] = df_analise[cols_meses_vendas].dot(pesos_vendas)

    # 2. Calcular Meses de Stock (Cobertura)
    df_analise['Meses_Stock'] = np.where(
        df_analise['Media'] > 0,
        df_analise['STOCK'] / df_analise['Media'],
        np.inf # Infinito se não há vendas
    )
    # Corrigir para 0 se stock=0 e media=0
    df_analise.loc[(df_analise['STOCK'] == 0) & (df_analise['Media'] == 0), 'Meses_Stock'] = 0.0

    # 3. Proteções: Validade e Compra Recente
    df_analise['DTVAL_Date'] = pd.to_datetime(df_analise['DTVAL'], format='%m/%Y', errors='coerce')
    # Se falhar o parse mm/yyyy, tenta d/m/y normal (caso o raw seja diferente)
    df_analise['DTVAL_Date'] = df_analise['DTVAL_Date'].fillna(pd.to_datetime(df_analise['DTVAL'], errors='coerce', dayfirst=True))
    
    df_analise['Meses_Para_Caducar'] = (df_analise['DTVAL_Date'] - hoje).dt.days / 30.0
    # Produtos sem validade assumem-se seguros (ou já foram triados noutro processo)
    df_analise['Validade_Curta'] = np.where(df_analise['Meses_Para_Caducar'].notna(), df_analise['Meses_Para_Caducar'] < meses_validade, False)

    df_analise['DUC_Date'] = pd.to_datetime(df_analise['DUC'], dayfirst=True, errors='coerce')
    df_analise['Dias_Desde_Compra'] = (hoje - df_analise['DUC_Date']).dt.days
    # DUC vazio = muito antigo = Imunidade Perdida (Is_Novo = False)
    df_analise['Is_Novo'] = np.where(df_analise['Dias_Desde_Compra'].notna(), df_analise['Dias_Desde_Compra'] < dias_imunidade, False)

    # 4. Classificações Táticas
    df_analise['Is_Zombie'] = (df_analise['STOCK'] > 0) & (df_analise['Media'] == 0) & (~df_analise['Is_Novo'])
    
    # Teve alguma venda nos meses avaliados? (Para o Failsafe contra devoluções)
    df_analise['Teve_Vendas_Positivas'] = (df_analise[cols_meses_vendas] > 0).any(axis=1)
    
    # Validação de "Forte Escoamento" (Constância ou Recência estrita nos últimos 2 meses da janela)
    vendas_positivas_por_mes = (df_analise[cols_meses_vendas] > 0).astype(int)
    df_analise['Meses_Com_Vendas'] = vendas_positivas_por_mes.sum(axis=1)
    
    # cols_meses_vendas vem do app.py já ordenado do mais recente para o mais antigo relativo ao toggle
    mes_atual = cols_meses_vendas[0]
    mes_anterior = cols_meses_vendas[1]
    
    vendeu_mes_atual = df_analise[mes_atual] > 0
    vendeu_mes_anterior = df_analise[mes_anterior] > 0
    multiplos_meses = df_analise['Meses_Com_Vendas'] >= 2
    
    df_analise['Destino_Forte'] = (df_analise['Media'] > 0) & (vendeu_mes_atual | (vendeu_mes_anterior & multiplos_meses))

    # ==========================================
    # PREPARAÇÃO FASE 1: Apagar Fogos
    # ==========================================
    # Necessidade: Destino precisa se Cobertura < 1.2 (Subimos de 1.0 para maior segurança). 
    # Objetivo = Encher até 2 meses.
    # NOVIDADE: Exigir 'Destino_Forte' para Fase 1 também, para evitar alimentar picos isolados (falsas ruturas).
    df_analise['Qtd_Necessaria_F1'] = np.where(
        (df_analise['Meses_Stock'] < 1.2) & df_analise['Destino_Forte'],
        np.ceil((df_analise['Media'] * 2.0) - df_analise['STOCK']),
        0
    )
    df_analise['Qtd_Necessaria_F1'] = df_analise['Qtd_Necessaria_F1'].clip(lower=0).astype(int)

    # Excesso Bruto: Origem cede o que tem acima de 2 meses.
    excesso_bruto = np.floor(df_analise['STOCK'] - (df_analise['Media'] * 2.0))
    excesso_bruto = np.where(excesso_bruto > 0, excesso_bruto, 0)
    
    # Excesso Líquido (Aplicando Proteções)
    # 1. Não cede se Validade Curta
    # 2. Failsafe: Se teve vendas positivas, deixa pelo menos 1
    limite_failsafe = np.where(df_analise['Teve_Vendas_Positivas'], df_analise['STOCK'] - 1, df_analise['STOCK'])
    excesso_liquido = np.minimum(excesso_bruto, limite_failsafe)
    
    # BUG 1 CORRIGIDO: Zombies podem e devem ceder stock na Fase 1
    df_analise['Qtd_Excesso_F1'] = np.where(
        ~df_analise['Validade_Curta'], 
        excesso_liquido, 
        0
    )
    df_analise['Qtd_Excesso_F1'] = df_analise['Qtd_Excesso_F1'].clip(lower=0).astype(int)

    return df_analise

def alocar_transferencias(origens_dict, destinos_dict, key_qty_origem, key_qty_destino, fase_nome, motivo_saida, motivo_entrada):
    sugestoes_geradas = []
    
    for destino in destinos_dict:
        need_qty = destino[key_qty_destino]
        if need_qty <= 0: continue
            
        for origem in origens_dict:
            if need_qty <= 0: break
            excess_qty = origem[key_qty_origem]
            if excess_qty <= 0: continue

            transfer_qty = int(min(need_qty, excess_qty))

            # BUG 2 CORRIGIDO: O destino é limitado na Fase 2 pela sua capacidade de escoar antes da origem caducar.
            if fase_nome == 'Fase 2':
                meses_validade_origem = origem.get('Meses_Para_Caducar', 12)
                if pd.isna(meses_validade_origem): meses_validade_origem = 12
                meses_validade_origem = min(meses_validade_origem, 12)
                
                capacidade_real = int(np.floor(destino['Media'] * meses_validade_origem) - destino['STOCK'])
                if capacidade_real <= 0: continue
                transfer_qty = min(transfer_qty, capacidade_real)

            if transfer_qty > 0:
                # BUG 4 CORRIGIDO: Atualizar stock destino em tempo real para cálculo preciso e encadeamento
                destino['STOCK'] += transfer_qty
                
                sugestoes_geradas.append({
                    'CÓDIGO': destino['CÓDIGO'],
                    'DESIGNAÇÃO': destino.get('DESIGNAÇÃO', ''),
                    'Origem': origem['LOCALIZACAO'],
                    'Motivo Saída': motivo_saida(origem),
                    'Stock_Origem': int(origem['STOCK']),
                    'Validade': origem.get('DTVAL', ''),
                    'Qtd Transferir': transfer_qty,
                    'Destino': destino['LOCALIZACAO'],
                    'Motivo Entrada': motivo_entrada(destino),
                    'Stock_Destino': int(destino['STOCK']),
                    'Tempo_Escoamento_Previsto': f"{round(destino['STOCK'] / destino['Media'], 1)} meses" if destino['Media'] > 0 else "N/A"
                })
                
                need_qty -= transfer_qty
                origem[key_qty_origem] -= transfer_qty
                destino[key_qty_destino] = need_qty
    
    return sugestoes_geradas

def executar_fase_1(df_analise):
    sugestoes_fase_1 = []
    grupos_produto = df_analise.groupby('CÓDIGO')
    
    for codigo, group in grupos_produto:
        origens = group[group['Qtd_Excesso_F1'] > 0].sort_values(by=['Meses_Stock'], ascending=[False]).to_dict('records')
        destinos = group[group['Qtd_Necessaria_F1'] > 0].sort_values(by=['Meses_Stock'], ascending=[True]).to_dict('records')

        if not origens or not destinos: continue

        sug_prod = alocar_transferencias(
            origens, destinos, 'Qtd_Excesso_F1', 'Qtd_Necessaria_F1', 'Fase 1',
            lambda o: f"Excesso (Cob: {round(o['Meses_Stock'],1)}m)",
            lambda d: f"Risco Rutura (Cob: {round(d['Meses_Stock'],1)}m)"
        )
        sugestoes_fase_1.extend(sug_prod)
        
    return pd.DataFrame(sugestoes_fase_1)

def atualizar_stock_virtual(df_analise_original, sugestoes_fase_1):
    if sugestoes_fase_1.empty: return df_analise_original
        
    df_virtual = df_analise_original.copy()
    saidas = sugestoes_fase_1.groupby(['CÓDIGO', 'Origem'])['Qtd Transferir'].sum().reset_index()
    saidas.rename(columns={'Origem': 'LOCALIZACAO', 'Qtd Transferir': 'Ajuste'}, inplace=True)
    saidas['Ajuste'] *= -1 
    
    entradas = sugestoes_fase_1.groupby(['CÓDIGO', 'Destino'])['Qtd Transferir'].sum().reset_index()
    entradas.rename(columns={'Destino': 'LOCALIZACAO', 'Qtd Transferir': 'Ajuste'}, inplace=True)
    
    ajustes_finais = pd.concat([saidas, entradas]).groupby(['CÓDIGO', 'LOCALIZACAO'])['Ajuste'].sum().reset_index()

    df_virtual = df_virtual.merge(ajustes_finais, on=['CÓDIGO', 'LOCALIZACAO'], how='left')
    df_virtual['Ajuste'] = df_virtual['Ajuste'].fillna(0)
    df_virtual['STOCK'] = df_virtual['STOCK'] + df_virtual['Ajuste']
    df_virtual.drop(columns=['Ajuste'], inplace=True)
    
    # Recalcular coberturas com o novo stock
    df_virtual['Meses_Stock'] = np.where(df_virtual['Media'] > 0, df_virtual['STOCK'] / df_virtual['Media'], np.inf)
    df_virtual.loc[(df_virtual['STOCK'] == 0) & (df_virtual['Media'] == 0), 'Meses_Stock'] = 0.0
    
    return df_virtual

def executar_fase_2(df_apos_fase_1):
    # ==========================================
    # PREPARAÇÃO FASE 2: Evacuação de Zombies
    # ==========================================
    # Origens: Zombies Puros (não novos, não em rutura de validade).
    # Excesso F2: O stock todo.
    df_apos_fase_1['Qtd_Excesso_F2'] = np.where(
        df_apos_fase_1['Is_Zombie'] & (~df_apos_fase_1['Validade_Curta']),
        df_apos_fase_1['STOCK'],
        0
    ).astype(int)

    # Destinos: Lojas com Destino_Forte (Media > 0 e com consistência/recência)
    # A capacidade será calculada dinamicamente no alocar_transferencias baseada na validade da Origem
    df_apos_fase_1['Qtd_Necessaria_F2'] = np.where(
        df_apos_fase_1['Destino_Forte'],
        9999,
        0
    )

    sugestoes_fase_2 = []
    grupos_produto = df_apos_fase_1.groupby('CÓDIGO')

    for codigo, group in grupos_produto:
        # BUG 3 CORRIGIDO: Ordenação descendente nas origens pelo STOCK (mais zombies libertam primeiro)
        origens = group[group['Qtd_Excesso_F2'] > 0].sort_values(by=['STOCK'], ascending=[False]).to_dict('records')
        # Priorizar destinos com maior volume de vendas
        destinos = group[group['Qtd_Necessaria_F2'] > 0].sort_values(by=['Media'], ascending=[False]).to_dict('records')

        if not origens or not destinos: continue

        sug_prod = alocar_transferencias(
            origens, destinos, 'Qtd_Excesso_F2', 'Qtd_Necessaria_F2', 'Fase 2',
            lambda o: "Evacuação Zombie",
            lambda d: f"Forte Escoamento (Média: {round(d['Media'],1)})"
        )
        sugestoes_fase_2.extend(sug_prod)
        
    return pd.DataFrame(sugestoes_fase_2)

def gerar_plano_redistribuicao(df_input, df_univ, meses_validade, dias_imunidade, cols_meses_vendas, pesos_vendas):
    """
    Ponto de entrada principal. Recebe a DF base detalhada (com as colunas dos meses)
    e retorna uma DF transparente com o plano de ação.
    """
    if df_input.empty:
        return pd.DataFrame()

    df_base = df_input.copy()
    
    # Remover linha totalizadora que não é uma localização real
    df_base = df_base[~df_base['LOCALIZACAO'].str.contains('Zgrupo', case=False, na=False)]
    
    # Se não tiver a designação universal, fazemos merge
    if 'DESIGNAÇÃO' not in df_base.columns:
        df_base = pd.merge(df_base, df_univ, on='CÓDIGO', how='left')
    
    df_analise_inicial = calcular_estado_stock(df_base, meses_validade, dias_imunidade, cols_meses_vendas, pesos_vendas)
    
    sugestoes_f1 = executar_fase_1(df_analise_inicial)
    df_apos_f1 = atualizar_stock_virtual(df_analise_inicial, sugestoes_f1)
    sugestoes_f2 = executar_fase_2(df_apos_f1)
    
    sugestoes_finais = pd.concat([sugestoes_f1, sugestoes_f2], ignore_index=True)
    
    if not sugestoes_finais.empty:
        # Organizar colunas de forma legível
        cols_output = ['CÓDIGO', 'DESIGNAÇÃO', 'Origem', 'Motivo Saída', 'Stock_Origem', 'Validade', 'Qtd Transferir', 'Destino', 'Motivo Entrada', 'Stock_Destino', 'Tempo_Escoamento_Previsto']
        sugestoes_finais = sugestoes_finais[cols_output].sort_values(['Origem', 'Destino', 'DESIGNAÇÃO'])
        return sugestoes_finais
    
    return pd.DataFrame()
