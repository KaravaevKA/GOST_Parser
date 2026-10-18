"""Расчёты технологических припусков и данные для графа размерной цепи.

Все величины геометрических ошибок и припусков задаются в микрометрах;
размеры заготовки и детали — в миллиметрах.
"""

from __future__ import annotations

from math import hypot, isfinite, sqrt


def default_drill_diameters_mm() -> list[float]:
    """Вернуть редактируемый ряд доступных номиналов сверл, мм.

    Это стартовый каталог для подбора, а не утверждение о наличии инструмента
    на конкретном предприятии. Диаметры можно заменить фактическим каталогом.
    """
    small_and_medium = [step / 10 for step in range(5, 201)]  # 0.5…20.0, шаг 0.1
    larger = [step / 4 for step in range(81, 127)]           # 20.25…31.5, шаг 0.25
    large = [float(step) for step in range(32, 81)]           # 32…80, шаг 1
    return sorted(set(small_and_medium + larger + large))


def _pick_drill_diameter(required_mm: float, candidates: list[float], *,
                         must_not_exceed: bool) -> float:
    values = sorted({float(value) for value in candidates if float(value) > 0})
    if not values:
        raise ValueError("В каталоге нет положительных диаметров сверл.")
    if must_not_exceed:
        admissible = [value for value in values if value <= required_mm + 1e-9]
        if not admissible:
            raise ValueError(
                f"В каталоге нет сверла не больше требуемого диаметра "
                f"{required_mm:.4f} мм."
            )
        return admissible[-1]
    return min(values, key=lambda value: (abs(value - required_mm), value))


def _nonnegative(name: str, value: float) -> float:
    value = float(value)
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name}: значение должно быть конечным и неотрицательным")
    return value


def blank_spatial_deviation(surface_shift_um: float, curvature_um_per_mm: float,
                            length_mm: float) -> float:
    """Пространственное отклонение заготовки ρ=√(ρсм²+ρкор²), в мкм."""
    shift = _nonnegative("Смещение поверхности", surface_shift_um)
    curvature = _nonnegative("Удельная кривизна", curvature_um_per_mm)
    length = _nonnegative("Длина поверхности", length_mm)
    return hypot(shift, curvature * length)


def setup_error(basing_error_um: float, clamping_error_um: float,
                reset: bool = True) -> float:
    """Погрешность установки ε=√(εб²+εз²); без переустановки равна нулю."""
    if not reset:
        return 0.0
    return hypot(_nonnegative("Погрешность базирования", basing_error_um),
                 _nonnegative("Погрешность закрепления", clamping_error_um))


def minimum_allowance(*, roughness_um: float, defect_layer_um: float,
                      spatial_deviation_um: float, setup_error_um: float,
                      kind: str = "rotational", finishing_only: bool = False) -> float:
    """Минимальный припуск по формулам пособия, результат в мкм.

    kind='rotational' — диаметральный припуск для наружных/внутренних
    поверхностей вращения: 2(Rz+T+√(ρ²+ε²)).
    kind='linear' — линейный припуск: Rz+T+ρ+ε.
    finishing_only=True — полирование/суперфиниш: 2Rz.
    """
    rz = _nonnegative("Rz", roughness_um)
    if finishing_only:
        return 2.0 * rz
    defect = _nonnegative("Глубина дефектного слоя", defect_layer_um)
    rho = _nonnegative("Пространственное отклонение", spatial_deviation_um)
    epsilon = _nonnegative("Погрешность установки", setup_error_um)
    if kind == "rotational":
        return 2.0 * (rz + defect + hypot(rho, epsilon))
    if kind == "linear":
        return rz + defect + rho + epsilon
    raise ValueError("Тип припуска должен быть rotational или linear")


def calculate_allowance_stages(stages: list[dict], *, initial_spatial_deviation_um: float,
                               operation_reset_errors: bool = True) -> list[dict]:
    """Рассчитать припуск каждого перехода и остаточное ρ для следующего.

    Строка перехода требует Rz, T, Ky, installation error components and kind;
    поля `basing_error_um` и `clamping_error_um` могут быть опущены (тогда 0).
    Для строк без переустановки задайте `reinstalled=False`.
    """
    rho = _nonnegative("Начальное пространственное отклонение", initial_spatial_deviation_um)
    results = []
    for number, stage in enumerate(stages, start=1):
        ky = _nonnegative("Коэффициент уточнения Ky", stage["ky"])
        if ky > 1:
            raise ValueError(f"Переход {number}: коэффициент Ky должен быть не больше 1")
        reinstalled = stage.get("reinstalled", operation_reset_errors)
        epsilon = setup_error(stage.get("basing_error_um", 0),
                              stage.get("clamping_error_um", 0), reinstalled)
        kind = stage.get("kind", "rotational")
        zmin = minimum_allowance(
            roughness_um=stage["roughness_um"],
            defect_layer_um=stage.get("defect_layer_um", 0),
            spatial_deviation_um=rho,
            setup_error_um=epsilon,
            kind=kind,
            finishing_only=stage.get("finishing_only", False),
        )
        residual_rho = ky * rho
        results.append({
            "stage": stage.get("name", f"Переход {number}"),
            "kind": kind,
            "spatial_deviation_um": rho,
            "setup_error_um": epsilon,
            "minimum_allowance_um": zmin,
            "minimum_allowance_mm": zmin / 1000.0,
            "residual_spatial_deviation_um": residual_rho,
            "positive_allowance": zmin > 0,
        })
        rho = residual_rho
    return results


def tolerance_width_um(nominal_mm: float, grade: int, surface_type: str,
                       tolerance_data: list[dict]) -> float:
    """Вернуть ширину допуска IT из локальной таблицы ГОСТ, в мкм."""
    nominal = _nonnegative("Номинальный размер", nominal_mm)
    grade = int(grade)
    symbol = "H" if surface_type == "hole" else "h"
    for item in tolerance_data:
        if (item.get("deviation_symbol") == symbol
                and int(item.get("grade", -1)) == grade
                and float(item.get("nominal_from", 0)) <= nominal
                and nominal < float(item.get("nominal_to", 0))):
            return float(item["upper_deviation_mkm"]) - float(item["lower_deviation_mkm"])
    raise ValueError(
        f"В таблице ГОСТ нет IT{grade} для размера {nominal:g} мм ({symbol})."
    )


def calculate_operation_route(*, operations: list[dict], final_nominal_mm: float,
                              category: str, surface_type: str,
                              stock_grade: int, stock_roughness_um: float,
                              stock_defect_layer_um: float,
                              initial_spatial_deviation_um: float,
                              tolerance_data: list[dict],
                              linear_direction: int = 1,
                              drill_diameters_mm: list[float] | None = None) -> dict:
    """Рассчитать припуски и промежуточные номиналы маршрута обработки.

    Интервальные значения Rz/T берутся по верхней границе таблицы обработки.
    Номиналы рассчитываются обратным ходом от готового размера по формуле
    Zc = Zmin + (Tдо + Tпосле)/2 из методического материала.
    """
    if not operations:
        return {"complete": False, "message": "Для расчёта задайте операции."}
    if category not in {"diametral", "longitudinal"}:
        raise ValueError("Неизвестный тип размерной цепи.")
    sign = ( -1 if surface_type == "hole" else 1
             ) if category == "diametral" else (1 if linear_direction >= 0 else -1)
    kind = "rotational" if category == "diametral" else "linear"
    starts_with_drilling_hole = (
        category == "diametral"
        and surface_type == "hole"
        and operations[0].get("operation") == "Сверление"
    )

    rho = _nonnegative("Начальное пространственное отклонение", initial_spatial_deviation_um)
    previous_rz = _nonnegative("Rz заготовки", stock_roughness_um)
    previous_defect = _nonnegative("Дефектный слой заготовки", stock_defect_layer_um)
    previous_grade = int(stock_grade)
    result_steps = []

    for number, operation in enumerate(operations, start=1):
        name = operation.get("operation")
        grade = operation.get("grade")
        parameters = operation.get("process_data")
        if not name or grade is None or parameters is None:
            return {
                "complete": False,
                "message": f"Для операции {number} выберите операцию и квалитет.",
            }
        grade = int(grade)
        epsilon = _nonnegative(
            f"Погрешность установки операции {number}",
            operation.get("setup_error_um", 0),
        )
        # Сверление первой операции в сплошной заготовке создаёт отверстие.
        # Для него нет предшествующей цилиндрической поверхности, поэтому
        # нельзя трактовать Ø0 как размер, от которого снимается Zmin.
        creates_hole_from_solid = starts_with_drilling_hole and number == 1
        zmin = None if creates_hole_from_solid else minimum_allowance(
            roughness_um=previous_rz,
            defect_layer_um=previous_defect,
            spatial_deviation_um=rho,
            setup_error_um=epsilon,
            kind=kind,
        )
        ky = _nonnegative(f"Коэффициент Ky операции {number}", parameters["ky"])
        if ky > 1:
            raise ValueError(f"Операция {number}: Ky должен быть не больше 1.")
        result_steps.append({
            "number": number,
            "operation": name,
            "grade": grade,
            "roughness_before_um": previous_rz,
            "defect_layer_before_um": previous_defect,
            "roughness_um": float(parameters["roughness_um"]),
            "defect_layer_um": float(parameters["defect_layer_um"]),
            "ky": ky,
            "spatial_deviation_um": rho,
            "setup_error_um": epsilon,
            "minimum_allowance_um": zmin,
            "grade_before": previous_grade,
            "creates_hole_from_solid": creates_hole_from_solid,
        })
        rho *= ky
        previous_rz = float(parameters["roughness_um"])
        previous_defect = float(parameters["defect_layer_um"])
        previous_grade = grade

    # Идём от готовой поверхности к заготовке, назначая номиналы промежуточным
    # поверхностям до каждого перехода.
    after_nominal = float(final_nominal_mm)
    steps_to_back_calculate = result_steps[1:] if starts_with_drilling_hole else result_steps
    for step in reversed(steps_to_back_calculate):
        before_nominal = after_nominal + sign * step["minimum_allowance_um"] / 1000.0
        for _ in range(3):
            tolerance_after = tolerance_width_um(
                after_nominal, step["grade"], surface_type, tolerance_data
            )
            tolerance_before = tolerance_width_um(
                before_nominal, step["grade_before"], surface_type, tolerance_data
            )
            mean_allowance = step["minimum_allowance_um"] + (
                tolerance_before + tolerance_after
            ) / 2
            before_nominal = after_nominal + sign * mean_allowance / 1000.0
        step["nominal_before_mm"] = before_nominal
        step["nominal_after_mm"] = after_nominal
        # Технологический размер — это размер поверхности после перехода.
        # Разность размеров до/после перехода хранится отдельно.
        step["technological_size_mm"] = after_nominal
        step["size_change_mm"] = abs(after_nominal - before_nominal)
        step["mean_allowance_um"] = abs(after_nominal - before_nominal) * 1000.0
        step["tolerance_before_um"] = tolerance_before
        step["tolerance_after_um"] = tolerance_after
        step["tolerance_after_mm"] = tolerance_after / 1000.0
        after_nominal = before_nominal

    drill_diameter_mm = None
    if starts_with_drilling_hole:
        candidates = drill_diameters_mm or default_drill_diameters_mm()
        # При последующей обработке выбираем ближайшее сверло, которое не
        # превышает требуемый диаметр до следующего перехода, чтобы оставить
        # материал на его обработку. При одном сверлении подбираем ближайшее
        # к конечному номиналу.
        required_drill_mm = after_nominal if len(result_steps) > 1 else float(final_nominal_mm)
        drill_diameter_mm = _pick_drill_diameter(
            required_drill_mm, candidates,
            must_not_exceed=len(result_steps) > 1,
        )
        drill_step = result_steps[0]
        drill_output_nominal = (
            drill_diameter_mm if len(result_steps) > 1
            else float(final_nominal_mm)
        )
        drill_step.update({
            "nominal_before_mm": 0.0,
            # Если сверление — единственная операция, целевое значение остаётся
            # номиналом готового отверстия; выбранный размер сверла хранится отдельно.
            # При дальнейшей обработке диаметр сверления является промежуточным.
            "nominal_after_mm": drill_output_nominal,
            "technological_size_mm": drill_output_nominal,
            "size_change_mm": None,
            "mean_allowance_um": None,
            "drill_diameter_mm": drill_diameter_mm,
            # Допуск после сверления есть, хотя для сплошной заготовки
            # допуск диаметра до перехода не определён.
            "tolerance_after_um": tolerance_width_um(
                drill_output_nominal, drill_step["grade"], surface_type,
                tolerance_data,
            ),
        })
        if len(result_steps) > 1:
            next_step = result_steps[1]
            # Реальный диаметр сверления может быть меньше расчётно требуемого;
            # тогда первый последующий переход снимает больший припуск.
            next_step["nominal_before_mm"] = drill_diameter_mm
            next_step["tolerance_before_um"] = tolerance_width_um(
                drill_diameter_mm, next_step["grade_before"], surface_type,
                tolerance_data,
            )
            next_step["technological_size_mm"] = abs(
                next_step["nominal_after_mm"]
            )
            next_step["size_change_mm"] = abs(
                next_step["nominal_after_mm"] - drill_diameter_mm
            )
            next_step["mean_allowance_um"] = (
                next_step["technological_size_mm"] * 1000.0
            )
        after_nominal = 0.0

    return {
        "complete": True,
        "kind": kind,
        "direction": sign,
        "final_nominal_mm": float(final_nominal_mm),
        "stock_nominal_mm": after_nominal,
        "stock_state": "solid_no_hole" if starts_with_drilling_hole else "machined_blank",
        "drill_diameter_mm": drill_diameter_mm,
        "drill_diameter_catalog_mm": list(drill_diameters_mm or default_drill_diameters_mm())
            if starts_with_drilling_hole else None,
        "steps": result_steps,
        "intermediate_nominals_mm": (
            [step["nominal_after_mm"] for step in result_steps]
            if starts_with_drilling_hole else
            [step["nominal_before_mm"] for step in result_steps]
        ),
    }


def validate_chain(surfaces: list[dict], links: list[dict]) -> list[str]:
    """Проверить топологию простого графа технологической размерной схемы."""
    errors = []
    ids = [str(item.get("id", "")).strip() for item in surfaces]
    if not surfaces:
        errors.append("Добавьте хотя бы одну поверхность.")
    if any(not value for value in ids):
        errors.append("У каждой поверхности должен быть код.")
    if len(set(ids)) != len(ids):
        errors.append("Коды поверхностей должны быть уникальны.")
    known = set(ids)
    for index, link in enumerate(links, start=1):
        start, end = str(link.get("start", "")), str(link.get("end", ""))
        if start not in known or end not in known:
            errors.append(f"Связь {index}: выберите существующие начальную и конечную поверхности.")
        if start == end:
            errors.append(f"Связь {index}: начало и конец не могут совпадать.")
        if not str(link.get("label", "")).strip():
            errors.append(f"Связь {index}: введите обозначение (например, A1 или Z1).")
    technological_links = [
        item for item in links if item.get("type") == "Технологический размер"
    ]
    # При нескольких независимо обрабатываемых CAD-поверхностях технологические
    # связи образуют лес: каждая ветвь начинается со своей заготовки. Проверяем,
    # что технологические размеры не образуют цикл; конструкторские размеры и
    # припуски могут замыкать контуры отдельно.
    parent = {value: value for value in known}

    def find(value):
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    for index, link in enumerate(technological_links, start=1):
        start, end = str(link.get("start", "")), str(link.get("end", ""))
        if start not in known or end not in known or start == end:
            continue
        root_start, root_end = find(start), find(end)
        if root_start == root_end:
            errors.append(f"Технологические размеры образуют цикл (связь {index}).")
        else:
            parent[root_start] = root_end
    return errors
