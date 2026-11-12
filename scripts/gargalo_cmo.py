"""Vertimento por gargalo de transmissão x por excesso no sistema, pelo custo marginal.

Ideia: na simulação com rede, se não há limite de transmissão ativo, o custo marginal
(CMO) é o mesmo em todas as barras. Quando um circuito ou uma restrição de intercâmbio
chega ao limite, o CMO se separa: atrás do gargalo ele cai (há energia sobrando que não
consegue sair) e do outro lado fica mais alto.

Para cada hora, cenário e usina com vertimento:
  CMO de referência = mediana do CMO de todas as barras CA naquela hora e cenário;
  diferença         = CMO da barra da usina - CMO de referência;
  GARGALO           = diferença < -tolerância  (a usina está atrás de um limite de rede);
  EXCESSO NO SISTEMA= caso contrário (o CMO é o mesmo do resto do sistema: sobra energia
                      no SIN como um todo, isto é, baixa demanda frente à oferta).

Vertimento analisado:
  - renovável: vergnd (por usina renovável);
  - hidrelétrico: envetu (energia vertida turbinável, por hidrelétrica), se existir.
Também conta, por hora, as restrições de intercâmbio (cmgsuc) e os elos CC (cmglnk) no
limite (custo marginal diferente de zero).

Lê os .bin aos poucos (cmgbus e vergnd têm vários GB).

Uso:
  python gargalo_cmo.py "<pasta do caso>" [--ano 2030] [--tolerancia 1] [--saida <pasta>]
Padrão de saída: <pasta do caso>\\resultados_uf\\gargalo_cmo

Requer numpy e matplotlib; usa agrega_saidas_uf.py, graficos_uf.py e as tabelas
barras_uf.csv, usinas_renovaveis_uf.csv e conexoes_usinas_uf.csv (mesma pasta).
"""
import argparse
import collections
import csv
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agrega_saidas_uf import ler_hdr, mes_ano                                   # noqa: E402
from graficos_uf import ORDEM_UF, REGIAO_DA_UF, MESES, TEXTO, TEXTO2, GRADE, FUNDO, plt, np  # noqa: E402

COR_GARG, COR_SIST = '#e34948', '#8a8984'
FONTES = [('ren', 'vergnd', 'renovável'), ('hid', 'envetu', 'hidrelétrico (vertimento turbinável)')]


# ----------------------------------------------------------------------------
def abrir(caso, nome, obrigatorio=True):
    hdr_p = os.path.join(caso, nome + '.hdr')
    bin_p = os.path.join(caso, nome + '.bin')
    if not (os.path.exists(hdr_p) and os.path.exists(bin_p)):
        if obrigatorio:
            sys.exit(f'ERRO: não achei {nome}.hdr e {nome}.bin em {caso}')
        print(f'  AVISO: {nome}.hdr/.bin não encontrados; essa parte fica de fora')
        return None
    h = ler_hdr(hdr_p)
    n_cen = h['n_cenarios'] if h['varia_cenario'] else 1
    if os.path.getsize(bin_p) != h['horas'][-1] * n_cen * h['n_agentes'] * 4:
        sys.exit(f'ERRO: o tamanho de {nome}.bin não bate com o {nome}.hdr')
    h['n_cen'] = n_cen
    h['dados'] = np.memmap(bin_p, dtype='<f4', mode='r')
    h['nome'] = nome
    return h


def bloco(h, e, c):
    """Matriz horas x agentes do estágio e (0 = primeiro) e cenário c."""
    n_ag, n_cen = h['n_agentes'], h['n_cen']
    h0, h1 = h['horas'][e], h['horas'][e + 1]
    b = h['dados'][h0 * n_cen * n_ag:h1 * n_cen * n_ag].reshape(n_cen, h1 - h0, n_ag)
    return np.asarray(b[min(c, n_cen - 1)], dtype=np.float64)


def hidro_por_unidades(caso):
    """Hidrelétricas ligadas à rede pelas unidades (hydrounit??.dat): nome -> lista de códigos de barra."""
    import glob
    import re
    nomes = {}
    for arq in glob.glob(os.path.join(caso, 'chidro??.dat')):
        sis = arq[-6:-4]
        with open(arq, encoding='latin-1') as f:
            for ln in f:
                if ln[:4].strip().isdigit():
                    nomes[(sis, int(ln[:4]))] = ln[5:17].strip()
    barras = collections.defaultdict(list)
    for arq in glob.glob(os.path.join(caso, 'hydrounit??.dat')):
        sis = re.search(r'hydrounit(..)\.dat$', arq).group(1)
        with open(arq, encoding='latin-1', newline='') as f:
            for r in csv.reader(f):
                if not r or r[0].startswith(('$', '!')):
                    continue
                try:
                    usina, barra = int(r[2]), int(r[3])
                except ValueError:
                    continue
                n = nomes.get((sis, usina))
                if n:
                    barras[n].append(barra)
    return barras


def ler_tab(caminho):
    with open(caminho, encoding='utf-8-sig', newline='') as f:
        primeira = f.readline()
        f.seek(0)
        sep = ';' if primeira.count(';') > primeira.count(',') else ','
        return list(csv.DictReader(f, delimiter=sep))


# ----------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description='Vertimento por gargalo x excesso no sistema (custo marginal).')
    p.add_argument('caso')
    p.add_argument('--ano', type=int, default=2030)
    p.add_argument('--tolerancia', type=float, default=1.0,
                   help='diferença mínima de CMO ($/MWh) para considerar gargalo (padrão 1)')
    p.add_argument('--tabelas', default=os.path.dirname(os.path.abspath(__file__)))
    p.add_argument('--saida')
    a = p.parse_args()
    saida = a.saida or os.path.join(a.caso, 'resultados_uf', 'gargalo_cmo')
    os.makedirs(saida, exist_ok=True)
    tol = a.tolerancia

    print('Abrindo as saídas do SDDP...')
    cmg = abrir(a.caso, 'cmgbus')
    fontes = {'ren': abrir(a.caso, 'vergnd'), 'hid': abrir(a.caso, 'envetu', obrigatorio=False)}
    suc = abrir(a.caso, 'cmgsuc', obrigatorio=False)
    lnk = abrir(a.caso, 'cmglnk', obrigatorio=False)
    for h in [fontes['ren'], fontes['hid'], suc, lnk]:
        if h is not None and (h['horas'] != cmg['horas'] or h['n_cen'] != cmg['n_cen']):
            sys.exit(f'ERRO: {h["nome"]} tem horas/cenários diferentes do cmgbus (são de rodadas diferentes?)')
    estagios = [e for e in range(cmg['n_estagios']) if mes_ano(cmg, e)[1] == a.ano]
    if not estagios:
        anos = sorted({mes_ano(cmg, e)[1] for e in range(cmg['n_estagios'])})
        sys.exit(f'ERRO: a rodada não tem estágios de {a.ano}. Anos disponíveis: {anos}')
    n_cen = cmg['n_cen']
    print(f'Ano {a.ano}: estágios {estagios[0] + 1} a {estagios[-1] + 1}, {n_cen} cenários, '
          f'tolerância {tol} $/MWh')

    # --- tabelas: barra de cada usina -------------------------------------------
    barras = [b for b in ler_tab(os.path.join(a.tabelas, 'barras_uf.csv')) if b['rede'] == 'CA']
    cod_para_nome = {int(b['codigo']): b['nome'] for b in barras}
    uf_barra = {b['nome']: b['uf'] for b in barras}
    col_cmg = {n: i for i, n in enumerate(cmg['nomes'])}
    ca_cols = np.array([col_cmg[n] for n in uf_barra if n in col_cmg])
    usinas = {}   # fonte -> lista de (nome, coluna no cmgbus, uf, tecnologia)
    ren = {u['nome_usina']: u for u in ler_tab(os.path.join(a.tabelas, 'usinas_renovaveis_uf.csv'))}
    lst = []
    for n in fontes['ren']['nomes']:
        u = ren.get(n)
        nb = cod_para_nome.get(int(u['barra'])) if u else None
        lst.append((n, col_cmg.get(nb, -1), u['uf_barra'] if u else '??', u['tecnologia'] if u else '??'))
    usinas['ren'] = lst
    if fontes['hid'] is not None:
        conex = os.path.join(a.tabelas, 'conexoes_usinas_uf.csv')
        hid = collections.defaultdict(list)
        if os.path.exists(conex):
            for r in ler_tab(conex):
                if r['tipo_usina'] == 'H':
                    hid[r['nome_usina']].append(r)
        else:
            print('  AVISO: conexoes_usinas_uf.csv não encontrado; hidrelétricas sem barra')
        por_unidade = hidro_por_unidades(a.caso)
        uf_cod = {int(b['codigo']): b['uf'] for b in barras}
        lst = []
        for n in fontes['hid']['nomes']:
            cods = [int(r['barra']) for r in hid.get(n, [])] or por_unidade.get(n, [])
            cods = [c_ for c_ in cods if c_ in cod_para_nome]
            if cods:
                uf = collections.Counter(uf_cod[c_] for c_ in cods).most_common(1)[0][0]
                nb = cod_para_nome[collections.Counter(cods).most_common(1)[0][0]]
                lst.append((n, col_cmg.get(nb, -1), uf, 'Hidrelétrica'))
            else:
                lst.append((n, -1, '??', 'Hidrelétrica'))
        usinas['hid'] = lst
    for f_, lst in usinas.items():
        sem = sum(1 for x in lst if x[1] < 0)
        if sem:
            sem_n = [x[0] for x in lst if x[1] < 0]
            print(f'  AVISO: {sem} usinas de {fontes[f_]["nome"]} sem barra na rede (contam como excesso no sistema): '
                  f'{", ".join(sem_n[:12])}{" ..." if sem > 12 else ""}')

    # --- acumuladores -------------------------------------------------------------
    ufs = ORDEM_UF
    meses = [mes_ano(cmg, e)[0] for e in estagios]
    acc_m = {f_: np.zeros((2, len(ufs), 12)) for f_ in usinas}               # [causa, uf, mês] MWh
    acc_h = {f_: np.zeros((2, len(ufs), 24)) for f_ in usinas}               # [causa, uf, hora] MWh
    acc_usina = {f_: np.zeros((2, len(usinas[f_]))) for f_ in usinas}
    tec_list = sorted({x[3] for f_ in usinas for x in usinas[f_]})
    acc_tec = {f_: np.zeros((2, len(ufs), len(tec_list))) for f_ in usinas}
    dif_vert = collections.defaultdict(list)    # uf -> diferenças de CMO (amostra) nas horas com vertimento
    n_horas = 0
    ativ_suc = np.zeros((suc['n_agentes'] if suc else 0, 12))
    ativ_lnk = np.zeros((lnk['n_agentes'] if lnk else 0, 12))
    vert_suc = np.zeros(suc['n_agentes'] if suc else 0)    # vertimento BR (MWh) nas horas com a restrição ativa
    horas_mes = np.zeros(12)
    vert_total_h = []                                       # para resumo: vertimento BR por hora
    ref_media = np.zeros(12)
    idx_uf = {f_: np.array([ufs.index(x[2]) if x[2] in ufs else -1 for x in usinas[f_]]) for f_ in usinas}
    idx_tec = {f_: np.array([tec_list.index(x[3]) for x in usinas[f_]]) for f_ in usinas}
    col = {f_: np.array([x[1] for x in usinas[f_]]) for f_ in usinas}
    rng = np.random.default_rng(0)

    t0 = time.time()
    for k, e in enumerate(estagios):
        m = meses[k] - 1
        for c in range(n_cen):
            P = bloco(cmg, e, c)                                     # horas x barras
            ref = np.median(P[:, ca_cols], axis=1)                   # horas
            ref_media[m] += ref.sum()
            nh = P.shape[0]
            hd = np.arange(nh) % 24
            vert_br = np.zeros(nh)
            for f_, h in fontes.items():
                if h is None:
                    continue
                V = bloco(h, e, c) * 1000.0                          # MWh na hora (= MW)
                cc = col[f_]
                Pp = np.where(cc >= 0, P[:, np.clip(cc, 0, None)], ref[:, None])
                dif = Pp - ref[:, None]
                garg = dif < -tol
                vg = np.where(garg, V, 0.0)
                vs = V - vg
                vert_br += V.sum(axis=1)
                for causa, X in ((0, vg), (1, vs)):
                    acc_usina[f_][causa] += X.sum(axis=0)
                    tot_us = X.sum(axis=0)
                    ok = idx_uf[f_] >= 0
                    np.add.at(acc_m[f_][causa], (idx_uf[f_][ok], m), tot_us[ok])
                    np.add.at(acc_tec[f_][causa], (idx_uf[f_][ok], idx_tec[f_][ok]), tot_us[ok])
                    por_hora = np.zeros((len(ufs), 24))
                    Xh = np.zeros((24, X.shape[1]))
                    np.add.at(Xh, hd, X)
                    np.add.at(por_hora, idx_uf[f_][ok], Xh[:, ok].T)
                    acc_h[f_][causa] += por_hora
                if f_ == 'ren':
                    # amostra das diferenças de CMO onde há vertimento (para o box plot)
                    hh, uu = np.nonzero(V > 1e-3)
                    if len(hh):
                        sel = rng.choice(len(hh), size=min(len(hh), 4000), replace=False)
                        for i_h, i_u in zip(hh[sel], uu[sel]):
                            if idx_uf[f_][i_u] >= 0:
                                dif_vert[ufs[idx_uf[f_][i_u]]].append((hd[i_h], dif[i_h, i_u]))
            if suc is not None:
                S = bloco(suc, e, c)
                at = np.abs(S) > 1e-9
                ativ_suc[:, m] += at.sum(axis=0)
                vert_suc += (at * vert_br[:, None]).sum(axis=0)
            if lnk is not None:
                L = bloco(lnk, e, c)
                ativ_lnk[:, m] += (np.abs(L) > 1e-9).sum(axis=0)
            horas_mes[m] += nh
            n_horas += nh
        print(f'  {MESES[m]}/{a.ano} ok - {time.time() - t0:.0f} s')

    # --- saídas: CSV ---------------------------------------------------------------
    nomes_f = {'ren': 'renovavel', 'hid': 'hidro_turbinavel'}
    with open(os.path.join(saida, 'vertimento_causa_uf_mensal.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['uf', 'fonte', 'mes', 'gargalo_GWh', 'excesso_sistema_GWh', 'pct_gargalo'])
        for f_ in acc_m:
            for i, u in enumerate(ufs):
                for mm in range(12):
                    g, s_ = acc_m[f_][0, i, mm] / n_cen / 1000, acc_m[f_][1, i, mm] / n_cen / 1000
                    if g + s_ > 0:
                        w.writerow([u, nomes_f[f_], mm + 1, round(g, 3), round(s_, 3), round(100 * g / (g + s_), 1)])
    with open(os.path.join(saida, 'vertimento_causa_usina.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['usina', 'fonte', 'uf', 'tecnologia', 'gargalo_GWh', 'excesso_sistema_GWh', 'pct_gargalo'])
        for f_ in acc_usina:
            for j, (n, _, u, t) in enumerate(usinas[f_]):
                g, s_ = acc_usina[f_][0, j] / n_cen / 1000, acc_usina[f_][1, j] / n_cen / 1000
                if g + s_ > 1e-6:
                    w.writerow([n, nomes_f[f_], u, t, round(g, 4), round(s_, 4), round(100 * g / (g + s_), 1)])
    with open(os.path.join(saida, 'vertimento_causa_uf_tecnologia.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['uf', 'fonte', 'tecnologia', 'gargalo_GWh', 'excesso_sistema_GWh', 'pct_gargalo'])
        for f_ in acc_tec:
            for i, u in enumerate(ufs):
                for t, tn in enumerate(tec_list):
                    g, s_ = acc_tec[f_][0, i, t] / n_cen / 1000, acc_tec[f_][1, i, t] / n_cen / 1000
                    if g + s_ > 1e-6:
                        w.writerow([u, nomes_f[f_], tn, round(g, 3), round(s_, 3), round(100 * g / (g + s_), 1)])
    if suc is not None:
        with open(os.path.join(saida, 'restricoes_ativas.csv'), 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f)
            w.writerow(['tipo', 'nome'] + [f'pct_horas_{MESES[mm]}' for mm in range(12)] +
                       ['pct_horas_ano', 'vertimento_BR_nessas_horas_GWh'])
            for j, n in enumerate(suc['nomes']):
                w.writerow(['intercâmbio', n] + [round(100 * ativ_suc[j, mm] / max(horas_mes[mm], 1), 2)
                                                 for mm in range(12)] +
                           [round(100 * ativ_suc[j].sum() / n_horas, 2), round(vert_suc[j] / n_cen / 1000, 1)])
            if lnk is not None:
                for j, n in enumerate(lnk['nomes']):
                    w.writerow(['elo CC', n] + [round(100 * ativ_lnk[j, mm] / max(horas_mes[mm], 1), 2)
                                                for mm in range(12)] +
                               [round(100 * ativ_lnk[j].sum() / n_horas, 2), ''])

    # --- gráficos -----------------------------------------------------------------
    fontes_ok = [f_ for f_ in ('ren', 'hid') if f_ in acc_m]

    def fig_uf(nome, i_uf):
        sel = (lambda X: X[:, i_uf]) if i_uf is not None else (lambda X: X.sum(axis=1))
        nlin = len(fontes_ok) * 2 + (1 if dif_vert else 0)
        fig, axs = plt.subplots(nlin, 1, figsize=(11, 2.9 * nlin + 0.6))
        axs = np.atleast_1d(axs)
        k = 0
        for f_ in fontes_ok:
            rot = dict((x[0], x[2]) for x in FONTES)[f_]
            M = sel(acc_m[f_]) / n_cen / 1000                     # [causa, mês] GWh
            ax = axs[k]
            x = np.arange(12)
            ax.bar(x, M[0], color=COR_GARG, width=0.7, label='gargalo de transmissão', edgecolor=FUNDO, linewidth=1)
            ax.bar(x, M[1], bottom=M[0], color=COR_SIST, width=0.7, label='excesso no sistema (baixa demanda)',
                   edgecolor=FUNDO, linewidth=1)
            tot = M.sum()
            pct = 100 * M[0].sum() / tot if tot > 0 else 0
            ax.set_title(f'Vertimento {rot} por mês (GWh) — {tot:,.0f} GWh no ano, {pct:.0f}% por gargalo'
                         .replace(',', '.'), loc='left', fontsize=10)
            ax.set_xticks(x, MESES)
            ax.set_ylabel('GWh')
            k += 1
            H = sel(acc_h[f_]) / (n_horas / 24)                    # MW médio por hora do dia
            ax = axs[k]
            hh = np.arange(1, 25)
            ax.bar(hh, H[0], color=COR_GARG, width=0.75, edgecolor=FUNDO, linewidth=1)
            ax.bar(hh, H[1], bottom=H[0], color=COR_SIST, width=0.75, edgecolor=FUNDO, linewidth=1)
            ax.set_title(f'Vertimento {rot} médio por hora do dia (MW)', loc='left', fontsize=10)
            ax.set_xticks(hh, [str(v) if v % 2 else '' for v in hh])
            ax.set_ylabel('MW')
            k += 1
        if dif_vert:
            ax = axs[k]
            amostra = dif_vert.get(nome, []) if i_uf is not None else [v for l_ in dif_vert.values() for v in l_]
            if amostra:
                hs = np.array([x[0] for x in amostra])
                ds = np.array([x[1] for x in amostra])
                ax.boxplot([ds[hs == h] if (hs == h).any() else [np.nan] for h in range(24)], positions=range(1, 25),
                           widths=0.6, whis=(5, 95), showfliers=False, patch_artist=True, manage_ticks=False,
                           boxprops=dict(facecolor=COR_GARG + '44', edgecolor=COR_GARG),
                           whiskerprops=dict(color=COR_GARG), capprops=dict(color=COR_GARG),
                           medianprops=dict(color=TEXTO, linewidth=1.4))
                ax.axhline(0, color=TEXTO2, linewidth=0.8)
                ax.axhline(-tol, color=TEXTO, linewidth=1, linestyle='--')
            ax.set_title('Diferença de CMO da barra da usina em relação ao SIN, nas horas com vertimento renovável '
                         '($/MWh) — abaixo do tracejado = gargalo', loc='left', fontsize=9.5)
            ax.set_xticks(range(1, 25), [str(v) if v % 2 else '' for v in range(1, 25)])
            ax.set_xlim(0.3, 24.7)
            ax.set_ylabel('$/MWh')
        for ax in axs:
            ax.grid(axis='y', color=GRADE, linewidth=0.6)
            ax.set_axisbelow(True)
        axs[-1].set_xlabel('Hora do dia (1 = 00h-01h)')
        titulo = 'Brasil' if i_uf is None else f'{nome} ({REGIAO_DA_UF.get(nome, "")})'
        fig.suptitle(f'{titulo} — vertimento por gargalo de transmissão × excesso no sistema, {a.ano}', x=0.01,
                     ha='left', fontsize=13, fontweight='bold')
        from matplotlib.patches import Patch
        fig.legend(handles=[Patch(color=COR_GARG, label='gargalo de transmissão'),
                            Patch(color=COR_SIST, label='excesso no sistema (baixa demanda)')],
                   loc='upper right', ncol=2, fontsize=9, frameon=False, bbox_to_anchor=(0.995, 0.985))
        fig.text(0.01, 0.004, f'Gargalo = CMO da barra da usina mais de {tol:g} $/MWh abaixo da mediana do CMO das '
                 f'barras do SIN na mesma hora e cenário. Média de {n_cen} cenários.', fontsize=7.5, color=TEXTO2)
        fig.tight_layout(rect=(0, 0.015, 1, 0.955))
        fig.savefig(os.path.join(saida, f'gargalo_{nome}.png'), dpi=120)
        plt.close(fig)

    tot_uf = {u: sum(acc_m[f_][:, i].sum() for f_ in fontes_ok) for i, u in enumerate(ufs)}
    for i, u in enumerate(ufs):
        if tot_uf[u] > 0:
            fig_uf(u, i)
    fig_uf('BR', None)

    # resumo por estado
    lista = sorted([u for u in ufs if tot_uf[u] / n_cen / 1000 >= 1], key=lambda u: tot_uf[u])
    if lista:
        fig, axs = plt.subplots(1, len(fontes_ok), figsize=(8 * len(fontes_ok), 0.38 * len(lista) + 2.2),
                                squeeze=False)
        for ax, f_ in zip(axs[0], fontes_ok):
            y = np.arange(len(lista))
            g = np.array([acc_m[f_][0, ufs.index(u)].sum() for u in lista]) / n_cen / 1000
            s_ = np.array([acc_m[f_][1, ufs.index(u)].sum() for u in lista]) / n_cen / 1000
            ax.barh(y, g, color=COR_GARG, height=0.7, label='gargalo de transmissão', edgecolor=FUNDO)
            ax.barh(y, s_, left=g, color=COR_SIST, height=0.7, label='excesso no sistema', edgecolor=FUNDO)
            for kk in range(len(lista)):
                t = g[kk] + s_[kk]
                if t > 0:
                    ax.text(t, kk, f'  {100 * g[kk] / t:.0f}% gargalo', va='center', fontsize=7.5, color=TEXTO2)
            ax.set_yticks(y, lista)
            ax.set_xlabel('GWh no ano (média dos cenários)')
            ax.set_title(f'Vertimento {dict((x[0], x[2]) for x in FONTES)[f_]}', loc='left', fontsize=10)
            ax.grid(axis='x', color=GRADE, linewidth=0.6)
            ax.set_axisbelow(True)
            ax.legend(loc='lower right', fontsize=8, frameon=False)
        fig.suptitle(f'Vertimento por causa e estado, {a.ano}', x=0.01, ha='left', fontsize=13, fontweight='bold')
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        fig.savefig(os.path.join(saida, 'gargalo_resumo.png'), dpi=130)
        plt.close(fig)

    # restrições de intercâmbio e elos CC no limite
    if suc is not None:
        linhas = [('intercâmbio', n, ativ_suc[j]) for j, n in enumerate(suc['nomes'])]
        if lnk is not None:
            linhas += [('elo CC', n, ativ_lnk[j]) for j, n in enumerate(lnk['nomes'])]
        linhas = [l_ for l_ in linhas if l_[2].sum() > 0]
        if linhas:
            Mx = np.array([100 * l_[2] / np.maximum(horas_mes, 1) for l_ in linhas])
            from matplotlib.colors import LinearSegmentedColormap
            cmap = LinearSegmentedColormap.from_list('seq', [FUNDO, '#e34948', '#5a1414'])
            fig, ax = plt.subplots(figsize=(11, 0.36 * len(linhas) + 2))
            im = ax.imshow(Mx, aspect='auto', cmap=cmap, vmin=0, vmax=max(Mx.max(), 1), interpolation='nearest')
            for i in range(Mx.shape[0]):
                for j in range(12):
                    if horas_mes[j]:
                        ax.text(j, i, f'{Mx[i, j]:.0f}', ha='center', va='center', fontsize=7,
                                color=FUNDO if Mx[i, j] > 0.6 * Mx.max() else TEXTO)
            ax.set_yticks(range(len(linhas)), [f'{l_[1]} ({l_[0]})' for l_ in linhas], fontsize=8)
            ax.set_xticks(range(12), MESES)
            for sp in ax.spines.values():
                sp.set_visible(False)
            cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
            cb.outline.set_visible(False)
            ax.set_title(f'% das horas (média dos cenários) em que cada restrição está no limite, {a.ano}',
                         loc='left', fontsize=10)
            fig.text(0.01, 0.005, 'No limite = custo marginal da restrição (cmgsuc) ou do elo CC (cmglnk) diferente '
                     'de zero.', fontsize=8, color=TEXTO2)
            fig.tight_layout(rect=(0, 0.02, 1, 1))
            fig.savefig(os.path.join(saida, 'restricoes_ativas.png'), dpi=130)
            plt.close(fig)

    for f_ in fontes_ok:
        g, s_ = acc_m[f_][0].sum() / n_cen / 1000, acc_m[f_][1].sum() / n_cen / 1000
        print(f'Brasil, vertimento {nomes_f[f_]}: {g + s_:,.0f} GWh, {100 * g / max(g + s_, 1e-9):.1f}% por gargalo')
    print('Fim. Arquivos em', saida)


if __name__ == '__main__':
    main()
