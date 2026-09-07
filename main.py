import streamlit as st
import pandas as pd
import sqlite3
import io
from datetime import datetime

# ==========================================
# 1. БАЗА ДАННЫХ
# ==========================================
conn = sqlite3.connect('sales_data.db', check_same_thread=False)


def init_db():
    conn.execute('''CREATE TABLE IF NOT EXISTS product_dictionary (
                        original_name TEXT PRIMARY KEY,
                        unified_name TEXT,
                        product_group TEXT)''')

    conn.execute('''CREATE TABLE IF NOT EXISTS raw_sales (
                        product_name TEXT, manufacturer TEXT, customer TEXT, 
                        number TEXT, sale_date DATE, amount REAL, 
                        source TEXT, inn TEXT, region TEXT, 
                        district TEXT, address TEXT, 
                        distributor_name TEXT, load_date TIMESTAMP)''')

    conn.execute('''CREATE TABLE IF NOT EXISTS pharmacy_workplace (
                        inn TEXT, 
                        product_group TEXT, 
                        workplace_id TEXT, 
                        share REAL)''')

    conn.execute('''CREATE TABLE IF NOT EXISTS workplace_employee (
                        workplace_id TEXT PRIMARY KEY, 
                        rep_name TEXT)''')
    conn.commit()


init_db()

GROUPS = ["Группа 1", "Группа 2", "Группа 3"]

# ==========================================
# 2. ИНТЕРФЕЙС
# ==========================================
st.set_page_config(layout="wide", page_title="Аналитика продаж")
st.title("Система управления продажами")

tab1, tab2, tab3 = st.tabs(["Загрузка данных", "Отчетность", "Настройка территорий"])

# ==========================================
# ВКЛАДКА 1: ЗАГРУЗКА ДАННЫХ (ЖЕСТКИЙ КОНТРОЛЬ)
# ==========================================
with tab1:
    distributor = st.selectbox("Дистрибьютор:", ["Grand", "Optima", "MegaPharm"])
    uploaded_file = st.file_uploader("Выберите Excel-файл продаж", type="xlsx")

    if uploaded_file and distributor:
        df = pd.read_excel(uploaded_file)
        mapping = {
            'Препарат': 'product_name', 'Производитель': 'manufacturer', 'Покупатель': 'customer',
            '№': 'number', 'Дата': 'sale_date', 'Кол-во': 'amount', 'Откуда_продано': 'source',
            'ИНН': 'inn', 'Регион': 'region', 'Город/Район': 'district', 'Адрес': 'address'
        }
        df = df.rename(columns=mapping)
        required = list(mapping.values())

        if not all(col in df.columns for col in required):
            st.error("Ошибка структуры файла! Убедитесь, что заголовки в Excel названы точно по шаблону.")
        else:
            # Очистка ИНН от ".0" на конце (особенность Excel) и лишних пробелов
            df['inn'] = df['inn'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

            # --- ПРОВЕРКА 1: ПРЕПАРАТЫ ---
            known_prods = set(pd.read_sql("SELECT original_name FROM product_dictionary", conn)['original_name'])
            unknown_prods = set(df['product_name'].dropna().unique()) - known_prods

            if unknown_prods:
                st.warning(f"Найдены новые препараты ({len(unknown_prods)} шт.). Сначала добавьте их в справочник!")
                with st.form("add_new"):
                    selected = st.selectbox("Выберите препарат для добавления:", list(unknown_prods))
                    unified = st.text_input("Унифицированное название:")
                    prod_group = st.selectbox("Отнести к группе:", GROUPS)

                    if st.form_submit_button("Добавить препарат"):
                        conn.execute("INSERT INTO product_dictionary VALUES (?, ?, ?)",
                                     (selected, unified, prod_group))
                        conn.commit()
                        st.rerun()
            else:
                # --- ПРОВЕРКА 2: АПТЕКИ ---
                known_inns = set(pd.read_sql("SELECT DISTINCT inn FROM pharmacy_workplace", conn)['inn'].astype(str))
                file_inns = set(df['inn'].dropna().unique())
                unknown_inns = file_inns - known_inns

                if unknown_inns:
                    st.error(
                        f"БЛОКИРОВКА ЗАГРУЗКИ: Найдено {len(unknown_inns)} новых аптек (ИНН), которых нет в базе распределения!")
                    st.info("Перейдите во вкладку «Настройка территорий» и привяжите эти аптеки к рабочим местам.")

                    # Формируем красивую таблицу новых аптек для пользователя
                    missing_df = df[df['inn'].isin(unknown_inns)][
                        ['inn', 'customer', 'address', 'region']].drop_duplicates(subset=['inn'])
                    st.dataframe(missing_df, use_container_width=True)

                    # Кнопка для удобного скачивания новых аптек, чтобы внести их в Excel-шаблон
                    buffer_inns = io.BytesIO()
                    with pd.ExcelWriter(buffer_inns, engine='xlsxwriter') as writer:
                        missing_df.to_excel(writer, sheet_name='Новые_Аптеки', index=False)
                    st.download_button("📥 Скачать список новых аптек (Excel)", buffer_inns.getvalue(),
                                       "Missing_Pharmacies.xlsx")

                else:
                    # --- ЕСЛИ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ ---
                    st.success("Все препараты и аптеки распознаны! Можно загружать данные.")
                    if st.button("Загрузить данные в базу"):
                        df_to_db = df[required].copy()
                        df_to_db['distributor_name'] = distributor
                        df_to_db['load_date'] = datetime.now()
                        df_to_db.to_sql('raw_sales', conn, if_exists='append', index=False)
                        st.success(f"Успешно загружено {len(df_to_db)} строк!")

# ==========================================
# ВКЛАДКА 3: НАСТРОЙКА ТЕРРИТОРИЙ (2 УРОВНЯ)
# ==========================================
with tab3:
    col_map1, col_map2 = st.columns(2)

    with col_map1:
        st.subheader("1. Аптеки -> Рабочие места")
        st.write("Колонки: `inn`, `product_group`, `workplace_id`, `share`")
        uploaded_pharm_wp = st.file_uploader("Загрузить базу аптек", type="xlsx", key="pharm")
        if uploaded_pharm_wp and st.button("Обновить базу аптек"):
            df_pharm = pd.read_excel(uploaded_pharm_wp)
            # Очистка ИНН при загрузке базы
            df_pharm['inn'] = df_pharm['inn'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

            conn.execute("DELETE FROM pharmacy_workplace")
            df_pharm.to_sql('pharmacy_workplace', conn, if_exists='append', index=False)
            st.success("Связи аптек и рабочих мест обновлены!")

    with col_map2:
        st.subheader("2. Рабочие места -> Сотрудники")
        st.write("Колонки: `workplace_id`, `rep_name`")
        uploaded_wp_emp = st.file_uploader("Загрузить список сотрудников", type="xlsx", key="emp")
        if uploaded_wp_emp and st.button("Обновить штат сотрудников"):
            df_emp = pd.read_excel(uploaded_wp_emp)
            conn.execute("DELETE FROM workplace_employee")
            df_emp.to_sql('workplace_employee', conn, if_exists='append', index=False)
            st.success("Штат сотрудников обновлен!")

# ==========================================
# ВКЛАДКА 2: ОТЧЕТНОСТЬ
# ==========================================
with tab2:
    all_dists = [row[0] for row in conn.execute("SELECT DISTINCT distributor_name FROM raw_sales").fetchall()]
    df_dates = pd.read_sql("SELECT sale_date FROM raw_sales", conn)
    all_periods = sorted(pd.to_datetime(df_dates['sale_date']).dt.strftime('%Y-%m').unique().tolist(),
                         reverse=True) if not df_dates.empty else []

    col1, col2 = st.columns(2)
    with col1:
        selected_dists = st.multiselect("Фильтр по дистрибьюторам:", all_dists, default=all_dists)
    with col2:
        selected_periods = st.multiselect("Фильтр по месяцам:", all_periods, default=all_periods)

    if selected_dists and selected_periods:
        dist_placeholders = ', '.join(['?'] * len(selected_dists))

        query = f"""
        SELECT 
            rs.sale_date,
            pd.unified_name,
            pd.product_group,
            IFNULL(pw.workplace_id, 'Не привязано') as workplace_id,
            IFNULL(we.rep_name, 'Вакантно') as rep_name,
            (rs.amount * IFNULL(pw.share, 1.0)) as distributed_amount
        FROM raw_sales rs
        LEFT JOIN product_dictionary pd ON rs.product_name = pd.original_name
        LEFT JOIN pharmacy_workplace pw ON rs.inn = pw.inn AND pd.product_group = pw.product_group
        LEFT JOIN workplace_employee we ON pw.workplace_id = we.workplace_id
        WHERE rs.distributor_name IN ({dist_placeholders})
        """

        df_rep = pd.read_sql(query, conn, params=tuple(selected_dists))

        if not df_rep.empty:
            df_rep['period'] = pd.to_datetime(df_rep['sale_date']).dt.strftime('%Y-%m')
            df_rep = df_rep[df_rep['period'].isin(selected_periods)]

            if not df_rep.empty:
                pivot = df_rep.pivot_table(
                    index=['rep_name', 'workplace_id', 'product_group', 'unified_name'],
                    columns='period',
                    values='distributed_amount',
                    aggfunc='sum',
                    fill_value=0
                ).sort_index(axis=1)

                st.dataframe(pivot, use_container_width=True)

                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    pivot.to_excel(writer, sheet_name='Отчет')

                st.download_button("📥 Скачать отчет (Excel)", buffer.getvalue(), "Sales_Distributed.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else:
                st.warning("Нет продаж за выбранные периоды.")
        else:
            st.warning("Нет данных.")