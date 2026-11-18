"""Vertimento por gargalo ENTRE SUBSISTEMAS x excesso no sistema, pelo CMO dos 14 subsistemas.

Complementa o gargalo_cmo.py (que compara a barra de cada usina com o SIN e agrega por
estado). Aqui a comparação é feita por SUBSISTEMA (sistem.dat: SE, SU, NE, NO, IT, AR, MA,
BM, TP, PA, TA, IV, IM, XI):

  CMO do subsistema = mediana do CMO (cmgbus) de todas as barras CA do subsistema, em cada
                      hora e cenário (barras_uf.csv, coluna "subsistema", vinda do dbus.dat);
  CMO do SIN        = mediana do CMO de todas as barras CA do país (o mesmo do gargalo_cmo).

Para cada hora, cenário e usina com vertimento (vergnd sem a geração distribuída MMGD/OMGD,
e envetu = vertimento turbinável das hidrelétricas), a usina pertence ao subsistema da sua
barra e o vertimento é classificado em:
  GARGALO ENTRE SUBSISTEMAS  CMO do subsistema < CMO do SIN - tolerância: o subsistema inteiro
                             está "preso", a energia não consegue sair pelas ligações com os
                             outros subsistemas;
  GARGALO DENTRO DO SUBSISTEMA  o subsistema está no preço do SIN, mas a barra da usina está
                             abaixo do CMO do subsistema - tolerância (gargalo local, na rede
                             interna do subsistema);
  EXCESSO NO SISTEMA         nenhum dos dois (sobra energia no SIN como um todo).
A classificação "subsistema x SIN" pedida é GARGALO ENTRE SUBSISTEMAS x (dentro + excesso);
a parcela "dentro do subsistema" é mostrada separada para ligar com a análise por barra.

Intercâmbio entre subsistemas: na rodada com rede elétrica (fluxo DC) o SDDP não usa os
limites do interc.dat (eles valem para o modelo "sistema com interconexões"); o intercâmbio
é o fluxo nos circuitos que cruzam a fronteira entre subsistemas, e a saída interc.bin traz
esses fluxos, circuito a circuito. Para cada par de subsistemas este script soma os fluxos
(sentido de A para B), compara com a soma dos limites dos circuitos (Rating/Rn do deck; elos
CC pela capacidade dos conversores) e conta as horas com circuito monitorado no limite e com
CMO separado entre os dois subsistemas. A capacidade do interc.dat aparece só como referência.

Precisa na pasta do caso: cmgbus, vergnd (e, se houver, envetu e interc) em .hdr/.bin;
sistem.dat, dcirc/mcirc/circstatus, dtrans/mtrans/transtatus, ddcline/mdcline/dclinestatus,
dcnvlcc/mcnvlcc, dseriescap e interc.dat do deck (os que faltarem ficam de fora, com aviso).

Uso:
  python gargalo_subsistema.py "<pasta do caso>" [--ano 2030] [--tolerancia 1] [--carregamento 99]
Padrão de saída: <pasta do caso>\\resultados_uf\\gargalo_subsistema
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
from limites_uf import ler, SEM_LIMITE                                         # noqa: E402
from limites_uf import num as numero                                            # noqa: E402
from gargalo_cmo import abrir, bloco, ler_tab, mapear_usinas                    # noqa: E402
from gargalo_linhas import circuitos_do_ano, quantil_hist                       # noqa: E402
from graficos_uf import MESES, TEXTO, TEXTO2, GRADE, FUNDO, plt, np             # noqa: E402

CAUSAS = [('entre', 'gargalo entre subsistemas'), ('dentro', 'gargalo dentro do subsistema (rede interna)'),
          ('exc', 'excesso no sistema (falta de demanda)')]
COR = {'entre': '#e34948', 'dentro': '#eda100', 'exc': '#8a8984'}
FONTES = [('ren', 'renovável (sem GD)'), ('hid', 'hidrelétrico (vertimento turbinável)')]
CORES_VIZ = ['#eb6834', '#1baf7a', '#6250d6']
COR_SUB = '#2a78d6'


def ler_sistemas(caso, barras):
    """Lista de (número, nome, id) dos subsistemas, na ordem do número (sistem.dat)."""
    arq = os.path.join(caso, 'sistem.dat')
    sis = []
    if os.path.exists(arq):
        with open(arq, encoding='latin-1') as f:
            for ln in f:
                p = ln.split()
                if len(p) >= 4 and p[0].isdigit():
                    sis.append((int(p[0]), ' '.join(p[1:-2]), p[-2].upper()))
    nomes = {s[1] for s in sis}
    extra = sorted({b['subsistema'] for b in barras if b['subsistema'] and b['subsistema'] not in nomes})
    for k, n in enumerate(extra):                       # subsistema das barras que não está no sistem.dat
        sis.append((1000 + k, n, n[:2].upper()))
    return sorted(sis)


def elementos_fronteira(caso, ano, sub_ca, nomes_interc):
    """Circuitos da saída interc com o subsistema de cada ponta e o limite (MW) em cada sentido.
    nome -> dict(tipo, a, b, lim_ab, lim_ba, mon); a/b = índice do subsistema de/para."""
    data = datetime.date(ano, 1, 1)
    porn = {}
    for (tipo, nome), e in circuitos_do_ano(caso, ano).items():
        porn[nome.strip()] = (tipo, e['de'], e['para'], e.get('limite', SEM_LIMITE), e.get('mon', 0))
    arq = os.path.join(caso, 'dseriescap.dat')
    if os.path.exists(arq):                              # compensadores série controlados (CSC)
        for r in ler(arq):
            try:
                porn.setdefault(r[1].strip(), ('csc', int(r[2]), int(r[3]), numero(r[9], SEM_LIMITE),
                                               int(r[12]) if len(r) > 12 and r[12] else 0))
            except (ValueError, IndexError):
                pass
    # elos CC: subsistema pela barra CA dos conversores; limite = menor capacidade entre o conversor
    # que leva CA->CC (retificador) e o que leva CC->CA (inversor), em cada sentido
    conv = {}
    if os.path.exists(os.path.join(caso, 'dcnvlcc.dat')):
        for r in ler(os.path.join(caso, 'dcnvlcc.dat')):
            conv[int(r[0])] = dict(ac=int(r[2]), dc=int(r[3]), exist=int(r[8]), desat=int(r[9]),
                                   dcac=numero(r[15]), acdc=numero(r[16]))
        if os.path.exists(os.path.join(caso, 'mcnvlcc.dat')):
            for r in ler(os.path.join(caso, 'mcnvlcc.dat')):
                if datetime.date(int(r[2]), int(r[1]), int(r[0])) <= data:
                    conv[int(r[3])] = dict(ac=int(r[5]), dc=int(r[6]), exist=int(r[8]), desat=int(r[9]),
                                           dcac=numero(r[15]), acdc=numero(r[16]))
    por_dc = {c['dc']: c for c in conv.values() if c['exist'] == 0 and c['desat'] == 0}
    if os.path.exists(os.path.join(caso, 'ddcline.dat')):
        for r in ler(os.path.join(caso, 'ddcline.dat')):
            ca, cb = por_dc.get(int(r[2])), por_dc.get(int(r[3]))
            if ca and cb:
                porn.setdefault(r[1].strip(), ('elo CC', ca['ac'], cb['ac'],
                                               (min(ca['acdc'], cb['dcac']), min(cb['acdc'], ca['dcac'])), 1))
    out, falta = {}, []
    for n in nomes_interc:
        d = porn.get(n.strip())
        if d is None:
            falta.append(n)
            continue
        tipo, de, para, lim, mon = d
        a, b = sub_ca.get(de), sub_ca.get(para)
        if a is None or b is None or a == b:
            falta.append(n)
            continue
        lab, lba = lim if isinstance(lim, tuple) else (lim, lim)
        out[n] = dict(tipo=tipo, a=a, b=b, lim_ab=lab, lim_ba=lba, mon=int(mon or 0))
    return out, falta


def capacidade_interc(caso, sis):
    """Capacidade do interc.dat (modelo sem rede, só referência): (i, j) -> MW de i para j."""
    arq = os.path.join(caso, 'interc.dat')
    cap = collections.Counter()
    if not os.path.exists(arq):
        return cap
    idx = {s[1].upper(): k for k, s in enumerate(sis)}
    with open(arq, encoding='latin-1') as f:
        for ln in f:
            if ln.startswith(('$', '!')) or len(ln) < 60:
                continue
            # colunas fixas: Num Name(12) FROM(12) TO(12) Type Currency CapacFT LossFT CapacTF LossTF
            de, para = ln[19:32].strip().upper(), ln[32:45].strip().upper()
            p = ln[45:].split()
            if de in idx and para in idx and len(p) >= 6:
                cap[(idx[de], idx[para])] += numero(p[2])
                cap[(idx[para], idx[de])] += numero(p[4])
    return cap


def main():
    p = argparse.ArgumentParser(description='Vertimento por gargalo entre subsistemas x excesso (CMO).')
    p.add_argument('caso')
    p.add_argument('--ano', type=int, default=2030)
    p.add_argument('--tolerancia', type=float, default=1.0,
                   help='diferença mínima de CMO ($/MWh) para considerar gargalo (padrão 1)')
    p.add_argument('--carregamento', type=float, default=99.0,
                   help='%% do limite a partir do qual um circuito está no limite (padrão 99)')
    p.add_argument('--tabelas', default=os.path.dirname(os.path.abspath(__file__)))
    p.add_argument('--saida')
    a = p.parse_args()
    saida = a.saida or os.path.join(a.caso, 'resultados_uf', 'gargalo_subsistema')
    os.makedirs(saida, exist_ok=True)
    tol, carr = a.tolerancia, a.carregamento / 100

    print('Abrindo as saídas do SDDP...')
    cmg = abrir(a.caso, 'cmgbus')
    fontes = {'ren': abrir(a.caso, 'vergnd'), 'hid': abrir(a.caso, 'envetu', obrigatorio=False)}
    itc = abrir(a.caso, 'interc', obrigatorio=False)
    for nome_h, h in (('vergnd', fontes['ren']), ('envetu', fontes['hid']), ('interc', itc)):
        if h is not None and (h['horas'] != cmg['horas'] or h['n_cen'] != cmg['n_cen']):
            print(f'  AVISO: {nome_h} tem horas/cenários diferentes do cmgbus (outra rodada?); fica de fora')
            if nome_h in ('vergnd',):
                sys.exit('ERRO: vergnd e cmgbus precisam ser da mesma rodada')
            if nome_h == 'envetu':
                fontes['hid'] = None
            else:
                itc = None
    fontes = {k: v for k, v in fontes.items() if v is not None}
    estagios = [e for e in range(cmg['n_estagios']) if mes_ano(cmg, e)[1] == a.ano]
    if not estagios:
        anos = sorted({mes_ano(cmg, e)[1] for e in range(cmg['n_estagios'])})
        sys.exit(f'ERRO: a rodada não tem estágios de {a.ano}. Anos disponíveis: {anos}')
    n_cen = cmg['n_cen']
    print(f'Ano {a.ano}: estágios {estagios[0] + 1} a {estagios[-1] + 1}, {n_cen} cenários, '
          f'tolerância {tol} $/MWh')

    # --- subsistemas, barras e usinas ---------------------------------------------
    M = mapear_usinas(a, fontes, cmg)
    barras, col_cmg, ca_cols, usinas = M['barras'], M['col_cmg'], M['ca_cols'], M['usinas']
    cols_fonte, nome_barra = M['cols_fonte'], M['nome_barra']
    sis = ler_sistemas(a.caso, barras)
    ns = len(sis)
    ids = [s[2] for s in sis]
    idx_nome = {s[1].upper(): k for k, s in enumerate(sis)}
    sub_barra = {b['nome']: idx_nome.get(b['subsistema'].upper()) for b in barras}
    sub_ca = {int(b['codigo']): idx_nome.get(b['subsistema'].upper()) for b in barras}
    cols_sub = [np.array([col_cmg[b['nome']] for b in barras if sub_barra.get(b['nome']) == k
                          and b['nome'] in col_cmg], dtype=int) for k in range(ns)]
    print('  barras CA por subsistema: ' + ', '.join(f'{ids[k]} {len(cols_sub[k])}' for k in range(ns)))
    # subsistema de cada usina: o da barra; sem barra, o do cadastro (renováveis), e conta como excesso
    ren_tab = {u['nome_usina']: u for u in ler_tab(os.path.join(a.tabelas, 'usinas_renovaveis_uf.csv'))}
    id_idx = {s[2]: k for k, s in enumerate(sis)}
    isub = {}
    for f_ in usinas:
        v = []
        for (n, _, _, _), nb in zip(usinas[f_], nome_barra[f_]):
            k = sub_barra.get(nb) if nb else None
            if k is None and f_ == 'ren' and n in ren_tab:
                k = id_idx.get(ren_tab[n].get('sistema', '').upper())
            v.append(-1 if k is None else k)
        isub[f_] = np.array(v, dtype=int)
        sem = int((isub[f_] < 0).sum())
        if sem:
            print(f'  AVISO: {sem} usinas de {fontes[f_]["nome"]} sem subsistema (ficam fora dos totais por subsistema)')
    ind = {}
    for f_ in usinas:
        Mi = np.zeros((len(usinas[f_]), ns))
        ok = isub[f_] >= 0
        Mi[np.nonzero(ok)[0], isub[f_][ok]] = 1
        ind[f_] = Mi
    col_us = {f_: np.array([x[1] for x in usinas[f_]], dtype=int) for f_ in usinas}

    # --- intercâmbio: circuitos de fronteira ------------------------------------------
    elem, pares = {}, []
    if itc is not None:
        elem, falta = elementos_fronteira(a.caso, a.ano, sub_ca, itc['nomes'])
        if falta:
            print(f'  AVISO: {len(falta)} dos {len(itc["nomes"])} circuitos do interc sem as duas pontas em '
                  f'subsistemas diferentes na rede de {a.ano} (ficam fora): {", ".join(falta[:8])}'
                  f'{" ..." if len(falta) > 8 else ""}')
        pares = sorted({tuple(sorted((e['a'], e['b']))) for e in elem.values()})
        print(f'  intercâmbio: {len(elem)} circuitos de fronteira, {len(pares)} pares de subsistemas')
    else:
        print('  AVISO: sem interc.hdr/.bin: a parte de intercâmbio entre subsistemas fica de fora')
    col_itc = {n: i for i, n in enumerate(itc['nomes'])} if itc is not None else {}
    fator_itc = 1000.0 if itc is not None and itc['unidade'].upper().startswith('GWH') else 1.0
    np_ = len(pares)
    # por par: colunas, sinal (+1 = circuito no sentido do 1º para o 2º subsistema do par), limites
    par_cols, par_sinal, par_lab, par_lba, par_mon, par_nomes = [], [], [], [], [], []
    for (i, j) in pares:
        cs, sg, la, lb, mo, nm = [], [], [], [], [], []
        for n, e in elem.items():
            if {e['a'], e['b']} != {i, j}:
                continue
            s_ = 1.0 if e['a'] == i else -1.0
            cs.append(col_itc[n])
            sg.append(s_)
            la.append(e['lim_ab'] if s_ > 0 else e['lim_ba'])
            lb.append(e['lim_ba'] if s_ > 0 else e['lim_ab'])
            mo.append(e['mon'])
            nm.append(n)
        par_cols.append(np.array(cs, dtype=int))
        par_sinal.append(np.array(sg))
        par_lab.append(np.array(la, dtype=float))
        par_lba.append(np.array(lb, dtype=float))
        par_mon.append(np.array(mo, dtype=int))
        par_nomes.append(nm)
    cap_ref = capacidade_interc(a.caso, sis)

    # --- acumuladores -------------------------------------------------------------------
    meses = [mes_ano(cmg, e)[0] for e in estagios]
    nc = len(CAUSAS)
    acc_m = {f_: np.zeros((nc, ns, 12)) for f_ in usinas}          # MWh por causa, subsistema, mês
    acc_h = {f_: np.zeros((nc, ns, 24)) for f_ in usinas}          # MWh por causa, subsistema, hora do dia
    w_sub = {f_: np.zeros((ns, 24)) for f_ in usinas}              # CMO do subsistema x MW vertido
    w_bar = {f_: np.zeros((ns, 24)) for f_ in usinas}              # CMO da barra da usina x MW vertido
    w_sin = {f_: np.zeros((ns, 24)) for f_ in usinas}              # CMO do SIN x MW vertido
    w_v = {f_: np.zeros((ns, 24)) for f_ in usinas}
    cnt_h = np.zeros(24)
    cmo_sin_h = np.zeros(24)
    cmo_sub_h = np.zeros((ns, 24))
    horas_mes = np.zeros(12)
    fl_h = np.zeros((np_, 24))                                     # fluxo líquido do par (MW), 1º -> 2º
    fl_pos = np.zeros(np_)                                         # horas com fluxo 1º -> 2º
    h_lim = np.zeros(np_)                                          # horas com circuito monitorado no limite
    h_sep = np.zeros(np_)                                          # horas com CMO separado entre os dois
    h_sep_lim = np.zeros(np_)
    h_lim_m = np.zeros((np_, 12))
    lado_baixo = np.zeros((np_, 2))                                # horas separadas com o 1º / 2º mais barato
    v_coinc = np.zeros(np_)                                        # vertimento "entre" do lado barato, MWh
    h_lim_h = np.zeros((np_, 24))
    h_sep_h = np.zeros((np_, 24))
    # carregamento (% do limite) do circuito monitorado mais carregado de cada ligação, hora a hora:
    # histograma por hora do dia (faixas de 2,5% de 0 a 150% + acima) para tirar mediana e 95%
    NB, PASSO = 61, 0.025
    hist_max = np.zeros((np_, 24, NB), dtype=np.int64)
    n_lim_circ = [np.zeros(len(par_cols[q])) for q in range(np_)]     # horas de cada circuito no limite
    n_max_circ = [np.zeros(len(par_cols[q])) for q in range(np_)]     # horas em que é o mais carregado
    horario = {k: [] for k, _ in CAUSAS}                           # (estágio, cenário, horas x subsistema) MW
    cmo_hor = []
    n_horas = 0

    t0 = time.time()
    for k_e, e in enumerate(estagios):
        m = meses[k_e] - 1
        for c in range(n_cen):
            P = bloco(cmg, e, c)
            ref = np.median(P[:, ca_cols], axis=1)
            nh = P.shape[0]
            hd = np.arange(nh) % 24
            Hd = np.zeros((24, nh))
            Hd[hd, np.arange(nh)] = 1
            Ps = np.column_stack([np.median(P[:, cs_], axis=1) if len(cs_) else ref for cs_ in cols_sub])
            cmo_hor.append((e, c, np.column_stack([Ps, ref])))
            cnt_h += Hd.sum(axis=1)
            cmo_sin_h += Hd @ ref
            cmo_sub_h += (Hd @ Ps).T
            sep = Ps < ref[:, None] - tol                         # subsistema preso (horas x subsistema)
            hor_c = {k: np.zeros((nh, ns)) for k, _ in CAUSAS}
            for f_, h in fontes.items():
                V = bloco(h, e, c)
                if f_ in cols_fonte:
                    V = V[:, cols_fonte[f_]]
                V = V * 1000.0
                ks = isub[f_]
                Pu = np.where(ks >= 0, Ps[:, np.clip(ks, 0, None)], ref[:, None])          # CMO do subsistema
                Pb = np.where(col_us[f_] >= 0, P[:, np.clip(col_us[f_], 0, None)], Pu)    # CMO da barra
                entre = Pu < ref[:, None] - tol
                dentro = ~entre & (Pb < Pu - tol)
                Vc = {'entre': np.where(entre, V, 0.0), 'dentro': np.where(dentro, V, 0.0)}
                Vc['exc'] = V - Vc['entre'] - Vc['dentro']
                for k_c, (cz, _) in enumerate(CAUSAS):
                    X = Vc[cz] @ ind[f_]                                                   # horas x subsistema
                    hor_c[cz] += X
                    acc_m[f_][k_c, :, m] += X.sum(axis=0)
                    acc_h[f_][k_c] += (Hd @ X).T
                Wv = V @ ind[f_]
                w_v[f_] += (Hd @ Wv).T
                w_sub[f_] += (Hd @ ((Pu * V) @ ind[f_])).T
                w_bar[f_] += (Hd @ ((Pb * V) @ ind[f_])).T
                w_sin[f_] += (Hd @ (ref[:, None] * Wv)).T
            for cz, _ in CAUSAS:
                horario[cz].append((e, c, hor_c[cz]))
            if itc is not None and np_:
                F = bloco(itc, e, c) * fator_itc
                for q, (i, j) in enumerate(pares):
                    Fq = F[:, par_cols[q]] * par_sinal[q]                                  # MW no sentido i -> j
                    liq = Fq.sum(axis=1)
                    fl_h[q] += Hd @ liq
                    fl_pos[q] += (liq > 0).sum()
                    lim = np.where(Fq >= 0, par_lab[q], par_lba[q])
                    com = (lim < SEM_LIMITE) & (lim > 0) & (par_mon[q] == 1)
                    if com.any():
                        car = np.abs(Fq) / np.where(com, lim, np.inf)                      # fração do limite
                        no_lim = (car >= carr).any(axis=1)
                        n_lim_circ[q] += (car >= carr).sum(axis=0)
                        np.add.at(n_max_circ[q], car.argmax(axis=1), 1)
                        faixa = np.minimum((car.max(axis=1) / PASSO).astype(np.int64), NB - 1)
                        np.add.at(hist_max[q], (hd, faixa), 1)
                    else:
                        no_lim = np.zeros(nh, dtype=bool)
                    s_ij = np.abs(Ps[:, i] - Ps[:, j]) > tol
                    h_lim[q] += no_lim.sum()
                    h_lim_m[q, m] += no_lim.sum()
                    h_sep[q] += s_ij.sum()
                    h_sep_lim[q] += (s_ij & no_lim).sum()
                    h_lim_h[q] += Hd @ no_lim
                    h_sep_h[q] += Hd @ s_ij
                    baixo_i = s_ij & (Ps[:, i] < Ps[:, j])
                    baixo_j = s_ij & (Ps[:, j] < Ps[:, i])
                    lado_baixo[q] += [baixo_i.sum(), baixo_j.sum()]
                    v_coinc[q] += (hor_c['entre'][:, i] * (baixo_i & sep[:, i])).sum() + \
                        (hor_c['entre'][:, j] * (baixo_j & sep[:, j])).sum()
            horas_mes[m] += nh
            n_horas += nh
        print(f'  {MESES[m]}/{a.ano} ok - {time.time() - t0:.0f} s')

    n_dia = np.maximum(cnt_h, 1)
    nomes_f = dict(FONTES)

    # --- CSVs -----------------------------------------------------------------------------
    def escrever_horario(nome_arq, unidade, linhas_, colunas):
        with open(os.path.join(saida, nome_arq), 'w', encoding='latin-1', newline='') as f:
            w = csv.writer(f, lineterminator='\r\n')
            n_col = 3 + len(colunas)
            vazio = [''] * n_col
            w.writerow((['Varies per block?       ', 2, 'Unit    ', unidade.ljust(7), cmg['tipo_estagio'],
                         cmg['mes_ini'], cmg['ano_ini']] + vazio)[:n_col])
            w.writerow((['Varies per sequence?    ', 1] + vazio)[:n_col])
            w.writerow((['# of agents             ', len(colunas)] + vazio)[:n_col])
            w.writerow(['Mês', 'Cenários', 'Hora'] + [u.ljust(12) for u in colunas])
            for e, c, G in linhas_:
                for hh in range(G.shape[0]):
                    w.writerow([e + 1, c + 1, hh + 1] + ['' if v != v else '%.6g' % v for v in G[hh]])

    escrever_horario('vertimento_gargalo_entre_subsistemas_horario.csv', 'MW', horario['entre'], ids)
    escrever_horario('vertimento_gargalo_dentro_subsistema_horario.csv', 'MW', horario['dentro'], ids)
    escrever_horario('vertimento_excesso_subsistema_horario.csv', 'MW', horario['exc'], ids)
    escrever_horario('cmo_subsistema_horario.csv', '$/MWh', cmo_hor, ids + ['SIN'])

    with open(os.path.join(saida, 'vertimento_causa_subsistema_mensal.csv'), 'w', encoding='utf-8-sig',
              newline='') as f:
        w = csv.writer(f)
        w.writerow(['subsistema', 'nome', 'fonte', 'mes', 'gargalo_entre_subsistemas_GWh',
                    'gargalo_dentro_subsistema_GWh', 'excesso_sistema_GWh', 'total_GWh', 'pct_gargalo_entre'])
        for f_ in usinas:
            for k in range(ns):
                for mm in list(range(12)) + ['ano']:
                    v = acc_m[f_][:, k, mm] if mm != 'ano' else acc_m[f_][:, k, :].sum(axis=1)
                    v = v / n_cen / 1000
                    if mm != 'ano' and horas_mes[mm] == 0:
                        continue
                    tot = v.sum()
                    w.writerow([ids[k], sis[k][1], nomes_f[f_], MESES[mm] if mm != 'ano' else 'ano'] +
                               [round(x, 3) for x in v] + [round(tot, 3), round(100 * v[0] / tot, 1) if tot > 0 else ''])

    # vizinhos de cada subsistema: os 3 ligados com maior limite somado (ou mais circuitos)
    viz = {k: [] for k in range(ns)}
    for q, (i, j) in enumerate(pares):
        lim = par_lab[q]
        lim_ok = lim[(lim < SEM_LIMITE) & (lim > 0)].sum()
        peso = (lim_ok, len(par_cols[q]))
        viz[i].append((peso, j, q))
        viz[j].append((peso, i, q))
    viz = {k: [(o, q) for _, o, q in sorted(v, reverse=True)[:3]] for k, v in viz.items()}

    with open(os.path.join(saida, 'perfil_horario_subsistema.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        cab = ['subsistema', 'hora']
        for f_, _ in FONTES:
            cab += [f'vert_{f_}_{cz}_MW' for cz, _ in CAUSAS] + \
                   [f'cmo_subsistema_quando_{f_}_verteu', f'cmo_barras_quando_{f_}_verteu',
                    f'cmo_sin_quando_{f_}_verteu']
        cab += ['cmo_subsistema', 'cmo_sin']
        for v_ in range(3):
            cab += [f'vizinho{v_ + 1}', f'vizinho{v_ + 1}_cmo', f'intercambio_para_vizinho{v_ + 1}_MW']
        w.writerow(cab)
        for k in range(ns):
            for hh in range(24):
                lin = [ids[k], hh + 1]
                for f_, _ in FONTES:
                    if f_ not in usinas:
                        lin += [''] * (nc + 3)
                        continue
                    vv = w_v[f_][k, hh]
                    lin += [round(acc_h[f_][k_c, k, hh] / n_dia[hh], 2) for k_c in range(nc)]
                    lin += [round(X[k, hh] / vv, 2) if vv > 1e-6 else '' for X in (w_sub[f_], w_bar[f_], w_sin[f_])]
                lin += [round(cmo_sub_h[k, hh] / n_dia[hh], 2), round(cmo_sin_h[hh] / n_dia[hh], 2)]
                for v_ in range(3):
                    if v_ < len(viz[k]):
                        o, q = viz[k][v_]
                        sg = 1 if pares[q][0] == k else -1
                        lin += [ids[o], round(cmo_sub_h[o, hh] / n_dia[hh], 2), round(sg * fl_h[q, hh] / n_dia[hh], 1)]
                    else:
                        lin += ['', '', '']
                w.writerow(lin)

    tot_h = max(n_horas, 1)

    def circ_destaque(q):
        """Circuito da ligação que mais vezes fica no limite (ou, se nenhum chega, o que mais vezes é o
        mais carregado): (nome, limite em MW, % das horas no limite, % das horas como o mais carregado)."""
        if not len(par_cols[q]) or (n_lim_circ[q].sum() == 0 and n_max_circ[q].sum() == 0):
            return None
        c_ = int(n_lim_circ[q].argmax()) if n_lim_circ[q].sum() else int(n_max_circ[q].argmax())
        lim_c = min(par_lab[q][c_], par_lba[q][c_])
        return (par_nomes[q][c_], lim_c, 100 * n_lim_circ[q][c_] / tot_h, 100 * n_max_circ[q][c_] / tot_h)
    if np_:
        with open(os.path.join(saida, 'intercambios_subsistemas.csv'), 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f)
            w.writerow(['de', 'para', 'n_circuitos', 'n_monitorados_com_limite', 'n_sem_limite',
                        'limite_somado_de_para_MW', 'limite_somado_para_de_MW',
                        'capacidade_interc_dat_de_para_MW (referencia, modelo sem rede)',
                        'capacidade_interc_dat_para_de_MW (referencia, modelo sem rede)',
                        'fluxo_medio_de_para_MW', 'pct_horas_fluxo_de_para', 'pct_horas_circuito_monitorado_no_limite',
                        'pct_horas_cmo_separado', 'pct_horas_cmo_separado_e_circuito_no_limite',
                        'pct_horas_separado_com_de_mais_barato', 'pct_horas_separado_com_para_mais_barato',
                        'vertimento_gargalo_entre_coincidente_GWh', 'circuito_que_mais_fica_no_limite',
                        'limite_desse_circuito_MW', 'pct_horas_desse_circuito_no_limite',
                        'pct_horas_em_que_e_o_mais_carregado', 'carregamento_mediano_do_mais_carregado_pct',
                        'carregamento_p95_do_mais_carregado_pct'] +
                       [f'pct_horas_no_limite_{mm}' for mm in MESES])
            for q, (i, j) in enumerate(pares):
                la, lb = par_lab[q], par_lba[q]
                ok = (la < SEM_LIMITE) & (la > 0)
                mon_ok = ok & (par_mon[q] == 1)
                w.writerow([ids[i], ids[j], len(par_cols[q]), int(mon_ok.sum()), int((~ok).sum()),
                            round(la[ok].sum()), round(lb[(lb < SEM_LIMITE) & (lb > 0)].sum()),
                            round(cap_ref.get((i, j), 0)), round(cap_ref.get((j, i), 0)),
                            round(fl_h[q].sum() / n_dia.sum(), 1), round(100 * fl_pos[q] / tot_h, 2),
                            round(100 * h_lim[q] / tot_h, 2), round(100 * h_sep[q] / tot_h, 2),
                            round(100 * h_sep_lim[q] / tot_h, 2),
                            round(100 * lado_baixo[q, 0] / tot_h, 2), round(100 * lado_baixo[q, 1] / tot_h, 2),
                            round(v_coinc[q] / n_cen / 1000, 1)] +
                           ([d_[0], round(d_[1]), round(d_[2], 2), round(d_[3], 2)] if (d_ := circ_destaque(q)) else
                            ['', '', '', '']) +
                           [quantil_hist(np.repeat(hist_max[q].sum(axis=0, keepdims=True), 24, axis=0), x_, NB, PASSO)[0]
                            if hist_max[q].sum() else '' for x_ in (0.5, 0.95)] +
                           [round(100 * h_lim_m[q, mm] / max(horas_mes[mm], 1), 2) for mm in range(12)])

    # --- gráficos ---------------------------------------------------------------------------
    from matplotlib.patches import Patch
    leg_causas = [Patch(color=COR[cz], label=rot) for cz, rot in CAUSAS]
    horas = np.arange(1, 25)
    fmt = (lambda x: f'{x:,.0f}'.replace(',', '.'))

    # 1) resumo: vertimento anual por subsistema e causa
    tot_sub = sum(acc_m[f_].sum(axis=(0, 2)) for f_ in usinas) / n_cen / 1000
    ordem = [k for k in np.argsort(-tot_sub) if tot_sub[k] > 0.05]
    if ordem:
        fig, axs = plt.subplots(1, len(usinas), figsize=(7 * len(usinas), 0.42 * len(ordem) + 2.0), squeeze=False)
        for ax, f_ in zip(axs[0], usinas):
            V = acc_m[f_].sum(axis=2)[:, ordem] / n_cen / 1000
            y = np.arange(len(ordem))[::-1]
            esq = np.zeros(len(ordem))
            for k_c, (cz, _) in enumerate(CAUSAS):
                ax.barh(y, V[k_c], left=esq, color=COR[cz], height=0.7, edgecolor=FUNDO, linewidth=1)
                esq += V[k_c]
            for yy, tt, g in zip(y, esq, V[0]):
                if tt > 0:
                    ax.text(tt, yy, f' {fmt(tt)} GWh ({100 * g / tt:.0f}% entre)', va='center', fontsize=8,
                            color=TEXTO2)
            ax.set_yticks(y, [f'{ids[k]} {sis[k][1]}' for k in ordem], fontsize=8.5)
            ax.set_xlim(0, max(esq.max() * 1.35, 1))
            ax.grid(axis='x', color=GRADE, linewidth=0.6)
            ax.set_axisbelow(True)
            tot = V.sum()
            ax.set_title(f'{nomes_f[f_][0].upper() + nomes_f[f_][1:]}: {fmt(tot)} GWh, '
                         f'{100 * V[0].sum() / tot if tot else 0:.0f}% entre subsistemas', loc='left', fontsize=10)
            ax.set_xlabel('GWh no ano (média dos cenários)')
        fig.legend(handles=leg_causas, loc='upper left', ncol=3, fontsize=9, frameon=False,
                   bbox_to_anchor=(0.005, 1 - 0.42 / fig.get_figheight()))
        fig.suptitle(f'Vertimento por subsistema: gargalo entre subsistemas × dentro do subsistema × excesso, {a.ano}',
                     x=0.01, y=1 - 0.12 / fig.get_figheight(), ha='left', fontsize=13, fontweight='bold')
        fig.text(0.01, 0.005, f'Entre subsistemas = CMO do subsistema (mediana das suas barras) mais de {tol:g} $/MWh '
                 'abaixo do CMO do SIN; dentro = subsistema no preço do SIN e barra da usina abaixo do subsistema. '
                 'Sem a geração distribuída (MMGD/OMGD).', fontsize=7.5, color=TEXTO2)
        fig.subplots_adjust(left=0.13, right=0.98, top=1 - 0.9 / fig.get_figheight(), bottom=0.9 / fig.get_figheight(),
                            wspace=0.35)
        fig.savefig(os.path.join(saida, 'resumo_subsistemas.png'), dpi=125)
        plt.close(fig)

    # 2) mês a mês, um painel por subsistema com vertimento (renovável + hidro, por causa)
    if ordem:
        nc_ = 3
        nl_ = int(np.ceil(len(ordem) / nc_))
        fig, axs = plt.subplots(nl_, nc_, figsize=(15, 2.7 * nl_ + 1.3), squeeze=False)
        for ax, k in zip(axs.flat, ordem):
            V = sum(acc_m[f_][:, k, :] for f_ in usinas) / n_cen / 1000
            base = np.zeros(12)
            for k_c, (cz, _) in enumerate(CAUSAS):
                ax.bar(np.arange(12), V[k_c], bottom=base, color=COR[cz], width=0.72, edgecolor=FUNDO, linewidth=0.8)
                base += V[k_c]
            ax.set_xticks(np.arange(12), [mm[0].upper() for mm in MESES], fontsize=7.5)
            ax.set_title(f'{ids[k]} {sis[k][1]} — {fmt(V.sum())} GWh', loc='left', fontsize=9.5)
            ax.grid(axis='y', color=GRADE, linewidth=0.6)
            ax.set_axisbelow(True)
        for ax in list(axs.flat)[len(ordem):]:
            ax.set_visible(False)
        fig.legend(handles=leg_causas, loc='upper left', ncol=3, fontsize=9, frameon=False,
                   bbox_to_anchor=(0.005, 1 - 0.42 / fig.get_figheight()))
        fig.suptitle(f'Vertimento renovável (sem GD) + hidrelétrico por subsistema e causa, mês a mês (GWh), {a.ano}',
                     x=0.01, y=1 - 0.12 / fig.get_figheight(), ha='left', fontsize=13, fontweight='bold')
        fig.subplots_adjust(left=0.05, right=0.99, top=1 - 0.9 / fig.get_figheight(), bottom=0.35 / fig.get_figheight(),
                            hspace=0.55, wspace=0.18)
        fig.savefig(os.path.join(saida, 'mensal_subsistemas.png'), dpi=120)
        plt.close(fig)

    # 3) um gráfico por subsistema, hora do dia no eixo x (mesmo modelo do estado_<UF>.png)
    pasta = os.path.join(saida, 'por_subsistema')
    os.makedirs(pasta, exist_ok=True)
    LEG = dict(loc='upper left', bbox_to_anchor=(1.01, 1.0), borderaxespad=0, frameon=False, fontsize=8)
    for k in ordem:
        tem_itc = bool(viz[k])
        n_pain = 5 + (2 if tem_itc else 0)
        fig, axs = plt.subplots(n_pain, 1, figsize=(15, 2.5 * n_pain + 1.3), sharex=True)
        for ax, (f_, rot) in zip(axs[:2], FONTES):
            if f_ not in usinas or acc_h[f_][:, k].sum() <= 0:
                ax.set_ylim(0, 1)
                ax.set_yticks([0])
                ax.text(0.5, 0.5, f'sem vertimento {rot.split(" ")[0]} no subsistema', ha='center', va='center',
                        color=TEXTO2, transform=ax.transAxes)
                ax.set_title(f'Vertimento {rot} médio por hora (MW)', loc='left', fontsize=10)
                continue
            V = acc_h[f_][:, k] / n_dia
            base = np.zeros(24)
            for k_c, (cz, _) in enumerate(CAUSAS):
                ax.bar(horas, V[k_c], bottom=base, color=COR[cz], width=0.75, edgecolor=FUNDO, linewidth=0.8)
                base += V[k_c]
            tot = V.sum()
            ax.set_title(f'Vertimento {rot} médio por hora (MW) — {100 * V[0].sum() / tot:.0f}% entre subsistemas, '
                         f'{100 * V[1].sum() / tot:.0f}% dentro do subsistema', loc='left', fontsize=10)
            ax.set_ylabel('MW')

        def linhas_cmo(ax, c_sub, rot_sub, c_sin, rot_sin, extra=()):
            ax.plot(horas, c_sub, color=COR_SUB, linewidth=2.6, marker='o', markersize=3.5, label=rot_sub, zorder=5)
            ax.plot(horas, c_sin, color=TEXTO, linewidth=2, linestyle='--', marker='o', markersize=3, label=rot_sin,
                    zorder=4)
            for cor_, est_, y_, rot_ in extra:
                ax.plot(horas, y_, color=cor_, linewidth=1.4, linestyle=est_, marker='s', markersize=2.5, label=rot_,
                        zorder=3)
            ax.set_ylabel('$/MWh')
            ax.legend(**LEG)
        extra = [(CORES_VIZ[v_], '-', cmo_sub_h[o] / n_dia, f'{ids[o]} ({sis[o][1]})')
                 for v_, (o, q) in enumerate(viz[k])]
        linhas_cmo(axs[2], cmo_sub_h[k] / n_dia, f'{ids[k]} (mediana das\nbarras do subsistema)', cmo_sin_h / n_dia,
                   'SIN (mediana de todas\nas barras do país)', extra)
        axs[2].set_title(f'CMO médio por hora ($/MWh) — todas as horas: {ids[k]}, SIN e subsistemas ligados ao {ids[k]}',
                         loc='left', fontsize=10)
        for ax, (f_, rot) in zip(axs[3:5], FONTES):
            ax.set_title(f'CMO no momento em que o {rot.split(" ")[0]} do subsistema verteu ($/MWh, ponderado pelo MW '
                         'vertido) — azul abaixo do SIN = gargalo entre subsistemas', loc='left', fontsize=10)
            vv = w_v[f_][k] if f_ in usinas else np.zeros(24)
            if vv.sum() <= 0:
                ax.set_yticks([])
                ax.text(0.5, 0.5, f'sem vertimento {rot.split(" ")[0]} no subsistema', ha='center', va='center',
                        color=TEXTO2, transform=ax.transAxes)
                continue
            with np.errstate(invalid='ignore', divide='ignore'):
                cs_, cb_, cr_ = (np.where(vv > 1e-6, X[k] / vv, np.nan) for X in (w_sub[f_], w_bar[f_], w_sin[f_]))
            linhas_cmo(ax, cs_, f'{ids[k]} nesses\nmomentos', cr_, 'SIN nesses\nmomentos',
                       [(COR['dentro'], '-', cb_, 'barras das usinas\nque verteram')])
            ax.fill_between(horas, cs_, cr_, where=np.isfinite(cs_) & np.isfinite(cr_) & (cs_ < cr_ - tol),
                            color=COR['entre'], alpha=0.12, linewidth=0)
        if tem_itc:
            ax = axs[5]
            for v_, (o, q) in enumerate(viz[k]):
                sg = 1 if pares[q][0] == k else -1
                n_mon = int(((par_lab[q] < SEM_LIMITE) & (par_lab[q] > 0) & (par_mon[q] == 1)).sum())
                ax.plot(horas, sg * fl_h[q] / n_dia, color=CORES_VIZ[v_], linewidth=2,
                        label=(f'{ids[k]} → {ids[o]}: em {100 * h_lim[q] / tot_h:.1f}% das horas, pelo\n'
                               f'menos 1 dos {n_mon} circuitos monitorados estava\nno limite; em '
                               f'{100 * h_sep[q] / tot_h:.1f}% das horas o CMO\ndo {ids[k]} e do {ids[o]} estava '
                               f'diferente').replace('.', ','))
            ax.axhline(0, color=TEXTO2, linewidth=0.8)
            ax.set_ylabel('MW')
            ax.set_title(f'Intercâmbio médio com os vizinhos (MW, soma dos fluxos nos circuitos de fronteira, interc) '
                         f'— positivo = {ids[k]} exporta', loc='left', fontsize=10)
            ax.legend(**dict(LEG, fontsize=7.5))
            # carregamento do circuito mais carregado de cada ligação
            ax = axs[6]
            from matplotlib.lines import Line2D
            hand = []
            for v_, (o, q) in enumerate(viz[k]):
                if not hist_max[q].sum():
                    continue
                cor_ = CORES_VIZ[v_]
                ax.plot(horas, quantil_hist(hist_max[q], 0.5, NB, PASSO), color=cor_, linewidth=2)
                ax.plot(horas, quantil_hist(hist_max[q], 0.95, NB, PASSO), color=cor_, linewidth=1, linestyle=':')
                d_ = circ_destaque(q)
                txt = f'{ids[k]} — {ids[o]}'
                if d_:
                    lim_t = f'{d_[1]:,.0f}'.replace(',', '.')
                    if d_[2] > 0:
                        txt += (f'\nmais vezes no limite: {d_[0][:30]}\n(limite {lim_t} MW; ' +
                                f'{d_[2]:.1f}% das horas no limite)'.replace('.', ','))
                    else:
                        txt += (f'\nnenhum no limite; o mais carregado com mais\nfrequência: {d_[0][:30]} '
                                f'(limite {lim_t} MW)')
                hand.append(Line2D([], [], color=cor_, linewidth=2, label=txt))
            hand.append(Line2D([], [], color=TEXTO2, linewidth=1, linestyle=':', label='pontilhado = 95% das horas abaixo'))
            ax.axhline(100, color=TEXTO, linewidth=1.2, linestyle='--')
            ax.set_ylabel('% do limite')
            ax.set_title('Carregamento do circuito monitorado MAIS CARREGADO de cada ligação, a cada hora (% do seu '
                         'limite físico; cheia = mediana, tracejado = 100%)', loc='left', fontsize=10)
            ax.legend(handles=hand, **dict(LEG, fontsize=7))
        for ax in axs:
            ax.grid(axis='y', color=GRADE, linewidth=0.6)
            ax.set_axisbelow(True)
            ax.set_xticks(horas, [str(h) for h in horas], fontsize=7.5)
            ax.tick_params(labelbottom=True)
            ax.set_xlim(0.4, 24.6)
        axs[-1].set_xlabel('Hora do dia (1 = 00h-01h)')
        fig.legend(handles=leg_causas, loc='upper left', ncol=3, fontsize=9, frameon=False,
                   bbox_to_anchor=(0.005, 1 - 0.42 / fig.get_figheight()))
        fig.suptitle(f'Subsistema {ids[k]} ({sis[k][1]}) — vertimento, CMO e intercâmbio por hora do dia, {a.ano}',
                     x=0.01, y=1 - 0.12 / fig.get_figheight(), ha='left', fontsize=13, fontweight='bold')
        fig.text(0.01, 0.004, f'Médias de todas as horas do ano e de todos os cenários. Entre subsistemas = CMO do '
                 f'subsistema mais de {tol:g} \\$/MWh abaixo do SIN; dentro = barra da usina mais de {tol:g} \\$/MWh abaixo '
                 'do subsistema. Sem a geração distribuída (MMGD/OMGD).', fontsize=7.5, color=TEXTO2)
        fig.subplots_adjust(left=0.055, right=0.78, top=1 - 0.95 / fig.get_figheight(),
                            bottom=0.75 / fig.get_figheight(), hspace=0.5)
        fig.savefig(os.path.join(pasta, f'subsistema_{ids[k]}.png'), dpi=115)
        plt.close(fig)

    # 4) intercâmbios: % das horas com CMO separado e com circuito no limite, por par
    if np_:
        ordem_p = sorted(range(np_), key=lambda q: -(h_sep[q] + h_lim[q]))
        fig, axs = plt.subplots(1, 2, figsize=(15, 0.36 * np_ + 2.2), sharey=True)
        y = np.arange(np_)[::-1]
        rot_p = [f'{ids[pares[q][0]]} — {ids[pares[q][1]]}' for q in ordem_p]
        ax = axs[0]
        ax.barh(y + 0.18, [100 * h_sep[q] / tot_h for q in ordem_p], height=0.36, color=COR['entre'],
                label='CMO dos dois subsistemas diferente (> tolerância)')
        ax.barh(y - 0.18, [100 * h_lim[q] / tot_h for q in ordem_p], height=0.36, color='#2a78d6',
                label='pelo menos 1 circuito monitorado da ligação no limite')
        ax.set_yticks(y, rot_p, fontsize=8.5)
        ax.set_xlabel('% das horas do ano (todos os cenários)')
        ax.set_title('Ligações entre subsistemas: % das horas com preço separado e com circuito no limite',
                     loc='left', fontsize=10)
        ax.legend(loc='lower right', fontsize=8, frameon=False)
        ax = axs[1]
        v = [v_coinc[q] / n_cen / 1000 for q in ordem_p]
        ax.barh(y, v, height=0.6, color=COR['entre'])
        for yy, vv in zip(y, v):
            if vv > 0:
                ax.text(vv, yy, f' {fmt(vv)}', va='center', fontsize=8, color=TEXTO2)
        ax.set_xlabel('GWh no ano (média dos cenários)')
        ax.set_title('Vertimento por gargalo entre subsistemas no lado mais barato, nas horas com preço separado',
                     loc='left', fontsize=10)
        for ax in axs:
            ax.grid(axis='x', color=GRADE, linewidth=0.6)
            ax.set_axisbelow(True)
        fig.suptitle(f'Intercâmbio entre subsistemas (circuitos de fronteira da saída interc), {a.ano}', x=0.01,
                     ha='left', fontsize=13, fontweight='bold')
        fig.text(0.01, 0.005, f'No limite = fluxo >= {a.carregamento:g}% do limite físico do deck (Rating/Rn; elo CC '
                 f'pelos conversores). Preço separado = diferença de CMO entre os subsistemas > {tol:g} $/MWh. Um mesmo '
                 'vertimento pode coincidir com mais de uma ligação.', fontsize=7.5, color=TEXTO2)
        fig.tight_layout(rect=(0, 0.02, 1, 1 - 0.5 / fig.get_figheight()))
        fig.savefig(os.path.join(saida, 'intercambios_subsistemas.png'), dpi=125)
        plt.close(fig)

    # --- resumo na tela ------------------------------------------------------------------------
    for f_ in usinas:
        V = acc_m[f_].sum(axis=(1, 2)) / n_cen / 1000
        tot = V.sum()
        if tot > 0:
            print(f'SIN, vertimento {nomes_f[f_]}: {fmt(tot)} GWh — entre subsistemas {100 * V[0] / tot:.1f}%, '
                  f'dentro do subsistema {100 * V[1] / tot:.1f}%, excesso {100 * V[2] / tot:.1f}%')
    print(f'Fim. Arquivos em {saida}')


if __name__ == '__main__':
    main()
