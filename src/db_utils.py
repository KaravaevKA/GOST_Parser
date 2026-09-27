# src/db_utils.py
import sqlite3

DB_PATH = r"C:\Users\janna\PycharmProjects\GOST_Parser\data\tolerances.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def find_grade_for_actual(actual, nominal, surface_type, conn=None):
    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True

    cursor = conn.cursor()
    cursor.execute('''
        SELECT grade, upper_deviation_mkm, lower_deviation_mkm
        FROM tolerances
        WHERE hole_or_shaft = ? 
          AND nominal_from <= ? AND nominal_to > ?
    ''', (surface_type, nominal, nominal))

    interval_records = cursor.fetchall()
    if not interval_records:
        if close_conn: conn.close()
        return None

    matches = []
    for grade, upper, lower in interval_records:
        lower_lim = nominal + lower / 1000.0
        upper_lim = nominal + upper / 1000.0
        if lower_lim - 1e-6 <= actual <= upper_lim + 1e-6:
            matches.append((grade, upper, lower))

    if close_conn:
        conn.close()
    return matches


def get_available_grades(nominal, surface_type, conn=None):
    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True

    cursor = conn.cursor()
    cursor.execute('''
        SELECT grade, upper_deviation_mkm, lower_deviation_mkm
        FROM tolerances
        WHERE hole_or_shaft = ? 
          AND nominal_from <= ? AND nominal_to > ?
        ORDER BY grade
    ''', (surface_type, nominal, nominal))
    rows = cursor.fetchall()
    if close_conn:
        conn.close()
    return rows