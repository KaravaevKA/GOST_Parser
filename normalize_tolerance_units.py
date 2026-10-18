#!/usr/bin/env python3
"""Normalize mixed mm/µm deviations in gost_h_h_tolerances.json.

The script is conservative: it compares each tolerance width with the expected
ISO 286 IT width for the row's grade and nominal size band. By default it only
reports what it would change. Use --write to save; a .bak copy is made first.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path


# ISO 286 tolerance unit multipliers, IT5–IT18.
IT_MULTIPLIERS = {
    5: 7, 6: 10, 7: 16, 8: 25, 9: 40, 10: 64, 11: 100,
    12: 160, 13: 250, 14: 400, 15: 640, 16: 1000,
    17: 1600, 18: 2500,
}
LOWER_RATIO = 0.50
UPPER_RATIO = 2.00


def expected_it_width_um(grade: int, nominal_from: float,
                         nominal_to: float) -> float | None:
    """Approximate standard IT width in µm for one nominal-size interval."""
    multiplier = IT_MULTIPLIERS.get(grade)
    if multiplier is None or nominal_to <= nominal_from:
        return None
    # ISO 286 uses the geometric mean of the nominal-step limits. The first
    # step starts at zero, so use half its upper limit as a practical estimate.
    if nominal_from > 0:
        diameter = math.sqrt(nominal_from * nominal_to)
    else:
        diameter = nominal_to / 2.0
    i = 0.45 * (diameter ** (1.0 / 3.0)) + 0.001 * diameter
    return multiplier * i


def ratio_matches(width_um: float, expected_um: float) -> bool:
    ratio = width_um / expected_um if expected_um else 0.0
    return LOWER_RATIO <= ratio <= UPPER_RATIO


def records_in(data, path="$", records=None):
    """Yield nested dictionaries that look like tolerance table rows."""
    if records is None:
        records = []
    if isinstance(data, dict):
        required = {
            "grade", "nominal_from", "nominal_to",
            "upper_deviation_mkm", "lower_deviation_mkm",
        }
        if required.issubset(data):
            records.append((path, data))
        else:
            for key, value in data.items():
                records_in(value, f"{path}.{key}", records)
    elif isinstance(data, list):
        for index, value in enumerate(data):
            records_in(value, f"{path}[{index}]", records)
    return records


def inspect_and_normalize(data):
    changes = []
    unchanged = []
    ambiguous = []

    for path, row in records_in(data):
        try:
            grade = int(row["grade"])
            low = float(row["nominal_from"])
            high = float(row["nominal_to"])
            upper = float(row["upper_deviation_mkm"])
            lower = float(row["lower_deviation_mkm"])
        except (TypeError, ValueError, KeyError):
            ambiguous.append((path, "нечисловые или отсутствующие поля"))
            continue

        width = upper - lower
        if 1 <= grade <= 4 and width > 0:
            unchanged.append((path, width, None))
            continue
        expected = expected_it_width_um(grade, low, high)
        if (not all(math.isfinite(x) for x in (low, high, upper, lower, width))
                or width <= 0 or expected is None):
            ambiguous.append((path, f"не удалось проверить ширину {width:g}"))
            continue

        raw_matches = ratio_matches(width, expected)
        scaled_matches = ratio_matches(width * 1000.0, expected)
        if raw_matches and not scaled_matches:
            unchanged.append((path, width, expected))
        elif scaled_matches and not raw_matches:
            changes.append((path, row, upper, lower, width, expected))
        else:
            ambiguous.append((
                path,
                f"ширина {width:g}; ожидается примерно {expected:.3g} мкм"
            ))

    return changes, unchanged, ambiguous


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Проверить и привести отклонения из мм к мкм."
    )
    parser.add_argument(
        "json_file", nargs="?",
        default="data/gost_h_h_tolerances.json",
        help="путь к таблице (по умолчанию data/gost_h_h_tolerances.json)",
    )
    parser.add_argument(
        "--write", action="store_true",
        help="сохранить преобразования; перед записью создать .bak",
    )
    args = parser.parse_args()

    path = Path(args.json_file)
    if not path.is_file():
        print(f"Файл не найден: {path}", file=sys.stderr)
        return 2

    try:
        original_text = path.read_text(encoding="utf-8")
        data = json.loads(original_text)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        print(f"Не удалось прочитать JSON: {error}", file=sys.stderr)
        return 2

    changes, unchanged, ambiguous = inspect_and_normalize(data)
    print(f"Строк таблицы проверено: {len(changes) + len(unchanged) + len(ambiguous)}")
    print(f"Уже похожи на мкм: {len(unchanged)}")
    print(f"Будут умножены на 1000: {len(changes)}")
    print(f"Неоднозначны: {len(ambiguous)}")

    for item_path, _, _, _, width, expected in changes:
        print(f"  мм → мкм: {item_path}: ширина {width:g} → {width * 1000:g}; "
              f"ожидается около {expected:.3g} мкм")
    for item_path, reason in ambiguous:
        print(f"  ПРОВЕРИТЬ: {item_path}: {reason}")

    if not args.write:
        print("Режим проверки: файл не изменён. Для записи добавьте --write.")
        return 1 if ambiguous else 0
    if ambiguous:
        print("Запись отменена: сначала проверьте неоднозначные строки.", file=sys.stderr)
        return 1
    if not changes:
        print("Преобразовывать нечего; файл не изменён.")
        return 0

    backup = path.with_suffix(path.suffix + ".bak")
    if backup.exists():
        print(f"Резервная копия уже существует, перезапись отменена: {backup}",
              file=sys.stderr)
        return 2

    for _, row, upper, lower, _, _ in changes:
        row["upper_deviation_mkm"] = upper * 1000.0
        row["lower_deviation_mkm"] = lower * 1000.0

    try:
        shutil.copy2(path, backup)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as error:
        print(f"Не удалось сохранить результат: {error}", file=sys.stderr)
        if backup.exists():
            print(f"Оригинал сохранён в резервной копии: {backup}", file=sys.stderr)
        return 2

    print(f"Готово. Исходник сохранён: {backup}")
    print(f"Изменённый файл: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
