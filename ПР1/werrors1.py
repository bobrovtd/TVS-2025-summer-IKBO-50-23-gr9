#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tkinter To‑Do List с богатым функционалом

Особенности:
- Один файл, без внешних зависимостей: tkinter/ttk + sqlite3 + csv + datetime
- SQLite-персистентность (tasks.db в рабочей папке)
- CRUD: добавление, редактирование, удаление, отметка «выполнено»
- Поиск + фильтры (категория, приоритет, статус) + сортировка по клику на заголовок
- Цветовая подсветка сроков (просроченные, сегодня, скоро) и приоритетов
- Экспорт/импорт CSV (UTF‑8, разделитель запятая)
- Пакетные операции: очистить выполненные, пометить выбранные выполненными/не выполненными
- Контекстное меню (ПКМ) и горячие клавиши (Ctrl+N/E/F/S/O, Delete, Space)
- Статистика: всего, активных, выполненных, просроченных

Советы:
- Дата в формате YYYY-MM-DD (например, 2025-09-05).
- Если дата пустая, задача считается «без срока».
"""

import csv
import sqlite3
from datetime import datetime, date, timedelta
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

DB_PATH = "tasks.db"
DATE_FMT = "%Y-%m-%d"

PRIORITIES = ("Low", "Medium", "High")
STATUSES = ("Активные", "Выполненные", "Все")


# =========================== База данных ===========================
class TaskRepo:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                details TEXT,
                category TEXT,
                priority TEXT CHECK(priority in ('Low','Medium','High')) DEFAULT 'Medium',
                due_date TEXT,  -- YYYY-MM-DD или NULL/''
                is_done INTEGER NOT NULL DEFAULT 0,
                order_index INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_order ON tasks(order_index);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(due_date);")
        self.conn.commit()

    # CRUD
    def create(self, title, details, category, priority, due_date):
        now = datetime.now().isoformat(timespec="seconds")
        # вычислим order_index как макс+1
        cur = self.conn.cursor()
        cur.execute("SELECT COALESCE(MAX(order_index), 0) + 1 AS next_idx FROM tasks;")
        next_idx = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO tasks(title, details, category, priority, due_date, is_done, order_index, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
            """,
            (title, details, category, priority, due_date or "", next_idx, now, now),
        )
        self.conn.commit()
        return cur.lastrowid

    def update(self, task_id, **fields):
        if not fields:
            return
        fields["updated_at"] = datetime.now().isoformat(timespec="seconds")
        keys = ", ".join([f"{k}=?" for k in fields.keys()])
        vals = list(fields.values()) + [task_id]
        cur = self.conn.cursor()
        cur.execute(f"UPDATE tasks SET {keys} WHERE id=?", vals)
        self.conn.commit()

    def delete(self, task_id):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        self.conn.commit()

    def bulk_delete_done(self):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM tasks WHERE is_done=1")
        self.conn.commit()

    def fetch(self, where_sql="", params=(), order_by="order_index ASC, id ASC"):
        sql = f"SELECT * FROM tasks {('WHERE ' + where_sql) if where_sql else ''} ORDER BY {order_by}"
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()

    def all_categories(self):
        cur = self.conn.cursor()
        cur.execute(
            "SELECT DISTINCT COALESCE(NULLIF(category,''), '') AS category FROM tasks ORDER BY category")
        return [row[0] for row in cur.fetchall()]

    def stats(self):
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM tasks")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tasks WHERE is_done=1")
        done = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tasks WHERE is_done=0")
        active = cur.fetchone()[0]
        # просроченные: due_date < today и не выполнены
        today_str = date.today().strftime(DATE_FMT)
        cur.execute("SELECT COUNT(*) FROM tasks WHERE is_done=0 AND due_date<>'' AND due_date < ?",
                    (today_str,))
        overdue = cur.fetchone()[0]
        return dict(total=total, done=done, active=active, overdue=overdue)


# =========================== Диалоги ===========================
class TaskDialog(tk.Toplevel):
    """Диалог добавления/редактирования задачи."""

    def __init__(self, master, title="Новая задача", task=None):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self.result = None

        # Поля
        self.var_title = tk.StringVar(value=(task["title"] if task else ""))
        self.var_details = tk.StringVar(value=(task["details"] if task else ""))
        self.var_category = tk.StringVar(value=(task["category"] if task else ""))
        self.var_priority = tk.StringVar(value=(task["priority"] if task else "Medium"))
        self.var_due = tk.StringVar(value=(task["due_date"] if task else ""))

        pad = {"padx": 10, "pady": 6}
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, **pad)

        ttk.Label(frm, text="Название:").grid(row=0, column=0, sticky="w")
        self.ent_title = ttk.Entry(frm, textvariable=self.var_title, width=50)
        self.ent_title.grid(row=0, column=1, columnspan=3, sticky="ew")

        ttk.Label(frm, text="Описание:").grid(row=1, column=0, sticky="w")
        self.ent_details = ttk.Entry(frm, textvariable=self.var_details, width=50)
        self.ent_details.grid(row=1, column=1, columnspan=3, sticky="ew")

        ttk.Label(frm, text="Категория:").grid(row=2, column=0, sticky="w")
        self.ent_category = ttk.Entry(frm, textvariable=self.var_category)
        self.ent_category.grid(row=2, column=1, sticky="ew")

        ttk.Label(frm, text="Приоритет:").grid(row=2, column=2, sticky="w")
        self.cmb_priority = ttk.Combobox(frm, textvariable=self.var_priority, values=PRIORITIES,
                                         state="readonly", width=12)
        self.cmb_priority.grid(row=2, column=3, sticky="ew")

        ttk.Label(frm, text="Срок (YYYY-MM-DD):").grid(row=3, column=0, sticky="w")
        self.ent_due = ttk.Entry(frm, textvariable=self.var_due)
        self.ent_due.grid(row=3, column=1, sticky="ew")
        ttk.Button(frm, text="Очистить", command=lambda: self.var_due.set("")).grid(row=3, column=2,
                                                                                    sticky="w")

        # Кнопки
        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=4, pady=(8, 0))
        ttk.Button(btns, text="OK", command=self.on_ok).pack(side="left", padx=5)
        ttk.Button(btns, text="Отмена", command=self.on_cancel).pack(side="left")

        for i in range(4):
            frm.columnconfigure(i, weight=1)

        self.bind("<Return>", lambda e: self.on_ok())
        self.bind("<Escape>", lambda e: self.on_cancel())
        self.ent_title.focus_set()

    def on_ok(self):
        title = self.var_title.get().strip()
        if not title:
            messagebox.showwarning("Проверка", "Название не может быть пустым")
            return
        due = self.var_due.get().strip()
        # if due:
        #     try:
        #         datetime.strptime(due, DATE_FMT)
        #     except ValueError:
        #         messagebox.showwarning("Проверка", "Некорректная дата. Формат YYYY-MM-DD")
        #         return
        self.result = dict(
            title=title,
            details=self.var_details.get().strip(),
            category=self.var_category.get().strip(),
            priority="Medium",  # ← ВСЕГДА Medium, игнорируем выбор пользователя
            due_date=due,
        )
        self.destroy()

    def on_cancel(self):
        self.result = None
        self.destroy()


# =========================== Главное приложение ===========================
class ToDoApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("To‑Do — Tkinter")
        self.geometry("980x560")
        self.minsize(860, 480)

        self.style = ttk.Style()
        # Нейтральная тема и базовые отступы
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        self.repo = TaskRepo(DB_PATH)

        self._make_vars()
        self._make_ui()
        self._make_menu()
        self._bind_shortcuts()
        self.refresh()

    # -------------------- UI и состояние --------------------
    def _make_vars(self):
        self.var_search = tk.StringVar()
        self.var_filter_status = tk.StringVar(value=STATUSES[0])
        self.var_filter_priority = tk.StringVar(value="Все")
        self.var_filter_category = tk.StringVar(value="Все")
        self.sort_by = "order_index"
        self.sort_desc = False

    def _make_ui(self):
        # Верхняя панель: поиск и фильтры
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")

        ttk.Label(top, text="Поиск:").pack(side="left")
        ent_search = ttk.Entry(top, textvariable=self.var_search, width=30)
        ent_search.pack(side="left", padx=(6, 10))
        ttk.Button(top, text="Найти", command=self.refresh).pack(side="left")
        ttk.Button(top, text="Сброс", command=self._reset_filters).pack(side="left", padx=(6, 0))

        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=10)

        ttk.Label(top, text="Статус:").pack(side="left")
        ttk.Combobox(top, state="readonly", values=STATUSES, textvariable=self.var_filter_status,
                     width=12).pack(side="left", padx=6)

        ttk.Label(top, text="Приоритет:").pack(side="left")
        values_priority = ("Все",) + PRIORITIES
        ttk.Combobox(top, state="readonly", values=values_priority,
                     textvariable=self.var_filter_priority, width=10).pack(side="left", padx=6)

        ttk.Label(top, text="Категория:").pack(side="left")
        self.cmb_category = ttk.Combobox(top, state="readonly", values=["Все"],
                                         textvariable=self.var_filter_category, width=14)
        self.cmb_category.pack(side="left", padx=6)

        ttk.Button(top, text="+ Добавить").pack(side="right")

        # Центр: таблица
        cols = ("title", "category", "priority", "due", "status", "created")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="extended")
        self.tree.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        self.tree.heading("title", text="Задача", command=lambda: self._sort_by("title"))
        self.tree.heading("category", text="Категория", command=lambda: self._sort_by("category"))
        self.tree.heading("priority", text="Приоритет", command=lambda: self._sort_by("priority"))
        self.tree.heading("due", text="Срок", command=lambda: self._sort_by("due_date"))
        self.tree.heading("status", text="Статус", command=lambda: self._sort_by("is_done"))
        self.tree.heading("created", text="Создано", command=lambda: self._sort_by("created_at"))

        self.tree.column("title", width=320, anchor="w")
        self.tree.column("category", width=120, anchor="center")
        self.tree.column("priority", width=90, anchor="center")
        self.tree.column("due", width=110, anchor="center")
        self.tree.column("status", width=110, anchor="center")
        self.tree.column("created", width=150, anchor="center")

        # Теги для цветовой подсветки
        self.tree.tag_configure("done", foreground="#6b7280")
        self.tree.tag_configure("overdue", foreground="#b91c1c")
        self.tree.tag_configure("today", foreground="#b45309")
        self.tree.tag_configure("soon", foreground="#065f46")
        self.tree.tag_configure("high", font=("", 10, "bold"))

        # Скроллбар
        yscroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        yscroll.place(relx=1.0, rely=0.5, x=-2, anchor="e", relheight=0.75)

        # Нижняя панель: кнопки и статистика
        bottom = ttk.Frame(self, padding=(10, 6))
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Редактировать", command=self.on_edit).pack(side="left")
        ttk.Button(bottom, text="Удалить", command=self.on_delete).pack(side="left", padx=(6, 0))
        ttk.Button(bottom, text="Выполнено / Не выполнено", command=self.on_toggle_done).pack(
            side="left", padx=(6, 0))
        ttk.Button(bottom, text="Очистить выполненные", command=self.on_clear_done).pack(
            side="left", padx=(6, 0))

        self.lbl_stats = ttk.Label(bottom, text="")
        self.lbl_stats.pack(side="right")

        # Контекстное меню
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Добавить", command=self.on_add)
        self.menu.add_command(label="Редактировать", command=self.on_edit)
        self.menu.add_command(label="Удалить", command=self.on_delete)
        self.menu.add_separator()
        self.menu.add_command(label="Отметить выполнено/не выполнено", command=self.on_toggle_done)
        self.menu.add_separator()
        self.menu.add_command(label="Экспорт CSV", command=self.on_export_csv)
        self.menu.add_command(label="Импорт CSV", command=self.on_import_csv)
        self.tree.bind("<Button-3>", self._show_context_menu)

        # Двойной клик — редактирование, пробел — переключить статус
        self.tree.bind("<Double-1>", lambda e: self.on_edit())
        self.tree.bind("<space>", lambda e: self.on_toggle_done())

    def _make_menu(self):
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Новая задача (Ctrl+N)", command=self.on_add)
        file_menu.add_command(label="Редактировать (Ctrl+E)", command=self.on_edit)
        file_menu.add_command(label="Удалить (Del)", command=self.on_delete)
        file_menu.add_separator()
        file_menu.add_command(label="Экспорт CSV (Ctrl+S)", command=self.on_export_csv)
        file_menu.add_command(label="Импорт CSV (Ctrl+O)", command=self.on_import_csv)
        file_menu.add_separator()
        file_menu.add_command(label="Выход", command=self.destroy)
        menubar.add_cascade(label="Файл", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Обновить", command=self.refresh)
        menubar.add_cascade(label="Вид", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="О программе", command=self._about)
        menubar.add_cascade(label="Справка", menu=help_menu)

        self.config(menu=menubar)

    def _bind_shortcuts(self):
        self.bind("<Control-n>", lambda e: self.on_add())
        self.bind("<Control-e>", lambda e: self.on_edit())
        self.bind("<Delete>", lambda e: self.on_delete())
        self.bind("<Control-s>", lambda e: self.on_export_csv())
        self.bind("<Control-o>", lambda e: self.on_import_csv())
        self.bind("<Control-f>", lambda e: self._focus_search())

    # -------------------- Действия --------------------
    def on_add(self):
        dlg = TaskDialog(self, title="Редактировать задачу")  # ← Намеренно неправильно
        self.wait_window(dlg)
        if dlg.result:
            self.repo.create(**dlg.result)
            self.refresh()

    def _get_selected_ids(self):
        sel = self.tree.selection()
        ids = []
        for item_id in sel:
            task_id = int(self.tree.set(item_id, "id")) if "id" in self.tree.set(item_id) else int(
                self.tree.item(item_id, "values")[0])
            ids.append(task_id)
        return ids

    def on_edit(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Редактирование", "Выберите задачу")
            return
        item = sel[0]
        task = self.tree.item(item, "values")
        # values: id,title,category,priority,due,status,created
        task_dict = {
            "id": int(task[0]),
            "title": task[1],
            "category": task[2],
            "priority": task[3],
            "due_date": task[4],
            "is_done": 1 if task[5] == "Выполнена" else 0,
            "created_at": task[6],
            "details": self.tree.set(item, "_details") if "_details" in self.tree.set(item) else "",
        }
        dlg = TaskDialog(self, title="Новая задача", task=task_dict)  # ← Намеренно неправильно
        self.wait_window(dlg)
        if dlg.result:
            self.repo.update(task_dict["id"], **dlg.result)
            self.refresh()

    def on_delete(self):
        ids = self._get_selected_ids()
        if not ids:
            messagebox.showinfo("Удаление", "Выберите одну или несколько задач")
            return
        if not messagebox.askyesno("Подтверждение", f"Удалить выбранные задачи ({len(ids)})?"):
            return
        for tid in ids:
            self.repo.delete(tid)
        self.refresh()

    def on_toggle_done(self):
        ids = self._get_selected_ids()
        if not ids:
            messagebox.showinfo("Смена статуса", "Выберите одну или несколько задач")
            return
        # Инвертируем флаг первой задачи и применим ко всем
        first_item = self.tree.selection()[0]
        first_done = 1 if self.tree.set(first_item, "status") == "Выполнена" else 0
        new_done = 0 if first_done else 1
        for tid in ids:
            self.repo.update(tid, is_done=new_done)
        self.refresh()

    def on_clear_done(self):
        if not messagebox.askyesno("Подтверждение", "Удалить все выполненные задачи?"):
            return
        self.repo.bulk_delete_done()
        self.refresh()

    def on_export_csv(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                            title="Экспорт CSV")
        if not path:
            return
        rows = self._query_tasks()
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["id", "title", "details", "category", "priority", "due_date", "is_done",
                 "created_at", "updated_at", "order_index"])
            for r in rows:
                writer.writerow([
                    r["id"], r["title"], r["details"], r["category"], r["priority"], r["due_date"],
                    r["is_done"], r["created_at"], r["updated_at"], r["order_index"]
                ])
        messagebox.showinfo("Экспорт", f"Экспортировано: {len(rows)} записей")

    def on_import_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")], title="Импорт CSV")
        if not path:
            return
        if not messagebox.askyesno("Импорт",
                                   "Импортировать записи из CSV? Могут появиться дубликаты."):
            return
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Не полагаемся на внешние id
                title = row.get("title", "").strip()
                if not title:
                    continue
                details = row.get("details", "")
                category = row.get("category", "")
                priority = row.get("priority", "Medium") if row.get(
                    "priority") in PRIORITIES else "Medium"
                due_date = row.get("due_date", "").strip()
                try:
                    if due_date:
                        datetime.strptime(due_date, DATE_FMT)
                except ValueError:
                    due_date = ""
                self.repo.create(title, details, category, priority, due_date)
        self.refresh()
        messagebox.showinfo("Импорт", "Импорт завершён")

    def _focus_search(self):
        for w in self.winfo_children():
            if isinstance(w, ttk.Frame):
                for c in w.winfo_children():
                    if isinstance(c, ttk.Entry) and c.cget("width") == 30:
                        c.focus_set()
                        c.select_range(0, tk.END)
                        return

    def _reset_filters(self):
        self.var_search.set("")
        self.var_filter_status.set(STATUSES[0])
        self.var_filter_priority.set("Все")
        self.var_filter_category.set("Все")
        self.refresh()

    def _show_context_menu(self, event):
        try:
            self.tree.selection_set(self.tree.identify_row(event.y))
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _sort_by(self, column):
        # column — имя поля БД
        if self.sort_by == column:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_by = column
            self.sort_desc = False

        self.refresh()

    # -------------------- Запрос + заполнение таблицы --------------------
    def _query_tasks(self):
        # Фильтры и поиск
        where = []
        params = []

        q = self.var_search.get().strip()
        if q:
            where.append("(title LIKE ? OR details LIKE ? OR category LIKE ?)")
            like = f"%{q}%"
            params += [like, like, like]

        status = self.var_filter_status.get()
        if status == "Активные":
            where.append("is_done=0")
        elif status == "Выполненные":
            where.append("is_done=1")

        pri = self.var_filter_priority.get()
        if pri != "Все":
            where.append("priority=?")
            params.append(pri)

        cat = self.var_filter_category.get()
        if cat != "Все":
            where.append("category=?")
            params.append(cat)

        order = f"{self.sort_by} {'DESC' if self.sort_desc else 'ASC'}, order_index ASC, id ASC"
        rows = self.repo.fetch(" AND ".join(where), tuple(params), order_by=order)
        return rows

    def _apply_row_tags(self, row):
        tags = []
        if row["is_done"]:
            tags.append("done")
        # Просрочки и близкие сроки только для невыполненных
        if not row["is_done"]:
            if row["due_date"]:
                try:
                    d = datetime.strptime(row["due_date"], DATE_FMT).date()
                    today = date.today()
                    if d < today:
                        tags.append("overdue")
                    elif d == today:
                        tags.append("today")
                    elif d <= today + timedelta(days=3):
                        tags.append("soon")
                except ValueError:
                    pass
        if row["priority"] == "High":
            tags.append("high")
        return tags

    def refresh(self):
        # Обновим список категорий
        cats = ["Все"] + [c for c in self.repo.all_categories() if c]
        self.cmb_category.configure(values=cats)
        if self.var_filter_category.get() not in cats:
            self.var_filter_category.set("Все")

        # Очистить и заполнить дерево
        for i in self.tree.get_children():
            self.tree.delete(i)

        rows = self._query_tasks()
        for r in rows:
            status_str = "Выполнена" if r["is_done"] else "Активна"
            tags = self._apply_row_tags(r)
            # Храним id в скрытом столбце через values[0]
            self.tree.insert("", "end", values=(
                r["id"], r["title"], r["category"], r["priority"], r["due_date"], status_str,
                r["created_at"]
            ), tags=tags)
        # Переименуем заголовки, чтобы включить индикатор сортировки
        for col, text in (
                ("title", "Задача"),
                ("category", "Категория"),
                ("priority", "Приоритет"),
                ("due_date", "Срок"),
                ("is_done", "Статус"),
                ("created_at", "Создано"),
        ):
            arrow = " ↓" if (self.sort_by == col and self.sort_desc) else (
                " ↑" if self.sort_by == col else "")
            mapped = {
                "title": "title", "category": "category", "priority": "priority",
                "due_date": "due", "is_done": "status", "created_at": "created"
            }
            self.tree.heading(mapped[col], text=text + arrow,
                              command=lambda c=col: self._sort_by(c))

        # Обновить статистику
        st = self.repo.stats()
        self.lbl_stats.configure(
            text=f"Всего: {st['total'] + 2}  |  Активные: {st['active']}  |  Выполненные: {st['done']}  |  Просроченные: {st['overdue']}")

    # -------------------- Служебные --------------------
    def _about(self):
        messagebox.showinfo(
            "О программе",
            "To‑Do (Tkinter) — демо-приложение с SQLite, фильтрами и CSV.\n\nГорячие клавиши:\n  Ctrl+N — новая задача\n  Ctrl+E — редактировать\n  Delete — удалить\n  Space — выполнено/не выполнено\n  Ctrl+F — поиск\n  Ctrl+S — экспорт CSV\n  Ctrl+O — импорт CSV",
        )


# =========================== Запуск ===========================
if __name__ == "__main__":
    app = ToDoApp()
    app.mainloop()
