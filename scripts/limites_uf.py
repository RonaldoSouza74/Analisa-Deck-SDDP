"""Capacidade de exportação e importação de cada estado a partir da rede do SDDP.

No SDDP a barra não tem um limite de injeção próprio: o que limita o fluxo que um
estado consegue mandar ou receber é a capacidade dos circuitos que cruzam a sua
divisa. Este script soma, por estado, a capacidade dos elementos de fronteira em
operação numa data (padrão: 1/1 do ano):

  - linhas CA (dcirc.dat + alterações em mcirc.dat + situação em circstatus_b004m.dat):
    coluna Rating (MW), vale nos dois sentidos (exportação e importação);
  - transformadores entre barras de estados diferentes (dtrans.dat + mtrans.dat +
    transtatus_b004m.dat): coluna Rn;
  - elos CC (ddcline.dat/mdcline.dat + conversores dcnvlcc.dat/mcnvlcc.dat): capacidade
    dos conversores; só no sentido retificador -> inversor (exportação de um estado e
    importação do outro).

Elementos com limite 99999 (sem limite no deck) não entram na soma e são contados à parte.

Também lista as restrições de intercâmbio entre regiões (csumcirc.dat), que não são
por estado.

Uso:
  python limites_uf.py <pasta_do_caso> <pasta_com_barras_uf.csv> <pasta_saida> [--ano 2030]
Saídas: limites_uf.csv, limites_pares_uf.csv, circuitos_fronteira_uf.csv,
        restricoes_intercambio.csv
"""
import argparse
import collections
import csv
import datetime
import os
import sys

SEM_LIMITE = 99999


def ler(caminho):
    if not os.path.exists(caminho):
        return []
    with open(caminho, encoding='latin-1', newline='') as f:
        return [r for r in csv.reader(f) if r and r[0] and r[0][0] not in '$!']


def num(x, padrao=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return padrao


def situacao(arq, data):
    """Situação (1 = em operação) de cada elemento na data, por bloco: {codigo: {bloco: status}}."""
    st = collections.defaultdict(dict)
    datas = collections.defaultdict(dict)
    for r in ler(arq):
        cod, d, bloco, s = int(r[0]), datetime.date(*map(int, r[1].split('/'))), int(r[2]), int(r[3])
        if d <= data and d >= datas[cod].get(bloco, datetime.date(1, 1, 1)):
            datas[cod][bloco] = d
            st[cod][bloco] = s
    return st


def em_operacao(st, cod):
    """Em operação se estiver ligado em todos os blocos (sem registro = ligado)."""
    blocos = st.get(cod)
    return True if not blocos else all(v == 1 for v in blocos.values())


def main():
    p = argparse.ArgumentParser()
    p.add_argument('caso')
    p.add_argument('tabelas', help='pasta com barras_uf.csv')
    p.add_argument('saida')
    p.add_argument('--ano', type=int, default=2030)
    a = p.parse_args()
    data = datetime.date(a.ano, 1, 1)
    os.makedirs(a.saida, exist_ok=True)

    with open(os.path.join(a.tabelas, 'barras_uf.csv'), encoding='utf-8-sig', newline='') as f:
        barras = list(csv.DictReader(f))
    uf_ca = {int(b['codigo']): b['uf'] for b in barras if b['rede'] == 'CA'}
    nome_ca = {int(b['codigo']): b['nome'] for b in barras if b['rede'] == 'CA'}
    uf_cc = {int(b['codigo']): b['uf'] for b in barras if b['rede'] == 'CC'}

    elementos = []   # (tipo, codigo, nome, uf_de, uf_para, capacidade, monitorado, barra_de, barra_para)

    # --- linhas CA ----------------------------------------------------------
    circ = {}
    for r in ler(os.path.join(a.caso, 'dcirc.dat')):
        circ[int(r[0])] = dict(nome=r[1], de=int(r[2]), para=int(r[3]), exist=int(r[6]), desat=int(r[7]),
                               rating=num(r[11]), mon=int(r[14]) if len(r) > 14 and r[14] else 0)
    mods = sorted(ler(os.path.join(a.caso, 'mcirc.dat')), key=lambda r: (int(r[2]), int(r[1]), int(r[0])))
    for r in mods:
        if datetime.date(int(r[2]), int(r[1]), int(r[0])) > data:
            continue
        c = circ.setdefault(int(r[3]), dict(nome=r[4], mon=0))
        c.update(nome=r[4], de=int(r[5]), para=int(r[6]), exist=int(r[7]), desat=int(r[8]), rating=num(r[12]))
    st = situacao(os.path.join(a.caso, 'circstatus_b004m.dat'), data)
    for cod, c in circ.items():
        if c['exist'] != 0 or c['desat'] != 0 or not em_operacao(st, cod):
            continue
        ua, ub = uf_ca.get(c['de']), uf_ca.get(c['para'])
        if ua and ub and ua != ub:
            elementos.append(('linha CA', cod, c['nome'], ua, ub, c['rating'], c['mon'], c['de'], c['para']))

    # --- transformadores ----------------------------------------------------
    trf = {}
    for r in ler(os.path.join(a.caso, 'dtrans.dat')):
        trf[int(r[0])] = dict(nome=r[1], de=int(r[2]), para=int(r[3]), exist=int(r[7]), desat=int(r[8]),
                              rating=num(r[14]))
    for r in sorted(ler(os.path.join(a.caso, 'mtrans.dat')), key=lambda r: (int(r[2]), int(r[1]), int(r[0]))):
        if datetime.date(int(r[2]), int(r[1]), int(r[0])) > data:
            continue
        t = trf.setdefault(int(r[3]), dict(nome=r[4]))
        t.update(nome=r[4], de=int(r[5]), para=int(r[6]), exist=int(r[7]), desat=int(r[8]), rating=num(r[14]))
    st = situacao(os.path.join(a.caso, 'transtatus_b004m.dat'), data)
    for cod, t in trf.items():
        if t['exist'] != 0 or t['desat'] != 0 or not em_operacao(st, cod):
            continue
        ua, ub = uf_ca.get(t['de']), uf_ca.get(t['para'])
        if ua and ub and ua != ub:
            elementos.append(('transformador', cod, t['nome'], ua, ub, t['rating'], '', t['de'], t['para']))

    # --- elos CC ------------------------------------------------------------
    conv = {}
    for r in ler(os.path.join(a.caso, 'dcnvlcc.dat')):
        conv[int(r[0])] = dict(ac=int(r[2]), dc=int(r[3]), exist=int(r[8]), desat=int(r[9]),
                               dcac=num(r[15]), acdc=num(r[16]))
    for r in ler(os.path.join(a.caso, 'mcnvlcc.dat')):
        if datetime.date(int(r[2]), int(r[1]), int(r[0])) > data:
            continue
        conv[int(r[3])] = dict(ac=int(r[5]), dc=int(r[6]), exist=int(r[8]), desat=int(r[9]),
                               dcac=num(r[15]), acdc=num(r[16]))
    por_dc = {c['dc']: c for c in conv.values() if c['exist'] == 0 and c['desat'] == 0}
    linhas_cc = {}
    for r in ler(os.path.join(a.caso, 'ddcline.dat')):
        linhas_cc[int(r[0])] = dict(nome=r[1], de=int(r[2]), para=int(r[3]), exist=int(r[5]), desat=int(r[6]))
    for r in ler(os.path.join(a.caso, 'mdcline.dat')):
        if datetime.date(int(r[2]), int(r[1]), int(r[0])) > data:
            continue
        k = 7 if len(r) == 14 else 8          # algumas linhas do mdcline.dat vêm sem a coluna Length
        linhas_cc[int(r[3])] = dict(nome=r[4], de=int(r[5]), para=int(r[6]), exist=int(r[k]), desat=int(r[k + 1]))
    st = situacao(os.path.join(a.caso, 'dclinestatus_b004m.dat'), data)
    for cod, l_ in linhas_cc.items():
        if l_['exist'] != 0 or l_['desat'] != 0 or not em_operacao(st, cod):
            continue
        ca, cb = por_dc.get(l_['de']), por_dc.get(l_['para'])
        if not (ca and cb):
            continue
        # sentido: do conversor que leva CA->CC (retificador) para o que leva CC->CA (inversor);
        # conversores com capacidade nos dois sentidos entram nos dois sentidos
        for ret, inv in ((ca, cb), (cb, ca)):
            cap = min(ret['acdc'], inv['dcac'])
            ua, ub = uf_ca.get(ret['ac']), uf_ca.get(inv['ac'])
            if cap > 0 and ua and ub and ua != ub:
                elementos.append(('elo CC', cod, f'{nome_ca.get(ret["ac"], "")} -> {nome_ca.get(inv["ac"], "")}',
                                  ua, ub, cap, '', ret['ac'], inv['ac']))

    # --- soma por estado ----------------------------------------------------
    lim = collections.defaultdict(lambda: collections.Counter())
    pares = collections.defaultdict(lambda: collections.Counter())
    for tipo, cod, nome, ua, ub, cap, mon, _, _ in elementos:
        sem = cap >= SEM_LIMITE
        if tipo == 'elo CC':                      # só um sentido
            if not sem:
                lim[ua]['exp_cc'] += cap
                lim[ub]['imp_cc'] += cap
                pares[(ua, ub)]['cc'] += cap
            continue
        for u in (ua, ub):
            lim[u]['n'] += 1
            if sem:
                lim[u]['sem_limite'] += 1
            else:
                lim[u]['ca'] += cap
                if mon == 1:
                    lim[u]['ca_monitorado'] += cap
        if not sem:
            pares[tuple(sorted((ua, ub)))]['ca'] += cap

    with open(os.path.join(a.saida, 'limites_uf.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['uf', 'limite_exportacao_MW', 'limite_importacao_MW', 'ca_fronteira_MW', 'ca_monitorado_MW',
                    'cc_exportacao_MW', 'cc_importacao_MW', 'circuitos_fronteira', 'circuitos_sem_limite'])
        for u in sorted(lim):
            c = lim[u]
            w.writerow([u, round(c['ca'] + c['exp_cc']), round(c['ca'] + c['imp_cc']), round(c['ca']),
                        round(c['ca_monitorado']), round(c['exp_cc']), round(c['imp_cc']), c['n'], c['sem_limite']])
    with open(os.path.join(a.saida, 'limites_pares_uf.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['uf_a', 'uf_b', 'capacidade_CA_MW', 'capacidade_CC_a_para_b_MW'])
        for (ua, ub), c in sorted(pares.items(), key=lambda z: -(z[1]['ca'] + z[1]['cc'])):
            w.writerow([ua, ub, round(c['ca']), round(c['cc'])])
    with open(os.path.join(a.saida, 'circuitos_fronteira_uf.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['tipo', 'codigo', 'nome', 'uf_de', 'uf_para', 'capacidade_MW', 'monitorado',
                    'barra_de', 'barra_para'])
        w.writerows(sorted(elementos, key=lambda e: (e[3], e[4], -e[5])))
    rest = ler(os.path.join(a.caso, 'csumcirc.dat'))
    ub_tempo = collections.defaultdict(list)
    for r in ler(os.path.join(a.caso, 'sumcircub_b004m.dat')):
        d = datetime.date(*map(int, r[1].split('/')))
        if d.year == a.ano:
            ub_tempo[int(r[0])].append(num(r[3]))
    with open(os.path.join(a.saida, 'restricoes_intercambio.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['codigo', 'nome', 'limite_inferior_MW', 'limite_superior_MW',
                    f'limite_superior_min_{a.ano}', f'limite_superior_max_{a.ano}'])
        for r in rest:
            cod = int(r[0])
            v = ub_tempo.get(cod)
            w.writerow([cod, r[1].strip(), r[3] if r[2].strip() == '1' else '', r[5] if r[4].strip() == '1' else '',
                        min(v) if v else '', max(v) if v else ''])
    print(f'Elementos de fronteira em operação em {data}: '
          f'{collections.Counter(e[0] for e in elementos)}')
    for u in sorted(lim, key=lambda u: -(lim[u]['ca'] + lim[u]['exp_cc'])):
        c = lim[u]
        print(f'  {u}: exportação {c["ca"] + c["exp_cc"]:8.0f} MW | importação {c["ca"] + c["imp_cc"]:8.0f} MW '
              f'(CA {c["ca"]:.0f}, CC +{c["exp_cc"]:.0f}/+{c["imp_cc"]:.0f}) | {c["n"]} circuitos, '
              f'{c["sem_limite"]} sem limite')


if __name__ == '__main__':
    main()
