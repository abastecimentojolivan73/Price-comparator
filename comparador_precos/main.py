"""
main.py - Entry point do ComparadorPrecos
Inicializa logging, banco de dados e lança a interface gráfica.
"""
import sys
import os

# Garante que o diretório do executável/script é o CWD
if getattr(sys, 'frozen', False):
    # Rodando como executável PyInstaller
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

os.chdir(BASE_DIR)

# Adiciona o diretório base ao path para imports relativos funcionarem
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from utils.helpers import setup_logging
from core.database import init_db
from ui.app import ComparadorApp

def main():
    setup_logging()
    init_db()
    app = ComparadorApp()
    app.mainloop()

if __name__ == "__main__":
    main()
