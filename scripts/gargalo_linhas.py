"""Quais linhas e transformadores ficam no limite nas horas com vertimento por gargalo.

Usa os fluxos do SDDP (acline_flow e transformer_flow) e os limites da rede do deck
(Rating das linhas em dcirc/mcirc, Rn dos transformadores em dtrans/mtrans, situação em
circstatus/transtatus) no ano analisado.

Para cada hora e cenário:
  carregamento = |fluxo| / limite;
  NO LIMITE    = circuito MONITORADO com carregamento >= 99% (opção --carregamento);
                 o lado "preso" é a barra de custo marginal (cmgbus) mais baixo; se a
                 diferença de custo marginal entre as duas barras passa da tolerância, o
                 limite está separando preços (gargalo efetivo);
  SOBRECARGA   = circuito NÃO monitorado com carregamento > 100% (o SDDP não limita esses
                 circuitos: é um gargalo que a simulação não representa).

Para cada circuito no limite também soma o vertimento por gargalo (de gargalo_cmo.py) do
estado do lado preso, nas horas em que o circuito estava no limite. Como vários circuitos
podem estar no limite na mesma hora, esse valor indica coincidência, não é uma divisão
exclusiva do vertimento entre os circuitos.

Antes, rode gargalo_cmo.py (ele grava vertimento_gargalo_uf_horario.csv).

Uso:
  python gargalo_linhas.py "<pasta do caso>" [--ano 2030] [--carregamento 99] [--tolerancia 1]
Padrão de saída: <pasta do caso>\\resultados_uf\\gargalo_linhas
"""
import argparse
import collections
import csv
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agrega_saidas_uf import mes_ano                                            # noqa: E402
from limites_uf import ler, situacao, em_operacao, SEM_LIMITE                   # noqa: E402
from limites_uf import num as numero                                            # noqa: E402
from gargalo_cmo import abrir, bloco, ler_tab                                   # noqa: E402
from graficos_uf import ORDEM_UF, MESES, TEXTO, TEXTO2, GRADE, FUNDO, plt, np   # noqa: E402

COR_LIM, COR_SOBRE = '#e34948', '#eda100'


def circuitos_do_ano(caso, ano):
    """{('linha'|'trafo', nome): dict(codigo, de, para, limite, mon, opera)} na rede de 1/1 do ano."""
    data = datetime.date(ano, 1, 1)
    out = {}

    def montar(tipo, base_arq, mod_arq, st_arq, i_lim_base, i_mon_base, i_lim_mod, i_exist, i_desat):
        elem = {}
        for r in ler(os.path.join(caso, base_arq)):
            elem[int(r[0])] = dict(nome=r[1].strip(), de=int(r[2]), para=int(r[3]), exist=int(r[i_exist]),
                                   desat=int(r[i_desat]), limite=numero(r[i_lim_base]),
                                   mon=int(r[i_mon_base]) if len(r) > i_mon_base and r[i_mon_base] else 0)
        for r in sorted(ler(os.path.join(caso, mod_arq)), key=lambda r: (int(r[2]), int(r[1]), int(r[0]))):
            if datetime.date(int(r[2]), int(r[1]), int(r[0])) > data:
                continue
            e = elem.setdefault(int(r[3]), dict(nome=r[4].strip(), mon=0))
            e.update(de=int(r[5]), para=int(r[6]), exist=int(r[7]), desat=int(r[8]), limite=numero(r[i_lim_mod]))
        st = situacao(os.path.join(caso, st_arq), data)
        for cod, e in elem.items():
            e['codigo'] = cod
            e['opera'] = e.get('exist', 1) == 0 and e.get('desat', 0) == 0 and em_operacao(st, cod)
            out[(tipo, e['nome'])] = e

    montar('linha', 'dcirc.dat', 'mcirc.dat', 'circstatus_b004m.dat', 11, 14, 12, 6, 7)
    montar('trafo', 'dtrans.dat', 'mtrans.dat', 'transtatus_b004m.dat', 14, 28, 14, 7, 8)
    return out


def ler_horario_sddp(caminho):
    """CSV no formato do SDDP -> {(estágio, cenário): matriz horas x UF} e lista de UFs."""
    with open(caminho, encoding='latin-1') as f:
        linhas = f.readlines()
    ufs = [c.strip() for c in linhas[3].split(',')][3:]
    dados = np.loadtxt(linhas[4:], delimiter=',', ndmin=2)
    out = {}
    for (e, c) in sorted({(int(a), int(b)) for a, b in dados[:, :2]}):
        m = (dados[:, 0] == e) & (dados[:, 1] == c)
        bloco_ = dados[m]
        out[(e - 1, c - 1)] = bloco_[np.argsort(bloco_[:, 2])][:, 3:]
    return out, ufs


def main():
    p = argparse.ArgumentParser(description='Linhas e transformadores no limite nas horas com vertimento.')
    p.add_argument('caso')
    p.add_argument('--ano', type=int, default=2030)
    p.add_argument('--carregamento', type=float, default=99.0, help='%% do limite para considerar "no limite"')
    p.add_argument('--tolerancia', type=float, default=1.0, help='diferença de custo marginal ($/MWh)')
    p.add_argument('--tabelas', default=os.path.dirname(os.path.abspath(__file__)))
    p.add_argument('--gargalo', help='pasta com vertimento_gargalo_uf_horario.csv (padrão: '
                                     '<caso>\\resultados_uf\\gargalo_cmo)')
    p.add_argument('--saida')
    p.add_argument('--top', type=int, default=30, help='quantos circuitos mostrar nos gráficos')
    a = p.parse_args()
    saida = a.saida or os.path.join(a.caso, 'resultados_uf', 'gargalo_linhas')
    os.makedirs(saida, exist_ok=True)
    lim_frac = a.carregamento / 100

    print('Abrindo as saídas do SDDP...')
    fl = {'linha': abrir(a.caso, 'acline_flow'), 'trafo': abrir(a.caso, 'transformer_flow', obrigatorio=False)}
    cmg = abrir(a.caso, 'cmgbus')
    ref = fl['linha']
    for h in [fl['trafo'], cmg]:
        if h is not None and (h['horas'] != ref['horas'] or h['n_cen'] != ref['n_cen']):
            sys.exit(f'ERRO: {h["nome"]} tem horas/cenários diferentes do acline_flow (rodadas diferentes?)')
    estagios = [e for e in range(ref['n_estagios']) if mes_ano(ref, e)[1] == a.ano]
    if not estagios:
        sys.exit(f'ERRO: a rodada não tem estágios de {a.ano}')
    n_cen = ref['n_cen']

    arq_g = os.path.join(a.gargalo or os.path.join(a.caso, 'resultados_uf', 'gargalo_cmo'),
                         'vertimento_gargalo_uf_horario.csv')
    if os.path.exists(arq_g):
        G, ufs_g = ler_horario_sddp(arq_g)
        print('Vertimento por gargalo:', arq_g)
    else:
        G, ufs_g = {}, []
        print(f'  AVISO: não achei {arq_g}; rode antes o gargalo_cmo.py. Sigo sem o vertimento coincidente.')

    lista_uf = list(ORDEM_UF) + ['??']
    iuf = {u: i for i, u in enumerate(lista_uf)}
    g_col = np.array([ufs_g.index(u) if u in ufs_g else -1 for u in lista_uf])   # UF -> coluna em G
    barras = [b for b in ler_tab(os.path.join(a.tabelas, 'barras_uf.csv')) if b['rede'] == 'CA']
    uf_cod = {int(b['codigo']): b['uf'] for b in barras}
    nome_cod = {int(b['codigo']): b['nome'] for b in barras}
    col_cmg = {n: i for i, n in enumerate(cmg['nomes'])}
    circ = circuitos_do_ano(a.caso, a.ano)

    # --- elementos de cada arquivo de fluxo ---------------------------------------
    elems = {}
    for tipo, h in fl.items():
        if h is None:
            continue
        info = []
        faltam = 0
        for n in h['nomes']:
            c = circ.get((tipo, n))
            if c is None:
                faltam += 1
                info.append(None)
                continue
            info.append(c)
        if faltam:
            print(f'  AVISO: {faltam} {tipo}s de {h["nome"]} sem cadastro no deck (ignorados)')
        lim = np.array([c['limite'] if c and c['opera'] and 0 < c['limite'] < SEM_LIMITE else np.nan for c in info])
        mon = np.array([bool(c and c['mon'] == 1) for c in info])
        cde = np.array([col_cmg.get(nome_cod.get(c['de'], ''), -1) if c else -1 for c in info])
        cpa = np.array([col_cmg.get(nome_cod.get(c['para'], ''), -1) if c else -1 for c in info])
        ufde = [uf_cod.get(c['de'], '??') if c else '??' for c in info]
        ufpa = [uf_cod.get(c['para'], '??') if c else '??' for c in info]
        elems[tipo] = dict(h=h, info=info, lim=lim, mon=mon, cde=cde, cpa=cpa, ufde=ufde, ufpa=ufpa,
                           ide=np.array([iuf.get(u, iuf['??']) for u in ufde]),
                           ipa=np.array([iuf.get(u, iuf['??']) for u in ufpa]))
        print(f'  {h["nome"]}: {len(info)} {tipo}s, {np.isfinite(lim).sum()} com limite, '
              f'{int((mon & np.isfinite(lim)).sum())} monitorados')

    # --- acumuladores ---------------------------------------------------------------
    acc = {}
    for tipo, E in elems.items():
        n = len(E['info'])
        acc[tipo] = dict(h_lim=np.zeros((n, 12)), h_sep=np.zeros(n), h_sobre=np.zeros((n, 12)),
                         cmax=np.zeros(n), vert=np.zeros(n), lado_baixo=np.zeros((n, len(lista_uf))))
    horas_mes = np.zeros(12)
    uf_garg_horas = collections.Counter()      # UF -> horas com vertimento por gargalo
    uf_garg_com_linha = collections.Counter()  # UF -> horas com vertimento por gargalo e algum circuito da UF no limite
    t0 = time.time()
    for e in estagios:
        m = mes_ano(ref, e)[0] - 1
        for c in range(n_cen):
            P = bloco(cmg, e, c)
            Gb = G.get((e, c))
            nh = P.shape[0]
            horas_mes[m] += nh
            uf_com_limite = np.zeros((nh, len(lista_uf)), dtype=bool)
            for tipo, E in elems.items():
                F = np.abs(bloco(E['h'], e, c))
                car = F / E['lim']                                    # NaN onde não há limite
                A = acc[tipo]
                with np.errstate(invalid='ignore'):
                    A['cmax'] = np.fmax(A['cmax'], np.nanmax(np.where(np.isfinite(car), car, -np.inf), axis=0))
                    no_lim = (car >= lim_frac) & E['mon']
                    sobre = (car > 1.0) & ~E['mon']
                A['h_lim'][:, m] += no_lim.sum(axis=0)
                A['h_sobre'][:, m] += sobre.sum(axis=0)
                hh, kk = np.nonzero(no_lim)
                if len(hh):
                    pde = np.where(E['cde'][kk] >= 0, P[hh, np.clip(E['cde'][kk], 0, None)], np.nan)
                    ppa = np.where(E['cpa'][kk] >= 0, P[hh, np.clip(E['cpa'][kk], 0, None)], np.nan)
                    sep = np.abs(pde - ppa) > a.tolerancia
                    np.add.at(A['h_sep'], kk[sep], 1)
                    baixo = np.where(pde <= ppa, E['ide'][kk], E['ipa'][kk])      # UF do lado preso
                    np.add.at(A['lado_baixo'], (kk, baixo), 1)
                    uf_com_limite[hh, E['ide'][kk]] = True
                    uf_com_limite[hh, E['ipa'][kk]] = True
                    if Gb is not None:
                        gc = g_col[baixo]
                        ok = sep & (gc >= 0)
                        np.add.at(A['vert'], kk[ok], Gb[hh[ok], gc[ok]])
            if Gb is not None:
                for j, uf in enumerate(ufs_g):
                    tem = Gb[:, j] > 1e-6
                    uf_garg_horas[uf] += int(tem.sum())
                    if uf in iuf:
                        uf_garg_com_linha[uf] += int((tem & uf_com_limite[:, iuf[uf]]).sum())
        print(f'  {MESES[m]}/{a.ano} ok - {time.time() - t0:.0f} s')

    n_horas = horas_mes.sum()
    # --- CSV --------------------------------------------------------------------------
    linhas = []
    for tipo, E in elems.items():
        A = acc[tipo]
        for k, cinfo in enumerate(E['info']):
            if cinfo is None or not np.isfinite(E['lim'][k]):
                continue
            hl, hs = A['h_lim'][k].sum(), A['h_sobre'][k].sum()
            if hl == 0 and hs == 0:
                continue
            lado = lista_uf[int(A['lado_baixo'][k].argmax())] if A['lado_baixo'][k].sum() else ''
            linhas.append(dict(tipo='linha' if tipo == 'linha' else 'transformador', nome=cinfo['nome'],
                               codigo=cinfo['codigo'], uf_de=E['ufde'][k], uf_para=E['ufpa'][k],
                               limite_MW=E['lim'][k], monitorado=int(E['mon'][k]),
                               pct_horas_no_limite=100 * hl / n_horas,
                               pct_horas_separando_precos=100 * A['h_sep'][k] / n_horas,
                               pct_horas_sobrecarga=100 * hs / n_horas, carregamento_max_pct=100 * A['cmax'][k],
                               uf_lado_preso=lado, vertimento_gargalo_coincidente_GWh=A['vert'][k] / n_cen / 1000,
                               meses=[100 * A['h_lim'][k][mm] / max(horas_mes[mm], 1) for mm in range(12)],
                               meses_sobre=[100 * A['h_sobre'][k][mm] / max(horas_mes[mm], 1) for mm in range(12)]))
    cab = ['tipo', 'nome', 'codigo', 'uf_de', 'uf_para', 'limite_MW', 'monitorado', 'pct_horas_no_limite',
           'pct_horas_separando_precos', 'pct_horas_sobrecarga', 'carregamento_max_pct', 'uf_lado_preso',
           'vertimento_gargalo_coincidente_GWh']
    with open(os.path.join(saida, 'circuitos_no_limite.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(cab + [f'pct_horas_no_limite_{MESES[mm]}' for mm in range(12)] +
                   [f'pct_horas_sobrecarga_{MESES[mm]}' for mm in range(12)])
        for l_ in sorted(linhas, key=lambda l_: (-l_['vertimento_gargalo_coincidente_GWh'], -l_['pct_horas_no_limite'],
                                                  -l_['pct_horas_sobrecarga'])):
            w.writerow([round(l_[k], 3) if isinstance(l_[k], float) else l_[k] for k in cab] +
                       [round(x, 2) for x in l_['meses']] + [round(x, 2) for x in l_['meses_sobre']])
    with open(os.path.join(saida, 'gargalos_por_uf.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['uf', 'circuitos_monitorados_no_limite', 'circuitos_nao_monitorados_sobrecarga',
                    'horas_com_vertimento_por_gargalo', 'pct_dessas_horas_com_circuito_da_uf_no_limite'])
        for uf in ORDEM_UF:
            nl = sum(1 for l_ in linhas if l_['monitorado'] and l_['pct_horas_no_limite'] > 0 and uf in (l_['uf_de'], l_['uf_para']))
            ns = sum(1 for l_ in linhas if not l_['monitorado'] and l_['pct_horas_sobrecarga'] > 0 and uf in (l_['uf_de'], l_['uf_para']))
            hg = uf_garg_horas.get(uf, 0)
            w.writerow([uf, nl, ns, hg, round(100 * uf_garg_com_linha.get(uf, 0) / hg, 1) if hg else ''])

    # --- gráficos -----------------------------------------------------------------------
    def barras_top(sel, chave, titulo, rot_x, cor, arquivo, extra):
        sel = sorted(sel, key=lambda l_: l_[chave], reverse=True)[:a.top]
        if not sel:
            return
        sel = sel[::-1]
        fig, axs = plt.subplots(1, 2, figsize=(17, 0.34 * len(sel) + 2.2), gridspec_kw=dict(width_ratios=[1, 1.25]))
        y = np.arange(len(sel))
        ax = axs[0]
        ax.barh(y, [l_[chave] for l_ in sel], color=cor, height=0.7)
        for k, l_ in enumerate(sel):
            ax.text(l_[chave], k, '  ' + extra(l_), va='center', fontsize=7, color=TEXTO2)
        ax.set_yticks(y, [f'{l_["nome"][:34]} ({l_["uf_de"]}-{l_["uf_para"]})' for l_ in sel], fontsize=7.5)
        ax.set_xlabel(rot_x)
        ax.grid(axis='x', color=GRADE, linewidth=0.6)
        ax.set_axisbelow(True)
        import textwrap
        sub = titulo.split(' — ', 1)[1] if ' — ' in titulo else rot_x
        ax.set_title('\n'.join(textwrap.wrap(sub[0].upper() + sub[1:], 70)), loc='left', fontsize=9.5)
        ax = axs[1]
        mk = 'meses' if 'sobre' not in arquivo else 'meses_sobre'
        Mx = np.array([l_[mk] for l_ in sel])
        from matplotlib.colors import LinearSegmentedColormap
        cmap = LinearSegmentedColormap.from_list('seq', [FUNDO, cor, '#3a1010'])
        im = ax.imshow(Mx, aspect='auto', cmap=cmap, vmin=0, vmax=max(Mx.max(), 1), interpolation='nearest')
        for i in range(Mx.shape[0]):
            for j in range(12):
                if horas_mes[j] and Mx[i, j] >= 0.5:
                    ax.text(j, i, f'{Mx[i, j]:.0f}', ha='center', va='center', fontsize=6.5,
                            color=FUNDO if Mx[i, j] > 0.6 * Mx.max() else TEXTO)
        ax.set_yticks([])
        ax.set_xticks(range(12), MESES)
        for sp in ax.spines.values():
            sp.set_visible(False)
        cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
        cb.outline.set_visible(False)
        ax.set_title('% das horas de cada mês (média dos cenários)', loc='left', fontsize=10)
        fig.suptitle(f'{titulo.split(" —")[0]}, {a.ano}', x=0.01, ha='left', fontsize=13, fontweight='bold')
        fig.tight_layout(rect=(0, 0, 1, 1 - 0.5 / fig.get_figheight()))
        fig.savefig(os.path.join(saida, arquivo), dpi=130)
        plt.close(fig)

    mon_lim = [l_ for l_ in linhas if l_['monitorado'] and l_['pct_horas_no_limite'] > 0]
    barras_top([l_ for l_ in mon_lim if l_['vertimento_gargalo_coincidente_GWh'] > 0],
               'vertimento_gargalo_coincidente_GWh',
               'Circuitos monitorados no limite com mais vertimento por gargalo — vertimento do lado preso nas horas '
               'em que o circuito estava no limite', 'GWh no ano (média dos cenários)', COR_LIM,
               'circuitos_vertimento.png',
               lambda l_: f'{l_["pct_horas_no_limite"]:.1f}% das horas no limite · lado preso: {l_["uf_lado_preso"]}'
               .replace('.', ','))
    barras_top(mon_lim, 'pct_horas_no_limite',
               f'Circuitos monitorados mais tempo no limite (≥ {a.carregamento:g}% do limite)',
               '% das horas do ano', COR_LIM, 'circuitos_horas_no_limite.png',
               lambda l_: f'limite {l_["limite_MW"]:,.0f} MW · lado preso: {l_["uf_lado_preso"]}'.replace(',', '.'))
    barras_top([l_ for l_ in linhas if not l_['monitorado'] and l_['pct_horas_sobrecarga'] > 0],
               'pct_horas_sobrecarga',
               'Circuitos NÃO monitorados acima de 100% do limite — gargalos que o SDDP não limita',
               '% das horas do ano', COR_SOBRE, 'circuitos_sobrecarga_nao_monitorados.png',
               lambda l_: f'máx. {l_["carregamento_max_pct"]:.0f}% · limite {l_["limite_MW"]:,.0f} MW'.replace(',', '.'))

    print(f'Circuitos monitorados que chegaram ao limite: {len(mon_lim)}')
    print(f'Circuitos não monitorados com sobrecarga: '
          f'{sum(1 for l_ in linhas if not l_["monitorado"] and l_["pct_horas_sobrecarga"] > 0)}')
    print('Fim. Arquivos em', saida)


if __name__ == '__main__':
    main()
