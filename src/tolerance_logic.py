"""Подбор и проверка квалитетов для цилиндрической поверхности."""


def suggest_nominal(actual_diameter):
    """Пока что предлагает ближайший целый номинал, как исходная программа."""
    return round(actual_diameter)


def grade_options(actual_diameter, nominal, tolerance_data, surface_type):
    """Возвращает все квалитеты для типа и номинала с отметкой попадания."""
    options = []
    for record in tolerance_data:
        if record["hole_or_shaft"] != surface_type:
            continue
        if not (record["nominal_from"] <= nominal < record["nominal_to"]):
            continue

        lower = nominal + record["lower_deviation_mkm"] / 1000.0
        upper = nominal + record["upper_deviation_mkm"] / 1000.0
        options.append({
            **record,
            "lower_limit_mm": lower,
            "upper_limit_mm": upper,
            "fits_model_diameter": lower - 1e-6 <= actual_diameter <= upper + 1e-6,
        })

    return sorted(options, key=lambda item: item["grade"])
