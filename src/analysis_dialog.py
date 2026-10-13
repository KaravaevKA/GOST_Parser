"""Поэтапный ввод переходов, расчёт припусков и схема размерной цепи."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from src.technological_analysis import (
    blank_spatial_deviation,
    calculate_allowance_stages,
    calculate_operation_route,
    validate_chain,
)
from src.operation_planning import (
    MACHINING_OPERATIONS,
    MAX_OPERATION_COUNT,
    OPERATION_PROCESS_DATA,
    build_operation_surfaces,
    build_process_surface_sequence,
    quality_options,
    resize_operation_sequence,
)


# Параметры волнистого обозначения припуска на схеме, в пикселях.
ALLOWANCE_WAVE_AMPLITUDE = 4.0
ALLOWANCE_WAVE_LENGTH = 55.0


class ChainGraphicsView(QtWidgets.QGraphicsView):
    """Просмотр схемы с перемещением мышью и масштабированием колёсиком."""

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self._zoom = 1.0
        self._has_fitted = False
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(
            QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        self.setResizeAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setToolTip(
            "Колесо мыши — масштаб; зажмите левую кнопку и двигайте мышь — перемещение."
        )

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if not delta:
            event.ignore()
            return

        factor = 1.15 if delta > 0 else 1 / 1.15
        next_zoom = self._zoom * factor
        if 0.15 <= next_zoom <= 8.0:
            self.scale(factor, factor)
            self._zoom = next_zoom
        event.accept()

    def fit_scene(self):
        scene = self.scene()
        if scene is None:
            return
        bounds = scene.itemsBoundingRect().adjusted(-30, -30, 30, 30)
        if bounds.isNull() or bounds.width() <= 0 or bounds.height() <= 0:
            return
        scene.setSceneRect(bounds)
        self.resetTransform()
        self.fitInView(bounds, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = 1.0
        self._has_fitted = True


class TechnologicalAnalysisWindow(QtWidgets.QMainWindow):
    def __init__(self, model_hash: str, model_name: str, parent=None,
                 detected_longitudinal_surfaces=None,
                 detected_diametral_surfaces=None):
        super().__init__(parent)
        self.model_hash = model_hash
        self.setWindowTitle(f"Расчёт припусков и цепей — {model_name}")
        self.resize(1080, 760)
        self.setMinimumSize(860, 600)
        self.data_path = Path(__file__).resolve().parents[1] / "data" / "analysis" / f"{model_hash[:16]}.json"
        tolerance_path = Path(__file__).resolve().parents[1] / "data" / "gost_h_h_tolerances.json"
        self.tolerance_data = json.loads(tolerance_path.read_text(encoding="utf-8"))
        self.detected_longitudinal_surfaces = list(detected_longitudinal_surfaces or [])
        self.detected_diametral_surfaces = list(detected_diametral_surfaces or [])
        self.chain_editors = {}
        self.processing_routes = {}
        self.processing_surfaces = []
        self._detected_chain_surfaces = {}
        self._selected_processing_key = None
        self._build_ui()
        self._load_data()
        for widget in (
            self.shift_box, self.curvature_box, self.length_box,
            self.stock_roughness_box, self.stock_defect_box,
        ):
            widget.valueChanged.connect(self._stock_parameters_changed)

    def _build_ui(self):
        root = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(root)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._build_operations_tab(), "Операции и квалитеты")
        self.tabs.addTab(self._build_allowance_tab(), "1. Переходы и припуски")
        self.tabs.addTab(
            self._build_chain_tab("diametral", "Построение диаметральной размерной цепи"),
            "Построение диаметральной размерной цепи",
        )
        self.tabs.addTab(
            self._build_chain_tab("longitudinal", "Построение размерной цепи продольных размеров"),
            "Построение размерной цепи продольных размеров",
        )
        outer.addWidget(self.tabs)
        self.setCentralWidget(root)

    def _build_operations_tab(self):
        """Редактор количества, типа операций и квалитетов поверхностей."""
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        intro = QtWidgets.QLabel(
            "Для распознанной поверхности задайте число переходов. Для каждого "
            "перехода выберите операцию и квалитет из рекомендованного диапазона. "
            "Схема маршрута показывает заготовку, промежуточные поверхности и "
            "распознанную целевую поверхность. По справочным данным автоматически "
            "рассчитываются минимальные припуски, номиналы и технологические связи."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.addWidget(QtWidgets.QLabel("Распознанные поверхности модели"))
        self.processing_surface_table = QtWidgets.QTableWidget(0, 4)
        self.processing_surface_table.setHorizontalHeaderLabels([
            "Код", "Тип поверхности", "Номинал, мм", "Число операций"
        ])
        self.processing_surface_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.processing_surface_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.processing_surface_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        self.processing_surface_table.horizontalHeader().setStretchLastSection(True)
        self.processing_surface_table.verticalHeader().setVisible(False)
        self.processing_surface_table.currentCellChanged.connect(
            self._select_processing_surface
        )
        left_layout.addWidget(self.processing_surface_table, 1)
        splitter.addWidget(left)

        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        self.processing_title = QtWidgets.QLabel("Операции выбранной поверхности")
        right_layout.addWidget(self.processing_title)
        self.operations_table = QtWidgets.QTableWidget(0, 10)
        self.operations_table.setHorizontalHeaderLabels([
            "Этап", "Поверхность", "Операция", "Рекомендуемый IT", "Выбранный IT",
            "ε установки, мкм", "Rz/T до операции, мкм", "Ky", "Zmin, мм",
            "Размер после операции, мм",
        ])
        self.operations_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        self.operations_table.horizontalHeader().setStretchLastSection(True)
        self.operations_table.verticalHeader().setVisible(False)
        right_layout.addWidget(self.operations_table, 2)

        view_box = QtWidgets.QGroupBox("Автоматически построенные поверхности маршрута")
        view_layout = QtWidgets.QVBoxLayout(view_box)
        controls = QtWidgets.QHBoxLayout()
        fit_button = QtWidgets.QPushButton("Показать весь маршрут")
        fit_button.clicked.connect(lambda: self.process_view.fit_scene())
        controls.addWidget(fit_button)
        controls.addStretch(1)
        view_layout.addLayout(controls)
        self.process_scene = QtWidgets.QGraphicsScene(self)
        self.process_view = ChainGraphicsView(self.process_scene)
        self.process_view.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        self.process_view.setMinimumHeight(190)
        view_layout.addWidget(self.process_view, 1)
        self.process_status = QtWidgets.QLabel(
            "Выберите поверхность и задайте число операций."
        )
        self.process_status.setWordWrap(True)
        view_layout.addWidget(self.process_status)
        right_layout.addWidget(view_box, 3)
        splitter.addWidget(right)
        splitter.setSizes([400, 680])
        layout.addWidget(splitter, 1)

        save_row = QtWidgets.QHBoxLayout()
        self.processing_save_status = QtWidgets.QLabel(
            "Операции, квалитеты и размерные цепи сохраняются в общий файл анализа."
        )
        self.processing_save_status.setWordWrap(True)
        save_row.addWidget(self.processing_save_status, 1)
        save_button = QtWidgets.QPushButton("Сохранить операции и квалитеты")
        save_button.clicked.connect(self._save_data)
        save_row.addWidget(save_button)
        layout.addLayout(save_row)
        return page

    def _populate_processing_surface_table(self):
        table = self.processing_surface_table
        table.blockSignals(True)
        table.setRowCount(0)
        self.processing_surfaces = list(self._detected_chain_surfaces.values())
        for row, surface in enumerate(self.processing_surfaces):
            table.insertRow(row)
            category = surface["category"]
            if category == "diametral":
                kind = "Диаметральная · " + (
                    "отверстие" if surface.get("surface_type") == "hole" else "вал"
                )
                nominal = f"Ø {surface['nominal_mm']:g}"
            else:
                kind = "Продольная · плоский торец/уступ"
                nominal = f"от первой грани: {surface['nominal_mm']:g}"
            source_key = surface["key"]
            values = (surface["chain_id"], kind, nominal)
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(QtCore.Qt.ItemDataRole.UserRole, source_key)
                table.setItem(row, column, item)
            route = self.processing_routes.setdefault(source_key, {
                "operation_count": 0, "stock_grade": None, "operations": []
            })
            operations = resize_operation_sequence(
                list(route.get("operations", [])),
                int(route.get("operation_count", 0)),
            )
            route["operations"] = operations
            count = QtWidgets.QSpinBox()
            count.setRange(0, MAX_OPERATION_COUNT)
            count.setValue(len(operations))
            count.setToolTip("Число технологических операций для этой поверхности")
            count.valueChanged.connect(
                lambda value, key=source_key: self._set_operation_count(key, value)
            )
            table.setCellWidget(row, 3, count)
        table.blockSignals(False)
        if table.rowCount():
            table.selectRow(0)
        else:
            self._selected_processing_key = None
            self.operations_table.setRowCount(0)
            self._refresh_process_graph()
            self.processing_title.setText("Операции выбранной поверхности")
            self.process_status.setText(
                "Модель не передала распознанные поверхности. Операционный маршрут пока пуст."
            )

    def update_detected_surfaces(self, longitudinal_surfaces=None,
                                 diametral_surfaces=None):
        """Обновить распознанные поверхности, если модель перечитали в главном окне."""
        self.detected_longitudinal_surfaces = list(longitudinal_surfaces or [])
        self.detected_diametral_surfaces = list(diametral_surfaces or [])
        self._detected_chain_surfaces.clear()

        self._merge_detected_surfaces(
            "diametral", [], self.detected_diametral_surfaces, add_missing=True
        )
        self._merge_detected_surfaces(
            "longitudinal", [], self.detected_longitudinal_surfaces, add_missing=True
        )
        self._populate_processing_surface_table()
        self._sync_operation_surfaces()
        self._refresh_chain("diametral")
        self._refresh_chain("longitudinal")

    def _select_processing_surface(self, row, _column, _previous_row, _previous_column):
        if row < 0 or row >= len(self.processing_surfaces):
            return
        self._selected_processing_key = self.processing_surfaces[row]["key"]
        self._render_operation_sequence()

    def _set_operation_count(self, source_key, count):
        route = self.processing_routes.setdefault(source_key, {
            "operation_count": 0, "stock_grade": None, "operations": []
        })
        route["operations"] = resize_operation_sequence(
            list(route.get("operations", [])), count
        )
        route["operation_count"] = count
        self._sync_operation_surfaces()
        self._selected_processing_key = source_key
        for row in range(self.processing_surface_table.rowCount()):
            item = self.processing_surface_table.item(row, 0)
            if item and item.data(QtCore.Qt.ItemDataRole.UserRole) == source_key:
                self.processing_surface_table.selectRow(row)
                break
        self._render_operation_sequence()

    def _current_processing_surface(self):
        return next(
            (surface for surface in self.processing_surfaces
             if surface["key"] == self._selected_processing_key),
            None,
        )

    @staticmethod
    def _grade_combo(options, selected=None):
        combo = QtWidgets.QComboBox()
        combo.addItem("— выбрать —", None)
        for grade in options:
            combo.addItem(f"IT{grade}", grade)
        selected_index = combo.findData(selected)
        combo.setCurrentIndex(max(0, selected_index))
        return combo

    def _render_operation_sequence(self):
        surface = self._current_processing_surface()
        if surface is None:
            return
        source_key = surface["key"]
        route = self.processing_routes.setdefault(source_key, {
            "operation_count": 0, "stock_grade": None, "operations": []
        })
        operations = resize_operation_sequence(
            list(route.get("operations", [])),
            int(route.get("operation_count", 0)),
        )
        route["operations"] = operations
        route["operation_count"] = len(operations)
        if route.get("stock_grade") is None:
            route["stock_grade"] = 17
        calculation = self._calculate_route_for_surface(surface, route)
        route["calculation"] = calculation
        label = surface.get("description") or surface["chain_id"]
        self.processing_title.setText(f"Операции для поверхности {surface['chain_id']}: {label}")

        table = self.operations_table
        table.setRowCount(0)
        if not operations:
            self.process_status.setText(
                "Задайте число операций в таблице поверхностей."
            )
            self._refresh_process_graph()
            return

        table.setRowCount(len(operations) + 1)
        stock_values = ("0", f"Заготовка для {surface['chain_id']}", "Заготовка")
        for column, value in enumerate(stock_values):
            table.setItem(0, column, QtWidgets.QTableWidgetItem(value))
        stock_grades = quality_options("Заготовка")
        stock_low, stock_high = stock_grades[0], stock_grades[-1]
        table.setItem(0, 3, QtWidgets.QTableWidgetItem(f"IT{stock_low}–{stock_high}"))
        stock_grade = self._grade_combo(
            quality_options("Заготовка"), route.get("stock_grade", 17)
        )
        stock_grade.currentIndexChanged.connect(self._processing_grade_changed)
        table.setCellWidget(0, 4, stock_grade)

        for index, stage in enumerate(operations, start=1):
            table.setItem(index, 0, QtWidgets.QTableWidgetItem(str(index)))
            process_surface = (
                surface["chain_id"] if index == len(operations)
                else f"{surface['chain_id']}.{index}"
            )
            label = "Целевая поверхность" if index == len(operations) else "Промежуточная поверхность"
            table.setItem(index, 1, QtWidgets.QTableWidgetItem(f"{process_surface} · {label}"))
            operation = QtWidgets.QComboBox()
            operation.addItem("— выбрать операцию —", None)
            # addItems() создаёт пункты без userData, а ниже код получает
            # выбранную операцию через currentData(). Связываем текст с данными.
            for operation_name in MACHINING_OPERATIONS:
                operation.addItem(operation_name, operation_name)
            operation_index = operation.findData(stage.get("operation"))
            operation.setCurrentIndex(max(0, operation_index))
            operation.currentTextChanged.connect(
                lambda _text, row=index: self._processing_operation_changed(row)
            )
            table.setCellWidget(index, 2, operation)
            operation_name = operation.currentData()
            operation_grades = quality_options(operation_name) if operation_name else []
            recommendation = (
                f"IT{operation_grades[0]}–{operation_grades[-1]}"
                if operation_grades else "— выберите операцию —"
            )
            table.setItem(index, 3, QtWidgets.QTableWidgetItem(recommendation))
            grade = self._grade_combo(
                operation_grades, stage.get("grade")
            )
            grade.setEnabled(bool(operation_name))
            grade.currentIndexChanged.connect(self._processing_grade_changed)
            table.setCellWidget(index, 4, grade)
            setup_error = self._float_box(
                float(stage.get("setup_error_um", 0)), 1_000_000.0
            )
            setup_error.setDecimals(3)
            setup_error.setToolTip(
                "Погрешность установки εi, мкм. Из таблицы приспособлений; "
                "без переустановки оставьте 0."
            )
            setup_error.valueChanged.connect(self._processing_grade_changed)
            table.setCellWidget(index, 5, setup_error)
            step = (
                calculation.get("steps", [])[index - 1]
                if calculation.get("complete") else None
            )
            table.setItem(index, 6, QtWidgets.QTableWidgetItem(
                f"{step['roughness_before_um']:g} / {step['defect_layer_before_um']:g}"
                if step else "—"
            ))
            table.setItem(index, 7, QtWidgets.QTableWidgetItem(
                f"{step['ky']:g}" if step else "—"
            ))
            table.setItem(index, 8, QtWidgets.QTableWidgetItem(
                f"{step['minimum_allowance_um'] / 1000:.6f}" if step else "—"
            ))
            table.setItem(index, 9, QtWidgets.QTableWidgetItem(
                f"{step['nominal_after_mm']:.6f}" if step else "—"
            ))
        self._refresh_process_graph()

    def _calculate_route_for_surface(self, surface, route):
        """Пересчитать один маршрут по справочным данным и настройкам заготовки."""
        operations = []
        for stage in route.get("operations", []):
            operation_name = stage.get("operation")
            operations.append({
                **stage,
                "process_data": OPERATION_PROCESS_DATA.get(operation_name),
            })
        try:
            rho0 = blank_spatial_deviation(
                self.shift_box.value(), self.curvature_box.value(),
                float(surface.get("length", self.length_box.value()))
                if surface.get("length") else self.length_box.value(),
            )
            return calculate_operation_route(
                operations=operations,
                final_nominal_mm=float(surface["nominal_mm"]),
                category=surface["category"],
                surface_type=surface.get("surface_type", "shaft"),
                stock_grade=int(route.get("stock_grade", 17)),
                stock_roughness_um=self.stock_roughness_box.value(),
                stock_defect_layer_um=self.stock_defect_box.value(),
                initial_spatial_deviation_um=rho0,
                tolerance_data=self.tolerance_data,
                linear_direction=int(surface.get("linear_direction", 1)),
            )
        except (ValueError, KeyError, TypeError) as error:
            return {"complete": False, "message": str(error)}

    def _stock_parameters_changed(self, *_):
        self._write_current_processing_route()
        self._render_operation_sequence()
        self._sync_operation_surfaces()
        self._refresh_process_graph()

    def _processing_operation_changed(self, row):
        if row <= 0 or row >= self.operations_table.rowCount():
            return
        table = self.operations_table
        operation = table.cellWidget(row, 2)
        if operation is None:
            return
        name = operation.currentData()
        operation_grades = quality_options(name) if name else []
        recommendation = (
            f"IT{operation_grades[0]}–{operation_grades[-1]}"
            if operation_grades else "— выберите операцию —"
        )
        table.item(row, 3).setText(recommendation)
        old_grade = table.cellWidget(row, 4).currentData()
        new_grade = self._grade_combo(operation_grades, old_grade)
        new_grade.setEnabled(bool(name))
        new_grade.currentIndexChanged.connect(self._processing_grade_changed)
        table.setCellWidget(row, 4, new_grade)
        self._write_current_processing_route()
        self._render_operation_sequence()
        self._sync_operation_surfaces()
        self._refresh_process_graph()

    def _processing_grade_changed(self, *_):
        self._write_current_processing_route()
        self._render_operation_sequence()
        self._sync_operation_surfaces()
        self._refresh_process_graph()

    def _write_current_processing_route(self):
        surface = self._current_processing_surface()
        if surface is None:
            return
        table = self.operations_table
        if table.rowCount() == 0:
            return
        route = self.processing_routes.setdefault(surface["key"], {})
        stock_grade = table.cellWidget(0, 4)
        route["stock_grade"] = stock_grade.currentData() if stock_grade else None
        operations = []
        for row in range(1, table.rowCount()):
            operation = table.cellWidget(row, 2)
            grade = table.cellWidget(row, 4)
            if operation is None or grade is None:
                continue
            operations.append({
                "number": row,
                "operation": operation.currentData(),
                "grade": grade.currentData(),
                "setup_error_um": (
                    table.cellWidget(row, 5).value()
                    if table.cellWidget(row, 5) else 0.0
                ),
            })
        route["operation_count"] = len(operations)
        route["operations"] = operations

    def _refresh_process_graph(self):
        scene = self.process_scene
        scene.clear()
        surface = self._current_processing_surface()
        if surface is None:
            scene.setSceneRect(0, 0, 400, 140)
            return
        route = self.processing_routes.get(surface["key"], {})
        sequence = build_process_surface_sequence(surface, route)
        calculation = route.get("calculation", {})
        if calculation.get("complete"):
            sequence[0]["nominal_mm"] = calculation["stock_nominal_mm"]
            for index, step in enumerate(calculation["steps"], start=1):
                if index < len(sequence):
                    sequence[index]["nominal_mm"] = step["nominal_after_mm"]
        if len(sequence) == 1 and sequence[0]["kind"] == "finished":
            self.process_status.setText(
                "Задайте число операций. Промежуточные поверхности будут добавлены автоматически."
            )
        else:
            operation_count = max(0, len(sequence) - 1)
            if calculation.get("complete"):
                allowance_text = "; ".join(
                    f"Z{step['number']}min={step['minimum_allowance_um'] / 1000:.4f} мм"
                    for step in calculation["steps"]
                )
                self.process_status.setText(
                    f"Рассчитано по верхним границам справочных диапазонов: {allowance_text}. "
                    "Промежуточные размеры показаны в блоках маршрута."
                )
            else:
                self.process_status.setText(
                    f"Поверхностей маршрута: {len(sequence)} — заготовка, "
                    f"{max(0, operation_count - 1)} промежуточных и целевая поверхность. "
                    + calculation.get("message", "Выберите операции и квалитеты для расчёта.")
                )
        y = 90
        x_start = 50
        gap = 210
        for index, stage in enumerate(sequence):
            x = x_start + index * gap
            color = "#f5cba7" if stage["kind"] == "stock" else (
                "#d6eaf8" if stage["kind"] == "intermediate" else "#d5f5e3"
            )
            rounded_rect = QtGui.QPainterPath()
            rounded_rect.addRoundedRect(QtCore.QRectF(x, y - 35, 170, 70), 8, 8)
            scene.addPath(
                rounded_rect,
                QtGui.QPen(QtGui.QColor("#34495e"), 2),
                QtGui.QBrush(QtGui.QColor(color)),
            )
            grade = f"IT{stage['grade']}" if stage.get("grade") is not None else "IT не выбран"
            title = stage.get("operation") or "Операция не выбрана"
            caption = "Заготовка" if stage["kind"] == "stock" else stage["id"]
            nominal = stage.get("nominal_mm")
            nominal_label = ""
            if nominal is not None:
                nominal_label = (
                    f"\nØ{nominal:.4f} мм" if surface.get("category") == "diametral"
                    else f"\nA={nominal:.4f} мм"
                )
            text = scene.addText(f"{caption}\n{title}\n{grade}{nominal_label}")
            text.setTextWidth(160)
            text.setPos(x + 5, y - 29)
            if index:
                previous_x = x_start + (index - 1) * gap
                scene.addLine(previous_x + 170, y, x, y, QtGui.QPen(QtGui.QColor("#2471a3"), 2))
                scene.addPolygon(QtGui.QPolygonF([
                    QtCore.QPointF(x, y), QtCore.QPointF(x - 8, y - 5),
                    QtCore.QPointF(x - 8, y + 5),
                ]), QtGui.QPen(QtGui.QColor("#2471a3"), 1),
                    QtGui.QBrush(QtGui.QColor("#2471a3")))
        bounds = scene.itemsBoundingRect().adjusted(-25, -25, 25, 25)
        scene.setSceneRect(bounds)
        if not self.process_view._has_fitted:
            self.process_view.fit_scene()

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
        self.stock_roughness_box = self._float_box(150.0)
        self.stock_defect_box = self._float_box(150.0)
        form.addRow("Смещение поверхности ρсм, мкм", self.shift_box)
        form.addRow("Удельная кривизна Δк, мкм/мм", self.curvature_box)
        form.addRow("Расчётная длина L, мм", self.length_box)
        form.addRow("Rz заготовки, мкм", self.stock_roughness_box)
        form.addRow("Дефектный слой заготовки T, мкм", self.stock_defect_box)
        stock_note = QtWidgets.QLabel(
            "Начальные Rz=150 мкм и T=150 мкм соответствуют верхним границам "
            "для горячекатаного проката обычной точности из таблицы 7. "
            "Измените их для другого способа получения заготовки."
        )
        stock_note.setWordWrap(True)
        form.addRow(stock_note)
        layout.addWidget(stock)

        help_text = QtWidgets.QLabel(
            "Припуски и промежуточные номиналы рассчитываются по выбранным операциям "
            "и IT. Rz и T операции берутся по верхним границам таблицы 7; Ky — из "
            "таблицы 6. ε установки указывается в маршруте операции; без переустановки "
            "оставьте 0. Если Ky отсутствует в таблице 6, принимается Ky=1 "
            "(пространственное отклонение не уменьшается)."
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

    def _build_chain_tab(self, chain_key, title):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        if chain_key == "longitudinal":
            help_text = QtWidgets.QLabel(
                "Добавьте продольные поверхности слева направо и связи между ними. "
                "Чтобы замкнуть цепь, добавьте связь типа «Продольный размер заготовки» "
                "между первой и последней поверхностями. Схема справа обновляется автоматически."
            )
        else:
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
        surface_table = QtWidgets.QTableWidget(0, 2)
        surface_table.setHorizontalHeaderLabels(["Код", "Описание / база"])
        surface_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        left_layout.addWidget(surface_table, 1)
        surface_buttons = QtWidgets.QHBoxLayout()
        add_surface = QtWidgets.QPushButton("Добавить поверхность")
        add_surface.clicked.connect(lambda _checked=False, key=chain_key: self._add_surface(key))
        remove_surface = QtWidgets.QPushButton("Удалить")
        remove_surface.clicked.connect(lambda _checked=False, key=chain_key: self._remove_surface(key))
        surface_buttons.addWidget(add_surface)
        surface_buttons.addWidget(remove_surface)
        left_layout.addLayout(surface_buttons)
        left_layout.addWidget(QtWidgets.QLabel("Размерные связи"))
        links_table = QtWidgets.QTableWidget(0, 7)
        links_table.setHorizontalHeaderLabels([
            "Обозначение", "Тип", "От", "До", "Номинал, мм", "Верхнее откл., мм", "Нижнее откл., мм"
        ])
        links_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        links_table.horizontalHeader().setStretchLastSection(True)
        left_layout.addWidget(links_table, 1)
        link_buttons = QtWidgets.QHBoxLayout()
        add_link = QtWidgets.QPushButton("Добавить связь")
        add_link.clicked.connect(lambda _checked=False, key=chain_key: self._add_link(key))
        remove_link = QtWidgets.QPushButton("Удалить связь")
        remove_link.clicked.connect(
            lambda _checked=False, key=chain_key: self._remove_link(key)
        )
        link_buttons.addWidget(add_link)
        link_buttons.addWidget(remove_link)
        left_layout.addLayout(link_buttons)
        splitter.addWidget(left)

        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.addWidget(QtWidgets.QLabel(f"Схема: {title.lower()}"))
        view_controls = QtWidgets.QHBoxLayout()
        refresh_visualization = QtWidgets.QPushButton("Обновить визуализацию")
        refresh_visualization.clicked.connect(
            lambda _checked=False, key=chain_key: self._refresh_chain(key)
        )
        view_controls.addWidget(refresh_visualization)
        fit_visualization = QtWidgets.QPushButton("Показать всю схему")
        fit_visualization.clicked.connect(
            lambda _checked=False, key=chain_key: self.chain_editors[key][
                "view"
            ].fit_scene()
        )
        view_controls.addWidget(fit_visualization)
        view_controls.addStretch(1)
        right_layout.addLayout(view_controls)
        scene = QtWidgets.QGraphicsScene(self)
        view = ChainGraphicsView(scene)
        view.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        view.setMinimumWidth(360)
        right_layout.addWidget(view, 1)
        right_layout.addWidget(
            QtWidgets.QLabel(
                "Колесо — масштаб; зажмите ЛКМ и двигайте мышь — перемещение."
            )
        )
        status = QtWidgets.QLabel("Добавьте поверхности и связи.")
        status.setWordWrap(True)
        right_layout.addWidget(status)
        splitter.addWidget(right)
        splitter.setSizes([600, 480])
        layout.addWidget(splitter, 1)
        save = QtWidgets.QPushButton("Сохранить исходные данные")
        save.clicked.connect(self._save_data)
        layout.addWidget(save, alignment=QtCore.Qt.AlignmentFlag.AlignRight)

        link_types = ["Технологический размер", "Конструкторский размер", "Припуск"]
        if chain_key == "longitudinal":
            link_types.append("Продольный размер заготовки")

        self.chain_editors[chain_key] = {
            "surface_table": surface_table,
            "links_table": links_table,
            "scene": scene,
            "view": view,
            "status": status,
            "link_types": link_types,
        }
        surface_table.itemChanged.connect(
            lambda _item=None, key=chain_key: self._refresh_surface_choices(key)
        )
        links_table.itemChanged.connect(
            lambda _item=None, key=chain_key: self._refresh_chain(key)
        )
        return page

    def _remove_link(self, chain_key):
        table = self.chain_editors[chain_key]["links_table"]
        row = table.currentRow()
        if row >= 0:
            table.removeRow(row)
            self._refresh_chain(chain_key)

    def _add_surface(self, chain_key, surface=None):
        surface = surface or {}
        table = self.chain_editors[chain_key]["surface_table"]
        row = table.rowCount()
        table.insertRow(row)
        id_item = QtWidgets.QTableWidgetItem(str(surface.get("id", row + 1)))
        id_item.setData(
            QtCore.Qt.ItemDataRole.UserRole,
            surface.get("process_meta", {}),
        )
        table.setItem(row, 0, id_item)
        table.setItem(row, 1, QtWidgets.QTableWidgetItem(surface.get("description", "")))
        self._refresh_surface_choices(chain_key)

    def _remove_surface(self, chain_key):
        table = self.chain_editors[chain_key]["surface_table"]
        row = table.currentRow()
        if row >= 0:
            table.removeRow(row)
            self._refresh_surface_choices(chain_key)

    def _surface_ids(self, chain_key):
        table = self.chain_editors[chain_key]["surface_table"]
        return [table.item(row, 0).text().strip()
                for row in range(table.rowCount()) if table.item(row, 0)]

    def _refresh_surface_choices(self, chain_key):
        editor = self.chain_editors[chain_key]
        ids = self._surface_ids(chain_key)
        links_table = editor["links_table"]
        for row in range(links_table.rowCount()):
            for column in (2, 3):
                combo = links_table.cellWidget(row, column)
                old = combo.currentText() if combo else ""
                combo.blockSignals(True)
                combo.clear()
                combo.addItems(ids)
                if old in ids:
                    combo.setCurrentText(old)
                elif old:
                    combo.setCurrentIndex(-1)
                combo.blockSignals(False)
        self._refresh_chain(chain_key)

    def _sync_operation_surfaces(self):
        """Синхронизировать строки переходных поверхностей с маршрутами операций."""
        for source_key, source_surface in self._detected_chain_surfaces.items():
            route = self.processing_routes.get(source_key)
            if route is not None:
                if route.get("stock_grade") is None:
                    route["stock_grade"] = 17
                route["calculation"] = self._calculate_route_for_surface(
                    source_surface, route
                )
        for chain_key in ("diametral", "longitudinal"):
            editor = self.chain_editors.get(chain_key)
            if editor is None:
                continue
            table = editor["surface_table"]

            # Сохраняем идентификаторы уже созданных строк, чтобы пересборка после
            # изменения типа операции или квалитета не меняла ссылки пользователя.
            previous_ids = {}
            generated_rows = []
            for row in range(table.rowCount()):
                id_item = table.item(row, 0)
                metadata = id_item.data(QtCore.Qt.ItemDataRole.UserRole) or {} if id_item else {}
                if metadata.get("route_generated"):
                    token = (
                        metadata.get("parent_source_key"),
                        metadata.get("operation_number"),
                    )
                    previous_ids.setdefault(token, id_item.text().strip() if id_item else "")
                    generated_rows.append(row)

            # Удаляем только строки, созданные автоматически этим механизмом.
            # Пользовательские и CAD-поверхности остаются на месте.
            signals_were_blocked = table.blockSignals(True)
            try:
                for row in reversed(generated_rows):
                    table.removeRow(row)

                used_ids = {
                    table.item(row, 0).text().strip()
                    for row in range(table.rowCount())
                    if table.item(row, 0) is not None
                }

                for source_key, source_surface in self._detected_chain_surfaces.items():
                    if source_surface.get("category") != chain_key:
                        continue
                    route = self.processing_routes.get(source_key, {})
                    generated = build_operation_surfaces(source_surface, route)
                    if not generated:
                        continue

                    # Вставляем переходные состояния непосредственно перед найденной
                    # конечной поверхностью, сохраняя порядок обработки слева направо.
                    target_row = None
                    for row in range(table.rowCount()):
                        id_item = table.item(row, 0)
                        metadata = id_item.data(QtCore.Qt.ItemDataRole.UserRole) or {} if id_item else {}
                        if metadata.get("key") == source_key:
                            target_row = row
                            break
                    if target_row is None:
                        continue

                    for offset, generated_surface in enumerate(generated):
                        operation_number = offset + 1
                        token = (source_key, operation_number)
                        candidate = previous_ids.get(token) or generated_surface["id"]
                        base_candidate = candidate
                        suffix = 2
                        while candidate in used_ids:
                            candidate = f"{base_candidate}_{suffix}"
                            suffix += 1
                        used_ids.add(candidate)
                        generated_surface["id"] = candidate

                        row = target_row + offset
                        table.insertRow(row)
                        table.setItem(row, 0, QtWidgets.QTableWidgetItem(candidate))
                        table.item(row, 0).setData(
                            QtCore.Qt.ItemDataRole.UserRole,
                            generated_surface["process_meta"],
                        )
                        table.setItem(
                            row, 1,
                            QtWidgets.QTableWidgetItem(generated_surface["description"]),
                        )
            finally:
                table.blockSignals(signals_were_blocked)

            self._sync_process_links(chain_key)
            self._refresh_surface_choices(chain_key)

    def _sync_process_links(self, chain_key):
        """Создать технологические размеры и минимальные припуски маршрута."""
        editor = self.chain_editors[chain_key]
        links_table = editor["links_table"]
        was_blocked = links_table.blockSignals(True)
        try:
            for row in reversed(range(links_table.rowCount())):
                label_item = links_table.item(row, 0)
                metadata = (
                    label_item.data(QtCore.Qt.ItemDataRole.UserRole) or {}
                    if label_item else {}
                )
                if metadata.get("route_generated_link"):
                    links_table.removeRow(row)
        finally:
            links_table.blockSignals(was_blocked)

        surface_table = editor["surface_table"]
        generated_ids = {}
        for row in range(surface_table.rowCount()):
            id_item = surface_table.item(row, 0)
            metadata = id_item.data(QtCore.Qt.ItemDataRole.UserRole) or {} if id_item else {}
            if metadata.get("route_generated") and metadata.get("category") == chain_key:
                generated_ids.setdefault(metadata.get("parent_source_key"), {})[
                    metadata.get("operation_number")
                ] = id_item.text().strip()

        for source_key, source_surface in self._detected_chain_surfaces.items():
            if source_surface.get("category") != chain_key:
                continue
            route = self.processing_routes.get(source_key, {})
            calculation = route.get("calculation", {})
            if not calculation.get("complete"):
                continue
            count = int(route.get("operation_count", 0))
            process_surface_ids = generated_ids.get(source_key, {})
            target_id = source_surface.get("chain_id")
            for number, step in enumerate(calculation.get("steps", []), start=1):
                start_id = process_surface_ids.get(number)
                end_id = process_surface_ids.get(number + 1, target_id)
                if not start_id or not end_id:
                    continue
                tol = (step["tolerance_before_um"] + step["tolerance_after_um"]) / 2000.0
                self._add_link(chain_key, {
                    "label": f"T{number}-{target_id}",
                    "type": "Технологический размер",
                    "start": start_id,
                    "end": end_id,
                    "nominal_mm": step["technological_size_mm"],
                    "upper_deviation_mm": tol,
                    "lower_deviation_mm": -tol,
                    "process_meta": {
                        "route_generated_link": True,
                        "parent_source_key": source_key,
                        "operation_number": number,
                        "link_kind": "technology",
                    },
                })
                self._add_link(chain_key, {
                    "label": f"Z{number}-{target_id}",
                    "type": "Припуск",
                    "start": start_id,
                    "end": end_id,
                    "nominal_mm": step["minimum_allowance_um"] / 1000.0,
                    "upper_deviation_mm": 0.0,
                    "lower_deviation_mm": 0.0,
                    "process_meta": {
                        "route_generated_link": True,
                        "parent_source_key": source_key,
                        "operation_number": number,
                        "link_kind": "allowance",
                    },
                })

    def _add_link(self, chain_key, link=None):
        link = link or {}
        editor = self.chain_editors[chain_key]
        links_table = editor["links_table"]
        row = links_table.rowCount()
        was_blocked = links_table.blockSignals(True)
        try:
            links_table.insertRow(row)
            default_label = f"Zз" if chain_key == "longitudinal" else f"A{row + 1}"
            links_table.setItem(
                row, 0,
                QtWidgets.QTableWidgetItem(link.get("label", default_label)),
            )
            if link.get("process_meta"):
                links_table.item(row, 0).setData(
                    QtCore.Qt.ItemDataRole.UserRole, link["process_meta"]
                )
            kind = QtWidgets.QComboBox()
            kind.addItems(editor["link_types"])
            kind.setCurrentText(link.get("type", "Технологический размер"))
            links_table.setCellWidget(row, 1, kind)
            ids = self._surface_ids(chain_key)
            for column, key in [(2, "start"), (3, "end")]:
                combo = QtWidgets.QComboBox()
                combo.addItems(ids)
                if link.get(key) in ids:
                    combo.setCurrentText(link[key])
                links_table.setCellWidget(row, column, combo)
            nominal = self._float_box(float(link.get("nominal_mm", 0)), 1_000_000)
            links_table.setCellWidget(row, 4, nominal)
            legacy_tolerance = float(link.get("tolerance_mm", 0))
            upper = self._signed_float_box(
                float(link.get("upper_deviation_mm", legacy_tolerance))
            )
            lower = self._signed_float_box(
                float(link.get("lower_deviation_mm", -legacy_tolerance))
            )
            links_table.setCellWidget(row, 5, upper)
            links_table.setCellWidget(row, 6, lower)
        finally:
            links_table.blockSignals(was_blocked)
        self._refresh_chain(chain_key)

    def _read_chain(self, chain_key):
        editor = self.chain_editors[chain_key]
        surface_table = editor["surface_table"]
        links_table = editor["links_table"]
        surfaces = []
        for row in range(surface_table.rowCount()):
            id_item = surface_table.item(row, 0)
            surfaces.append({
                "id": id_item.text().strip() if id_item else "",
                "description": surface_table.item(row, 1).text().strip() if surface_table.item(row, 1) else "",
                "process_meta": id_item.data(QtCore.Qt.ItemDataRole.UserRole) or {} if id_item else {},
            })
        links = []
        for row in range(links_table.rowCount()):
            kind = links_table.cellWidget(row, 1)
            start = links_table.cellWidget(row, 2)
            end = links_table.cellWidget(row, 3)
            nominal = links_table.cellWidget(row, 4)
            upper = links_table.cellWidget(row, 5)
            lower = links_table.cellWidget(row, 6)
            # Пропускаем строку, пока при её создании не установлены все поля.
            if any(widget is None for widget in
                   (kind, start, end, nominal, upper, lower)):
                continue
            links.append({
                "label": links_table.item(row, 0).text().strip() if links_table.item(row, 0) else "",
                "type": kind.currentText(),
                "start": start.currentText(),
                "end": end.currentText(),
                "nominal_mm": nominal.value(),
                "upper_deviation_mm": upper.value(),
                "lower_deviation_mm": lower.value(),
                "process_meta": links_table.item(row, 0).data(
                    QtCore.Qt.ItemDataRole.UserRole
                ) if links_table.item(row, 0) else {},
            })
        return surfaces, links

    def _refresh_chain(self, chain_key, *_):
        editor = self.chain_editors[chain_key]
        scene = editor["scene"]
        view = editor["view"]
        status = editor["status"]
        surfaces, links = self._read_chain(chain_key)
        ids = [item["id"] for item in surfaces]
        index = {value: position for position, value in enumerate(ids)}
        scene.clear()
        if not ids:
            scene.setSceneRect(0, 0, 400, 200)
            status.setText("Добавьте поверхности и связи.")
            return
        valid_links = [
            link for link in links
            if link["start"] in index
            and link["end"] in index
            and link["start"] != link["end"]
        ]
        lane_step = 62
        y0 = max(230, 105 + lane_step * len(valid_links))
        x0, gap = 50, 130
        node_positions = {value: (x0 + i * gap, y0) for i, value in enumerate(ids)}
        pen_node = QtGui.QPen(QtGui.QColor("#20354a"), 2)
        for surface in surfaces:
            x, y = node_positions[surface["id"]]
            node_pen = QtGui.QPen(QtGui.QColor("#20354a"), 2)
            metadata = surface.get("process_meta", {})
            node_color = "#fce4c7" if metadata.get("route_generated") else "#dcecff"
            node_brush = QtGui.QBrush(QtGui.QColor(node_color))
            scene.addEllipse(x - 20, y - 20, 40, 40, node_pen, node_brush)
            label = scene.addText(surface["id"])
            label.setPos(x - label.boundingRect().width() / 2, y - 10)
            if surface["description"]:
                desc = scene.addText(surface["description"])
                desc.setPos(x - 50, y + 26)
        colors = {
            "Технологический размер": "#2471a3",
            "Конструкторский размер": "#8e44ad",
            "Припуск": "#d35400",
            "Продольный размер заготовки": "#13866d",
        }
        for number, link in enumerate(valid_links):
            x1, _ = node_positions[link["start"]]
            x2, _ = node_positions[link["end"]]
            y = y0 - 55 - number * lane_step
            color = QtGui.QColor(colors[link["type"]])
            pen = QtGui.QPen(color, 2)
            scene.addLine(x1, y0 - 20, x1, y, pen)
            scene.addLine(x2, y, x2, y0 - 20, pen)
            if link["type"] == "Припуск":
                # Амплитуда управляет высотой волн, длина — расстоянием между ними.
                path = QtGui.QPainterPath()
                path.moveTo(x1, y)
                wave_count = max(2, round(abs(x2 - x1) / ALLOWANCE_WAVE_LENGTH))
                segments = wave_count * 2
                step = (x2 - x1) / segments
                for part in range(segments):
                    start_x = x1 + part * step
                    end_x = start_x + step
                    direction = 1 if part % 2 == 0 else -1
                    path.cubicTo(
                        start_x + step / 3,
                        y + direction * ALLOWANCE_WAVE_AMPLITUDE,
                        start_x + 2 * step / 3,
                        y - direction * ALLOWANCE_WAVE_AMPLITUDE,
                        end_x,
                        y,
                    )
                scene.addPath(path, pen)
            else:
                scene.addLine(x1, y, x2, y, pen)
            text = (f"{link['label']}  {link['nominal_mm']:g} "
                    f"({link['upper_deviation_mm']:+g}; {link['lower_deviation_mm']:+g}) мм")
            label = scene.addText(text)
            label.setDefaultTextColor(color)
            label.setPos(
                (x1 + x2) / 2 - label.boundingRect().width() / 2,
                y - label.boundingRect().height() - 7,
            )
            label.setZValue(2)
            background = scene.addRect(
                label.sceneBoundingRect().adjusted(-4, -2, 4, 2),
                QtGui.QPen(QtCore.Qt.PenStyle.NoPen),
                QtGui.QBrush(QtGui.QColor("#ffffff")),
            )
            background.setZValue(1)
            scene.addPolygon(QtGui.QPolygonF([
                QtCore.QPointF(x2, y0 - 20), QtCore.QPointF(x2 - 5, y0 - 29), QtCore.QPointF(x2 + 5, y0 - 29)
            ]), pen, QtGui.QBrush(color))
        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-30, -30, 30, 30))
        if not view._has_fitted:
            view.fit_scene()
        errors = validate_chain(surfaces, links)
        if chain_key == "longitudinal":
            stock_links = [link for link in links if link["type"] == "Продольный размер заготовки"]
            if not stock_links:
                errors.append("Добавьте продольный размер заготовки — он замкнёт размерную цепь.")
            elif len(stock_links) > 1:
                errors.append("Для замыкания укажите только один продольный размер заготовки.")
            elif len(ids) >= 2:
                outer_surfaces = {ids[0], ids[-1]}
                stock_link = stock_links[0]
                if {stock_link["start"], stock_link["end"]} != outer_surfaces:
                    errors.append("Размер заготовки должен связывать первую и последнюю поверхности.")
        status.setText(
            "Проверка схемы: " + ("; ".join(errors) if errors else (
                "структура размерной цепи корректна."
                if chain_key == "longitudinal"
                else "структура дерева корректна."
            ))
        )

    def _save_data(self):
        self._write_current_processing_route()
        self._sync_operation_surfaces()
        surfaces, links = self._read_chain("diametral")
        longitudinal_surfaces, longitudinal_links = self._read_chain("longitudinal")
        payload = {
            "model_sha256": self.model_hash,
            "stock": {"surface_shift_um": self.shift_box.value(),
                      "curvature_um_per_mm": self.curvature_box.value(),
                      "length_mm": self.length_box.value(),
                      "surface_roughness_um": self.stock_roughness_box.value(),
                      "surface_defect_layer_um": self.stock_defect_box.value()},
            "stages": self._read_stages(),
            "processing_routes": self.processing_routes,
            # Старые ключи сохраняются для совместимости с уже созданными JSON.
            "surfaces": surfaces,
            "links": links,
            "longitudinal_surfaces": longitudinal_surfaces,
            "longitudinal_links": longitudinal_links,
        }
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        self.data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.processing_save_status.setText(
            f"Данные сохранены в файл:\n{self.data_path}"
        )
        for editor in self.chain_editors.values():
            editor["status"].setText(f"Исходные данные сохранены: {self.data_path.name}")

    def _normalized_detected_surface(self, chain_key, detected, number):
        surface = dict(detected)
        face_index = surface.get("face_index")
        source_key = (
            f"{chain_key}:face:{face_index}"
            if face_index is not None else f"{chain_key}:detected:{number}"
        )
        if chain_key == "diametral":
            diameter = float(surface.get("diameter", 0.0))
            nominal = float(surface.get("nominal_mm", round(diameter)))
            surface_type = surface.get("type", "shaft")
            description = surface.get("description") or (
                f"Авто: {'отверстие' if surface_type == 'hole' else 'вал'}, "
                f"Ø{diameter:.4f} мм; осевая длина {float(surface.get('length', 0)):.4f} мм"
            )
            category_label = "diametral"
        else:
            nominal = float(surface.get("nominal_mm", surface.get("station_mm", 0.0)))
            surface_type = "plane"
            description = surface.get("description", "Продольная плоская поверхность")
            category_label = "longitudinal"
        surface["key"] = source_key
        surface["category"] = category_label
        surface["nominal_mm"] = nominal
        surface["surface_type"] = surface_type
        surface["linear_direction"] = int(surface.get("linear_direction", 1))
        surface["description"] = str(description)
        surface["process_meta"] = {
            "key": source_key,
            "category": category_label,
            "face_index": face_index,
            "surface_type": surface_type,
            "nominal_mm": nominal,
            "diameter_mm": float(surface.get("diameter", 0.0)),
            "length_mm": float(surface.get("length", 0.0)),
            "station_mm": surface.get("station_mm"),
            "linear_direction": surface["linear_direction"],
        }
        return surface

    def _merge_detected_surfaces(self, chain_key, saved_surfaces, detected_surfaces,
                                 add_missing=True):
        table = self.chain_editors[chain_key]["surface_table"]
        for item in saved_surfaces:
            self._add_surface(chain_key, item)

        generated = {}
        used_ids = set(self._surface_ids(chain_key))
        prefix = "D" if chain_key == "diametral" else "L"
        for number, detected in enumerate(detected_surfaces, start=1):
            surface = self._normalized_detected_surface(chain_key, detected, number)
            source_key = surface["key"]
            match_row = None
            for row in range(table.rowCount()):
                id_item = table.item(row, 0)
                description_item = table.item(row, 1)
                metadata = id_item.data(QtCore.Qt.ItemDataRole.UserRole) or {}
                description = description_item.text().strip() if description_item else ""
                same_source = metadata.get("key") == source_key
                same_face = (
                    surface.get("face_index") is not None
                    and metadata.get("face_index") == surface.get("face_index")
                )
                same_description = description == surface["description"]
                if same_source or same_face or same_description:
                    match_row = row
                    break

            if match_row is None and add_missing:
                candidate = str(detected.get("id", "")).strip()
                if chain_key == "diametral" or not candidate:
                    candidate = f"{prefix}{number}"
                if candidate in used_ids:
                    candidate = f"{prefix}CAD{number}"
                suffix = 2
                initial_candidate = candidate
                while candidate in used_ids:
                    candidate = f"{initial_candidate}_{suffix}"
                    suffix += 1
                surface["id"] = candidate
                self._add_surface(chain_key, {
                    "id": candidate,
                    "description": surface["description"],
                    "process_meta": surface["process_meta"],
                })
                used_ids.add(candidate)
                match_row = table.rowCount() - 1
            elif match_row is not None:
                id_item = table.item(match_row, 0)
                id_item.setData(QtCore.Qt.ItemDataRole.UserRole, surface["process_meta"])
                surface["description"] = (
                    table.item(match_row, 1).text().strip()
                    if table.item(match_row, 1) else surface["description"]
                )

            if match_row is not None:
                surface["chain_id"] = table.item(match_row, 0).text().strip()
            else:
                candidate = f"{prefix}{number}"
                if candidate in used_ids:
                    candidate = f"{prefix}CAD{number}"
                surface["chain_id"] = candidate
            generated[source_key] = surface
        self._detected_chain_surfaces.update(generated)

    def _load_data(self):
        data = {}
        if self.data_path.exists():
            try:
                data = json.loads(self.data_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                QtWidgets.QMessageBox.warning(
                    self, "Не удалось загрузить анализ",
                    "Файл исходных данных повреждён или имеет неверный формат. Будут загружены распознанные поверхности.",
                )
                data = {}
        try:
            stock = data.get("stock", {})
            self.shift_box.setValue(float(stock.get("surface_shift_um", 0)))
            self.curvature_box.setValue(float(stock.get("curvature_um_per_mm", 0)))
            self.length_box.setValue(float(stock.get("length_mm", 1)))
            self.stock_roughness_box.setValue(
                float(stock.get("surface_roughness_um", 150))
            )
            self.stock_defect_box.setValue(
                float(stock.get("surface_defect_layer_um", 150))
            )
            self.processing_routes = data.get("processing_routes", {})
            for stage in data.get("stages", []):
                self._add_stage(stage)

            self._merge_detected_surfaces(
                "diametral", data.get("surfaces", []),
                self.detected_diametral_surfaces, add_missing=True,
            )
            self._merge_detected_surfaces(
                "longitudinal", data.get("longitudinal_surfaces", []),
                self.detected_longitudinal_surfaces,
            )
            for link in data.get("links", []):
                self._add_link("diametral", link)
            for link in data.get("longitudinal_links", []):
                self._add_link("longitudinal", link)
            self._populate_processing_surface_table()
            self._sync_operation_surfaces()
            self._refresh_chain("diametral")
            self._refresh_chain("longitudinal")
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            QtWidgets.QMessageBox.warning(
                self, "Не удалось загрузить анализ", str(error)
            )
