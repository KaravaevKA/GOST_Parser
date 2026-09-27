# src/cadquery_analyzer.py
import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_Cylinder
from OCP.TopAbs import TopAbs_REVERSED

def get_cylinder_type(face):
    """
    Определяет тип цилиндрической грани по ориентации.
    Возвращает 'hole' для внутренней грани (отверстие), 'shaft' для внешней (вал).
    """
    # Проверяем ориентацию грани в топологическом представлении
    if face.wrapped.Orientation() == TopAbs_REVERSED:
        return 'hole'
    else:
        return 'shaft'


def get_cylinder_length(face):
    """Возвращает осевую длину цилиндрической грани в миллиметрах."""
    u_min, u_max, v_min, v_max = BRepTools.UVBounds_s(face.wrapped)
    # Для цилиндра параметр v отсчитывается вдоль его оси и измеряется в мм.
    return v_max - v_min


def extract_cylinders(step_path: str):
    """
    Загружает STEP-файл, находит все цилиндрические грани.
    Возвращает список словарей с ключами: radius, diameter, length, type.
    """
    part = cq.importers.importStep(step_path)
    if part is None:
        raise ValueError(f"Не удалось загрузить модель: {step_path}")

    return extract_cylinders_from_part(part)


def extract_cylinders_from_part(part):
    """Извлекает цилиндрические грани из уже загруженной CadQuery-детали."""
    all_faces = part.faces().vals()
    cylinders = []

    for face_index, face in enumerate(all_faces):
        # Определяем тип поверхности через OCP
        surf_adaptor = BRepAdaptor_Surface(face.wrapped, True)
        if surf_adaptor.GetType() == GeomAbs_Cylinder:
            radius = surf_adaptor.Cylinder().Radius()
            length = get_cylinder_length(face)
            cyl_type = get_cylinder_type(face)
            cylinders.append({
                # Номер грани нужен, чтобы связать запись таблицы с моделью.
                "face_index": face_index,
                "radius": radius,
                "diameter": radius * 2,
                "length": length,
                "type": cyl_type
            })

    # Каждая грань остаётся отдельной: у одинаковых поверхностей
    # могут быть разные назначенные пользователем квалитеты.
    return cylinders
