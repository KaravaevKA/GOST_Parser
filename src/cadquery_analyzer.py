# src/cadquery_analyzer.py
import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Cylinder

def extract_cylinders(step_path: str):
    """
    Загружает STEP-файл, находит все цилиндрические грани.
    Возвращает список словарей с ключами: radius, diameter.
    """
    # Загружаем модель
    part = cq.importers.importStep(step_path)
    if part is None:
        raise ValueError(f"Не удалось загрузить модель: {step_path}")

    # Получаем все грани
    all_faces = part.faces()
    cylinders = []

    for face in all_faces.vals():
        # Создаём адаптер поверхности для OCP-представления грани
        surf_adaptor = BRepAdaptor_Surface(face.wrapped, True)
        if surf_adaptor.GetType() == GeomAbs_Cylinder:
            radius = surf_adaptor.Cylinder().Radius()
            cylinders.append({
                "radius": radius,
                "diameter": radius * 2,
                "type": "cylinder"
            })

    # Удаляем дубликаты (одна и та же цилиндрическая поверхность может дать несколько граней)
    unique = []
    seen = set()
    for c in cylinders:
        r = round(c["radius"], 6)
        if r not in seen:
            seen.add(r)
            unique.append(c)

    return unique