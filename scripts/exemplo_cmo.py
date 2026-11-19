"""Exemplo com os dados reais: de onde vem cada ponto do gráfico subsistema_<ID>.png.

Para um subsistema (ex.: NE), uma hora do dia (ex.: 22 = 21h-22h) e uma fonte (renovável ou
hidrelétrica), lista TODOS os momentos do ano (dia x cenário) em que alguma usina do subsistema
verteu nessa hora, com:
  usina, MW vertido, CMO da barra da usina (cmgbus), CMO do subsistema (mediana das barras do
  subsistema), CMO do SIN (mediana de todas as barras) e a classificação
  (entre subsistemas / dentro do subsistema / excesso)
e faz as contas que geram os pontos do gráfico:
  painel "CMO no momento em que verteu":  Σ(CMO x MW vertido) ÷ Σ MW vertido
  painel de barras (MW médio por hora):   Σ MW de cada tipo ÷ número de vezes da hora (dias x cenários)

Uso:
  python exemplo_cmo.py "<pasta do caso>" [--subsistema NE] [--hora 22] [--fonte ren|hid] [--ano 2030]
Saída (em <caso>\\resultados_uf\\gargalo_subsistema):
  exemplo_cmo_<SUB>_<hora>h_<fonte>.txt   a explicação com as contas
  exemplo_cmo_<SUB>_<hora>h_<fonte>.csv   todos os momentos (abre no Excel)
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agrega_saidas_uf import mes_ano                                            # noqa: E402
from gargalo_cmo import abrir, bloco, mapear_usinas                             # noqa: E402
from gargalo_subsistema import ler_sistemas                                     # noqa: E402
from graficos_uf import np                                                      # noqa: E402

ROT = {'entre': 'entre subsistemas (vermelho)', 'dentro': 'dentro do subsistema (laranja)',
       'exc': 'excesso (cinza)'}


def br(x, c=1):
    return f'{x:,.{c}f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def main():
    p = argparse.ArgumentParser(description='Exemplo real das contas do gráfico por subsistema.')
    p.add_argument('caso')
    p.add_argument('--subsistema', default='NE')
    p.add_argument('--hora', type=int, default=22, help='hora do dia, 1 a 24 (1 = 00h-01h)')
    p.add_argument('--fonte', default='ren', choices=['ren', 'hid'])
    p.add_argument('--ano', type=int, default=2030)
    p.add_argument('--tolerancia', type=float, default=1.0)
    p.add_argument('--tabelas', default=os.path.dirname(os.path.abspath(__file__)))
    a = p.parse_args()
    sub, hora, tol = a.subsistema.upper(), a.hora, a.tolerancia
    if not 1 <= hora <= 24:
        sys.exit('ERRO: --hora deve ser de 1 a 24')
    saida = os.path.join(a.caso, 'resultados_uf', 'gargalo_subsistema')
    os.makedirs(saida, exist_ok=True)

    print('Abrindo as saídas do SDDP...')
    cmg = abrir(a.caso, 'cmgbus')
    fontes = {'ren': abrir(a.caso, 'vergnd'), 'hid': abrir(a.caso, 'envetu', obrigatorio=a.fonte == 'hid')}
    fontes = {k: v for k, v in fontes.items() if v is not None}
    M = mapear_usinas(a, fontes, cmg)
    barras, col_cmg, ca_cols = M['barras'], M['col_cmg'], M['ca_cols']
    sis = ler_sistemas(a.caso, barras)
    ids = [s[2] for s in sis]
    if sub not in ids:
        sys.exit(f'ERRO: subsistema {sub} não existe. Opções: {", ".join(ids)}')
    k_sub = ids.index(sub)
    nome_sub = sis[k_sub][1]
    sub_barra = {b['nome']: b['subsistema'].upper() for b in barras}
    cols_sub = np.array([col_cmg[b['nome']] for b in barras if sub_barra[b['nome']] == nome_sub.upper()
                         and b['nome'] in col_cmg], dtype=int)
    f_ = a.fonte
    usinas, nome_barra = M['usinas'][f_], M['nome_barra'][f_]
    sel = [j for j, nb in enumerate(nome_barra) if nb and sub_barra.get(nb) == nome_sub.upper()]
    if not sel:
        sys.exit(f'ERRO: nenhuma usina de {f_} com barra no subsistema {sub}')
    cols_v = M['cols_fonte'].get(f_, np.arange(len(usinas)))[sel]
    col_b = np.array([usinas[j][1] for j in sel])
    nomes_u = [usinas[j][0] for j in sel]
    estagios = [e for e in range(cmg['n_estagios']) if mes_ano(cmg, e)[1] == a.ano]
    n_cen = cmg['n_cen']
    print(f'{len(sel)} usinas de {"renováveis (sem GD)" if f_ == "ren" else "hidrelétricas"} no subsistema {sub}; '
          f'{len(cols_sub)} barras no subsistema; hora {hora}; {len(estagios)} meses x {n_cen} cenários')

    linhas = []
    n_vezes = 0
    for e in estagios:
        mes = mes_ano(cmg, e)[0]
        for c in range(n_cen):
            P = bloco(cmg, e, c)
            nh = P.shape[0]
            r = np.arange(hora - 1, nh, 24)                  # linhas da hora escolhida em cada dia do mês
            n_vezes += len(r)
            V = bloco(fontes[f_], e, c)[r][:, cols_v] * 1000.0
            Pr = P[r]
            ref = np.median(Pr[:, ca_cols], axis=1)
            cne = np.median(Pr[:, cols_sub], axis=1)
            for i_d, i_u in zip(*np.nonzero(V > 1e-6)):
                cb = Pr[i_d, col_b[i_u]] if col_b[i_u] >= 0 else cne[i_d]
                if cne[i_d] < ref[i_d] - tol:
                    cl = 'entre'
                elif cb < cne[i_d] - tol:
                    cl = 'dentro'
                else:
                    cl = 'exc'
                linhas.append(dict(mes=mes, dia=int(r[i_d] // 24) + 1, cenario=c + 1, usina=nomes_u[i_u],
                                   mw=float(V[i_d, i_u]), cmo_barra=float(cb), cmo_sub=float(cne[i_d]),
                                   cmo_sin=float(ref[i_d]), classe=cl))
        print(f'  mês {mes}/{a.ano} ok')

    base = f'exemplo_cmo_{sub}_{hora}h_{f_}'
    with open(os.path.join(saida, base + '.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['mes', 'dia', 'cenario', 'usina', 'MW_vertido', 'CMO_barra_usina', f'CMO_{sub}', 'CMO_SIN',
                    'SIN_menos_sub', 'sub_menos_barra', 'classificacao'])
        for l_ in linhas:
            w.writerow([l_['mes'], l_['dia'], l_['cenario'], l_['usina'], round(l_['mw'], 3), round(l_['cmo_barra'], 2),
                        round(l_['cmo_sub'], 2), round(l_['cmo_sin'], 2), round(l_['cmo_sin'] - l_['cmo_sub'], 2),
                        round(l_['cmo_sub'] - l_['cmo_barra'], 2), ROT[l_['classe']]])

    # --- texto com as contas -------------------------------------------------------------
    T = []
    fonte_txt = 'renovável (sem GD)' if f_ == 'ren' else 'hidrelétrico (vertimento turbinável)'
    T.append(f'Subsistema {sub} ({nome_sub}) — vertimento {fonte_txt} — hora {hora} ({hora - 1:02d}h-{hora:02d}h), {a.ano}')
    T.append(f'Vezes que a hora {hora} ocorreu no ano: {n_vezes} (dias x {n_cen} cenários)')
    T.append(f'Momentos usina x dia x cenário com vertimento nessa hora: {len(linhas)} (lista completa em {base}.csv)')
    T.append('')
    if not linhas:
        T.append('Nenhuma usina verteu nessa hora: o ponto não aparece no painel "CMO no momento em que verteu" e a barra é 0.')
    else:
        T.append('1) Os momentos (os 15 com mais MW vertido):')
        T.append(f'{"mês":>3} {"dia":>3} {"cen":>3}  {"usina":<16}{"MW":>9}{"CMO barra":>11}{"CMO " + sub:>9}'
                 f'{"CMO SIN":>9}  classificação')
        for l_ in sorted(linhas, key=lambda l_: -l_['mw'])[:15]:
            T.append(f'{l_["mes"]:>3} {l_["dia"]:>3} {l_["cenario"]:>3}  {l_["usina"][:15]:<16}{br(l_["mw"]):>9}'
                     f'{br(l_["cmo_barra"]):>11}{br(l_["cmo_sub"]):>9}{br(l_["cmo_sin"]):>9}  {ROT[l_["classe"]]}')
        T.append('')
        T.append('   Regra, em cada momento:')
        T.append(f'   CMO do SIN − CMO do {sub} > {tol:g}  → entre subsistemas (vermelho)')
        T.append(f'   senão, CMO do {sub} − CMO da barra > {tol:g}  → dentro do subsistema (laranja)')
        T.append('   senão → excesso (cinza)')
        T.append('')
        mw = np.array([l_['mw'] for l_ in linhas])
        sm = mw.sum()
        T.append('2) Painel "CMO no momento em que verteu" — Σ(CMO × MW vertido) ÷ Σ MW vertido:')
        T.append(f'   Σ MW vertido = {br(sm, 2)} MW')
        for chave, rot in (('cmo_barra', 'barras das usinas que verteram'), ('cmo_sub', f'{sub} nesses momentos'),
                           ('cmo_sin', 'SIN nesses momentos')):
            s_ = float((np.array([l_[chave] for l_ in linhas]) * mw).sum())
            T.append(f'   "{rot}": {br(s_, 1)} ÷ {br(sm, 2)} = {br(s_ / sm, 1)} $/MWh')
        T.append('')
        T.append(f'3) Painel de barras (MW médio na hora {hora}) — Σ MW de cada tipo ÷ {n_vezes} vezes da hora:')
        for cl in ('entre', 'dentro', 'exc'):
            s_ = sum(l_['mw'] for l_ in linhas if l_['classe'] == cl)
            T.append(f'   {ROT[cl]:<32} {br(s_, 1):>12} MW ÷ {n_vezes} = {br(s_ / n_vezes, 2)} MW médio')
        T.append(f'   {"total":<32} {br(sm, 1):>12} MW ÷ {n_vezes} = {br(sm / n_vezes, 2)} MW médio')
        T.append('')
        T.append('Os valores de 2) são os pontos da hora ' + str(hora) + ' no painel "CMO no momento em que o '
                 + ('renovável' if f_ == 'ren' else 'hidrelétrico') + ' do subsistema verteu";')
        T.append('os de 3) são a altura e as cores da barra da hora ' + str(hora) + ' no painel de vertimento.')
    txt = '\n'.join(T)
    with open(os.path.join(saida, base + '.txt'), 'w', encoding='utf-8') as f:
        f.write(txt + '\n')
    print()
    print(txt)
    print(f'\nArquivos: {os.path.join(saida, base)}.txt e .csv')


if __name__ == '__main__':
    main()
