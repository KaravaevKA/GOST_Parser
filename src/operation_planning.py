"""Маршруты обработки и рекомендуемые квалитеты для операций."""

from __future__ import annotations


# Рекомендации перенесены из таблицы, приложенной к проекту.
OPERATION_QUALITY_RANGES = {
    "Заготовка": (14, 17),
    "Черновое точение": (11, 13),
    "Черновое фрезерование": (11, 13),
    "Сверление": (11, 12),
    "Получистовое точение": (9, 10),
    "Получистовое фрезерование": (9, 10),
    "Чистовое точение": (7, 8),
    "Тонкое точение": (6, 7),
    "Черновое шлифование": (8, 9),
    "Чистовое шлифование": (5, 7),
    "Чистовое фрезерование": (7, 8),
    "Развертывание": (6,7)
}

MACHINING_OPERATIONS = tuple(
    name for name in OPERATION_QUALITY_RANGES if name != "Заготовка"
)
MAX_OPERATION_COUNT = 20

# Верхние границы диапазонов Rz и T из таблицы 7 пособия пользователя.
# Верхняя граница выбрана, чтобы не занижать требуемый съём при интервальных
# исходных данных. Ky используется только там, где он указан в таблице 6.
# Для отсутствующего в таблице Ky принимается 1.0: пространственное отклонение
# не уменьшается, пока пользователь не задаст подтверждённое значение.
OPERATION_PROCESS_DATA = {
    "Черновое точение": {"roughness_um": 150, "defect_layer_um": 100, "ky": 0.06},
    "Сверление": {"roughness_um": 150, "defect_layer_um": 100, "ky": 1.0},
    "Получистовое точение": {"roughness_um": 50, "defect_layer_um": 60, "ky": 0.05},
    "Чистовое точение": {"roughness_um": 25, "defect_layer_um": 30, "ky": 0.04},
    "Тонкое точение": {"roughness_um": 10, "defect_layer_um": 20, "ky": 1.0},
    "Черновое шлифование": {"roughness_um": 40, "defect_layer_um": 50, "ky": 1.0},
    "Чистовое шлифование": {"roughness_um": 10, "defect_layer_um": 25, "ky": 1.0},
    "Черновое фрезерование": {"roughness_um": 150, "defect_layer_um": 100, "ky": 1.0},
    "Получистовое фрезерование": {"roughness_um": 150, "defect_layer_um": 100, "ky": 1.0},
    "Чистовое фрезерование": {"roughness_um": 50, "defect_layer_um": 60, "ky": 1.0},
}


def quality_options(operation: str) -> list[int]:
    """Вернуть целые IT из рекомендованного для операции диапазона."""
    try:
        minimum, maximum = OPERATION_QUALITY_RANGES[operation]
    except KeyError as error:
        raise ValueError(f"Неизвестная операция: {operation}") from error
    return list(range(minimum, maximum + 1))


def resize_operation_sequence(operations: list[dict], count: int) -> list[dict]:
    """Сохранить существующие этапы и создать недостающие до заданного числа."""
    if isinstance(count, bool) or not isinstance(count, int):
        raise ValueError("Число операций должно быть целым.")
    if not 0 <= count <= MAX_OPERATION_COUNT:
        raise ValueError(f"Число операций должно быть от 0 до {MAX_OPERATION_COUNT}.")

    result = [dict(item) for item in operations[:count]]
    result.extend(
        {"operation": None, "grade": None}
        for _ in range(count - len(result))
    )
    for number, stage in enumerate(result, start=1):
        operation = stage.get("operation")
        if operation not in MACHINING_OPERATIONS:
            stage["operation"] = None
        grade = stage.get("grade")
        if grade is not None and (
            stage["operation"] is None
            or grade not in quality_options(stage["operation"])
        ):
            stage["grade"] = None
        stage["number"] = number
    return result


def build_process_surface_sequence(surface: dict, route: dict) -> list[dict]:
    """Собрать поверхности заготовки и после каждого перехода.

    Последняя операция заканчивается на распознанной поверхности детали.
    Предшествующие этапы — новые поверхности, которые будут использоваться
    при последующей реализации расчёта межпереходных размеров и припусков.
    """
    source_id = str(surface.get("chain_id", surface.get("id", "S")))
    source_key = str(surface.get("key", source_id))
    operations = resize_operation_sequence(
        list(route.get("operations", [])), int(route.get("operation_count", 0))
    )
    if not operations:
        return [{
            "id": source_id,
            "source_key": source_key,
            "stage": 0,
            "kind": "finished",
            "operation": "Целевая поверхность модели",
            "grade": surface.get("grade"),
            "is_detected_surface": True,
            "description": str(surface.get("description", source_id)),
        }]
    sequence = [{
        "id": f"{source_id}-З",
        "source_key": source_key,
        "stage": 0,
        "kind": "stock",
        "operation": "Заготовка",
        "grade": route.get("stock_grade"),
        "is_detected_surface": False,
        "description": f"Заготовка для поверхности {source_id}",
    }]
    for index, operation in enumerate(operations, start=1):
        is_final = index == len(operations)
        stage_id = source_id if is_final else f"{source_id}.{index}"
        sequence.append({
            "id": stage_id,
            "source_key": source_key,
            "stage": index,
            "kind": "finished" if is_final else "intermediate",
            "operation": operation["operation"],
            "grade": operation.get("grade"),
            "is_detected_surface": is_final,
            "description": (
                f"Целевая поверхность {source_id} после {operation['operation']}"
                if is_final else f"Поверхность {stage_id} после {operation['operation']}"
            ),
        })
    return sequence


def build_operation_surfaces(surface: dict, route: dict) -> list[dict]:
    """Создать по одной записи промежуточной поверхности на каждую операцию.

    Найденная в CAD поверхность остаётся отдельной целевой поверхностью. Поэтому
    число возвращаемых промежуточных поверхностей равно числу операций маршрута.
    Их номиналы здесь не задаются: они будут вычислены при расчёте припусков.
    """
    source_id = str(surface.get("chain_id", surface.get("id", "S")))
    source_key = str(surface.get("key", source_id))
    category = surface.get("category")
    id_prefix = source_id
    if category == "longitudinal" and not id_prefix.upper().startswith("L"):
        id_prefix = f"L{id_prefix}"
    operations = resize_operation_sequence(
        list(route.get("operations", [])), int(route.get("operation_count", 0))
    )

    generated = []
    calculation = route.get("calculation", {})
    calculated_steps = calculation.get("steps", []) if calculation.get("complete") else []
    steps_by_number = {
        int(step.get("number", index)): step
        for index, step in enumerate(calculated_steps, start=1)
    }
    for number, stage in enumerate(operations, start=1):
        step_data = steps_by_number.get(number)
        if number == 1:
            operation = "Заготовка"
            grade = route.get("stock_grade")
            description = f"Авто: Заготовка перед оп. 1"
        else:
            previous_stage = operations[number - 2]
            operation = previous_stage.get("operation") or "операция не выбрана"
            grade = previous_stage.get("grade")
            description = f"Авто: после оп. {number - 1} — {operation}"
        grade_label = f", IT{grade}" if grade is not None else ""
        if step_data:
            nominal = step_data["nominal_before_mm"]
            value_label = (
                f"Ø{nominal:.4f} мм" if category == "diametral"
                else f"A={nominal:.4f} мм"
            )
            description += f"; {value_label}"
        description += grade_label
        generated.append({
            "id": f"{id_prefix}-T{number}",
            "description": description,
            "process_meta": {
                "route_generated": True,
                "parent_source_key": source_key,
                "operation_number": number,
                "category": category,
                "operation": operation,
                "grade": grade,
                "nominal_mm": step_data.get("nominal_before_mm") if step_data else None,
                "tolerance_after_mm": (
                    step_data.get("tolerance_before_um") / 1000.0
                    if step_data and step_data.get("tolerance_before_um") is not None
                    else None
                ),
            },
        })
    return generated
