# src/cadquery_analyzer.py
import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface
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

def extract_cylinders(step_path: str):
    """
    Загружает STEP-файл, находит все цилиндрические грани.
    Возвращает список словарей с ключами: radius, diameter, type.
    """
    part = cq.importers.importStep(step_path)
    if part is None:
        raise ValueError(f"Не удалось загрузить модель: {step_path}")

    all_faces = part.faces()
    cylinders = []

    for face in all_faces.vals():
        # Определяем тип поверхности через OCP
        surf_adaptor = BRepAdaptor_Surface(face.wrapped, True)
        if surf_adaptor.GetType() == GeomAbs_Cylinder:
            radius = surf_adaptor.Cylinder().Radius()
            cyl_type = get_cylinder_type(face)
            cylinders.append({
                "radius": radius,
                "diameter": radius * 2,
                "type": cyl_type
            })

    # Удаляем дубликаты (по радиусу и типу, но можно и по радиусу)
    unique = []
    seen = set()
    for c in cylinders:
        key = (round(c["radius"], 6), c["type"])
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique