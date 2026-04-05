# main.py
import json
from src.aspose_analyzer import extract_cylinders


def load_tolerance_data(json_path: str):
    """Загружает данные допусков из JSON-файла."""
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def find_tolerance(diameter: float, surface_type: str, tolerance_data: list, preferred_grade: int = 7):
    """
    Ищет подходящую запись допуска для заданного диаметра и типа поверхности.
    Возвращает словарь с допуском или None.
    """
    # Фильтруем записи по типу поверхности и интервалу размеров
    candidates = [item for item in tolerance_data
                  if item['hole_or_shaft'] == surface_type
                  and item['nominal_from'] <= diameter < item['nominal_to']]
    if not candidates:
        return None
    # Сначала ищем предпочтительный квалитет
    for candidate in candidates:
        if candidate['grade'] == preferred_grade:
            return candidate
    # Если не нашли, возвращаем первый попавшийся (или можно ближайший по квалитету)
    return candidates[0]


def main():
    # Укажите путь к вашей 3D-модели (STEP, STL, OBJ и т.д.)
    MODEL_PATH = "data/test_cylinder.step"  # Замените на реальный файл
    TOLERANCES_JSON = "data/gost_h_h_tolerances.json"

    # Загружаем данные допусков
    tolerance_data = load_tolerance_data(TOLERANCES_JSON)
    print(f"Загружено {len(tolerance_data)} записей допусков.")

    # Извлекаем цилиндры из модели
    cylinders = extract_cylinders(MODEL_PATH)
    print(f"Найдено цилиндрических поверхностей: {len(cylinders)}")

    # Анализируем каждый цилиндр
    for cyl in cylinders:
        diam = cyl["diameter"]
        surf_type = cyl["type"]
        tolerance = find_tolerance(diam, surf_type, tolerance_data, preferred_grade=7)
        if tolerance:
            print(f"Цилиндр '{cyl['name']}': D={diam:.2f} мм, тип={surf_type}, "
                  f"квалитет IT{tolerance['grade']}, "
                  f"отклонения: +{tolerance['upper_deviation_mkm']}/-{tolerance['lower_deviation_mkm']} мкм")
        else:
            print(f"Внимание: для цилиндра '{cyl['name']}' (D={diam:.2f} мм, тип={surf_type}) "
                  f"не найден подходящий квалитет.")


if __name__ == "__main__":
    main()