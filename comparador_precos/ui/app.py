"""
ui/app.py - Interface gráfica principal usando CustomTkinter.
Abas: Processamento e Admin Config.
Toda operação pesada roda em thread separada para não bloquear a mainloop.
"""
import os
import threading
from tkinter import filedialog, messagebox
import tkinter as tk
import customtkinter as ctk
from core.database import (
    upsert_config_fornecedor, list_config_fornecedores, delete_config_fornecedor,
    list_resultados, clear_resultados, insert_resultado
)
from core.api_service import fetch_and_cache_prices, get_price_from_cache
from core.xml_processor import iter_xml_files, parse_nfe_file
from core.comparator import build_result_row
from core.reports import export_excel, export_pdf
from utils.helpers import get_logger, now_str, format_currency

logger = get_logger(__name__)

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

STATUS_COLORS = {
    "OK": "#2ecc71",
    "ALERTA": "#f39c12",
    "CRITICO": "#e74c3c",
    "INFO": "#3498db",
    "ERRO": "#c0392b",
}


class ComparadorApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Comparador de Preços — NF-e")
        self.geometry("1200x760")
        self.minsize(900, 600)
        self._selected_folder = tk.StringVar(value="")
        self._api_url = tk.StringVar(value="")
        self._api_token = tk.StringVar(value="")
        self._processing = False
        self._build_ui()

    # ─── Build UI ────────────────────────────────────────────────────────────

    def _build_ui(self):
        """Constrói toda a interface gráfica."""
        self.tabview = ctk.CTkTabview(self, anchor="nw")
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)

        self.tabview.add("Processamento")
        self.tabview.add("Admin Config")

        self._build_processamento_tab(self.tabview.tab("Processamento"))
        self._build_admin_tab(self.tabview.tab("Admin Config"))

    # ─── Aba Processamento ────────────────────────────────────────────────────

    def _build_processamento_tab(self, tab):
        # Painel superior: configurações de API
        api_frame = ctk.CTkFrame(tab)
        api_frame.pack(fill="x", padx=8, pady=(8, 4))

        ctk.CTkLabel(api_frame, text="URL da API:", width=100, anchor="w").grid(
            row=0, column=0, padx=8, pady=6, sticky="w"
        )
        ctk.CTkEntry(api_frame, textvariable=self._api_url, width=380,
                     placeholder_text="https://api.exemplo.com/precos").grid(
            row=0, column=1, padx=4, pady=6, sticky="w"
        )
        ctk.CTkLabel(api_frame, text="Token:", width=60, anchor="w").grid(
            row=0, column=2, padx=(16, 4), pady=6, sticky="w"
        )
        ctk.CTkEntry(api_frame, textvariable=self._api_token, width=200, show="*",
                     placeholder_text="Bearer token (opcional)").grid(
            row=0, column=3, padx=4, pady=6, sticky="w"
        )
        self._btn_cache = ctk.CTkButton(
            api_frame, text="Atualizar Cache", width=140,
            command=self._on_update_cache, fg_color="#2980b9"
        )
        self._btn_cache.grid(row=0, column=4, padx=12, pady=6)

        # Seleção de pasta e botão processar
        folder_frame = ctk.CTkFrame(tab)
        folder_frame.pack(fill="x", padx=8, pady=4)

        ctk.CTkLabel(folder_frame, text="Pasta de XMLs:", width=110, anchor="w").grid(
            row=0, column=0, padx=8, pady=6, sticky="w"
        )
        self._lbl_folder = ctk.CTkEntry(
            folder_frame, textvariable=self._selected_folder,
            width=450, state="readonly", placeholder_text="Nenhuma pasta selecionada"
        )
        self._lbl_folder.grid(row=0, column=1, padx=4, pady=6)
        ctk.CTkButton(
            folder_frame, text="Selecionar Pasta", width=140,
            command=self._on_select_folder, fg_color="#7f8c8d"
        ).grid(row=0, column=2, padx=8, pady=6)

        self._btn_processar = ctk.CTkButton(
            folder_frame, text="Processar XMLs", width=150,
            command=self._on_process, fg_color="#27ae60"
        )
        self._btn_processar.grid(row=0, column=3, padx=8, pady=6)

        self._btn_limpar = ctk.CTkButton(
            folder_frame, text="Limpar Resultados", width=150,
            command=self._on_clear_results, fg_color="#e67e22"
        )
        self._btn_limpar.grid(row=0, column=4, padx=8, pady=6)

        # Status label
        self._lbl_status = ctk.CTkLabel(
            tab, text="Pronto.", anchor="w",
            text_color=STATUS_COLORS["INFO"],
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self._lbl_status.pack(fill="x", padx=12, pady=(4, 2))

        # Barra de progresso
        self._progress = ctk.CTkProgressBar(tab, mode="indeterminate")
        self._progress.pack(fill="x", padx=12, pady=(0, 4))
        self._progress.stop()

        # Treeview de resultados
        tree_frame = ctk.CTkFrame(tab)
        tree_frame.pack(fill="both", expand=True, padx=8, pady=4)

        self._tree = self._create_results_tree(tree_frame)

        # Barra inferior: export
        export_frame = ctk.CTkFrame(tab)
        export_frame.pack(fill="x", padx=8, pady=(4, 8))

        ctk.CTkButton(
            export_frame, text="Exportar Excel", width=150,
            command=self._on_export_excel, fg_color="#1abc9c"
        ).pack(side="left", padx=8, pady=6)

        ctk.CTkButton(
            export_frame, text="Exportar PDF", width=150,
            command=self._on_export_pdf, fg_color="#8e44ad"
        ).pack(side="left", padx=8, pady=6)

        ctk.CTkButton(
            export_frame, text="Recarregar Tabela", width=150,
            command=self._load_results_to_tree, fg_color="#2c3e50"
        ).pack(side="left", padx=8, pady=6)

        # Carrega resultados existentes
        self.after(300, self._load_results_to_tree)

    def _create_results_tree(self, parent):
        """Cria e retorna o Treeview de resultados com scrollbars."""
        import tkinter.ttk as ttk

        columns = (
            "arquivo", "cnpj", "codigo", "descricao",
            "qtd", "v_total", "p_xml", "p_api",
            "dif_abs", "dif_pct", "status", "data"
        )

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", rowheight=22, font=("Helvetica", 9))
        style.configure("Treeview.Heading", font=("Helvetica", 9, "bold"))
        style.map("Treeview", background=[("selected", "#2980b9")])

        frame = tk.Frame(parent, bg="#2b2b2b")
        frame.pack(fill="both", expand=True, padx=4, pady=4)

        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")

        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        col_config = [
            ("arquivo", "Arquivo", 180),
            ("cnpj", "CNPJ Fornecedor", 130),
            ("codigo", "Código", 100),
            ("descricao", "Descrição", 200),
            ("qtd", "Qtd", 70),
            ("v_total", "Val. Total", 100),
            ("p_xml", "Preço XML", 100),
            ("p_api", "Preço API", 100),
            ("dif_abs", "Dif. Abs.", 90),
            ("dif_pct", "Dif. %", 70),
            ("status", "Status", 80),
            ("data", "Data", 130),
        ]

        for col_id, heading, width in col_config:
            tree.heading(col_id, text=heading)
            tree.column(col_id, width=width, minwidth=50, anchor="w")

        # Tags de cor por status
        tree.tag_configure("OK", background="#d4edda")
        tree.tag_configure("ALERTA", background="#fff3cd")
        tree.tag_configure("CRITICO", background="#f8d7da")

        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        tree.pack(fill="both", expand=True)

        return tree

    # ─── Aba Admin Config ─────────────────────────────────────────────────────

    def _build_admin_tab(self, tab):
        form_frame = ctk.CTkFrame(tab)
        form_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(form_frame, text="Cadastro de Tolerância por Fornecedor",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, columnspan=6, padx=8, pady=8, sticky="w"
        )

        fields = [
            ("CNPJ Fornecedor:", "cnpj", 150, "00.000.000/0000-00"),
            ("Código Produto:", "cod_prod", 120, "Ex: ABC123"),
            ("Tipo Combustível:", "tipo_comb", 120, "Opcional"),
        ]

        self._admin_vars = {}
        for col, (label, key, width, placeholder) in enumerate(fields):
            ctk.CTkLabel(form_frame, text=label, anchor="w").grid(
                row=1, column=col * 2, padx=(12 if col == 0 else 8, 2), pady=6, sticky="w"
            )
            var = tk.StringVar()
            self._admin_vars[key] = var
            ctk.CTkEntry(form_frame, textvariable=var, width=width,
                         placeholder_text=placeholder).grid(
                row=1, column=col * 2 + 1, padx=(2, 8), pady=6, sticky="w"
            )

        # Tolerância tipo e valor
        ctk.CTkLabel(form_frame, text="Tipo Tolerância:", anchor="w").grid(
            row=2, column=0, padx=(12, 2), pady=6, sticky="w"
        )
        self._tol_tipo = ctk.CTkComboBox(
            form_frame, values=["%", "VALOR"], width=100, state="readonly"
        )
        self._tol_tipo.set("%")
        self._tol_tipo.grid(row=2, column=1, padx=(2, 8), pady=6, sticky="w")

        ctk.CTkLabel(form_frame, text="Valor Tolerância:", anchor="w").grid(
            row=2, column=2, padx=(8, 2), pady=6, sticky="w"
        )
        self._tol_valor = tk.StringVar(value="5.0")
        ctk.CTkEntry(form_frame, textvariable=self._tol_valor, width=100,
                     placeholder_text="Ex: 5.0").grid(
            row=2, column=3, padx=(2, 8), pady=6, sticky="w"
        )

        ctk.CTkButton(
            form_frame, text="Salvar Configuração", width=160,
            command=self._on_save_config, fg_color="#27ae60"
        ).grid(row=2, column=4, padx=16, pady=6)

        # Lista de configurações
        list_frame = ctk.CTkFrame(tab)
        list_frame.pack(fill="both", expand=True, padx=10, pady=(4, 10))

        self._config_tree = self._create_config_tree(list_frame)

        ctk.CTkButton(
            list_frame, text="Excluir Selecionado", width=160,
            command=self._on_delete_config, fg_color="#e74c3c"
        ).pack(side="bottom", pady=8)

        self.after(200, self._load_configs_to_tree)

    def _create_config_tree(self, parent):
        import tkinter.ttk as ttk

        columns = ("id", "cnpj", "codigo_produto", "tipo_comb", "tol_tipo", "tol_valor")
        frame = tk.Frame(parent, bg="#2b2b2b")
        frame.pack(fill="both", expand=True, padx=4, pady=4)

        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)

        col_cfg = [
            ("id", "ID", 50),
            ("cnpj", "CNPJ", 160),
            ("codigo_produto", "Cód. Produto", 130),
            ("tipo_comb", "Tipo Combustível", 130),
            ("tol_tipo", "Tipo Tolerância", 120),
            ("tol_valor", "Valor Tolerância", 120),
        ]
        for col_id, heading, width in col_cfg:
            tree.heading(col_id, text=heading)
            tree.column(col_id, width=width, minwidth=40)

        vsb.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        return tree

    # ─── Event handlers ───────────────────────────────────────────────────────

    def _on_select_folder(self):
        folder = filedialog.askdirectory(title="Selecione a pasta com os XMLs")
        if folder:
            self._selected_folder.set(folder)
            self._set_status(f"Pasta selecionada: {folder}", "INFO")

    def _on_update_cache(self):
        url = self._api_url.get().strip()
        token = self._api_token.get().strip()
        if not url:
            messagebox.showwarning("Atenção", "Informe a URL da API antes de atualizar o cache.")
            return
        self._set_status("Atualizando cache de preços da API…", "INFO")
        self._set_ui_busy(True)

        def task():
            count, errors = fetch_and_cache_prices(url, token)
            def done():
                self._set_ui_busy(False)
                if errors:
                    self._set_status(
                        f"Cache atualizado: {count} produtos. {len(errors)} erro(s) — veja o log.",
                        "ALERTA"
                    )
                    messagebox.showwarning(
                        "Avisos durante atualização",
                        "\n".join(errors[:10]) + ("\n..." if len(errors) > 10 else "")
                    )
                else:
                    self._set_status(f"Cache atualizado: {count} produtos.", "OK")
            self.after(0, done)

        threading.Thread(target=task, daemon=True).start()

    def _on_process(self):
        folder = self._selected_folder.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("Atenção", "Selecione uma pasta de XMLs válida.")
            return
        if self._processing:
            messagebox.showinfo("Aguarde", "Processamento já em andamento.")
            return

        self._set_ui_busy(True)
        self._processing = True
        self._set_status("Processando XMLs…", "INFO")

        def task():
            results = []
            errors = []
            xml_files = list(iter_xml_files(folder))

            if not xml_files:
                self.after(0, lambda: (
                    self._set_ui_busy(False),
                    self._set_status("Nenhum arquivo XML encontrado na pasta.", "ALERTA"),
                    setattr(self, '_processing', False)
                ))
                return

            data_proc = now_str()

            for filepath in xml_files:
                filename = os.path.basename(filepath)
                nfe_data, parse_errors = parse_nfe_file(filepath)
                errors.extend(parse_errors)

                if nfe_data is None:
                    continue

                cnpj = nfe_data["cnpj_emitente"]
                for item in nfe_data["itens"]:
                    preco_api = get_price_from_cache(item["codigo_produto"]) or 0.0
                    row = build_result_row(filename, cnpj, item, preco_api, data_proc)
                    insert_resultado(row)
                    results.append(row)

            def done():
                self._set_ui_busy(False)
                self._processing = False
                self._load_results_to_tree()
                msg = f"Processamento concluído: {len(results)} item(s) em {len(xml_files)} arquivo(s)."
                if errors:
                    msg += f" {len(errors)} aviso(s) — veja o log."
                self._set_status(msg, "OK" if not errors else "ALERTA")
                if errors:
                    messagebox.showwarning(
                        "Avisos de Processamento",
                        "\n".join(errors[:15]) + ("\n..." if len(errors) > 15 else "")
                    )

            self.after(0, done)

        threading.Thread(target=task, daemon=True).start()

    def _on_clear_results(self):
        if not messagebox.askyesno("Confirmar", "Deseja excluir TODOS os resultados do banco?"):
            return
        clear_resultados()
        self._load_results_to_tree()
        self._set_status("Resultados limpos.", "INFO")

    def _on_export_excel(self):
        rows = list_resultados()
        if not rows:
            messagebox.showinfo("Sem dados", "Não há resultados para exportar.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile="relatorio_comparacao.xlsx",
            title="Salvar relatório Excel"
        )
        if not path:
            return
        self._set_status("Gerando Excel…", "INFO")

        def task():
            ok = export_excel(rows, path)
            def done():
                if ok:
                    self._set_status(f"Excel exportado: {path}", "OK")
                    messagebox.showinfo("Exportação concluída", f"Arquivo salvo em:\n{path}")
                else:
                    self._set_status("Erro ao exportar Excel. Veja o log.", "ERRO")
                    messagebox.showerror("Erro", "Não foi possível gerar o Excel. Veja o log.")
            self.after(0, done)

        threading.Thread(target=task, daemon=True).start()

    def _on_export_pdf(self):
        rows = list_resultados()
        if not rows:
            messagebox.showinfo("Sem dados", "Não há resultados para exportar.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            initialfile="relatorio_comparacao.pdf",
            title="Salvar relatório PDF"
        )
        if not path:
            return
        self._set_status("Gerando PDF…", "INFO")

        def task():
            ok = export_pdf(rows, path)
            def done():
                if ok:
                    self._set_status(f"PDF exportado: {path}", "OK")
                    messagebox.showinfo("Exportação concluída", f"Arquivo salvo em:\n{path}")
                else:
                    self._set_status("Erro ao exportar PDF. Veja o log.", "ERRO")
                    messagebox.showerror("Erro", "Não foi possível gerar o PDF. Veja o log.")
            self.after(0, done)

        threading.Thread(target=task, daemon=True).start()

    def _on_save_config(self):
        cnpj = self._admin_vars["cnpj"].get().strip()
        cod = self._admin_vars["cod_prod"].get().strip()
        tipo_comb = self._admin_vars["tipo_comb"].get().strip()
        tol_tipo = self._tol_tipo.get().strip()
        tol_valor_str = self._tol_valor.get().strip()

        if not cnpj or not cod:
            messagebox.showwarning("Validação", "CNPJ e Código do Produto são obrigatórios.")
            return
        if tol_tipo not in ("%", "VALOR"):
            messagebox.showwarning("Validação", "Tipo de tolerância deve ser '%' ou 'VALOR'.")
            return
        try:
            tol_valor = float(tol_valor_str)
            if tol_valor < 0:
                raise ValueError("Valor negativo")
        except ValueError:
            messagebox.showwarning("Validação", "Valor de tolerância deve ser um número positivo.")
            return

        ok = upsert_config_fornecedor(cnpj, cod, tipo_comb, tol_tipo, tol_valor)
        if ok:
            messagebox.showinfo("Salvo", "Configuração salva com sucesso.")
            self._load_configs_to_tree()
            for var in self._admin_vars.values():
                var.set("")
            self._tol_valor.set("5.0")
        else:
            messagebox.showerror("Erro", "Não foi possível salvar a configuração. Veja o log.")

    def _on_delete_config(self):
        selected = self._config_tree.selection()
        if not selected:
            messagebox.showwarning("Atenção", "Selecione um item para excluir.")
            return
        item_values = self._config_tree.item(selected[0], "values")
        record_id = int(item_values[0])
        if messagebox.askyesno("Confirmar", f"Excluir configuração ID={record_id}?"):
            delete_config_fornecedor(record_id)
            self._load_configs_to_tree()

    # ─── Helpers de UI ────────────────────────────────────────────────────────

    def _set_status(self, message: str, level: str = "INFO"):
        """Atualiza o label de status com cor conforme o nível."""
        color = STATUS_COLORS.get(level, STATUS_COLORS["INFO"])
        self._lbl_status.configure(text=message, text_color=color)
        logger.info("[STATUS] %s", message)

    def _set_ui_busy(self, busy: bool):
        """Ativa/desativa a barra de progresso e bloqueia botões críticos."""
        if busy:
            self._progress.start()
            self._btn_processar.configure(state="disabled")
            self._btn_cache.configure(state="disabled")
        else:
            self._progress.stop()
            self._btn_processar.configure(state="normal")
            self._btn_cache.configure(state="normal")

    def _load_results_to_tree(self):
        """Recarrega a tabela de resultados do banco para o Treeview."""
        for item in self._tree.get_children():
            self._tree.delete(item)

        rows = list_resultados()
        for row in rows:
            values = (
                row.get("nome_arquivo", ""),
                row.get("cnpj_fornecedor", ""),
                row.get("codigo_produto", ""),
                row.get("descricao", ""),
                f"{row.get('qtd', 0):.4f}",
                f"R$ {row.get('valor_total', 0):,.4f}",
                f"R$ {row.get('preco_xml', 0):,.4f}",
                f"R$ {row.get('preco_api', 0):,.4f}",
                f"R$ {row.get('diff_abs', 0):,.4f}",
                f"{row.get('diff_pct', 0):.2f}%",
                row.get("status", ""),
                row.get("data_processamento", ""),
            )
            tag = row.get("status", "OK")
            self._tree.insert("", "end", values=values, tags=(tag,))

    def _load_configs_to_tree(self):
        """Recarrega a lista de configurações de fornecedores."""
        for item in self._config_tree.get_children():
            self._config_tree.delete(item)

        configs = list_config_fornecedores()
        for cfg in configs:
            self._config_tree.insert("", "end", values=(
                cfg.get("id", ""),
                cfg.get("cnpj", ""),
                cfg.get("codigo_produto", ""),
                cfg.get("tipo_combustivel", ""),
                cfg.get("tolerancia_tipo", ""),
                cfg.get("tolerancia_valor", ""),
            ))
