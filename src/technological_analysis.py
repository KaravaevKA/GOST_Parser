"""Расчёты технологических припусков и данные для графа размерной цепи.

Все величины геометрических ошибок и припусков задаются в микрометрах;
размеры заготовки и детали — в миллиметрах.
"""

from __future__ import annotations

from math import hypot, isfinite, sqrt


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
    technological_links = [item for item in links if item.get("type") == "Технологический размер"]
    if surfaces and len(technological_links) != len(surfaces) - 1:
        errors.append("Для дерева число технологических размеров должно быть на единицу меньше числа поверхностей.")
    return errors
