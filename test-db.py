from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class RowEditorDialog(QDialog):
    def __init__(
        self,
        columns: list[dict[str, Any]],
        values: dict[str, Any] | None = None,
        *,
        parent: QWidget | None = None,
        is_insert: bool,
    ) -> None:
        super().__init__(parent)
        self.columns = columns
        self.values = values or {}
        self.is_insert = is_insert
        self.inputs: dict[str, QPlainTextEdit] = {}

        self.setWindowTitle("Добавить запись" if is_insert else "Изменить запись")
        self.resize(700, 520)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        for column in columns:
            editor = QPlainTextEdit()
            editor.setMinimumHeight(70)
            editor.setPlainText(self._format_value(self.values.get(column["name"])))
            if column["pk"] and not is_insert:
                editor.setReadOnly(True)
            placeholder = column["type"] or "TEXT"
            if column["notnull"]:
                placeholder += " | NOT NULL"
            editor.setPlaceholderText(placeholder)
            self.inputs[column["name"]] = editor
            form.addRow(column["name"], editor)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_button = QPushButton("Сохранить")
        save_button.clicked.connect(self.accept)
        buttons.addWidget(save_button)
        cancel_button = QPushButton("Отмена")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

    @staticmethod
    def _format_value(value: Any) -> str:
        return "" if value is None else str(value)

    def get_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for column in self.columns:
            raw_text = self.inputs[column["name"]].toPlainText().strip()
            if column["pk"] and self.is_insert and raw_text == "":
                continue
            payload[column["name"]] = self._convert_value(column, raw_text)
        return payload

    def _convert_value(self, column: dict[str, Any], raw_text: str) -> Any:
        if raw_text == "":
            return None

        column_type = (column["type"] or "").upper()
        try:
            if "INT" in column_type:
                return int(raw_text)
            if any(marker in column_type for marker in ("REAL", "FLOA", "DOUB")):
                return float(raw_text)
        except ValueError as error:
            raise ValueError(
                f"Поле '{column['name']}' ожидает тип {column['type'] or 'TEXT'}."
            ) from error
        return raw_text


class TableViewerDialog(QDialog):
    def __init__(self, db_path: Path, table_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db_path = db_path
        self.table_name = table_name
        self.columns = self._load_columns()
        self.primary_key = next(
            (column["name"] for column in self.columns if column["pk"]),
            None,
        )
        self.uses_rowid = self.primary_key is None
        self.page_size = 25
        self.current_page = 0
        self.total_rows = 0
        self.current_records: list[dict[str, Any]] = []

        self.setWindowTitle(f"Таблица: {table_name}")
        self.resize(1100, 760)

        layout = QVBoxLayout(self)

        controls = QHBoxLayout()
        self.page_info_label = QLabel()
        controls.addWidget(self.page_info_label)
        controls.addStretch(1)
        controls.addWidget(QLabel("Строк на страницу:"))
        self.page_size_spin = QSpinBox()
        self.page_size_spin.setRange(5, 500)
        self.page_size_spin.setValue(self.page_size)
        self.page_size_spin.valueChanged.connect(self.on_page_size_changed)
        controls.addWidget(self.page_size_spin)

        self.prev_button = QPushButton("Назад")
        self.prev_button.clicked.connect(self.go_prev_page)
        controls.addWidget(self.prev_button)

        self.next_button = QPushButton("Вперёд")
        self.next_button.clicked.connect(self.go_next_page)
        controls.addWidget(self.next_button)

        refresh_button = QPushButton("Обновить")
        refresh_button.clicked.connect(self.load_page)
        controls.addWidget(refresh_button)
        layout.addLayout(controls)

        self.table_widget = QTableWidget(0, 0)
        self.table_widget.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_widget.setSelectionMode(QTableWidget.SingleSelection)
        self.table_widget.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table_widget, 1)

        actions = QHBoxLayout()
        add_button = QPushButton("Добавить")
        add_button.clicked.connect(self.add_record)
        actions.addWidget(add_button)
        self.edit_button = QPushButton("Изменить")
        self.edit_button.clicked.connect(self.edit_record)
        actions.addWidget(self.edit_button)
        self.delete_button = QPushButton("Удалить")
        self.delete_button.clicked.connect(self.delete_record)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.load_page()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _load_columns(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                f"PRAGMA table_info({quote_identifier(self.table_name)})"
            ).fetchall()
        return [
            {
                "cid": row["cid"],
                "name": row["name"],
                "type": row["type"],
                "notnull": bool(row["notnull"]),
                "default": row["dflt_value"],
                "pk": bool(row["pk"]),
            }
            for row in rows
        ]

    def load_page(self) -> None:
        limit = self.page_size
        offset = self.current_page * self.page_size
        order_column = self.primary_key or "rowid"
        select_prefix = "rowid AS __rowid__, " if self.uses_rowid else ""

        with self.connect() as connection:
            self.total_rows = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {quote_identifier(self.table_name)}"
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT {select_prefix}*
                FROM {quote_identifier(self.table_name)}
                ORDER BY {quote_identifier(order_column)}
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

        self.current_records = [dict(row) for row in rows]
        visible_columns = (
            ["__rowid__"] + [column["name"] for column in self.columns]
            if self.uses_rowid
            else [column["name"] for column in self.columns]
        )
        self.table_widget.setColumnCount(len(visible_columns))
        self.table_widget.setHorizontalHeaderLabels(visible_columns)
        self.table_widget.setRowCount(len(self.current_records))

        for row_index, record in enumerate(self.current_records):
            for column_index, column_name in enumerate(visible_columns):
                value = record.get(column_name)
                item = QTableWidgetItem("" if value is None else str(value))
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                if column_index == 0:
                    item.setData(Qt.UserRole, record)
                self.table_widget.setItem(row_index, column_index, item)

        self.table_widget.resizeColumnsToContents()
        self._update_page_info()

    def _update_page_info(self) -> None:
        if self.total_rows == 0:
            self.page_info_label.setText("Строк нет")
            self.prev_button.setEnabled(False)
            self.next_button.setEnabled(False)
            self.edit_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            return

        start_row = self.current_page * self.page_size + 1
        end_row = min((self.current_page + 1) * self.page_size, self.total_rows)
        total_pages = max(1, (self.total_rows + self.page_size - 1) // self.page_size)
        self.page_info_label.setText(
            f"Строки {start_row}-{end_row} из {self.total_rows} | Страница {self.current_page + 1}/{total_pages}"
        )
        self.prev_button.setEnabled(self.current_page > 0)
        self.next_button.setEnabled(end_row < self.total_rows)
        has_rows = bool(self.current_records)
        self.edit_button.setEnabled(has_rows)
        self.delete_button.setEnabled(has_rows)

    def on_page_size_changed(self, value: int) -> None:
        self.page_size = value
        self.current_page = 0
        self.load_page()

    def go_prev_page(self) -> None:
        if self.current_page > 0:
            self.current_page -= 1
            self.load_page()

    def go_next_page(self) -> None:
        if (self.current_page + 1) * self.page_size < self.total_rows:
            self.current_page += 1
            self.load_page()

    def get_selected_record(self) -> dict[str, Any] | None:
        row_index = self.table_widget.currentRow()
        if row_index < 0:
            return None
        item = self.table_widget.item(row_index, 0)
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def add_record(self) -> None:
        dialog = RowEditorDialog(self.columns, parent=self, is_insert=True)
        if dialog.exec_() != QDialog.Accepted:
            return
        try:
            payload = dialog.get_payload()
            columns = [name for name, value in payload.items() if value is not None]
            values = [payload[name] for name in columns]
            if not columns:
                QMessageBox.warning(self, "SQLite", "Нет данных для вставки.")
                return
            placeholders = ", ".join("?" for _ in columns)
            query = (
                f"INSERT INTO {quote_identifier(self.table_name)} "
                f"({', '.join(quote_identifier(name) for name in columns)}) "
                f"VALUES ({placeholders})"
            )
            with self.connect() as connection:
                connection.execute(query, values)
                connection.commit()
        except ValueError as error:
            QMessageBox.warning(self, "SQLite", str(error))
            return
        self.load_page()

    def edit_record(self) -> None:
        record = self.get_selected_record()
        if record is None:
            QMessageBox.information(self, "SQLite", "Выберите строку для изменения.")
            return

        dialog = RowEditorDialog(
            self.columns,
            values=record,
            parent=self,
            is_insert=False,
        )
        if dialog.exec_() != QDialog.Accepted:
            return

        try:
            payload = dialog.get_payload()
            key_name = self.primary_key or "__rowid__"
            if key_name not in record:
                QMessageBox.warning(
                    self,
                    "SQLite",
                    "Не удалось определить ключ записи для обновления.",
                )
                return
            update_fields = [
                column["name"]
                for column in self.columns
                if column["name"] in payload and column["name"] != self.primary_key
            ]
            if not update_fields:
                QMessageBox.information(self, "SQLite", "Нет данных для обновления.")
                return
            query = (
                f"UPDATE {quote_identifier(self.table_name)} SET "
                + ", ".join(f"{quote_identifier(name)} = ?" for name in update_fields)
                + f" WHERE {quote_identifier(self.primary_key or 'rowid')} = ?"
            )
            values = [payload[name] for name in update_fields]
            values.append(record[key_name])
            with self.connect() as connection:
                connection.execute(query, values)
                connection.commit()
        except ValueError as error:
            QMessageBox.warning(self, "SQLite", str(error))
            return
        self.load_page()

    def delete_record(self) -> None:
        record = self.get_selected_record()
        if record is None:
            QMessageBox.information(self, "SQLite", "Выберите строку для удаления.")
            return
        key_name = self.primary_key or "__rowid__"
        key_value = record.get(key_name)
        if key_value is None:
            QMessageBox.warning(self, "SQLite", "Не удалось определить ключ записи.")
            return

        confirmation = QMessageBox.question(
            self,
            "SQLite",
            f"Удалить запись {key_name}={key_value} из таблицы {self.table_name}?",
        )
        if confirmation != QMessageBox.Yes:
            return

        with self.connect() as connection:
            connection.execute(
                f"DELETE FROM {quote_identifier(self.table_name)} "
                f"WHERE {quote_identifier(self.primary_key or 'rowid')} = ?",
                (key_value,),
            )
            connection.commit()
        if self.current_page > 0 and self.current_page * self.page_size >= max(
            self.total_rows - 1, 0
        ):
            self.current_page -= 1
        self.load_page()


class DatabaseBrowserWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.db_path: Path | None = None
        self.setWindowTitle("SQLite Test DB")
        self.resize(900, 640)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        file_controls = QHBoxLayout()
        file_controls.addWidget(QLabel("SQLite файл:"))
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Выберите файл .db или .sqlite")
        file_controls.addWidget(self.path_input, 1)
        browse_button = QPushButton("Выбрать")
        browse_button.clicked.connect(self.choose_database_file)
        file_controls.addWidget(browse_button)
        open_button = QPushButton("Загрузить")
        open_button.clicked.connect(self.load_tables)
        file_controls.addWidget(open_button)
        layout.addLayout(file_controls)

        self.tables_widget = QTableWidget(0, 3)
        self.tables_widget.setHorizontalHeaderLabels(["Таблица", "Строк", "Открыть"])
        self.tables_widget.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tables_widget.setSelectionBehavior(QTableWidget.SelectRows)
        self.tables_widget.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.tables_widget, 1)

        self.status_label = QLabel("Выберите SQLite-файл для просмотра.")
        layout.addWidget(self.status_label)

        default_path = Path.cwd() / "chatlist.db"
        if default_path.exists():
            self.path_input.setText(str(default_path))
            self.load_tables()

    def choose_database_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите SQLite файл",
            str(Path.cwd()),
            "SQLite files (*.db *.sqlite *.sqlite3);;All files (*.*)",
        )
        if file_path:
            self.path_input.setText(file_path)
            self.load_tables()

    def connect(self) -> sqlite3.Connection:
        if self.db_path is None:
            raise RuntimeError("SQLite файл не выбран.")
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def load_tables(self) -> None:
        candidate = Path(self.path_input.text().strip())
        if not candidate.exists():
            QMessageBox.warning(self, "SQLite", "Укажите существующий SQLite-файл.")
            return

        self.db_path = candidate
        try:
            with self.connect() as connection:
                rows = connection.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                    ORDER BY name
                    """
                ).fetchall()
                table_names = [row["name"] for row in rows]

                self.tables_widget.setRowCount(len(table_names))
                for row_index, table_name in enumerate(table_names):
                    count = int(
                        connection.execute(
                            f"SELECT COUNT(*) FROM {quote_identifier(table_name)}"
                        ).fetchone()[0]
                    )
                    name_item = QTableWidgetItem(table_name)
                    name_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                    count_item = QTableWidgetItem(str(count))
                    count_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                    open_button = QPushButton("Открыть")
                    open_button.clicked.connect(
                        lambda _checked=False, name=table_name: self.open_table(name)
                    )

                    self.tables_widget.setItem(row_index, 0, name_item)
                    self.tables_widget.setItem(row_index, 1, count_item)
                    self.tables_widget.setCellWidget(row_index, 2, open_button)

                self.tables_widget.resizeColumnsToContents()
                self.status_label.setText(
                    f"Загружено таблиц: {len(table_names)} | Файл: {candidate}"
                )
        except sqlite3.Error as error:
            QMessageBox.critical(self, "SQLite", f"Не удалось открыть базу: {error}")

    def open_table(self, table_name: str) -> None:
        if self.db_path is None:
            QMessageBox.warning(self, "SQLite", "Сначала выберите SQLite-файл.")
            return
        dialog = TableViewerDialog(self.db_path, table_name, self)
        dialog.exec_()
        self.load_tables()


def main() -> int:
    app = QApplication(sys.argv)
    window = DatabaseBrowserWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
