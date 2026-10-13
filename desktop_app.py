"""Оконная программа для просмотра цилиндрических поверхностей и выбора IT."""

import hashlib
import json
from pathlib import Path
import sys

import cadquery as cq
from PySide6 import QtCore, QtWidgets
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData, vtkTriangle
from vtkmodules.vtkRenderingCore import (
    vtkActor,
    vtkCellPicker,
    vtkPolyDataMapper,
    vtkRenderer,
)
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera

from src.cadquery_analyzer import (
    extract_cylinders_from_part,
    extract_longitudinal_planes_from_part,
)
from src.tolerance_logic import grade_options, suggest_nominal
from src.analysis_dialog import TechnologicalAnalysisWindow


PROJECT_DIR = Path(__file__).resolve().parent
TOLERANCE_FILE = PROJECT_DIR / "data" / "gost_h_h_tolerances.json"
DEFAULT_MODEL = PROJECT_DIR / "data" / "model1.step"
ASSIGNMENTS_DIR = PROJECT_DIR / "data" / "assignments"

COLOR_UNSELECTED = (0.60, 0.68, 0.74)
COLOR_OTHER_FACE = (0.82, 0.84, 0.87)
COLOR_SELECTED = (1.0, 0.78, 0.08)
GRADE_PALETTE = [
    (0.26, 0.62, 0.86), (0.92, 0.48, 0.27), (0.35, 0.70, 0.48),
    (0.66, 0.48, 0.78), (0.91, 0.68, 0.26), (0.28, 0.72, 0.70),
    (0.86, 0.40, 0.54), (0.54, 0.65, 0.32),
]


def make_face_actor(face, color):
    """Триангулирует CAD-грань и создаёт для неё отдельный VTK-объект."""
    vertices, triangles = face.tessellate(0.1, 0.1)
    points = vtkPoints()
    for vertex in vertices:
        points.InsertNextPoint(*vertex.toTuple())

    polygons = vtkCellArray()
    for indices in triangles:
        triangle = vtkTriangle()
        for local_index, point_index in enumerate(indices):
            triangle.GetPointIds().SetId(local_index, point_index)
        polygons.InsertNextCell(triangle)

    polydata = vtkPolyData()
    polydata.SetPoints(points)
    polydata.SetPolys(polygons)
    mapper = vtkPolyDataMapper()
    mapper.SetInputData(polydata)

    actor = vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(*color)
    actor.GetProperty().SetInterpolationToPhong()
    return actor


class ModelViewWindow(QtWidgets.QMainWindow):
    """Отдельное окно VTK с подсветкой и выбором граней мышью."""

    surface_picked = QtCore.Signal(int)
    open_model_requested = QtCore.Signal()
    analysis_requested = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("3D-визуализация детали")
        self.resize(850, 700)
        self.setMinimumSize(600, 500)

        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)

        toolbar = QtWidgets.QHBoxLayout()

        open_button = QtWidgets.QPushButton("Открыть STEP…")
        open_button.clicked.connect(
            lambda _checked=False: self.open_model_requested.emit()
        )
        toolbar.addWidget(open_button)

        self.analysis_button = QtWidgets.QPushButton("Расчёт припусков и цепей…")
        self.analysis_button.setEnabled(False)
        self.analysis_button.clicked.connect(
            lambda _checked=False: self.analysis_requested.emit()
        )
        toolbar.addWidget(self.analysis_button)

        layout.addLayout(toolbar)

        self.vtk_widget = QVTKRenderWindowInteractor(central)
        layout.addWidget(self.vtk_widget, stretch=1)
        layout.addWidget(QtWidgets.QLabel(
            "Жёлтый — выбрана сейчас · серо-голубой — без квалитета · цветной — квалитет назначен"
        ))
        self.setCentralWidget(central)

        self.renderer = vtkRenderer()
        self.renderer.SetBackground(0.96, 0.97, 0.98)
        self.render_window = self.vtk_widget.GetRenderWindow()
        self.render_window.AddRenderer(self.renderer)
        self.vtk_widget.Initialize()

        self.interactor = self.vtk_widget.GetRenderWindow().GetInteractor()
        self.interactor.SetInteractorStyle(vtkInteractorStyleTrackballCamera())
        self.picker = vtkCellPicker()
        self.picker.SetTolerance(0.0005)
        self.interactor.AddObserver("LeftButtonReleaseEvent", self._on_model_click)

        self.actors = {}
        self.actor_to_face_index = {}
        self.surface_by_face = {}

    def set_model(self, faces, surfaces):
        for actor in self.actors.values():
            self.renderer.RemoveActor(actor)
        self.actors.clear()
        self.actor_to_face_index.clear()
        self.surface_by_face = {item["face_index"]: item for item in surfaces}
        self.analysis_button.setEnabled(True)

        for face_index, face in enumerate(faces):
            color = COLOR_UNSELECTED if face_index in self.surface_by_face else COLOR_OTHER_FACE
            actor = make_face_actor(face, color)
            self.renderer.AddActor(actor)
            self.actors[face_index] = actor
            self.actor_to_face_index[actor] = face_index

        self.renderer.ResetCamera()
        self.render_window.Render()

    def set_surface_colors(self, colors_by_face):
        for face_index, color in colors_by_face.items():
            actor = self.actors.get(face_index)
            if actor is not None:
                actor.GetProperty().SetColor(*color)
        self.render_window.Render()

    def _on_model_click(self, _interactor, _event):
        x, y = self.interactor.GetEventPosition()
        self.picker.Pick(x, y, 0, self.renderer)
        face_index = self.actor_to_face_index.get(self.picker.GetActor())
        if face_index in self.surface_by_face:
            self.surface_picked.emit(face_index)

    def closeEvent(self, event):
        event.accept()


class SurfaceApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Выбор квалитета цилиндрических поверхностей")
        self.resize(820, 620)
        self.setMinimumSize(700, 500)

        with TOLERANCE_FILE.open("r", encoding="utf-8") as file:
            self.tolerance_data = json.load(file)

        self.model_path = None
        self.model_hash = None
        self.surfaces = []
        self.assignments = {}
        self.faces = []
        self.longitudinal_planes = []
        self.surface_by_face = {}
        self.current_face_index = None
        self.analysis_window = None

        self.viewer = ModelViewWindow()
        self.viewer.surface_picked.connect(self.select_surface_from_model)
        self.viewer.open_model_requested.connect(self.choose_model)
        self.viewer.analysis_requested.connect(self.show_analysis_window)
        self._build_interface()
        self.open_model(DEFAULT_MODEL)

    def _build_interface(self):
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)

        toolbar = QtWidgets.QHBoxLayout()
        open_button = QtWidgets.QPushButton("Открыть STEP…")
        open_button.clicked.connect(self.choose_model)
        toolbar.addWidget(open_button)

        viewer_button = QtWidgets.QPushButton("Показать 3D-модель")
        viewer_button.clicked.connect(self.show_model_window)
        toolbar.addWidget(viewer_button)

        analysis_button = QtWidgets.QPushButton("Расчёт припусков и цепи…")
        analysis_button.clicked.connect(self.show_analysis_window)
        toolbar.addWidget(analysis_button)

        save_button = QtWidgets.QPushButton("Сохранить назначения")
        save_button.clicked.connect(self.save_assignments)
        toolbar.addWidget(save_button)

        self.model_label = QtWidgets.QLabel("Модель не загружена")
        toolbar.addWidget(self.model_label, stretch=1)
        layout.addLayout(toolbar)

        layout.addWidget(QtWidgets.QLabel("Цилиндрические поверхности"))
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Тип", "Диаметр, мм", "Длина, мм", "Квалитет"])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.currentCellChanged.connect(self.on_table_selection)
        layout.addWidget(self.table, stretch=1)

        assignment_box = QtWidgets.QGroupBox("Назначение выбранной поверхности")
        assignment_layout = QtWidgets.QVBoxLayout(assignment_box)
        self.surface_details = QtWidgets.QLabel("Выберите поверхность в таблице или в 3D-модели.")
        self.surface_details.setWordWrap(True)
        assignment_layout.addWidget(self.surface_details)

        controls = QtWidgets.QHBoxLayout()
        self.grade_combo = QtWidgets.QComboBox()
        self.grade_combo.setEnabled(False)
        controls.addWidget(self.grade_combo, stretch=1)
        self.apply_button = QtWidgets.QPushButton("Применить квалитет")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply_grade)
        controls.addWidget(self.apply_button)
        assignment_layout.addLayout(controls)
        layout.addWidget(assignment_box)

        note = QtWidgets.QLabel(
            "Пометка «диаметр в допуске» означает, что размер модели попадает в это поле допуска. "
            "Выбор квалитета остаётся за вами."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.setCentralWidget(central)

    def choose_model(self):
        selected, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Выберите STEP-модель",
            str(PROJECT_DIR / "data"),
            "STEP-модели (*.step *.stp);;Все файлы (*.*)",
        )
        if selected:
            self.open_model(Path(selected))

    def open_model(self, model_path):
        try:
            model_path = Path(model_path).resolve()
            part = cq.importers.importStep(str(model_path))
            new_surfaces = extract_cylinders_from_part(part)
            new_longitudinal_planes = extract_longitudinal_planes_from_part(part)
            faces = part.faces().vals()

            digest = hashlib.sha256()
            with model_path.open("rb") as file:
                for block in iter(lambda: file.read(1024 * 1024), b""):
                    digest.update(block)
            model_hash = digest.hexdigest()

            if not new_surfaces:
                QtWidgets.QMessageBox.warning(
                    self, "Цилиндры не найдены",
                    "В выбранной STEP-модели не найдено цилиндрических поверхностей.",
                )
                return

            self.model_path = model_path
            self.model_hash = model_hash
            self.surfaces = new_surfaces
            self.longitudinal_planes = new_longitudinal_planes
            self.surface_by_face = {item["face_index"]: item for item in self.surfaces}
            self.faces = faces
            self.assignments = self._read_assignments()
            self.current_face_index = None

            self.viewer.set_model(self.faces, self.surfaces)
            self._refresh_table()
            self.model_label.setText(model_path.name)
            self.show_model_window()
            self._update_view_colors()
        except Exception as error:
            QtWidgets.QMessageBox.critical(self, "Не удалось открыть модель", str(error))

    def _assignment_file(self):
        return ASSIGNMENTS_DIR / f"{self.model_path.stem}_{self.model_hash[:12]}.json"

    def _read_assignments(self):
        path = self._assignment_file()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("model_sha256") != self.model_hash:
                return {}
            return {int(key): value for key, value in data.get("assignments", {}).items()}
        except (OSError, ValueError, TypeError):
            return {}

    def save_assignments(self):
        if not self.model_path:
            return
        path = self._assignment_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model_file": self.model_path.name,
            "model_sha256": self.model_hash,
            "assignments": {str(key): value for key, value in self.assignments.items()},
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.setWindowTitle("Выбор квалитета цилиндрических поверхностей · сохранено")

    def _refresh_table(self, selected_face=None):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.surfaces))
        face_to_row = {}
        for row, surface in enumerate(self.surfaces):
            face_index = surface["face_index"]
            face_to_row[face_index] = row
            grade = self.assignments.get(face_index, {}).get("grade")
            values = (
                "Отверстие" if surface["type"] == "hole" else "Вал",
                f"{surface['diameter']:.4f}",
                f"{surface['length']:.4f}",
                f"IT{grade}" if grade is not None else "Не выбран",
            )
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, item)

        if selected_face in face_to_row:
            self.table.selectRow(face_to_row[selected_face])
        self.table.blockSignals(False)

    def on_table_selection(self, row, _column, _previous_row, _previous_column):
        if row < 0 or row >= len(self.surfaces):
            return
        self._select_surface(self.surfaces[row]["face_index"])

    def select_surface_from_model(self, face_index):
        self._select_surface(face_index, select_table_row=True)

    def _select_surface(self, face_index, select_table_row=False):
        surface = self.surface_by_face.get(face_index)
        if surface is None:
            return
        self.current_face_index = face_index

        if select_table_row:
            for row, item in enumerate(self.surfaces):
                if item["face_index"] == face_index:
                    self.table.blockSignals(True)
                    self.table.selectRow(row)
                    self.table.blockSignals(False)
                    break

        nominal = suggest_nominal(surface["diameter"])
        options = grade_options(surface["diameter"], nominal, self.tolerance_data, surface["type"])
        self.grade_combo.clear()
        self.grade_combo.addItem("— не назначать —", None)
        for option in options:
            status = "диаметр в допуске" if option["fits_model_diameter"] else "диаметр вне допуска"
            label = (
                f"IT{option['grade']} — {status} "
                f"[{option['lower_limit_mm']:.4f}; {option['upper_limit_mm']:.4f}] мм"
            )
            self.grade_combo.addItem(label, option["grade"])

        existing_grade = self.assignments.get(face_index, {}).get("grade")
        existing_index = self.grade_combo.findData(existing_grade)
        self.grade_combo.setCurrentIndex(max(existing_index, 0))
        self.grade_combo.setEnabled(True)
        self.apply_button.setEnabled(True)

        surface_type = "отверстие" if surface["type"] == "hole" else "вал"
        self.surface_details.setText(
            f"Поверхность {face_index + 1}: {surface_type}; "
            f"диаметр {surface['diameter']:.4f} мм; длина {surface['length']:.4f} мм; "
            f"предполагаемый номинал {nominal} мм."
        )
        self._update_view_colors()

    def apply_grade(self):
        if self.current_face_index is None:
            return
        grade = self.grade_combo.currentData()
        if grade is None:
            self.assignments.pop(self.current_face_index, None)
        else:
            self.assignments[self.current_face_index] = {"grade": int(grade)}
        selected_face = self.current_face_index
        self._refresh_table(selected_face)
        self._update_view_colors()
        self.save_assignments()

    def _update_view_colors(self):
        grade_ids = sorted({item["grade"] for item in self.assignments.values()})
        grade_colors = {
            grade: GRADE_PALETTE[index % len(GRADE_PALETTE)]
            for index, grade in enumerate(grade_ids)
        }
        colors = {}
        for face_index in self.surface_by_face:
            if face_index == self.current_face_index:
                colors[face_index] = COLOR_SELECTED
            else:
                assignment = self.assignments.get(face_index)
                colors[face_index] = (
                    grade_colors[assignment["grade"]] if assignment else COLOR_UNSELECTED
                )
        self.viewer.set_surface_colors(colors)

    def show_model_window(self):
        self.viewer.show()
        self.viewer.raise_()
        self.viewer.activateWindow()

    def show_analysis_window(self):
        if not self.model_hash:
            QtWidgets.QMessageBox.information(self, "Нет модели", "Сначала откройте STEP-модель детали.")
            return
        if self.analysis_window is None or self.analysis_window.model_hash != self.model_hash:
            self.analysis_window = TechnologicalAnalysisWindow(
                self.model_hash,
                self.model_path.name,
                self,
                detected_longitudinal_surfaces=self.longitudinal_planes,
                detected_diametral_surfaces=self.surfaces,
            )
        self.analysis_window.show()
        self.analysis_window.raise_()
        self.analysis_window.activateWindow()

    def closeEvent(self, event):
        self.save_assignments()
        self.viewer.close()
        event.accept()


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = SurfaceApp()
    window.viewer.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
