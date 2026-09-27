# migrate_json_to_db.py
import json
import sqlite3

def main():
    # Подключаемся к базе данных (файл создастся автоматически)
    conn = sqlite3.connect("data/tolerances.db")
    cursor = conn.cursor()

    # Создаём таблицу (если её нет)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tolerances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            standard TEXT,
            hole_or_shaft TEXT,
            deviation_symbol TEXT,
            nominal_from REAL,
            nominal_to REAL,
            grade INTEGER,
            upper_deviation_mkm REAL,
            lower_deviation_mkm REAL
        )
    ''')

    # Загружаем JSON
    with open("data/gost_h_h_tolerances.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    # Вставляем записи
    for record in data:
        cursor.execute('''
            INSERT INTO tolerances (standard, hole_or_shaft, deviation_symbol, nominal_from, nominal_to, grade, upper_deviation_mkm, lower_deviation_mkm)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            record.get("standard", ""),
            record.get("hole_or_shaft", ""),
            record.get("deviation_symbol", ""),
            record.get("nominal_from"),
            record.get("nominal_to"),
            record.get("grade"),
            record.get("upper_deviation_mkm"),
            record.get("lower_deviation_mkm")
        ))

    conn.commit()
    conn.close()
    print(f"Данные успешно перенесены в data/tolerances.db. Всего записей: {len(data)}")

if __name__ == "__main__":
    main()