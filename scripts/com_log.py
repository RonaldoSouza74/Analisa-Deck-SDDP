"""Roda um script Python mostrando a saída na tela e copiando tudo para um arquivo de log.

Uso (pelos .bat):
  python com_log.py "<arquivo de log>" <script.py> [argumentos do script...]

O log é acrescentado (não apaga o que já existe). O código de saída do script é mantido,
para o .bat saber se a etapa deu certo.
"""
import datetime
import os
import runpy
import sys
import traceback


class Duplicador:
    """Escreve ao mesmo tempo na tela e no arquivo de log."""

    def __init__(self, tela, arquivo):
        self.tela, self.arquivo = tela, arquivo

    def write(self, texto):
        try:
            self.tela.write(texto)
        except UnicodeEncodeError:
            self.tela.write(texto.encode('ascii', 'replace').decode('ascii'))
        self.arquivo.write(texto)
        self.tela.flush()
        self.arquivo.flush()

    def flush(self):
        self.tela.flush()
        self.arquivo.flush()


def main():
    if len(sys.argv) < 3:
        sys.exit('uso: python com_log.py <log> <script.py> [argumentos]')
    log, script, args = sys.argv[1], sys.argv[2], sys.argv[3:]
    pasta = os.path.dirname(os.path.abspath(log))
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    with open(log, 'a', encoding='utf-8') as f:
        tela_out, tela_err = sys.stdout, sys.stderr
        sys.stdout = Duplicador(tela_out, f)
        sys.stderr = Duplicador(tela_err, f)
        inicio = datetime.datetime.now()
        print(f'[{inicio:%d/%m/%Y %H:%M:%S}] python {script} {" ".join(args)}')
        codigo = 0
        caminho = script if os.path.isabs(script) else os.path.join(os.path.dirname(os.path.abspath(__file__)), script)
        sys.argv = [caminho] + args
        try:
            runpy.run_path(caminho, run_name='__main__')
        except SystemExit as e:
            if isinstance(e.code, int):
                codigo = e.code
            elif e.code is None:
                codigo = 0
            else:
                print(e.code, file=sys.stderr)          # mensagem de erro do script (sys.exit('ERRO: ...'))
                codigo = 1
        except Exception:
            traceback.print_exc()
            codigo = 1
        fim = datetime.datetime.now()
        print(f'[{fim:%d/%m/%Y %H:%M:%S}] fim ({"ok" if codigo == 0 else "ERRO"}, '
              f'{(fim - inicio).total_seconds() / 60:.1f} min)\n')
        sys.stdout, sys.stderr = tela_out, tela_err
    sys.exit(codigo)


if __name__ == '__main__':
    main()
