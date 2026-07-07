import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import io

# Настройка соединения
conn = sqlite3.connect('sales_data.db', check_same_thread=False)


def init_db():
    # Создаем таблицы, если их нет
    conn.execute('''CREATE TABLE IF NOT EXISTS product_dictionary (
                        original_name TEXT PRIMARY KEY,
                        unified_name TEXT)''')

    conn.execute('''CREATE TABLE IF NOT EXISTS raw_sales (
                        product_name TEXT, manufacturer TEXT, customer TEXT, 
                        number TEXT, sale_date DATE, amount REAL, 
                        source TEXT, inn TEXT, region TEXT, 
                        district TEXT, address TEXT, 
                        distributor_name TEXT, load_date TIMESTAMP)''')
    conn.commit()


init_db()

st.set_page_config(layout="wide")
st.title("Система учета индивидуальных данных")
tab1, tab2 = st.tabs(["Загрузка данных", "Отчеты"])

with tab1:
    distributor = st.selectbox("Дистрибьютор:", ["Grand", "Optima", "MegaPharm"])
    uploaded_file = st.file_uploader("Выберите Excel-файл продаж", type="xlsx")

    if uploaded_file and distributor:
        df = pd.read_excel(uploaded_file)

        # Словарь переименования
        mapping = {
            'Препарат': 'product_name', 'Производитель': 'manufacturer', 'Покупатель': 'customer',
            '№': 'number', 'Дата': 'sale_date', 'Кол-во': 'amount', 'Откуда_продано': 'source',
            'ИНН': 'inn', 'Регион': 'region', 'Город/Район': 'district', 'Адрес': 'address'
        }
        df = df.rename(columns=mapping)

        # Проверяем, все ли нужные колонки на месте
        required = list(mapping.values())
        if not all(col in df.columns for col in required):
            st.error(f"Не хватает колонок. Проверьте заголовки в Excel.")
            st.write("Ожидались:", required)
        else:
            # Проверка новых препаратов
            known = set(pd.read_sql("SELECT original_name FROM product_dictionary", conn)['original_name'])
            unknown = set(df['product_name'].dropna().unique()) - known

            if unknown:
                st.warning(f"Новые препараты: {list(unknown)}")
                with st.form("add_new"):
                    selected = st.selectbox("Выберите препарат:", list(unknown))
                    unified = st.text_input("Унифицированное название:")
                    if st.form_submit_button("Добавить в справочник"):
                        conn.execute("INSERT INTO product_dictionary VALUES (?, ?)", (selected, unified))
                        conn.commit()
                        st.rerun()
            else:
                if st.button("Загрузить данные в базу"):
                    df_to_db = df[required].copy()
                    df_to_db['distributor_name'] = distributor
                    df_to_db['load_date'] = datetime.now()
                    df_to_db.to_sql('raw_sales', conn, if_exists='append', index=False)
                    st.success("Данные успешно добавлены!")

# with tab2:
#     st.header("Сводный отчет")
#
#     # 1. Получаем уникальный список дистрибьюторов из базы
#     cursor = conn.execute("SELECT DISTINCT distributor_name FROM raw_sales")
#     all_distributors = [row[0] for row in cursor.fetchall()]
#
#     # 2. Multiselect для выбора нескольких
#     selected_dists = st.multiselect("Фильтр по дистрибьюторам:", all_distributors)
#
#     if selected_dists:
#         # 3. Формируем динамический запрос для любого количества выбранных дистрибьюторов
#         placeholders = ', '.join(['?'] * len(selected_dists))
#         query = f"""
#         SELECT rs.*, pd.unified_name
#         FROM raw_sales rs
#         LEFT JOIN product_dictionary pd ON rs.product_name = pd.original_name
#         WHERE rs.distributor_name IN ({placeholders})
#         """
#
#         # Передаем список выбранных дистрибьюторов как параметры
#         df_rep = pd.read_sql(query, conn, params=tuple(selected_dists))
#
#         if not df_rep.empty:
#             # Преобразование дат и создание периода
#             df_rep['sale_date'] = pd.to_datetime(df_rep['sale_date'])
#             df_rep['period'] = df_rep['sale_date'].dt.strftime('%Y-%m')
#
#             # Сводная таблица
#             pivot = df_rep.pivot_table(
#                 index='unified_name',
#                 columns='period',
#                 values='amount',
#                 aggfunc='sum',
#                 fill_value=0
#             ).sort_index(axis=1)
#
#             # Отображение
#             st.dataframe(pivot, use_container_width=True)
#
#             # Скачивание в Excel
#             buffer = io.BytesIO()
#             with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
#                 pivot.to_excel(writer, sheet_name='Отчет')
#
#             st.download_button(
#                 label="📥 Скачать сводный отчет в Excel",
#                 data=buffer.getvalue(),
#                 file_name="Report_MultiDist.xlsx",
#                 mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
#             )
#         else:
#             st.warning("Для выбранных дистрибьюторов нет данных в базе.")
#     else:
#         st.info("Пожалуйста, выберите одного или нескольких дистрибьюторов из списка.")
with tab2:
    st.header("Сводный отчет: Продукты по Месяцам")

    # 1. Получаем списки для фильтров
    cursor = conn.execute("SELECT DISTINCT distributor_name FROM raw_sales")
    all_dists = [row[0] for row in cursor.fetchall()]

    # Получаем все уникальные месяцы из базы
    df_all = pd.read_sql("SELECT sale_date FROM raw_sales", conn)
    df_all['period'] = pd.to_datetime(df_all['sale_date']).dt.strftime('%Y-%m')
    all_periods = sorted(df_all['period'].unique().tolist(), reverse=True)

    # 2. Фильтры
    col1, col2 = st.columns(2)
    with col1:
        selected_dists = st.multiselect("Фильтр по дистрибьюторам:", all_dists)
    with col2:
        selected_periods = st.multiselect("Фильтр по месяцам:", all_periods)

    if selected_dists and selected_periods:
        # 3. SQL запрос с фильтрацией по обоим параметрам
        dist_placeholders = ', '.join(['?'] * len(selected_dists))
        period_placeholders = ', '.join(['?'] * len(selected_periods))

        query = f"""
        SELECT rs.*, pd.unified_name 
        FROM raw_sales rs
        LEFT JOIN product_dictionary pd ON rs.product_name = pd.original_name
        WHERE rs.distributor_name IN ({dist_placeholders})
        AND strftime('%Y-%m', rs.sale_date) IN ({period_placeholders})
        """

        # Передаем параметры: сначала дистрибьюторы, потом периоды
        params = tuple(selected_dists) + tuple(selected_periods)
        df_rep = pd.read_sql(query, conn, params=params)

        if not df_rep.empty:
            df_rep['period'] = pd.to_datetime(df_rep['sale_date']).dt.strftime('%Y-%m')

            pivot = df_rep.pivot_table(
                index='unified_name',
                columns='period',
                values='amount',
                aggfunc='sum',
                fill_value=0
            ).sort_index(axis=1)

            st.dataframe(pivot, use_container_width=True)

            # Скачивание
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                pivot.to_excel(writer, sheet_name='Отчет')

            st.download_button("📥 Скачать сводный отчет в Excel", buffer.getvalue(), "Report.xlsx")
        else:
            st.warning("Нет данных для выбранных параметров.")
    else:
        st.info("Пожалуйста, выберите дистрибьютора и хотя бы один месяц.")
