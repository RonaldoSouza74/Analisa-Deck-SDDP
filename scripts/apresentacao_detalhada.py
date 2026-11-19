"""Apresentação detalhada (.pptx): balanço, situação de cada hora e circuitos no limite, para o
Brasil, cada subsistema e cada estado, com explicações em cada slide.

Usa só os gráficos:
  balanco_uf\\balanco_<UF>.png, balanco_subsistema\\balanco_<ID>.png (+ balanco_resumo.png)
  relacao_gargalo\\ocorrencias_estados.png, gargalo_subsistema\\ocorrencias_subsistemas.png
  gargalo_linhas\\circuitos_horas_no_limite*.png, circuitos_sobrecarga_nao_monitorados*.png,
  circuitos_vertimento*.png (Brasil) e os mesmos em circuitos_por_estado\\ e circuitos_por_subsistema\\
Cada slide traz à direita um quadro "Como ler" e, nas anotações do apresentador, a explicação
completa. Os estados e subsistemas aparecem na ordem do vertimento (do maior para o menor).

Uso:
  python apresentacao_detalhada.py "<pasta do caso>" [--ano 2030] [--saida <pasta>]
Saída: <caso>\\resultados_uf\\apresentacao\\apresentacao_detalhada_<ano>.pptx
Requer python-pptx (python -m pip install python-pptx).
"""
import argparse
import datetime
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apresentacao import Deck, numeros, br, NOME_UF                                # noqa: E402
from graficos_uf import ORDEM_UF                                                  # noqa: E402

# --- textos de explicação de cada tipo de gráfico ------------------------------------
LER = {
    'balanco': ['Como ler',
                '• Barras empilhadas: o que gerou em cada hora do dia (média do ano): hidrelétrica, '
                'termelétrica e renovável.',
                '• Linha preta: carga. Abaixo dela, o que foi consumido no próprio local.',
                '• Contorno roxo: o que foi exportado (tracejado = importado).',
                '• Hachurado no topo: o que foi vertido (vermelho = gargalo, cinza = excesso).',
                '• Meio: o mesmo separado pela situação da hora. Embaixo: térmica, hidro e "outros" em caixas.'],
    'balanco_sub': ['Como ler',
                    '• Igual ao balanço do estado, somando todas as barras do subsistema.',
                    '• Hachurado: vermelho = gargalo entre subsistemas (subsistema inteiro abaixo do SIN); laranja = '
                    'gargalo dentro do subsistema; cinza = excesso.',
                    '• Contorno roxo: exportado para outros subsistemas.'],
    'ocorrencias': ['Como ler',
                    '• Cada barra é uma hora do dia (1 = 00h–01h).',
                    '• A altura mostra quanto % dos dias × cenários caiu em cada situação.',
                    '• Vermelho: houve vertimento por gargalo. Cinza: só por excesso. Azul-claro: sem vertimento.',
                    '• No título: % de todas as horas do ano com gargalo.'],
    'ocorrencias_sub': ['Como ler',
                        '• Cada barra é uma hora do dia; a altura é o % dos dias × cenários em cada situação.',
                        '• Vermelho: subsistema inteiro abaixo do CMO do SIN (gargalo entre subsistemas).',
                        '• Laranja: só barras dentro do subsistema presas. Cinza: só excesso. Azul-claro: sem '
                        'vertimento.'],
    'horas': ['Como ler',
              '• Esquerda: % das horas do ano com fluxo ≥ 99% do limite físico do deck (Rating/Rn).',
              '• Lado preso: a ponta de CMO mais baixo, onde a energia fica presa.',
              '• Direita: % das horas de cada mês no limite, na mesma ordem das barras.',
              '• Só circuitos monitorados (o SDDP respeita o limite deles).'],
    'sobre': ['Como ler',
              '• Circuitos que o SDDP NÃO monitora: o fluxo pode passar do limite sem custo.',
              '• Esquerda: % das horas acima de 100% do limite; texto: carregamento máximo e limite.',
              '• Direita: % das horas de cada mês acima do limite.',
              '• São gargalos que a simulação não representa.'],
    'vert': ['Como ler',
             '• Vertimento por gargalo do estado do lado preso, somado nas horas em que o circuito estava no limite.',
             '• É coincidência, não divisão: vários circuitos podem estar no limite na mesma hora.',
             '• Direita: % das horas de cada mês com o circuito no limite.'],
}
NOTAS = {
    'balanco': 'Balanço hora a hora: renovável gerada (gergnd) + hidrelétrica (gerhid) + termelétrica (gerter) − carga '
               '(demxba) = injeção líquida (businj). "Outros" é a diferença (baterias, déficit, arredondamentos). '
               'O vertimento (vergnd sem geração distribuída e envetu) aparece hachurado no topo, separado em gargalo '
               '(CMO da barra da usina mais de 1 $/MWh abaixo do SIN) e excesso no sistema. A segunda linha repete o '
               'balanço só nas horas com gargalo, só com excesso e sem vertimento.',
    'ocorrencias': 'Para cada hora do dia são contados todos os dias do ano × cenários. Cada um é classificado em: '
                   'com vertimento por gargalo, só com vertimento por excesso, ou sem vertimento. A barra mostra a '
                   'proporção de cada situação.',
    'horas': 'Fluxo dos arquivos acline_flow e transformer_flow do SDDP comparado com o limite físico do deck (Rating '
             'das linhas, Rn dos transformadores) na rede de 1º de janeiro do ano. No limite = fluxo ≥ 99% do limite. '
             'Lado preso = ponta do circuito com CMO mais baixo.',
    'sobre': 'Circuitos não monitorados (FlagMonitored = 0) não têm limite no problema do SDDP; o fluxo pode passar do '
             'limite físico. A lista mostra os que passaram de 100% e por quanto tempo.',
    'vert': 'Para cada circuito monitorado no limite, soma o vertimento por gargalo do estado do lado preso nas horas em '
            'que o circuito estava no limite. Indica quais circuitos coincidem com o vertimento; não é uma divisão '
            'exclusiva do vertimento entre os circuitos.',
}
TIPOS_CIRC = [('horas', 'circuitos_horas_no_limite', 'circuitos monitorados mais tempo no limite'),
              ('vert', 'circuitos_vertimento', 'circuitos no limite com mais vertimento coincidente'),
              ('sobre', 'circuitos_sobrecarga_nao_monitorados', 'circuitos NÃO monitorados acima de 100%')]


def paginas(pasta, base):
    """Arquivos base.png, base_2.png, ... na ordem das páginas."""
    arqs = [a for a in glob.glob(os.path.join(pasta, base + '*.png'))
            if re.fullmatch(re.escape(base) + r'(_\d+)?\.png', os.path.basename(a))]
    return sorted(arqs, key=lambda a: int(re.search(r'_(\d+)\.png$', a).group(1)) if re.search(r'_(\d+)\.png$', a)
                  and os.path.basename(a) != base + '.png' else 1)


def main():
    p = argparse.ArgumentParser(description='Apresentação detalhada: balanço, situação das horas e circuitos.')
    p.add_argument('caso', help='pasta do caso SDDP (com resultados_uf dentro) ou a própria resultados_uf')
    p.add_argument('--ano', type=int, default=2030)
    p.add_argument('--saida')
    a = p.parse_args()
    res = a.caso if os.path.basename(os.path.normpath(a.caso)).lower() == 'resultados_uf' else \
        os.path.join(a.caso, 'resultados_uf')
    if not os.path.isdir(res):
        sys.exit(f'ERRO: não achei a pasta {res}. Rode antes o rodar_tudo.bat')
    saida = a.saida or os.path.join(res, 'apresentacao')
    os.makedirs(saida, exist_ok=True)
    N = numeros(res)
    D = Deck(res, saida)
    gl = os.path.join(res, 'gargalo_linhas')

    def circuitos(pasta, prefixo, onde):
        for chave, base, rot in TIPOS_CIRC:
            arqs = paginas(pasta, prefixo + base)
            for k, arq in enumerate(arqs):
                parte = f' ({k + 1}/{len(arqs)})' if len(arqs) > 1 else ''
                D.imagem(f'{onde}: {rot}{parte}', arq, lateral=LER[chave], notas=NOTAS[chave],
                         fonte=os.path.relpath(arq, res))

    D.capa(f'Balanço, situação das horas e linhas no limite — {a.ano}',
           'Brasil, subsistemas e estados: o que gerava quando houve vertimento, em que horas houve gargalo e quais '
           'linhas e transformadores ficaram no limite',
           datetime.date.today().strftime('%d/%m/%Y'))
    D.texto('O que tem nesta apresentação', [
        '• Balanço: geração por fonte, carga, exportação e vertimento, hora a hora (média do ano).',
        '• Situação de cada hora do dia: com gargalo, só com excesso ou sem vertimento.',
        '• Circuitos: monitorados no limite, com mais vertimento coincidente, e não monitorados acima de 100%.',
        '• Ordem: Brasil → subsistemas → estados (do maior para o menor vertimento).',
        '• Gargalo (estado) = CMO da barra da usina mais de 1 $/MWh abaixo do CMO do SIN (mediana das barras).',
        '• Gargalo entre subsistemas = CMO do subsistema (mediana das suas barras) abaixo do SIN.',
        '• Vertimento sem a geração distribuída (MMGD/OMGD). Só dados de entrada e saída do SDDP.'])

    # --- Brasil -------------------------------------------------------------------------
    D.secao('Brasil', 'Visão geral de todos os estados e subsistemas')
    D.imagem('Em que situação cada hora do dia ocorreu, por estado', 'relacao_gargalo/ocorrencias_estados.png',
             lateral=LER['ocorrencias'], notas=NOTAS['ocorrencias'])
    D.imagem('Em que situação cada hora do dia ocorreu, por subsistema', 'gargalo_subsistema/ocorrencias_subsistemas.png',
             lateral=LER['ocorrencias_sub'], notas=NOTAS['ocorrencias'])
    D.imagem('Vertimento × geração hidrelétrica e termelétrica do estado nas mesmas horas', 'balanco_uf/balanco_resumo.png',
             notas='Para cada estado: vertimento por gargalo (esquerda) e por excesso (direita) e quanto a hidrelétrica e '
                   'a termelétrica do próprio estado geravam nessas horas.')
    D.imagem('Vertimento × geração hidrelétrica e termelétrica do subsistema nas mesmas horas',
             'balanco_subsistema/balanco_resumo.png',
             notas='Igual ao gráfico por estado, somando as barras de cada subsistema.')
    circuitos(gl, '', 'Brasil')

    # --- subsistemas ----------------------------------------------------------------------
    D.secao('Subsistemas', 'Balanço e circuitos de cada subsistema')
    pasta_bs = os.path.join(res, 'balanco_subsistema')
    pasta_cs = os.path.join(gl, 'circuitos_por_subsistema')
    subs = list(N.get('ordem_sub', []))
    for arq in sorted(glob.glob(os.path.join(pasta_bs, 'balanco_*.png')) + glob.glob(os.path.join(pasta_cs, '*_*.png'))):
        k = os.path.basename(arq).split('_')[1 if arq.startswith(pasta_bs) else 0].replace('.png', '')
        if k != 'resumo' and k not in subs:
            subs.append(k)
    for k in subs:
        nome = N.get('sub_nome', {}).get(k, '')
        onde = f'Subsistema {k}' + (f' ({nome})' if nome else '')
        v = N.get('sub', {}).get(k)
        tit = f'{onde}: balanço nas horas de vertimento' + (f' — {br(v.sum())} GWh vertidos' if v is not None else '')
        D.imagem(tit, os.path.join(pasta_bs, f'balanco_{k}.png'), lateral=LER['balanco_sub'], notas=NOTAS['balanco'],
                 fonte=f'balanco_subsistema\\balanco_{k}.png', partes=2)
        circuitos(pasta_cs, f'{k}_', onde)

    # --- estados -----------------------------------------------------------------------------
    D.secao('Estados', 'Balanço e circuitos de cada estado')
    pasta_bu = os.path.join(res, 'balanco_uf')
    pasta_cu = os.path.join(gl, 'circuitos_por_estado')
    ufs = list(N.get('ordem_uf', [])) + [u for u in ORDEM_UF if u not in N.get('ordem_uf', [])]
    for u in ufs:
        onde = f'{NOME_UF.get(u, u)} ({u})'
        v = N.get('uf', {}).get('renovavel', {}).get(u)
        tit = f'{onde}: balanço nas horas de vertimento' + \
            (f' — {br(v.sum())} GWh de vertimento renovável, {br(100 * v[0] / v.sum())}% por gargalo'
             if v is not None and v.sum() > 0 else '')
        D.imagem(tit, os.path.join(pasta_bu, f'balanco_{u}.png'), lateral=LER['balanco'], notas=NOTAS['balanco'],
                 fonte=f'balanco_uf\\balanco_{u}.png', partes=2)
        circuitos(pasta_cu, f'{u}_', onde)

    arq = os.path.join(saida, f'apresentacao_detalhada_{a.ano}.pptx')
    try:
        D.prs.save(arq)
    except PermissionError:
        sys.exit(f'ERRO: não consegui gravar {arq}. Ele está aberto no PowerPoint? Feche e rode de novo.')
    falt = [f for f in D.faltando if 'balanco_' in f or 'ocorrencias' in f]
    print(f'{D.n} slides.')
    if falt:
        print(f'  AVISO: {len(falt)} gráficos não encontrados (slides pulados; estados/subsistemas sem vertimento '
              f'não têm balanço): ' + ', '.join(os.path.basename(f) for f in falt[:12]) + (' ...' if len(falt) > 12 else ''))
    print(f'Fim. Apresentação: {arq}')


if __name__ == '__main__':
    main()
