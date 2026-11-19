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
  - renovável: vergnd (por usina renovável), SEM a geração distribuída (usinas MMGD = GD solar e
    OMGD = outras GD), que na operação real não é cortada;
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
from _base import pasta_base  # noqa: E402
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agrega_saidas_uf import ler_hdr, mes_ano                                   # noqa: E402
from graficos_uf import ORDEM_UF, REGIAO_DA_UF, MESES, TEXTO, TEXTO2, GRADE, FUNDO, plt, np  # noqa: E402

COR_GARG, COR_SIST = '#e34948', '#8a8984'
FONTES = [('ren', 'vergnd', 'renovável (sem GD)'), ('hid', 'envetu', 'hidrelétrico (vertimento turbinável)')]


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


def mapear_usinas(a, fontes, cmg):
    """Barra de cada usina com vertimento (vergnd sem a GD; envetu) e colunas do cmgbus.
    Devolve dict com barras, cod_para_nome, uf_barra, col_cmg, ca_cols, cols_por_uf, usinas
    (fonte -> lista de (nome, coluna no cmgbus, uf, tecnologia)), cols_fonte (colunas do .bin usadas)
    e nome_barra (fonte -> nome da barra de cada usina, ou None)."""
    barras = [b for b in ler_tab(os.path.join(a.tabelas, 'barras_uf.csv')) if b['rede'] == 'CA']
    cod_para_nome = {int(b['codigo']): b['nome'] for b in barras}
    uf_barra = {b['nome']: b['uf'] for b in barras}
    col_cmg = {n: i for i, n in enumerate(cmg['nomes'])}
    ca_cols = np.array([col_cmg[n] for n in uf_barra if n in col_cmg])
    cols_por_uf = {u: np.array([col_cmg[n] for n, uu in uf_barra.items() if uu == u and n in col_cmg])
                   for u in ORDEM_UF}
    usinas = {}   # fonte -> lista de (nome, coluna no cmgbus, uf, tecnologia)
    ren = {u['nome_usina']: u for u in ler_tab(os.path.join(a.tabelas, 'usinas_renovaveis_uf.csv'))}
    lst, barra_ren = [], []
    for n in fontes['ren']['nomes']:
        u = ren.get(n)
        nb = cod_para_nome.get(int(u['barra'])) if u else None
        lst.append((n, col_cmg.get(nb, -1), u['uf_barra'] if u else '??', u['tecnologia'] if u else '??'))
        barra_ren.append(nb)
    # a geração distribuída (MMGD = GD solar, OMGD = outras GD) fica fora da conta de gargalo x excesso:
    # na operação real ela está atrás do medidor e não é cortada (no deck ela só tem custo de corte 11 $/MWh)
    eh_gd = [x[3] in ('GD Solar', 'Outras GD') or x[0].strip().upper().startswith(('MMGD', 'OMGD')) for x in lst]
    cols_fonte = {'ren': np.array([i for i, g in enumerate(eh_gd) if not g], dtype=int)}
    usinas['ren'] = [x for x, g in zip(lst, eh_gd) if not g]
    nome_barra = {'ren': [b_ for b_, g in zip(barra_ren, eh_gd) if not g]}
    print(f'  {sum(eh_gd)} usinas de geração distribuída (MMGD/OMGD) fora da conta de gargalo x excesso')
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
        lst, barra_hid = [], []
        for n in fontes['hid']['nomes']:
            cods = [int(r['barra']) for r in hid.get(n, [])] or por_unidade.get(n, [])
            cods = [c_ for c_ in cods if c_ in cod_para_nome]
            if cods:
                uf = collections.Counter(uf_cod[c_] for c_ in cods).most_common(1)[0][0]
                nb = cod_para_nome[collections.Counter(cods).most_common(1)[0][0]]
                lst.append((n, col_cmg.get(nb, -1), uf, 'Hidrelétrica'))
                barra_hid.append(nb)
            else:
                lst.append((n, -1, '??', 'Hidrelétrica'))
                barra_hid.append(None)
        usinas['hid'] = lst
        nome_barra['hid'] = barra_hid
    for f_, lst in usinas.items():
        sem = sum(1 for x in lst if x[1] < 0)
        if sem:
            sem_n = [x[0] for x in lst if x[1] < 0]
            print(f'  AVISO: {sem} usinas de {fontes[f_]["nome"]} sem barra na rede (contam como excesso no sistema): '
                  f'{", ".join(sem_n[:12])}{" ..." if sem > 12 else ""}')

    return dict(barras=barras, cod_para_nome=cod_para_nome, uf_barra=uf_barra, col_cmg=col_cmg, ca_cols=ca_cols,
                cols_por_uf=cols_por_uf, usinas=usinas, cols_fonte=cols_fonte, nome_barra=nome_barra)


# ----------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description='Vertimento por gargalo x excesso no sistema (custo marginal).')
    p.add_argument('caso')
    p.add_argument('--ano', type=int, default=2030)
    p.add_argument('--tolerancia', type=float, default=1.0,
                   help='diferença mínima de CMO ($/MWh) para considerar gargalo (padrão 1)')
    p.add_argument('--tabelas', default=pasta_base())
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
    M = mapear_usinas(a, fontes, cmg)
    ca_cols, cols_por_uf, usinas, cols_fonte = M['ca_cols'], M['cols_por_uf'], M['usinas'], M['cols_fonte']

    # --- acumuladores -------------------------------------------------------------
    ufs = ORDEM_UF
    meses = [mes_ano(cmg, e)[0] for e in estagios]
    acc_m = {f_: np.zeros((2, len(ufs), 12)) for f_ in usinas}               # [causa, uf, mês] MWh
    acc_h = {f_: np.zeros((2, len(ufs), 24)) for f_ in usinas}               # [causa, uf, hora] MWh
    acc_usina = {f_: np.zeros((2, len(usinas[f_]))) for f_ in usinas}
    tec_list = sorted({x[3] for f_ in usinas for x in usinas[f_]})
    acc_tec = {f_: np.zeros((2, len(ufs), len(tec_list))) for f_ in usinas}
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
    # usina -> estado (matriz indicadora) para o vertimento por gargalo hora a hora
    ind_uf = {}
    for f_ in usinas:
        Mi = np.zeros((len(usinas[f_]), len(ufs)))
        ok = idx_uf[f_] >= 0
        Mi[np.nonzero(ok)[0], idx_uf[f_][ok]] = 1
        ind_uf[f_] = Mi
    garg_horario = []                                       # (estágio, cenário, horas x UF em MW)
    exc_horario = []                                        # idem, vertimento por excesso no sistema
    dif_horario = []                                        # idem, CMO do estado - CMO do SIN ($/MWh)
    cmo_horario = []                                        # CMO mediano de cada estado e do SIN ($/MWh)
    # perfil por hora do dia: CMO do SIN e de cada estado (todas as horas) e CMO nas barras das usinas que
    # verteram, ponderado pelo MW vertido, junto com o CMO do SIN nesses mesmos momentos
    cmo_sin_h, cnt_h = np.zeros(24), np.zeros(24)
    cmo_uf_h = np.zeros((len(ufs), 24))
    wp = {f_: np.zeros((len(ufs), 24)) for f_ in usinas}    # soma de CMO da barra x MW vertido
    wr = {f_: np.zeros((len(ufs), 24)) for f_ in usinas}    # soma de CMO do SIN x MW vertido
    wv = {f_: np.zeros((len(ufs), 24)) for f_ in usinas}    # soma de MW vertido
    # CMO de cada estado (2º índice) x MW vertido no estado (1º índice): CMO dos vizinhos quando o estado verteu
    wn = {f_: np.zeros((len(ufs), len(ufs), 24)) for f_ in usinas}

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
            garg_uf = np.zeros((nh, len(ufs)))
            exc_uf = np.zeros((nh, len(ufs)))
            dif_uf = np.full((nh, len(ufs)), np.nan)
            for j_u, u in enumerate(ufs):
                cu = cols_por_uf.get(u)
                if cu is not None and len(cu):
                    dif_uf[:, j_u] = np.median(P[:, cu], axis=1) - ref
            cmo_horario.append((e, c, np.column_stack([dif_uf + ref[:, None], ref])))
            Hd = np.zeros((24, nh))
            Hd[hd, np.arange(nh)] = 1                                # agrega horas -> hora do dia
            cmo_sin_h += Hd @ ref
            cnt_h += Hd.sum(axis=1)
            cmo_uf_h += (Hd @ np.nan_to_num(dif_uf + ref[:, None])).T
            for f_, h in fontes.items():
                if h is None:
                    continue
                V = bloco(h, e, c)
                if f_ in cols_fonte:
                    V = V[:, cols_fonte[f_]]                         # sem a geração distribuída
                V = V * 1000.0                                       # MWh na hora (= MW)
                cc = col[f_]
                Pp = np.where(cc >= 0, P[:, np.clip(cc, 0, None)], ref[:, None])
                dif = Pp - ref[:, None]
                garg = dif < -tol
                vg = np.where(garg, V, 0.0)
                vs = V - vg
                vert_br += V.sum(axis=1)
                garg_uf += vg @ ind_uf[f_]
                exc_uf += vs @ ind_uf[f_]
                wp[f_] += (Hd @ ((Pp * V) @ ind_uf[f_])).T
                wr[f_] += (Hd @ ((ref[:, None] * V) @ ind_uf[f_])).T
                wv[f_] += (Hd @ (V @ ind_uf[f_])).T
                Wu, Cu = V @ ind_uf[f_], np.nan_to_num(dif_uf + ref[:, None])
                for hh in range(24):
                    sh = hd == hh
                    wn[f_][:, :, hh] += Wu[sh].T @ Cu[sh]
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
            if suc is not None:
                S = bloco(suc, e, c)
                at = np.abs(S) > 1e-9
                ativ_suc[:, m] += at.sum(axis=0)
                vert_suc += (at * vert_br[:, None]).sum(axis=0)
            if lnk is not None:
                L = bloco(lnk, e, c)
                ativ_lnk[:, m] += (np.abs(L) > 1e-9).sum(axis=0)
            horas_mes[m] += nh
            garg_horario.append((e, c, garg_uf))
            exc_horario.append((e, c, exc_uf))
            dif_horario.append((e, c, dif_uf))
            n_horas += nh
        print(f'  {MESES[m]}/{a.ano} ok - {time.time() - t0:.0f} s')

    # --- saídas: CSV ---------------------------------------------------------------
    # por estado, hora a hora, no formato do SDDP: vertimento por gargalo e por excesso (renovável +
    # hidro, MW) e diferença entre o CMO mediano das barras do estado e o CMO do SIN ($/MWh)
    def escrever_uf_horario(nome_arq, unidade, linhas_):
        with open(os.path.join(saida, nome_arq), 'w', encoding='latin-1', newline='') as f:
            w = csv.writer(f, lineterminator='\r\n')
            n_col = 3 + len(ufs)
            vazio = [''] * n_col
            w.writerow((['Varies per block?       ', 2, 'Unit    ', unidade.ljust(7), cmg['tipo_estagio'],
                         cmg['mes_ini'], cmg['ano_ini']] + vazio)[:n_col])
            w.writerow((['Varies per sequence?    ', 1] + vazio)[:n_col])
            w.writerow((['# of agents             ', len(ufs)] + vazio)[:n_col])
            w.writerow(['Mês', 'Cenários', 'Hora'] + [u.ljust(12) for u in ufs])
            for e, c, G in linhas_:
                for hh in range(G.shape[0]):
                    w.writerow([e + 1, c + 1, hh + 1] + ['' if v != v else '%.6g' % v for v in G[hh]])

    escrever_uf_horario('vertimento_gargalo_uf_horario.csv', 'MW', garg_horario)
    escrever_uf_horario('vertimento_excesso_uf_horario.csv', 'MW', exc_horario)
    escrever_uf_horario('cmo_diferenca_uf_horario.csv', '$/MWh', dif_horario)
    ufs_sin = ufs + ['SIN']
    ufs, ufs_orig = ufs_sin, ufs
    escrever_uf_horario('cmo_uf_horario.csv', '$/MWh', cmo_horario)   # colunas: estados + SIN (mediana do país)
    ufs = ufs_orig

    nomes_f = {'ren': 'renovavel', 'hid': 'hidro_turbinavel'}
    # vizinhos de cada estado: os 3 de maior capacidade de divisa (limites_pares_uf.csv da etapa 2)
    N_VIZ = 3
    vizinhos = {u: [] for u in ufs}
    arq_p = os.path.join(a.caso, 'resultados_uf', 'limites_pares_uf.csv')
    if os.path.exists(arq_p):
        cap_par = collections.defaultdict(float)
        with open(arq_p, encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f):
                cap = float(r['capacidade_CA_MW'] or 0) + float(r['capacidade_CC_a_para_b_MW'] or 0)
                cap_par[(r['uf_a'], r['uf_b'])] += cap
                cap_par[(r['uf_b'], r['uf_a'])] += cap
        for u in ufs:
            cand = [(cap, v) for (x, v), cap in cap_par.items() if x == u and v in ufs and v != u
                    and cols_por_uf.get(v) is not None and len(cols_por_uf[v])]
            vizinhos[u] = [(v, cap) for cap, v in sorted(cand, reverse=True)[:N_VIZ]]
    else:
        print(f'  AVISO: {arq_p} não encontrado (etapa 2); sem CMO dos estados vizinhos no perfil horário')
    # perfil por hora do dia (média do ano e dos cenários), usado pelo gráfico por estado do gargalo_linhas
    with open(os.path.join(saida, 'perfil_horario_uf.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        cab = ['uf', 'hora']
        for f_ in ('ren', 'hid'):
            cab += [f'vert_{f_}_gargalo_MW', f'vert_{f_}_excesso_MW', f'cmo_usinas_{f_}_que_verteram',
                    f'cmo_sin_quando_{f_}_verteu']
        cab += ['cmo_estado', 'cmo_sin']
        for k in range(N_VIZ):
            cab += [f'vizinho{k + 1}_uf', f'vizinho{k + 1}_capacidade_divisa_MW', f'vizinho{k + 1}_cmo'] + \
                   [f'vizinho{k + 1}_cmo_quando_{f_}_verteu' for f_ in ('ren', 'hid')]
        w.writerow(cab)
        n_dia = np.maximum(cnt_h, 1)                         # ocorrências de cada hora (dias x cenários)

        def linha(rot, i_uf):
            sel = (lambda X: X[i_uf]) if i_uf is not None else (lambda X: X.sum(axis=0))
            for h in range(24):
                lin = [rot, h + 1]
                for f_ in ('ren', 'hid'):
                    if f_ in acc_h:
                        vv = sel(wv[f_])[h]
                        lin += [round(sel(acc_h[f_][0])[h] / n_dia[h], 2), round(sel(acc_h[f_][1])[h] / n_dia[h], 2),
                                round(sel(wp[f_])[h] / vv, 2) if vv > 1e-6 else '',
                                round(sel(wr[f_])[h] / vv, 2) if vv > 1e-6 else '']
                    else:
                        lin += ['', '', '', '']
                est = cmo_uf_h[i_uf, h] / n_dia[h] if i_uf is not None else cmo_sin_h[h] / n_dia[h]
                lin += [round(est, 2), round(cmo_sin_h[h] / n_dia[h], 2)]
                viz = vizinhos[rot] if i_uf is not None else []
                for k in range(N_VIZ):
                    if k >= len(viz):
                        lin += ['', '', '', '', '']
                        continue
                    v, cap = viz[k]
                    j_v = ufs.index(v)
                    lin += [v, round(cap), round(cmo_uf_h[j_v, h] / n_dia[h], 2)]
                    for f_ in ('ren', 'hid'):
                        vv = wv[f_][i_uf, h] if f_ in wv else 0
                        lin.append(round(wn[f_][i_uf, j_v, h] / vv, 2) if vv > 1e-6 else '')
                w.writerow(lin)
        for i, u in enumerate(ufs):
            linha(u, i)
        linha('BR', None)
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
        """Vertimento por causa mês a mês (renovável e hidro). O perfil por hora do dia fica no gráfico
        estado_<UF>.png do gargalo_linhas.py."""
        sel = (lambda X: X[:, i_uf]) if i_uf is not None else (lambda X: X.sum(axis=1))
        fig, axs = plt.subplots(len(fontes_ok), 1, figsize=(11, 3.1 * len(fontes_ok) + 1.0), squeeze=False)
        axs = axs[:, 0]
        for ax, f_ in zip(axs, fontes_ok):
            rot = dict((x[0], x[2]) for x in FONTES)[f_]
            M = sel(acc_m[f_]) / n_cen / 1000                     # [causa, mês] GWh
            x = np.arange(12)
            ax.bar(x, M[0], color=COR_GARG, width=0.7, edgecolor=FUNDO, linewidth=1)
            ax.bar(x, M[1], bottom=M[0], color=COR_SIST, width=0.7, edgecolor=FUNDO, linewidth=1)
            tot = M.sum()
            pct = 100 * M[0].sum() / tot if tot > 0 else 0
            ax.set_title(f'Vertimento {rot} por mês (GWh) — {tot:,.0f} GWh no ano, {pct:.0f}% por gargalo'
                         .replace(',', '.'), loc='left', fontsize=10)
            if tot <= 0:
                ax.set_ylim(0, 1)
                ax.set_yticks([0])
                ax.text(0.5, 0.5, f'sem vertimento {rot.split(" ")[0]} no estado', ha='center', va='center',
                        color=TEXTO2, transform=ax.transAxes)
            ax.set_xticks(x, MESES)
            ax.set_ylabel('GWh')
            ax.grid(axis='y', color=GRADE, linewidth=0.6)
            ax.set_axisbelow(True)
        titulo = 'Brasil' if i_uf is None else f'{nome} ({REGIAO_DA_UF.get(nome, "")})'
        fig.suptitle(f'{titulo} — vertimento por gargalo de transmissão × excesso no sistema, mês a mês, {a.ano}',
                     x=0.01, ha='left', fontsize=13, fontweight='bold')
        from matplotlib.patches import Patch
        fig.legend(handles=[Patch(color=COR_GARG, label='gargalo de transmissão'),
                            Patch(color=COR_SIST, label='excesso no sistema (falta de demanda)')],
                   loc='upper left', ncol=2, fontsize=9, frameon=False,
                   bbox_to_anchor=(0.005, 1 - 0.42 / fig.get_figheight()))
        fig.text(0.01, 0.004, f'Gargalo = CMO da barra da usina mais de {tol:g} $/MWh abaixo da mediana do CMO das '
                 f'barras do SIN na mesma hora e cenário. Média de {n_cen} cenários. Sem a geração distribuída (MMGD/OMGD).',
                 fontsize=7.5, color=TEXTO2)
        fig.tight_layout(rect=(0, 0.02, 1, 1 - 0.6 / fig.get_figheight()))
        fig.savefig(os.path.join(saida, f'gargalo_mensal_{nome}.png'), dpi=120)
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
