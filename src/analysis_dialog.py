"""Поэтапный ввод переходов, расчёт припусков и схема размерной цепи."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from src.technological_analysis import (
    blank_spatial_deviation,
    calculate_allowance_stages,
    validate_chain,
)


class TechnologicalAnalysisWindow(QtWidgets.QMainWindow):
    def __init__(self, model_hash: str, model_name: str, parent=None):
        super().__init__(parent)
        self.model_hash = model_hash
        self.setWindowTitle(f"Технологический анализ — {model_name}")
        self.resize(1080, 760)
        self.setMinimumSize(860, 600)
        self.data_path = Path(__file__).resolve().parents[1] / "data" / "analysis" / f"{model_hash[:16]}.json"
        self._build_ui()
        self._load_data()

    def _build_ui(self):
        root = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(root)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._build_allowance_tab(), "1. Переходы и припуски")
        self.tabs.addTab(self._build_chain_tab(), "2. Размерная цепь")
        outer.addWidget(self.tabs)
        self.setCentralWidget(root)

    @staticmethod
    def _float_box(value=0.0, maximum=1_000_000.0):
        widget = QtWidgets.QDoubleSpinBox()
        widget.setRange(0.0, maximum)
        widget.setDecimals(4)
        widget.setValue(value)
        widget.setKeyboardTracking(False)
        return widget

    @staticmethod
    def _signed_float_box(value=0.0):
        widget = QtWidgets.QDoubleSpinBox()
        widget.setRange(-1_000_000.0, 1_000_000.0)
        widget.setDecimals(4)
        widget.setValue(value)
        widget.setKeyboardTracking(False)
        return widget

    def _build_allowance_tab(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        stock = QtWidgets.QGroupBox("Заготовка: исходное пространственное отклонение")
        form = QtWidgets.QFormLayout(stock)
        self.shift_box = self._float_box()
        self.curvature_box = self._float_box()
        self.length_box = self._float_box(1.0)
        form.addRow("Смещение поверхности ρсм, мкм", self.shift_box)
        form.addRow("Удельная кривизна Δк, мкм/мм", self.curvature_box)
        form.addRow("Расчётная длина L, мм", self.length_box)
        layout.addWidget(stock)

        help_text = QtWidgets.QLabel(
            "Добавьте переходы по порядку обработки. Для каждого укажите Rz и T после "
            "предыдущего перехода, коэффициент уточнения Ky и ошибки установки εб, εз. "
            "Размеры ошибок — в мкм; диаметр и длина — в мм."
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.stages_table = QtWidgets.QTableWidget(0, 9)
        self.stages_table.setHorizontalHeaderLabels([
            "Операция/переход", "Тип", "Rz, мкм", "T, мкм", "Ky",
            "εб, мкм", "εз, мкм", "Переустановка", "Финишная обработка",
        ])
        self.stages_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.stages_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.stages_table, stretch=1)
        buttons = QtWidgets.QHBoxLayout()
        add = QtWidgets.QPushButton("Добавить переход")
        add.clicked.connect(self._add_stage)
        remove = QtWidgets.QPushButton("Удалить выбранный")
        remove.clicked.connect(lambda: self.stages_table.removeRow(self.stages_table.currentRow())
                               if self.stages_table.currentRow() >= 0 else None)
        calculate = QtWidgets.QPushButton("Рассчитать минимальные припуски")
        calculate.clicked.connect(self._calculate)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        buttons.addWidget(calculate)
        layout.addLayout(buttons)
        self.allowance_status = QtWidgets.QLabel("Расчёт ещё не выполнен.")
        self.allowance_status.setWordWrap(True)
        layout.addWidget(self.allowance_status)
        return page

    def _add_stage(self, values=None):
        values = values or {}
        row = self.stages_table.rowCount()
        self.stages_table.insertRow(row)
        self.stages_table.setItem(row, 0, QtWidgets.QTableWidgetItem(values.get("name", f"Переход {row + 1}")))
        kind = QtWidgets.QComboBox()
        kind.addItem("Вращение (диаметральный)", "rotational")
        kind.addItem("Линейный размер", "linear")
        kind.setCurrentIndex(0 if values.get("kind", "rotational") == "rotational" else 1)
        self.stages_table.setCellWidget(row, 1, kind)
        for column, key, default in [(2, "roughness_um", 0), (3, "defect_layer_um", 0),
                                     (4, "ky", 0.06), (5, "basing_error_um", 0),
                                     (6, "clamping_error_um", 0)]:
            spin = self._float_box(float(values.get(key, default)), 1.0 if key == "ky" else 1_000_000.0)
            spin.setDecimals(5 if key == "ky" else 3)
            self.stages_table.setCellWidget(row, column, spin)
        reset = QtWidgets.QComboBox()
        reset.addItems(["Да", "Нет"])
        reset.setCurrentIndex(0 if values.get("reinstalled", True) else 1)
        self.stages_table.setCellWidget(row, 7, reset)
        finish = QtWidgets.QComboBox()
        finish.addItems(["Нет", "Полирование / суперфиниш"])
        finish.setCurrentIndex(1 if values.get("finishing_only", False) else 0)
        self.stages_table.setCellWidget(row, 8, finish)

    def _read_stages(self):
        stages = []
        for row in range(self.stages_table.rowCount()):
            stages.append({
                "name": self.stages_table.item(row, 0).text().strip() if self.stages_table.item(row, 0) else f"Переход {row + 1}",
                "kind": self.stages_table.cellWidget(row, 1).currentData(),
                "roughness_um": self.stages_table.cellWidget(row, 2).value(),
                "defect_layer_um": self.stages_table.cellWidget(row, 3).value(),
                "ky": self.stages_table.cellWidget(row, 4).value(),
                "basing_error_um": self.stages_table.cellWidget(row, 5).value(),
                "clamping_error_um": self.stages_table.cellWidget(row, 6).value(),
                "reinstalled": self.stages_table.cellWidget(row, 7).currentIndex() == 0,
                "finishing_only": self.stages_table.cellWidget(row, 8).currentIndex() == 1,
            })
        return stages

    def _calculate(self):
        try:
            rho0 = blank_spatial_deviation(self.shift_box.value(), self.curvature_box.value(), self.length_box.value())
            results = calculate_allowance_stages(self._read_stages(), initial_spatial_deviation_um=rho0)
            if not results:
                self.allowance_status.setText("Добавьте хотя бы один переход обработки.")
                return
            self._show_allowance_results(results, rho0)
            self._save_data()
        except (ValueError, KeyError) as error:
            QtWidgets.QMessageBox.warning(self, "Проверьте исходные данные", str(error))

    def _show_allowance_results(self, results, rho0):
        lines = [f"Начальное пространственное отклонение заготовки: ρ₀ = {rho0:.3f} мкм."]
        for item in results:
            lines.append(
                f"{item['stage']}: Zmin = {item['minimum_allowance_um']:.3f} мкм "
                f"({item['minimum_allowance_mm']:.6f} мм); ρост = "
                f"{item['residual_spatial_deviation_um']:.3f} мкм; "
                f"ε = {item['setup_error_um']:.3f} мкм."
            )
        self.allowance_status.setText("\n".join(lines))

    def _build_chain_tab(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        help_text = QtWidgets.QLabel(
            "Добавьте поверхности слева направо, затем связи между ними. Связи могут быть "
            "технологическими размерами, конструкторскими размерами или припусками. "
            "Схема справа обновляется автоматически."
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.addWidget(QtWidgets.QLabel("Поверхности"))
        self.surface_table = QtWidgets.QTableWidget(0, 2)
        self.surface_table.setHorizontalHeaderLabels(["Код", "Описание / база"])
        self.surface_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        left_layout.addWidget(self.surface_table, 1)
        surface_buttons = QtWidgets.QHBoxLayout()
        add_surface = QtWidgets.QPushButton("Добавить поверхность")
        add_surface.clicked.connect(self._add_surface)
        remove_surface = QtWidgets.QPushButton("Удалить")
        remove_surface.clicked.connect(self._remove_surface)
        surface_buttons.addWidget(add_surface)
        surface_buttons.addWidget(remove_surface)
        left_layout.addLayout(surface_buttons)
        left_layout.addWidget(QtWidgets.QLabel("Размерные связи"))
        self.links_table = QtWidgets.QTableWidget(0, 7)
        self.links_table.setHorizontalHeaderLabels([
            "Обозначение", "Тип", "От", "До", "Номинал, мм", "Верхнее откл., мм", "Нижнее откл., мм"
        ])
        self.links_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.links_table.horizontalHeader().setStretchLastSection(True)
        left_layout.addWidget(self.links_table, 1)
        link_buttons = QtWidgets.QHBoxLayout()
        add_link = QtWidgets.QPushButton("Добавить связь")
        add_link.clicked.connect(self._add_link)
        remove_link = QtWidgets.QPushButton("Удалить связь")
        remove_link.clicked.connect(lambda: self.links_table.removeRow(self.links_table.currentRow())
                                    if self.links_table.currentRow() >= 0 else None)
        link_buttons.addWidget(add_link)
        link_buttons.addWidget(remove_link)
        left_layout.addLayout(link_buttons)
        splitter.addWidget(left)

        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.addWidget(QtWidgets.QLabel("Схема технологической размерной цепи"))
        self.chain_scene = QtWidgets.QGraphicsScene(self)
        self.chain_view = QtWidgets.QGraphicsView(self.chain_scene)
        self.chain_view.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        self.chain_view.setMinimumWidth(360)
        right_layout.addWidget(self.chain_view, 1)
        self.chain_status = QtWidgets.QLabel("Добавьте поверхности и связи.")
        self.chain_status.setWordWrap(True)
        right_layout.addWidget(self.chain_status)
        splitter.addWidget(right)
        splitter.setSizes([600, 480])
        layout.addWidget(splitter, 1)
        save = QtWidgets.QPushButton("Сохранить исходные данные")
        save.clicked.connect(self._save_data)
        layout.addWidget(save, alignment=QtCore.Qt.AlignmentFlag.AlignRight)
        self.surface_table.itemChanged.connect(self._refresh_surface_choices)
        self.links_table.itemChanged.connect(self._refresh_chain)
        return page

    def _add_surface(self, surface=None):
        surface = surface or {}
        row = self.surface_table.rowCount()
        self.surface_table.insertRow(row)
        self.surface_table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(surface.get("id", row + 1))))
        self.surface_table.setItem(row, 1, QtWidgets.QTableWidgetItem(surface.get("description", "")))
        self._refresh_surface_choices()

    def _remove_surface(self):
        row = self.surface_table.currentRow()
        if row >= 0:
            self.surface_table.removeRow(row)
            self._refresh_surface_choices()

    def _surface_ids(self):
        return [self.surface_table.item(row, 0).text().strip()
                for row in range(self.surface_table.rowCount()) if self.surface_table.item(row, 0)]

    def _refresh_surface_choices(self, *_):
        ids = self._surface_ids()
        for row in range(self.links_table.rowCount()):
            for column in (2, 3):
                combo = self.links_table.cellWidget(row, column)
                old = combo.currentText() if combo else ""
                combo.blockSignals(True)
                combo.clear()
                combo.addItems(ids)
                if old in ids:
                    combo.setCurrentText(old)
                combo.blockSignals(False)
        self._refresh_chain()

    def _add_link(self, link=None):
        link = link or {}
        row = self.links_table.rowCount()
        self.links_table.insertRow(row)
        self.links_table.setItem(row, 0, QtWidgets.QTableWidgetItem(link.get("label", f"A{row + 1}")))
        kind = QtWidgets.QComboBox()
        kind.addItems(["Технологический размер", "Конструкторский размер", "Припуск"])
        kind.setCurrentText(link.get("type", "Технологический размер"))
        self.links_table.setCellWidget(row, 1, kind)
        ids = self._surface_ids()
        for column, key in [(2, "start"), (3, "end")]:
            combo = QtWidgets.QComboBox()
            combo.addItems(ids)
            if link.get(key) in ids:
                combo.setCurrentText(link[key])
            self.links_table.setCellWidget(row, column, combo)
        nominal = self._float_box(float(link.get("nominal_mm", 0)), 1_000_000)
        self.links_table.setCellWidget(row, 4, nominal)
        legacy_tolerance = float(link.get("tolerance_mm", 0))
        upper = self._signed_float_box(float(link.get("upper_deviation_mm", legacy_tolerance)))
        lower = self._signed_float_box(float(link.get("lower_deviation_mm", -legacy_tolerance)))
        self.links_table.setCellWidget(row, 5, upper)
        self.links_table.setCellWidget(row, 6, lower)
        self._refresh_chain()

    def _read_chain(self):
        surfaces = []
        for row in range(self.surface_table.rowCount()):
            surfaces.append({
                "id": self.surface_table.item(row, 0).text().strip() if self.surface_table.item(row, 0) else "",
                "description": self.surface_table.item(row, 1).text().strip() if self.surface_table.item(row, 1) else "",
            })
        links = []
        for row in range(self.links_table.rowCount()):
            links.append({
                "label": self.links_table.item(row, 0).text().strip() if self.links_table.item(row, 0) else "",
                "type": self.links_table.cellWidget(row, 1).currentText(),
                "start": self.links_table.cellWidget(row, 2).currentText(),
                "end": self.links_table.cellWidget(row, 3).currentText(),
                "nominal_mm": self.links_table.cellWidget(row, 4).value(),
                "upper_deviation_mm": self.links_table.cellWidget(row, 5).value(),
                "lower_deviation_mm": self.links_table.cellWidget(row, 6).value(),
            })
        return surfaces, links

    def _refresh_chain(self, *_):
        surfaces, links = self._read_chain()
        ids = [item["id"] for item in surfaces]
        index = {value: position for position, value in enumerate(ids)}
        self.chain_scene.clear()
        if not ids:
            self.chain_scene.setSceneRect(0, 0, 400, 200)
            self.chain_status.setText("Добавьте поверхности и связи.")
            return
        x0, gap, y0 = 50, 130, 230
        node_positions = {value: (x0 + i * gap, y0) for i, value in enumerate(ids)}
        pen_node = QtGui.QPen(QtGui.QColor("#20354a"), 2)
        for surface in surfaces:
            x, y = node_positions[surface["id"]]
            self.chain_scene.addEllipse(x - 20, y - 20, 40, 40, pen_node, QtGui.QBrush(QtGui.QColor("#dcecff")))
            label = self.chain_scene.addText(surface["id"])
            label.setPos(x - label.boundingRect().width() / 2, y - 10)
            if surface["description"]:
                desc = self.chain_scene.addText(surface["description"])
                desc.setPos(x - 50, y + 26)
        colors = {"Технологический размер": "#2471a3", "Конструкторский размер": "#8e44ad", "Припуск": "#d35400"}
        for number, link in enumerate(links):
            if link["start"] not in index or link["end"] not in index or link["start"] == link["end"]:
                continue
            x1, _ = node_positions[link["start"]]
            x2, _ = node_positions[link["end"]]
            level = number // max(len(ids) - 1, 1)
            y = y0 - 65 - level * 45
            color = QtGui.QColor(colors[link["type"]])
            pen = QtGui.QPen(color, 2)
            self.chain_scene.addLine(x1, y0 - 20, x1, y, pen)
            self.chain_scene.addLine(x1, y, x2, y, pen)
            self.chain_scene.addLine(x2, y, x2, y0 - 20, pen)
            text = (f"{link['label']}  {link['nominal_mm']:g} "
                    f"({link['upper_deviation_mm']:+g}; {link['lower_deviation_mm']:+g}) мм")
            label = self.chain_scene.addText(text)
            label.setDefaultTextColor(color)
            label.setPos((x1 + x2) / 2 - label.boundingRect().width() / 2, y - 22)
            arrow = self.chain_scene.addPolygon(QtGui.QPolygonF([
                QtCore.QPointF(x2, y0 - 20), QtCore.QPointF(x2 - 5, y0 - 29), QtCore.QPointF(x2 + 5, y0 - 29)
            ]), pen, QtGui.QBrush(color))
        self.chain_scene.setSceneRect(self.chain_scene.itemsBoundingRect().adjusted(-30, -30, 30, 30))
        self.chain_view.fitInView(self.chain_scene.sceneRect(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)
        errors = validate_chain(surfaces, links)
        self.chain_status.setText("Проверка схемы: " + ("; ".join(errors) if errors else "структура дерева корректна."))

    def _save_data(self):
        surfaces, links = self._read_chain()
        payload = {
            "model_sha256": self.model_hash,
            "stock": {"surface_shift_um": self.shift_box.value(),
                      "curvature_um_per_mm": self.curvature_box.value(),
                      "length_mm": self.length_box.value()},
            "stages": self._read_stages(),
            "surfaces": surfaces,
            "links": links,
        }
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        self.data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.chain_status.setText(f"Исходные данные сохранены: {self.data_path.name}")

    def _load_data(self):
        if not self.data_path.exists():
            return
        try:
            data = json.loads(self.data_path.read_text(encoding="utf-8"))
            stock = data.get("stock", {})
            self.shift_box.setValue(float(stock.get("surface_shift_um", 0)))
            self.curvature_box.setValue(float(stock.get("curvature_um_per_mm", 0)))
            self.length_box.setValue(float(stock.get("length_mm", 1)))
            for stage in data.get("stages", []):
                self._add_stage(stage)
            for surface in data.get("surfaces", []):
                self._add_surface(surface)
            for link in data.get("links", []):
                self._add_link(link)
            self._refresh_chain()
        except (OSError, ValueError, TypeError, KeyError):
            QtWidgets.QMessageBox.warning(self, "Не удалось загрузить анализ",
                                          "Файл исходных данных повреждён или имеет неверный формат.")
