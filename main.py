from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PyQt5.QtCore import QThread, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from db import DEFAULT_SETTINGS, Database
from app_paths import get_app_base_dir
from models import ModelConfig, ModelRepository
from network import NetworkClient, NetworkResult, get_env_search_paths


LOGS_DIR = get_app_base_dir() / "logs"
LOG_FILE = LOGS_DIR / "chatlist.log"


@dataclass(slots=True)
class RuntimeResult:
    model_id: int | None
    model_name: str
    response_text: str
    status: str
    error_text: str | None = None
    selected: bool = True

    def export_record(self, prompt_text: str) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "prompt_text": prompt_text,
            "response_text": self.response_text,
            "status": self.status,
            "error_text": self.error_text,
            "selected": self.selected,
        }

    @property
    def display_text(self) -> str:
        if self.response_text:
            return self.response_text
        return self.error_text or ""


class RequestWorker(QThread):
    progress = pyqtSignal(str)
    result_ready = pyqtSignal(object)
    batch_finished = pyqtSignal(object)

    def __init__(
        self,
        network_client: NetworkClient,
        models: list[ModelConfig],
        prompt: str,
        system_prompt: str,
        temperature: float,
    ) -> None:
        super().__init__()
        self.network_client = network_client
        self.models = models
        self.prompt = prompt
        self.system_prompt = system_prompt
        self.temperature = temperature

    def run(self) -> None:
        results: list[NetworkResult] = []
        for model in self.models:
            self.progress.emit(f"Отправка запроса в {model.name}...")
            result = self.network_client.send_prompt(
                model=model,
                prompt=self.prompt,
                system_prompt=self.system_prompt or None,
                temperature=self.temperature,
            )
            results.append(result)
            self.result_ready.emit(result)
        self.batch_finished.emit(results)


def bootstrap_database() -> Database:
    database = Database()
    database.initialize()
    return database


class MainWindow(QMainWindow):
    def __init__(
        self,
        database: Database,
        model_repository: ModelRepository,
        network_client: NetworkClient,
    ) -> None:
        super().__init__()
        self.database = database
        self.model_repository = model_repository
        self.network_client = network_client
        self.runtime_results: list[RuntimeResult] = []
        self.current_prompt_id: int | None = None
        self._results_table_updating = False
        self._worker: RequestWorker | None = None

        self.setWindowTitle("ChatList")
        self._setup_ui()
        self._setup_window_size()
        self._ensure_initial_data()
        self.refresh_all_views()
        self.log_event("Приложение запущено.")

    def _setup_window_size(self) -> None:
        width = self.get_int_setting("window_width", 1400)
        height = self.get_int_setting("window_height", 900)
        self.resize(width, height)

    def _setup_ui(self) -> None:
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        self._build_request_tab()
        self._build_saved_results_tab()
        self._build_models_tab()
        self._build_settings_tab()
        self._build_logs_tab()

    def _build_request_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form_group = QGroupBox("Новый запрос")
        form_layout = QVBoxLayout(form_group)

        self.prompt_input = QPlainTextEdit()
        self.prompt_input.setPlaceholderText("Введите промт для отправки в активные модели...")
        self.prompt_input.setMinimumHeight(140)
        form_layout.addWidget(self.prompt_input)

        meta_layout = QHBoxLayout()
        meta_layout.addWidget(QLabel("Теги:"))
        self.tags_input = QLineEdit()
        self.tags_input.setPlaceholderText("Например: сравнение, python, идеи")
        meta_layout.addWidget(self.tags_input, 1)
        self.current_prompt_label = QLabel("Текущий промт: новый")
        meta_layout.addWidget(self.current_prompt_label)
        form_layout.addLayout(meta_layout)

        button_layout = QHBoxLayout()
        self.send_button = QPushButton("Отправить")
        self.send_button.clicked.connect(self.send_prompt)
        button_layout.addWidget(self.send_button)

        self.clear_prompt_button = QPushButton("Очистить")
        self.clear_prompt_button.clicked.connect(self.clear_prompt_form)
        button_layout.addWidget(self.clear_prompt_button)

        self.save_selected_button = QPushButton("Сохранить выбранное")
        self.save_selected_button.clicked.connect(self.save_selected_results)
        button_layout.addWidget(self.save_selected_button)

        self.export_runtime_md_button = QPushButton("Экспорт MD")
        self.export_runtime_md_button.clicked.connect(
            lambda: self.export_runtime_results("markdown")
        )
        button_layout.addWidget(self.export_runtime_md_button)

        self.export_runtime_json_button = QPushButton("Экспорт JSON")
        self.export_runtime_json_button.clicked.connect(
            lambda: self.export_runtime_results("json")
        )
        button_layout.addWidget(self.export_runtime_json_button)

        button_layout.addStretch(1)
        form_layout.addLayout(button_layout)

        layout.addWidget(form_group)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        prompts_panel = QWidget()
        prompts_layout = QVBoxLayout(prompts_panel)
        prompts_search_layout = QHBoxLayout()
        prompts_search_layout.addWidget(QLabel("Поиск промтов:"))
        self.prompts_search_input = QLineEdit()
        self.prompts_search_input.textChanged.connect(self.refresh_prompts_table)
        prompts_search_layout.addWidget(self.prompts_search_input, 1)
        self.refresh_prompts_button = QPushButton("Обновить")
        self.refresh_prompts_button.clicked.connect(self.refresh_prompts_table)
        prompts_search_layout.addWidget(self.refresh_prompts_button)
        prompts_layout.addLayout(prompts_search_layout)

        self.prompts_table = QTableWidget(0, 4)
        self.prompts_table.setHorizontalHeaderLabels(
            ["ID", "Дата", "Теги", "Промт"]
        )
        self.prompts_table.setSortingEnabled(True)
        self.prompts_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.prompts_table.setSelectionMode(QTableWidget.SingleSelection)
        self.prompts_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.prompts_table.cellDoubleClicked.connect(self.load_selected_prompt)
        self.prompts_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch
        )
        self.prompts_table.setColumnHidden(0, True)
        prompts_layout.addWidget(self.prompts_table)

        prompts_action_layout = QHBoxLayout()
        self.load_prompt_button = QPushButton("Загрузить промт")
        self.load_prompt_button.clicked.connect(self.load_selected_prompt)
        prompts_action_layout.addWidget(self.load_prompt_button)
        self.new_prompt_button = QPushButton("Новый промт")
        self.new_prompt_button.clicked.connect(self.clear_prompt_form)
        prompts_action_layout.addWidget(self.new_prompt_button)
        self.add_prompt_button = QPushButton("Добавить")
        self.add_prompt_button.clicked.connect(self.create_prompt_from_form)
        prompts_action_layout.addWidget(self.add_prompt_button)
        self.update_prompt_button = QPushButton("Обновить")
        self.update_prompt_button.clicked.connect(self.update_selected_prompt)
        prompts_action_layout.addWidget(self.update_prompt_button)
        self.delete_prompt_button = QPushButton("Удалить")
        self.delete_prompt_button.clicked.connect(self.delete_selected_prompt)
        prompts_action_layout.addWidget(self.delete_prompt_button)
        prompts_action_layout.addStretch(1)
        prompts_layout.addLayout(prompts_action_layout)

        results_panel = QWidget()
        results_layout = QVBoxLayout(results_panel)
        results_search_layout = QHBoxLayout()
        results_search_layout.addWidget(QLabel("Поиск результатов:"))
        self.runtime_results_search_input = QLineEdit()
        self.runtime_results_search_input.textChanged.connect(
            self.refresh_runtime_results_table
        )
        results_search_layout.addWidget(self.runtime_results_search_input, 1)
        self.select_all_button = QPushButton("Выбрать все")
        self.select_all_button.clicked.connect(lambda: self.set_all_runtime_selected(True))
        results_search_layout.addWidget(self.select_all_button)
        self.clear_selection_button = QPushButton("Снять все")
        self.clear_selection_button.clicked.connect(
            lambda: self.set_all_runtime_selected(False)
        )
        results_search_layout.addWidget(self.clear_selection_button)
        results_layout.addLayout(results_search_layout)

        self.runtime_results_table = QTableWidget(0, 4)
        self.runtime_results_table.setHorizontalHeaderLabels(
            ["Selected", "Модель", "Статус", "Ответ"]
        )
        self.runtime_results_table.setSortingEnabled(True)
        self.runtime_results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.runtime_results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.runtime_results_table.setWordWrap(True)
        self.runtime_results_table.setTextElideMode(Qt.ElideNone)
        self.runtime_results_table.verticalHeader().setDefaultSectionSize(72)
        self.runtime_results_table.verticalHeader().setMinimumSectionSize(56)
        self.runtime_results_table.itemChanged.connect(self.on_runtime_result_changed)
        self.runtime_results_table.itemSelectionChanged.connect(
            self.update_runtime_preview
        )
        self.runtime_results_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch
        )
        results_layout.addWidget(self.runtime_results_table, 1)

        runtime_preview_group = QGroupBox("Предпросмотр ответа")
        runtime_preview_layout = QVBoxLayout(runtime_preview_group)
        runtime_preview_actions = QHBoxLayout()
        runtime_preview_actions.addStretch(1)
        self.open_runtime_markdown_button = QPushButton("Открыть")
        self.open_runtime_markdown_button.clicked.connect(
            self.open_runtime_preview_markdown
        )
        self.open_runtime_markdown_button.setEnabled(False)
        runtime_preview_actions.addWidget(self.open_runtime_markdown_button)
        runtime_preview_layout.addLayout(runtime_preview_actions)
        self.runtime_preview = QPlainTextEdit()
        self.runtime_preview.setReadOnly(True)
        self.runtime_preview.setPlaceholderText(
            "Выберите строку результата, чтобы увидеть полный ответ."
        )
        self.runtime_preview.setMinimumHeight(180)
        runtime_preview_layout.addWidget(self.runtime_preview)
        results_layout.addWidget(runtime_preview_group)

        splitter.addWidget(prompts_panel)
        splitter.addWidget(results_panel)
        splitter.setSizes([420, 900])

        self.tabs.addTab(tab, "Запрос")

    def _build_saved_results_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Поиск:"))
        self.saved_results_search_input = QLineEdit()
        self.saved_results_search_input.textChanged.connect(
            self.refresh_saved_results_table
        )
        controls.addWidget(self.saved_results_search_input, 1)

        refresh_button = QPushButton("Обновить")
        refresh_button.clicked.connect(self.refresh_saved_results_table)
        controls.addWidget(refresh_button)

        export_md_button = QPushButton("Экспорт MD")
        export_md_button.clicked.connect(lambda: self.export_saved_results("markdown"))
        controls.addWidget(export_md_button)

        export_json_button = QPushButton("Экспорт JSON")
        export_json_button.clicked.connect(lambda: self.export_saved_results("json"))
        controls.addWidget(export_json_button)
        layout.addLayout(controls)

        self.saved_results_table = QTableWidget(0, 5)
        self.saved_results_table.setHorizontalHeaderLabels(
            ["ID", "Дата", "Модель", "Промт", "Ответ"]
        )
        self.saved_results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.saved_results_table.setSelectionMode(QTableWidget.MultiSelection)
        self.saved_results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.saved_results_table.setSortingEnabled(True)
        self.saved_results_table.setWordWrap(True)
        self.saved_results_table.setTextElideMode(Qt.ElideNone)
        self.saved_results_table.verticalHeader().setDefaultSectionSize(72)
        self.saved_results_table.verticalHeader().setMinimumSectionSize(56)
        self.saved_results_table.itemSelectionChanged.connect(self.update_saved_preview)
        self.saved_results_table.setColumnHidden(0, True)
        self.saved_results_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.Stretch
        )
        layout.addWidget(self.saved_results_table, 1)

        saved_preview_group = QGroupBox("Предпросмотр ответа")
        saved_preview_layout = QVBoxLayout(saved_preview_group)
        saved_preview_actions = QHBoxLayout()
        saved_preview_actions.addStretch(1)
        self.open_saved_markdown_button = QPushButton("Открыть")
        self.open_saved_markdown_button.clicked.connect(self.open_saved_preview_markdown)
        self.open_saved_markdown_button.setEnabled(False)
        saved_preview_actions.addWidget(self.open_saved_markdown_button)
        saved_preview_layout.addLayout(saved_preview_actions)
        self.saved_preview = QPlainTextEdit()
        self.saved_preview.setReadOnly(True)
        self.saved_preview.setPlaceholderText(
            "Выберите сохранённый результат, чтобы увидеть полный ответ."
        )
        self.saved_preview.setMinimumHeight(220)
        saved_preview_layout.addWidget(self.saved_preview)
        layout.addWidget(saved_preview_group)

        self.tabs.addTab(tab, "Сохраненные")

    def _build_models_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Поиск моделей:"))
        self.models_search_input = QLineEdit()
        self.models_search_input.textChanged.connect(self.refresh_models_table)
        controls.addWidget(self.models_search_input, 1)

        refresh_button = QPushButton("Обновить")
        refresh_button.clicked.connect(self.refresh_models_table)
        controls.addWidget(refresh_button)

        seed_button = QPushButton("Добавить дефолтные")
        seed_button.clicked.connect(self.seed_default_models)
        controls.addWidget(seed_button)

        activate_button = QPushButton("Активировать по .env")
        activate_button.clicked.connect(self.activate_models_from_env)
        controls.addWidget(activate_button)

        detect_openrouter_button = QPushButton("Подстроить OpenRouter")
        detect_openrouter_button.clicked.connect(self.auto_configure_openrouter_env)
        controls.addWidget(detect_openrouter_button)
        layout.addLayout(controls)

        self.models_table = QTableWidget(0, 7)
        self.models_table.setHorizontalHeaderLabels(
            ["ID", "Active", "Name", "API URL", "API ID", "Env", "Тест"]
        )
        self.models_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.models_table.setSelectionMode(QTableWidget.SingleSelection)
        self.models_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.models_table.setSortingEnabled(True)
        self.models_table.cellClicked.connect(self.load_selected_model)
        self.models_table.setColumnHidden(0, True)
        self.models_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch
        )
        self.models_table.horizontalHeader().setSectionResizeMode(
            6, QHeaderView.ResizeToContents
        )
        layout.addWidget(self.models_table)

        form_group = QGroupBox("Модель")
        form_layout = QGridLayout(form_group)
        form_layout.addWidget(QLabel("Название"), 0, 0)
        self.model_name_input = QLineEdit()
        form_layout.addWidget(self.model_name_input, 0, 1)

        form_layout.addWidget(QLabel("API URL"), 1, 0)
        self.model_api_url_input = QLineEdit()
        form_layout.addWidget(self.model_api_url_input, 1, 1)

        form_layout.addWidget(QLabel("API ID"), 2, 0)
        self.model_api_id_input = QLineEdit()
        form_layout.addWidget(self.model_api_id_input, 2, 1)

        form_layout.addWidget(QLabel("Имя переменной"), 3, 0)
        self.model_api_key_env_input = QLineEdit()
        form_layout.addWidget(self.model_api_key_env_input, 3, 1)

        self.model_active_checkbox = QCheckBox("Активна")
        form_layout.addWidget(self.model_active_checkbox, 4, 1)
        layout.addWidget(form_group)

        buttons = QHBoxLayout()
        add_button = QPushButton("Добавить")
        add_button.clicked.connect(self.add_model)
        buttons.addWidget(add_button)

        update_button = QPushButton("Обновить")
        update_button.clicked.connect(self.update_model)
        buttons.addWidget(update_button)

        delete_button = QPushButton("Удалить")
        delete_button.clicked.connect(self.delete_model)
        buttons.addWidget(delete_button)

        clear_button = QPushButton("Очистить форму")
        clear_button.clicked.connect(self.clear_model_form)
        buttons.addWidget(clear_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.tabs.addTab(tab, "Модели")

    def _build_settings_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        quick_group = QGroupBox("Базовые настройки")
        quick_layout = QFormLayout(quick_group)
        self.system_prompt_input = QPlainTextEdit()
        self.system_prompt_input.setPlaceholderText("Системный промт для всех запросов")
        self.system_prompt_input.setMinimumHeight(120)
        quick_layout.addRow("System prompt", self.system_prompt_input)

        self.temperature_input = QDoubleSpinBox()
        self.temperature_input.setDecimals(2)
        self.temperature_input.setRange(0.0, 2.0)
        self.temperature_input.setSingleStep(0.05)
        quick_layout.addRow("Temperature", self.temperature_input)

        self.timeout_input = QSpinBox()
        self.timeout_input.setRange(5, 300)
        quick_layout.addRow("Timeout", self.timeout_input)
        layout.addWidget(quick_group)

        settings_buttons = QHBoxLayout()
        save_settings_button = QPushButton("Сохранить настройки")
        save_settings_button.clicked.connect(self.save_base_settings)
        settings_buttons.addWidget(save_settings_button)

        reset_settings_button = QPushButton("Сбросить по умолчанию")
        reset_settings_button.clicked.connect(self.reset_base_settings)
        settings_buttons.addWidget(reset_settings_button)
        settings_buttons.addStretch(1)
        layout.addLayout(settings_buttons)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Поиск настроек:"))
        self.settings_search_input = QLineEdit()
        self.settings_search_input.textChanged.connect(self.refresh_settings_table)
        controls.addWidget(self.settings_search_input, 1)
        layout.addLayout(controls)

        self.settings_table = QTableWidget(0, 3)
        self.settings_table.setHorizontalHeaderLabels(["Key", "Value", "Updated"])
        self.settings_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.settings_table.setSelectionMode(QTableWidget.SingleSelection)
        self.settings_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.settings_table.setSortingEnabled(True)
        self.settings_table.cellClicked.connect(self.load_selected_setting)
        self.settings_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        layout.addWidget(self.settings_table)

        manual_group = QGroupBox("Ручное изменение")
        manual_layout = QGridLayout(manual_group)
        manual_layout.addWidget(QLabel("Key"), 0, 0)
        self.setting_key_input = QLineEdit()
        manual_layout.addWidget(self.setting_key_input, 0, 1)
        manual_layout.addWidget(QLabel("Value"), 1, 0)
        self.setting_value_input = QLineEdit()
        manual_layout.addWidget(self.setting_value_input, 1, 1)
        layout.addWidget(manual_group)

        manual_buttons = QHBoxLayout()
        save_setting_button = QPushButton("Сохранить key/value")
        save_setting_button.clicked.connect(self.save_manual_setting)
        manual_buttons.addWidget(save_setting_button)

        delete_setting_button = QPushButton("Удалить key")
        delete_setting_button.clicked.connect(self.delete_manual_setting)
        manual_buttons.addWidget(delete_setting_button)
        manual_buttons.addStretch(1)
        layout.addLayout(manual_buttons)

        self.tabs.addTab(tab, "Настройки")

    def _build_logs_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        controls = QHBoxLayout()
        self.logs_path_label = QLabel(f"Файл логов: {LOG_FILE}")
        controls.addWidget(self.logs_path_label)
        controls.addStretch(1)
        refresh_button = QPushButton("Обновить логи")
        refresh_button.clicked.connect(self.refresh_logs_view)
        controls.addWidget(refresh_button)
        layout.addLayout(controls)

        self.logs_view = QPlainTextEdit()
        self.logs_view.setReadOnly(True)
        layout.addWidget(self.logs_view)

        self.tabs.addTab(tab, "Логи")

    def _ensure_initial_data(self) -> None:
        self.model_repository.seed_defaults()
        self.model_repository.auto_configure_api_key_env_names()
        self.model_repository.activate_models_with_available_keys()
        self.database.ensure_default_settings()

    def refresh_all_views(self) -> None:
        self.refresh_prompts_table()
        self.refresh_runtime_results_table()
        self.refresh_saved_results_table()
        self.refresh_models_table()
        self.load_base_settings()
        self.refresh_settings_table()
        self.refresh_logs_view()

    def log_event(self, message: str) -> None:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as log_file:
            timestamp = datetime.now().isoformat(timespec="seconds")
            log_file.write(f"{timestamp} | {message}\n")

    def show_status(self, message: str) -> None:
        self.status_bar.showMessage(message, 5000)
        self.log_event(message)

    def get_float_setting(self, key: str, default: float) -> float:
        try:
            return float(self.database.get_setting(key, str(default)) or default)
        except ValueError:
            return default

    def get_int_setting(self, key: str, default: int) -> int:
        try:
            return int(float(self.database.get_setting(key, str(default)) or default))
        except ValueError:
            return default

    def get_selected_prompt_record(self) -> dict[str, Any] | None:
        row = self.prompts_table.currentRow()
        if row < 0:
            return None
        item = self.prompts_table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def load_selected_prompt(self, *_args: Any) -> None:
        record = self.get_selected_prompt_record()
        if record is None:
            QMessageBox.information(self, "ChatList", "Выберите промт из таблицы.")
            return
        self.current_prompt_id = int(record["id"])
        self.prompt_input.setPlainText(record["prompt_text"])
        self.tags_input.setText(record.get("tags") or "")
        self.current_prompt_label.setText(f"Текущий промт: #{record['id']}")
        self.show_status(f"Загружен промт #{record['id']}.")

    def clear_prompt_form(self) -> None:
        self.current_prompt_id = None
        self.prompt_input.clear()
        self.tags_input.clear()
        self.current_prompt_label.setText("Текущий промт: новый")
        self.runtime_results = []
        self.refresh_runtime_results_table()
        self.show_status("Форма промта очищена.")

    def create_prompt_from_form(self) -> None:
        prompt_text = self.prompt_input.toPlainText().strip()
        tags = self.tags_input.text().strip()
        if not prompt_text:
            QMessageBox.warning(self, "ChatList", "Введите текст промта.")
            return

        prompt_id = self.database.create_prompt(prompt_text=prompt_text, tags=tags or None)
        self.current_prompt_id = prompt_id
        self.current_prompt_label.setText(f"Текущий промт: #{prompt_id}")
        self.refresh_prompts_table()
        self.show_status(f"Промт #{prompt_id} добавлен.")

    def update_selected_prompt(self) -> None:
        record = self.get_selected_prompt_record()
        prompt_id = (
            int(record["id"])
            if record is not None
            else self.current_prompt_id
        )
        if prompt_id is None:
            QMessageBox.information(
                self, "ChatList", "Выберите промт в таблице или загрузите его в форму."
            )
            return

        prompt_text = self.prompt_input.toPlainText().strip()
        tags = self.tags_input.text().strip()
        if not prompt_text:
            QMessageBox.warning(self, "ChatList", "Введите текст промта.")
            return

        self.database.update_prompt(prompt_id, prompt_text=prompt_text, tags=tags or None)
        self.current_prompt_id = prompt_id
        self.current_prompt_label.setText(f"Текущий промт: #{prompt_id}")
        self.refresh_prompts_table()
        self.show_status(f"Промт #{prompt_id} обновлён.")

    def delete_selected_prompt(self) -> None:
        record = self.get_selected_prompt_record()
        prompt_id = (
            int(record["id"])
            if record is not None
            else self.current_prompt_id
        )
        if prompt_id is None:
            QMessageBox.information(self, "ChatList", "Выберите промт для удаления.")
            return

        confirmation = QMessageBox.question(
            self,
            "ChatList",
            f"Удалить промт #{prompt_id}? Связанные сохранённые результаты тоже будут удалены.",
        )
        if confirmation != QMessageBox.Yes:
            return

        self.database.delete_prompt(prompt_id)
        if self.current_prompt_id == prompt_id:
            self.clear_prompt_form()
        self.refresh_prompts_table()
        self.refresh_saved_results_table()
        self.show_status(f"Промт #{prompt_id} удалён.")

    def resolve_prompt_id(self, prompt_text: str, tags: str) -> int:
        existing_prompt = self.database.get_prompt_by_text(prompt_text)
        if existing_prompt is not None:
            self.current_prompt_id = int(existing_prompt["id"])
            if (existing_prompt.get("tags") or "") != tags:
                self.database.update_prompt(self.current_prompt_id, tags=tags)
            return self.current_prompt_id

        self.current_prompt_id = self.database.create_prompt(prompt_text=prompt_text, tags=tags)
        return self.current_prompt_id

    def send_prompt(self) -> None:
        prompt_text = self.prompt_input.toPlainText().strip()
        tags = self.tags_input.text().strip()
        if not prompt_text:
            QMessageBox.warning(self, "ChatList", "Введите промт перед отправкой.")
            return

        active_models = self.model_repository.list_active_models()
        if not active_models:
            QMessageBox.warning(
                self,
                "ChatList",
                "Нет активных моделей. Активируйте хотя бы одну модель на вкладке 'Модели'.",
            )
            return

        prompt_id = self.resolve_prompt_id(prompt_text, tags)
        self.current_prompt_label.setText(f"Текущий промт: #{prompt_id}")
        self.database.set_setting("last_prompt_tags", tags)
        self.network_client.timeout = float(self.get_int_setting("request_timeout", 60))

        self.runtime_results = []
        self.refresh_runtime_results_table()

        self.send_button.setEnabled(False)
        self.save_selected_button.setEnabled(False)
        self.show_status(
            f"Отправка промта #{prompt_id} в {len(active_models)} активных моделей..."
        )

        self._worker = RequestWorker(
            network_client=self.network_client,
            models=active_models,
            prompt=prompt_text,
            system_prompt=self.database.get_setting("system_prompt", "") or "",
            temperature=self.get_float_setting("temperature", 0.7),
        )
        self._worker.progress.connect(self.show_status)
        self._worker.result_ready.connect(self.on_network_result)
        self._worker.batch_finished.connect(self.on_request_batch_finished)
        self._worker.start()

    def on_network_result(self, result: NetworkResult) -> None:
        runtime_result = RuntimeResult(
            model_id=result.model.id,
            model_name=result.model.name,
            response_text=result.response_text,
            status=result.status,
            error_text=result.error_text,
            selected=result.status == "success",
        )
        self.runtime_results.append(runtime_result)
        self.refresh_runtime_results_table()
        self.show_status(f"{result.model.name}: {result.status}")

    def on_request_batch_finished(self, _results: list[NetworkResult]) -> None:
        self.send_button.setEnabled(True)
        self.save_selected_button.setEnabled(True)
        success_count = sum(1 for result in self.runtime_results if result.status == "success")
        self.show_status(
            f"Запрос завершён. Успешных ответов: {success_count} из {len(self.runtime_results)}."
        )
        self.refresh_saved_results_table()
        self.refresh_prompts_table()
        self._worker = None

    def on_runtime_result_changed(self, item: QTableWidgetItem) -> None:
        if self._results_table_updating or item.column() != 0:
            return
        result_index = item.data(Qt.UserRole)
        if result_index is None:
            return
        self.runtime_results[int(result_index)].selected = (
            item.checkState() == Qt.Checked
        )

    def set_all_runtime_selected(self, selected: bool) -> None:
        for runtime_result in self.runtime_results:
            runtime_result.selected = selected
        self.refresh_runtime_results_table()

    def save_selected_results(self) -> None:
        if self.current_prompt_id is None:
            QMessageBox.warning(self, "ChatList", "Сначала отправьте промт.")
            return

        rows_to_save = [
            {
                "prompt_id": self.current_prompt_id,
                "model_id": runtime_result.model_id,
                "response_text": runtime_result.response_text,
            }
            for runtime_result in self.runtime_results
            if runtime_result.selected
            and runtime_result.status == "success"
            and runtime_result.model_id is not None
        ]

        if not rows_to_save:
            QMessageBox.information(
                self,
                "ChatList",
                "Нет выбранных успешных результатов для сохранения.",
            )
            return

        self.database.save_results(rows_to_save)
        saved_count = len(rows_to_save)
        self.runtime_results = []
        self.refresh_runtime_results_table()
        self.refresh_saved_results_table()
        self.show_status(f"Сохранено результатов: {saved_count}.")

    def refresh_prompts_table(self) -> None:
        prompts = self.database.list_prompts(
            search=self.prompts_search_input.text().strip() or None
        )
        self.prompts_table.setSortingEnabled(False)
        self.prompts_table.setRowCount(len(prompts))
        for row_index, record in enumerate(prompts):
            id_item = QTableWidgetItem(str(record["id"]))
            id_item.setData(Qt.UserRole, record)
            date_item = QTableWidgetItem(record["created_at"])
            tags_item = QTableWidgetItem(record.get("tags") or "")
            prompt_item = QTableWidgetItem(record["prompt_text"])
            for column, item in enumerate([id_item, date_item, tags_item, prompt_item]):
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                self.prompts_table.setItem(row_index, column, item)
        self.prompts_table.setSortingEnabled(True)

    def refresh_runtime_results_table(self) -> None:
        search = self.runtime_results_search_input.text().strip().lower()
        filtered_results = [
            (index, result)
            for index, result in enumerate(self.runtime_results)
            if not search
            or search in result.model_name.lower()
            or search in result.status.lower()
            or search in result.display_text.lower()
        ]
        self._results_table_updating = True
        self.runtime_results_table.setSortingEnabled(False)
        self.runtime_results_table.setRowCount(len(filtered_results))
        for row_index, (result_index, result) in enumerate(filtered_results):
            checkbox_item = QTableWidgetItem()
            checkbox_item.setFlags(
                Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable
            )
            checkbox_item.setCheckState(Qt.Checked if result.selected else Qt.Unchecked)
            checkbox_item.setData(Qt.UserRole, result_index)

            model_item = QTableWidgetItem(result.model_name)
            status_item = QTableWidgetItem(result.status)
            response_item = QTableWidgetItem(result.display_text)
            for item in [model_item, status_item, response_item]:
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

            self.runtime_results_table.setItem(row_index, 0, checkbox_item)
            self.runtime_results_table.setItem(row_index, 1, model_item)
            self.runtime_results_table.setItem(row_index, 2, status_item)
            self.runtime_results_table.setItem(row_index, 3, response_item)
        self.runtime_results_table.resizeRowsToContents()
        self.runtime_results_table.setSortingEnabled(True)
        self._results_table_updating = False
        self.update_runtime_preview()

    def get_selected_runtime_result(self) -> RuntimeResult | None:
        row = self.runtime_results_table.currentRow()
        if row < 0:
            return None
        item = self.runtime_results_table.item(row, 0)
        if item is None:
            return None
        result_index = item.data(Qt.UserRole)
        if result_index is None:
            return None
        if 0 <= int(result_index) < len(self.runtime_results):
            return self.runtime_results[int(result_index)]
        return None

    def update_runtime_preview(self) -> None:
        result = self.get_selected_runtime_result()
        if result is None:
            self.runtime_preview.clear()
            self.open_runtime_markdown_button.setEnabled(False)
            return

        parts = [
            f"Модель: {result.model_name}",
            f"Статус: {result.status}",
            "",
            result.display_text,
        ]
        self.runtime_preview.setPlainText("\n".join(parts))
        self.open_runtime_markdown_button.setEnabled(True)

    def open_runtime_preview_markdown(self) -> None:
        result = self.get_selected_runtime_result()
        if result is None:
            QMessageBox.information(self, "ChatList", "Выберите результат для открытия.")
            return

        markdown_text = "\n".join(
            [
                f"# {result.model_name}",
                "",
                f"- Статус: {result.status}",
                "",
                "## Ответ",
                "",
                result.display_text,
            ]
        )
        self.open_markdown_dialog(
            title=f"Ответ: {result.model_name}",
            markdown_text=markdown_text,
        )

    def export_runtime_results(self, export_format: str) -> None:
        selected_results = [
            result
            for result in self.runtime_results
            if result.selected
        ]
        if not selected_results:
            QMessageBox.information(
                self,
                "ChatList",
                "Нет выбранных временных результатов для экспорта.",
            )
            return
        self.export_records(
            records=[
                result.export_record(self.prompt_input.toPlainText().strip())
                for result in selected_results
            ],
            export_format=export_format,
            default_name="chatlist_runtime_export",
        )

    def refresh_saved_results_table(self) -> None:
        records = self.database.list_results(
            search=self.saved_results_search_input.text().strip() or None
        )
        self.saved_results_table.setSortingEnabled(False)
        self.saved_results_table.setRowCount(len(records))
        for row_index, record in enumerate(records):
            values = [
                QTableWidgetItem(str(record["id"])),
                QTableWidgetItem(record["saved_at"]),
                QTableWidgetItem(record["model_name"]),
                QTableWidgetItem(record["prompt_text"]),
                QTableWidgetItem(record["response_text"]),
            ]
            values[0].setData(Qt.UserRole, record)
            for column, item in enumerate(values):
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                self.saved_results_table.setItem(row_index, column, item)
        self.saved_results_table.resizeRowsToContents()
        self.saved_results_table.setSortingEnabled(True)
        self.update_saved_preview()

    def get_selected_saved_records(self) -> list[dict[str, Any]]:
        selected_rows = sorted(
            {index.row() for index in self.saved_results_table.selectionModel().selectedRows()}
        )
        records: list[dict[str, Any]] = []
        for row in selected_rows:
            item = self.saved_results_table.item(row, 0)
            if item is not None:
                record = item.data(Qt.UserRole)
                if record is not None:
                    records.append(record)
        return records

    def get_current_saved_record(self) -> dict[str, Any] | None:
        row = self.saved_results_table.currentRow()
        if row < 0:
            return None
        item = self.saved_results_table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def update_saved_preview(self) -> None:
        record = self.get_current_saved_record()
        if record is None:
            self.saved_preview.clear()
            self.open_saved_markdown_button.setEnabled(False)
            return

        parts = [
            f"Дата: {record.get('saved_at', '')}",
            f"Модель: {record.get('model_name', '')}",
            "",
            "Промт:",
            record.get("prompt_text", ""),
            "",
            "Ответ:",
            record.get("response_text", ""),
        ]
        self.saved_preview.setPlainText("\n".join(parts))
        self.open_saved_markdown_button.setEnabled(True)

    def open_saved_preview_markdown(self) -> None:
        record = self.get_current_saved_record()
        if record is None:
            QMessageBox.information(
                self, "ChatList", "Выберите сохранённый результат для открытия."
            )
            return

        markdown_text = "\n".join(
            [
                f"# {record.get('model_name', 'Результат')}",
                "",
                f"- Дата: {record.get('saved_at', '')}",
                "",
                "## Промт",
                "",
                record.get("prompt_text", ""),
                "",
                "## Ответ",
                "",
                record.get("response_text", ""),
            ]
        )
        self.open_markdown_dialog(
            title=f"Сохранённый ответ: {record.get('model_name', '')}",
            markdown_text=markdown_text,
        )

    def open_markdown_dialog(self, title: str, markdown_text: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(960, 720)

        layout = QVBoxLayout(dialog)
        browser = QTextBrowser(dialog)
        browser.setOpenExternalLinks(True)
        browser.setMarkdown(markdown_text)
        layout.addWidget(browser)

        close_button = QPushButton("Закрыть", dialog)
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)

        dialog.exec_()

    def export_saved_results(self, export_format: str) -> None:
        records = self.get_selected_saved_records()
        if not records:
            QMessageBox.information(
                self,
                "ChatList",
                "Выберите сохранённые результаты для экспорта.",
            )
            return
        self.export_records(
            records=records,
            export_format=export_format,
            default_name="chatlist_saved_export",
        )

    def export_records(
        self, records: list[dict[str, Any]], export_format: str, default_name: str
    ) -> None:
        if export_format == "markdown":
            target_path, _ = QFileDialog.getSaveFileName(
                self,
                "Сохранить Markdown",
                f"{default_name}.md",
                "Markdown files (*.md)",
            )
            if not target_path:
                return
            content = self.build_markdown_export(records)
        else:
            target_path, _ = QFileDialog.getSaveFileName(
                self,
                "Сохранить JSON",
                f"{default_name}.json",
                "JSON files (*.json)",
            )
            if not target_path:
                return
            content = json.dumps(records, ensure_ascii=False, indent=2)

        Path(target_path).write_text(content, encoding="utf-8")
        self.show_status(f"Экспортировано записей: {len(records)}.")

    def build_markdown_export(self, records: list[dict[str, Any]]) -> str:
        parts = ["# ChatList Export", ""]
        for record in records:
            model_name = record.get("model_name") or record.get("model") or "Unknown"
            prompt_text = record.get("prompt_text", "")
            response_text = record.get("response_text", "")
            status = record.get("status", "saved")
            parts.extend(
                [
                    f"## {model_name}",
                    f"- Status: {status}",
                    "",
                    "### Prompt",
                    "",
                    prompt_text,
                    "",
                    "### Response",
                    "",
                    response_text,
                    "",
                ]
            )
        return "\n".join(parts)

    def refresh_models_table(self) -> None:
        models = self.model_repository.list_models(
            search=self.models_search_input.text().strip() or None
        )
        self.models_table.setSortingEnabled(False)
        self.models_table.setRowCount(len(models))
        for row_index, model in enumerate(models):
            items = [
                QTableWidgetItem(str(model.id or "")),
                QTableWidgetItem("Yes" if model.is_active else "No"),
                QTableWidgetItem(model.name),
                QTableWidgetItem(model.api_url),
                QTableWidgetItem(model.api_id),
                QTableWidgetItem(model.api_key_env),
            ]
            items[0].setData(Qt.UserRole, asdict(model))
            for column, item in enumerate(items):
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                self.models_table.setItem(row_index, column, item)
            test_button = QPushButton("Тест подключения")
            test_button.clicked.connect(
                lambda _checked=False, model_id=model.id: self.test_model_connection(
                    model_id
                )
            )
            self.models_table.setCellWidget(row_index, 6, test_button)
        self.models_table.setSortingEnabled(True)

    def get_selected_model_record(self) -> dict[str, Any] | None:
        row = self.models_table.currentRow()
        if row < 0:
            return None
        item = self.models_table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def load_selected_model(self, *_args: Any) -> None:
        record = self.get_selected_model_record()
        if record is None:
            return
        self.model_name_input.setText(record["name"])
        self.model_api_url_input.setText(record["api_url"])
        self.model_api_id_input.setText(record["api_id"])
        self.model_api_key_env_input.setText(record["api_key_env"])
        self.model_active_checkbox.setChecked(bool(record["is_active"]))

    def build_model_from_form(self, require_id: bool) -> ModelConfig | None:
        name = self.model_name_input.text().strip()
        api_url = self.model_api_url_input.text().strip()
        api_id = self.model_api_id_input.text().strip()
        api_key_env = self.model_api_key_env_input.text().strip()
        if not all([name, api_url, api_id, api_key_env]):
            QMessageBox.warning(
                self,
                "ChatList",
                "Заполните все поля модели перед сохранением.",
            )
            return None

        record = self.get_selected_model_record()
        model_id = None
        if require_id:
            if record is None:
                QMessageBox.warning(self, "ChatList", "Сначала выберите модель.")
                return None
            model_id = int(record["id"])

        return ModelConfig(
            id=model_id,
            name=name,
            api_url=api_url,
            api_id=api_id,
            api_key_env=api_key_env,
            is_active=self.model_active_checkbox.isChecked(),
        )

    def add_model(self) -> None:
        model = self.build_model_from_form(require_id=False)
        if model is None:
            return
        self.model_repository.add_model(model)
        self.refresh_models_table()
        self.show_status(f"Добавлена модель: {model.name}.")
        self.clear_model_form()

    def update_model(self) -> None:
        model = self.build_model_from_form(require_id=True)
        if model is None:
            return
        self.model_repository.update_model(model)
        self.refresh_models_table()
        self.show_status(f"Обновлена модель: {model.name}.")

    def delete_model(self) -> None:
        record = self.get_selected_model_record()
        if record is None:
            QMessageBox.information(self, "ChatList", "Выберите модель для удаления.")
            return
        self.model_repository.delete_model(int(record["id"]))
        self.refresh_models_table()
        self.show_status(f"Удалена модель: {record['name']}.")
        self.clear_model_form()

    def clear_model_form(self) -> None:
        self.models_table.clearSelection()
        self.model_name_input.clear()
        self.model_api_url_input.clear()
        self.model_api_id_input.clear()
        self.model_api_key_env_input.clear()
        self.model_active_checkbox.setChecked(False)

    def seed_default_models(self) -> None:
        try:
            before = {model.name for model in self.model_repository.list_models()}
            self.model_repository.seed_defaults()
            after = {model.name for model in self.model_repository.list_models()}
            added = sorted(after - before)
            self.refresh_models_table()
            if added:
                self.show_status(f"Добавлено дефолтных моделей: {len(added)}.")
            else:
                self.show_status("Новых дефолтных моделей нет.")
        except Exception as exc:
            QMessageBox.warning(
                self,
                "ChatList",
                f"Не удалось добавить дефолтные модели.\n\nОшибка: {exc}",
            )
            self.show_status("Ошибка при добавлении дефолтных моделей.")

    def activate_models_from_env(self) -> None:
        self.model_repository.auto_configure_api_key_env_names()
        self.model_repository.activate_models_with_available_keys()
        self.refresh_models_table()
        self.show_status("Модели с найденными ключами активированы.")

    def auto_configure_openrouter_env(self) -> None:
        changes = self.model_repository.auto_configure_api_key_env_names()
        self.refresh_models_table()
        openrouter_changes = [
            change for change in changes if "openrouter" in change[0].lower()
        ]
        if openrouter_changes:
            model_name, old_name, new_name = openrouter_changes[0]
            self.show_status(
                f"{model_name}: переменная ключа обновлена с {old_name} на {new_name}."
            )
            return

        openrouter_model = next(
            (
                model
                for model in self.model_repository.list_models()
                if "openrouter" in model.name.lower()
            ),
            None,
        )
        if openrouter_model is None:
            self.show_status("Модель OpenRouter не найдена.")
            return

        env_path = Path(__file__).with_name(".env")
        if not env_path.exists():
            self.show_status(
                "Файл .env не найден в папке проекта, поэтому имя переменной не изменено."
            )
            return

        self.show_status(
            f"Для {openrouter_model.name} оставлено текущее имя переменной: "
            f"{openrouter_model.api_key_env}."
        )

    def test_model_connection(self, model_id: int | None = None) -> None:
        if model_id is None:
            record = self.get_selected_model_record()
            if record is None:
                QMessageBox.information(self, "ChatList", "Выберите модель для теста.")
                return
            model_id = int(record["id"])

        model = self.model_repository.get_model(int(model_id))
        if model is None:
            QMessageBox.warning(self, "ChatList", "Модель не найдена.")
            return

        self.model_repository.auto_configure_api_key_env_names()
        model = self.model_repository.get_model(int(model_id))
        if model is None:
            QMessageBox.warning(self, "ChatList", "Модель не найдена.")
            return

        self.network_client.timeout = float(self.get_int_setting("request_timeout", 60))
        result = self.network_client.send_prompt(
            model=model,
            prompt="Ответь одним словом: OK",
            system_prompt=self.database.get_setting("system_prompt", "") or "",
            temperature=self.get_float_setting("temperature", 0.7),
        )

        self.refresh_models_table()

        if result.status == "success":
            message = (
                f"Подключение к {model.name} успешно.\n\n"
                f"Ответ: {result.response_text[:300]}"
            )
            QMessageBox.information(self, "Тест подключения", message)
            self.show_status(f"Тест подключения успешен для {model.name}.")
            return

        if result.status == "missing_api_key":
            searched_paths = [str(path) for path in get_env_search_paths(None)]
            loaded_paths = [str(path) for path in getattr(self.network_client, "loaded_env_files", [])]
            hint = (
                "Проверьте, что файл .env.local лежит либо рядом с main.py, либо рядом с ChatListApp.exe,\n"
                "либо на уровень выше папки dist.\n\n"
                f"Папка приложения: {get_app_base_dir()}\n"
                f"Загружены env-файлы: {loaded_paths or ['(ничего)']}\n\n"
                "Файлы, которые приложение пытается загрузить:\n- "
                + "\n- ".join(searched_paths[:12])
            )
            if len(searched_paths) > 12:
                hint += "\n- ...\n"
            message = (
                f"Тест подключения для {model.name} завершился со статусом {result.status}.\n\n"
                f"Ошибка: {result.error_text or 'Нет дополнительной информации.'}\n\n"
                f"{hint}"
            )
            QMessageBox.warning(self, "Тест подключения", message)
            self.show_status(f"Тест подключения неуспешен для {model.name}: {result.status}.")
            return

        message = (
            f"Тест подключения для {model.name} завершился со статусом {result.status}.\n\n"
            f"Ошибка: {result.error_text or 'Нет дополнительной информации.'}"
        )
        QMessageBox.warning(self, "Тест подключения", message)
        self.show_status(f"Тест подключения неуспешен для {model.name}: {result.status}.")

    def load_base_settings(self) -> None:
        self.system_prompt_input.setPlainText(
            self.database.get_setting("system_prompt", DEFAULT_SETTINGS["system_prompt"])
            or ""
        )
        self.temperature_input.setValue(
            self.get_float_setting("temperature", float(DEFAULT_SETTINGS["temperature"]))
        )
        self.timeout_input.setValue(
            self.get_int_setting("request_timeout", int(DEFAULT_SETTINGS["request_timeout"]))
        )

    def save_base_settings(self) -> None:
        self.database.set_setting("system_prompt", self.system_prompt_input.toPlainText())
        self.database.set_setting("temperature", str(self.temperature_input.value()))
        self.database.set_setting("request_timeout", str(self.timeout_input.value()))
        self.database.set_setting("window_width", str(self.width()))
        self.database.set_setting("window_height", str(self.height()))
        self.network_client.timeout = float(self.timeout_input.value())
        self.refresh_settings_table()
        self.show_status("Базовые настройки сохранены.")

    def reset_base_settings(self) -> None:
        for key, value in DEFAULT_SETTINGS.items():
            self.database.set_setting(key, value)
        self.load_base_settings()
        self.refresh_settings_table()
        self.show_status("Настройки сброшены по умолчанию.")

    def refresh_settings_table(self) -> None:
        settings = self.database.list_settings(
            search=self.settings_search_input.text().strip() or None
        )
        self.settings_table.setSortingEnabled(False)
        self.settings_table.setRowCount(len(settings))
        for row_index, setting in enumerate(settings):
            items = [
                QTableWidgetItem(setting["key"]),
                QTableWidgetItem(setting.get("value") or ""),
                QTableWidgetItem(setting.get("updated_at") or ""),
            ]
            items[0].setData(Qt.UserRole, setting)
            for column, item in enumerate(items):
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                self.settings_table.setItem(row_index, column, item)
        self.settings_table.setSortingEnabled(True)

    def get_selected_setting_record(self) -> dict[str, Any] | None:
        row = self.settings_table.currentRow()
        if row < 0:
            return None
        item = self.settings_table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def load_selected_setting(self, *_args: Any) -> None:
        record = self.get_selected_setting_record()
        if record is None:
            return
        self.setting_key_input.setText(record["key"])
        self.setting_value_input.setText(record.get("value") or "")

    def save_manual_setting(self) -> None:
        key = self.setting_key_input.text().strip()
        value = self.setting_value_input.text()
        if not key:
            QMessageBox.warning(self, "ChatList", "Введите key настройки.")
            return
        self.database.set_setting(key, value)
        self.refresh_settings_table()
        if key in {"system_prompt", "temperature", "request_timeout"}:
            self.load_base_settings()
        self.show_status(f"Сохранена настройка: {key}.")

    def delete_manual_setting(self) -> None:
        key = self.setting_key_input.text().strip()
        if not key:
            QMessageBox.information(self, "ChatList", "Выберите или введите key.")
            return
        self.database.delete_setting(key)
        self.refresh_settings_table()
        self.show_status(f"Удалена настройка: {key}.")

    def refresh_logs_view(self) -> None:
        if LOG_FILE.exists():
            self.logs_view.setPlainText(LOG_FILE.read_text(encoding="utf-8"))
        else:
            self.logs_view.setPlainText("Логи пока отсутствуют.")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.database.set_setting("window_width", str(self.width()))
        self.database.set_setting("window_height", str(self.height()))
        super().closeEvent(event)


def bootstrap_application() -> tuple[QApplication, MainWindow]:
    database = bootstrap_database()
    app = QApplication.instance() or QApplication(sys.argv)
    model_repository = ModelRepository(database)
    network_client = NetworkClient(timeout=float(database.get_setting("request_timeout", "60")))
    window = MainWindow(
        database=database,
        model_repository=model_repository,
        network_client=network_client,
    )
    return app, window


def main() -> int:
    app, window = bootstrap_application()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
