# auto_tolerance.py
import json
from src.cadquery_analyzer import extract_cylinders

def load_tolerance_data(json_path="data/gost_h_h_tolerances.json"):
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def suggest_nominal(actual):
    """Округляет фактический диаметр до ближайшего целого (можно до 0.5, но для начала целое)"""
    return round(actual)


def find_grade_for_actual(actual, nominal, tolerance_data, surface_type):
    """Возвращает список квалитетов, в которые попадает фактический размер"""
    interval_records = [t for t in tolerance_data
                        if t['hole_or_shaft'] == surface_type
                        and t['nominal_from'] <= nominal < t['nominal_to']]
    if not interval_records:
        return None
    matches = []
    for rec in interval_records:
        lower_lim = nominal + rec['lower_deviation_mkm'] / 1000.0
        upper_lim = nominal + rec['upper_deviation_mkm'] / 1000.0
        if lower_lim - 1e-6 <= actual <= upper_lim + 1e-6:
            matches.append(rec)
    return matches


def main():
    # Путь к вашей STEP-модели (замените на реальный файл)
    model_path = "data/model1.step"

    # Загружаем допуски
    data = load_tolerance_data()
    print(f"Загружено {len(data)} записей допусков.")

    cylinders = extract_cylinders(model_path)
    print(f"Найдено цилиндрических поверхностей: {len(cylinders)}")

    for idx, cyl in enumerate(cylinders):
        actual_diam = cyl["diameter"]
        nominal = suggest_nominal(actual_diam)
        surface_type = cyl.get("type", "unknown")

        # Если тип не определен, можно предложить пользователю ввести вручную
        if surface_type == 'unknown':
            # Здесь можно запросить ввод, но для автоматики пропустим
            print(f"\n--- Цилиндр {idx + 1} (тип не распознан) ---")
            continue

        matches = find_grade_for_actual(actual_diam, nominal, data, surface_type)

        print(f"\n--- Цилиндр {idx + 1} ---")
        print(f"  Тип: {'вал' if surface_type == 'shaft' else 'отверстие'}")
        print(f"  Фактический диаметр: {actual_diam:.4f} мм")
        print(f"  Длина цилиндрической поверхности: {cyl['length']:.4f} мм")
        print(f"  Предполагаемый номинальный размер: {nominal:.3f} мм")
        if matches:
            print("  Подходящие квалитеты:")
            for m in matches:
                print(
                    f"    IT{m['grade']}: верхнее отклонение {m['upper_deviation_mkm']:+.0f} мкм, нижнее {m['lower_deviation_mkm']:+.0f} мкм")
        else:
            print("  Квалитет не найден. Возможные квалитеты для этого номинала:")
            interval_records = [t for t in data
                                if t['hole_or_shaft'] == surface_type
                                and t['nominal_from'] <= nominal < t['nominal_to']]
            if interval_records:
                for rec in interval_records:
                    low = nominal + rec['lower_deviation_mkm'] / 1000.0
                    high = nominal + rec['upper_deviation_mkm'] / 1000.0
                    print(f"    IT{rec['grade']:2d}: [{low:.4f}, {high:.4f}] мм")
            else:
                print("    Нет данных для этого номинала.")


if __name__ == "__main__":
    main()
