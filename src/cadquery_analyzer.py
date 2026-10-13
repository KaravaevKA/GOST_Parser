# src/cadquery_analyzer.py
import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
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


def _unit_vector(x, y, z):
    length = (x * x + y * y + z * z) ** 0.5
    if length == 0:
        return None
    vector = (x / length, y / length, z / length)
    # Стандартизируем знак, чтобы сортировка была устойчивой к ориентации граней.
    for component in vector:
        if abs(component) > 1e-9:
            if component < 0:
                vector = tuple(-value for value in vector)
            break
    return vector


def _dot(a, b):
    return sum(left * right for left, right in zip(a, b))


def _longitudinal_axis(part, faces):
    """Выбирает доминирующую ось цилиндрических граней или ось габарита."""
    axis_groups = []
    for face in faces:
        adaptor = BRepAdaptor_Surface(face.wrapped, True)
        if adaptor.GetType() != GeomAbs_Cylinder:
            continue
        direction = adaptor.Cylinder().Axis().Direction()
        axis = _unit_vector(direction.X(), direction.Y(), direction.Z())
        if axis is None:
            continue

        group = next(
            (item for item in axis_groups if abs(_dot(axis, item["axis"])) >= 0.999),
            None,
        )
        if group is None:
            axis_groups.append({"axis": axis, "score": face.Area()})
        else:
            group["score"] += face.Area()

    if axis_groups:
        return max(axis_groups, key=lambda item: item["score"])["axis"]

    bounds = part.val().BoundingBox()
    extents = (
        (bounds.xlen, (1.0, 0.0, 0.0)),
        (bounds.ylen, (0.0, 1.0, 0.0)),
        (bounds.zlen, (0.0, 0.0, 1.0)),
    )
    return max(extents, key=lambda item: item[0])[1]


def extract_longitudinal_planes_from_part(part, angular_tolerance=1e-5):
    """Возвращает плоские торцы и уступы, перпендикулярные оси детали.

    Грани сортируются по положению вдоль главной оси и могут использоваться
    для первоначального заполнения таблицы поверхностей продольной цепи.
    """
    if part is None:
        raise ValueError("Не удалось прочитать STEP-модель.")

    faces = part.faces().vals()
    axis = _longitudinal_axis(part, faces)
    detected = []

    for face_index, face in enumerate(faces):
        adaptor = BRepAdaptor_Surface(face.wrapped, True)
        if adaptor.GetType() != GeomAbs_Plane:
            continue

        direction = adaptor.Plane().Axis().Direction()
        normal = _unit_vector(direction.X(), direction.Y(), direction.Z())
        if normal is None or abs(abs(_dot(normal, axis)) - 1.0) > angular_tolerance:
            continue

        center = face.Center()
        station = _dot((center.x, center.y, center.z), axis)
        detected.append({"face_index": face_index, "station_mm": station})

    detected.sort(key=lambda item: (item["station_mm"], item["face_index"]))
    return [
        {
            "id": str(number),
            "description": (
                f"Авто: плоская грань STEP №{item['face_index'] + 1}; "
                f"положение по оси детали {item['station_mm']:.3f} мм"
            ),
            "face_index": item["face_index"],
            "station_mm": item["station_mm"],
        }
        for number, item in enumerate(detected, start=1)
    ]
