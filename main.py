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
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        original_name TEXT UNIQUE,
                        unified_name TEXT,
                        product_line TEXT)''')

    conn.execute('''CREATE TABLE IF NOT EXISTS raw_sales (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_id INTEGER, manufacturer TEXT, customer TEXT, 
                        number TEXT, sale_date DATE, amount REAL, 
                        source TEXT, inn TEXT, region TEXT, district TEXT, address TEXT, 
                        distributor_name TEXT, load_date TIMESTAMP)''')

    # Справочник рабочих мест
    conn.execute('''CREATE TABLE IF NOT EXISTS workplaces (
                        workplace_id TEXT PRIMARY KEY)''')

    # Добавлено поле pharmacy_name
    conn.execute('''CREATE TABLE IF NOT EXISTS pharmacies (
                        inn TEXT PRIMARY KEY,
                        pharmacy_name TEXT,
                        pharmacy_type INTEGER)''')

    conn.execute('''CREATE TABLE IF NOT EXISTS pharmacy_workplaces (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        inn TEXT,
                        workplace_id TEXT)''')

    conn.execute('''CREATE TABLE IF NOT EXISTS employees (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        full_name TEXT,
                        workplace_id TEXT UNIQUE,
                        rep_line TEXT)''')

    conn.execute('''CREATE TABLE IF NOT EXISTS type3_shares (
                        unified_name TEXT PRIMARY KEY,
                        share_line2 REAL,
                        share_line3 REAL)''')
    conn.commit()


init_db()

LINES = ["Линия 1", "Линия 2", "Линия 3", "Другая"]

st.markdown("""<style>[data-testid="stToolbar"] {visibility: hidden !important;}
            #MainMenu {visibility: hidden !important;}
            header {visibility: hidden !important;}</style>""", unsafe_allow_html=True)

st.set_page_config(layout="wide", page_title="Аналитика продаж")
st.title("Система управления продажами")

tab1, tab2, tab3 = st.tabs(["Загрузка данных", "Отчетность", "Настройка бизнес-логики"])

# ==========================================
# ВКЛАДКА 1: ЗАГРУЗКА И РЕГИСТРАЦИЯ
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
            st.error("Ошибка структуры файла!")
        else:
            df['inn'] = df['inn'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

            prod_dict_df = pd.read_sql("SELECT id, original_name FROM product_dictionary", conn)
            known_prods = set(prod_dict_df['original_name'])
            unknown_prods = set(df['product_name'].dropna().unique()) - known_prods

            if unknown_prods:
                st.warning(f"Новые препараты ({len(unknown_prods)} шт.).")
                with st.form("add_prod", clear_on_submit=True):
                    selected = st.selectbox("Выберите препарат:", list(unknown_prods))
                    unified = st.text_input("Унифицированное название:")
                    prod_line = st.selectbox("Линия препарата:", LINES)
                    if st.form_submit_button("Добавить в базу"):
                        conn.execute(
                            "INSERT INTO product_dictionary (original_name, unified_name, product_line) VALUES (?, ?, ?)",
                            (selected, unified, prod_line))
                        conn.commit()
                        st.rerun()
            else:
                known_inns = set(pd.read_sql("SELECT DISTINCT inn FROM pharmacies", conn)['inn'].astype(str))
                file_inns = set(df['inn'].dropna().unique())
                unknown_inns = file_inns - known_inns

                if unknown_inns:
                    st.error(f"БЛОКИРОВКА: Найдено {len(unknown_inns)} новых аптек (ИНН). Зарегистрируйте их ниже:")

                    missing_df = df[df['inn'].isin(unknown_inns)][['inn', 'customer', 'address']].drop_duplicates(
                        subset=['inn'])
                    st.dataframe(missing_df.head(5), use_container_width=True)

                    avail_wps = pd.read_sql("SELECT workplace_id FROM workplaces", conn)['workplace_id'].tolist()

                    with st.form("add_pharmacy", clear_on_submit=True):
                        st.subheader("Регистрация аптеки")
                        sel_inn = st.selectbox("ИНН новой аптеки:", list(unknown_inns))

                        # Автоматически подтягиваем название аптеки из Excel, если оно там есть
                        suggested_name = missing_df[missing_df['inn'] == sel_inn]['customer'].iloc[
                            0] if not missing_df.empty else ""
                        ph_name = st.text_input("Название аптеки:", value=suggested_name)

                        p_type = st.selectbox("Тип аптеки:", [1, 2, 3, 4])
                        # Теперь рабочие места выбираются из мультиселекта
                        workplaces = st.multiselect("Рабочие места (не нужно для Тип 1):", avail_wps)

                        if st.form_submit_button("Зарегистрировать аптеку"):
                            conn.execute("INSERT INTO pharmacies (inn, pharmacy_name, pharmacy_type) VALUES (?, ?, ?)",
                                         (sel_inn, ph_name, p_type))
                            if p_type != 1 and workplaces:
                                for wp in workplaces:
                                    conn.execute("INSERT INTO pharmacy_workplaces (inn, workplace_id) VALUES (?, ?)",
                                                 (sel_inn, wp))
                            conn.commit()
                            st.success("Аптека добавлена!")
                            st.rerun()
                else:
                    st.success("Все препараты и аптеки распознаны!")
                    if st.button("Загрузить данные в базу продаж"):
                        df_to_db = df[required].copy()
                        prod_map = dict(zip(prod_dict_df['original_name'], prod_dict_df['id']))
                        df_to_db['product_id'] = df_to_db['product_name'].map(prod_map)
                        df_to_db = df_to_db.drop(columns=['product_name'])

                        df_to_db['distributor_name'] = distributor
                        df_to_db['load_date'] = datetime.now()
                        df_to_db.to_sql('raw_sales', conn, if_exists='append', index=False)
                        st.success("Данные успешно загружены!")

# ==========================================
# ВКЛАДКА 3: НАСТРОЙКИ (ПРЯМАЯ ПРАВКА)
# ==========================================
with tab3:
    c1, c2, c3 = st.columns(3)

    with c1:
        st.subheader("1. Справочник рабочих мест")
        with st.form("add_wp", clear_on_submit=True):
            wp_name = st.text_input("Название/Номер (например, RM-101)")
            if st.form_submit_button("Добавить рабочее место"):
                try:
                    conn.execute("INSERT INTO workplaces (workplace_id) VALUES (?)", (wp_name.strip(),))
                    conn.commit()
                    st.success("Рабочее место создано!")
                except sqlite3.IntegrityError:
                    st.error("Такое рабочее место уже существует.")
        st.dataframe(pd.read_sql("SELECT * FROM workplaces", conn), use_container_width=True)

    with c2:
        st.subheader("2. Штат сотрудников")
        avail_wps = pd.read_sql("SELECT workplace_id FROM workplaces", conn)['workplace_id'].tolist()

        with st.form("add_emp", clear_on_submit=True):
            e_name = st.text_input("ФИО сотрудника")
            # Замена текстового поля на выпадающий список
            e_wp = st.selectbox("Рабочее место", avail_wps if avail_wps else ["Создайте рабочее место в шаге 1"])
            e_line = st.selectbox("Линия", LINES)
            if st.form_submit_button("Добавить / Обновить"):
                if avail_wps:
                    conn.execute(
                        "INSERT OR REPLACE INTO employees (full_name, workplace_id, rep_line) VALUES (?, ?, ?)",
                        (e_name, e_wp, e_line))
                    conn.commit()
                    st.success("Сотрудник сохранен!")
                else:
                    st.error("Сначала создайте рабочие места!")
        st.dataframe(pd.read_sql("SELECT full_name, workplace_id, rep_line FROM employees", conn),
                     use_container_width=True)

    with c3:
        st.subheader("3. Пропорции Тип 3")
        with st.form("add_share", clear_on_submit=True):
            unified_names = pd.read_sql("SELECT DISTINCT unified_name FROM product_dictionary", conn)[
                'unified_name'].tolist()
            s_name = st.selectbox("Препарат", unified_names if unified_names else ["Пусто"])
            s_l2 = st.number_input("Доля Линии 2 (0.0 - 1.0)", value=0.5, step=0.1)
            s_l3 = st.number_input("Доля Линии 3 (0.0 - 1.0)", value=0.5, step=0.1)
            if st.form_submit_button("Сохранить пропорцию"):
                if unified_names:
                    conn.execute(
                        "INSERT OR REPLACE INTO type3_shares (unified_name, share_line2, share_line3) VALUES (?, ?, ?)",
                        (s_name, s_l2, s_l3))
                    conn.commit()
                    st.success("Пропорция сохранена!")
        st.dataframe(pd.read_sql("SELECT * FROM type3_shares", conn), use_container_width=True)

# ==========================================
# ВКЛАДКА 2: РАСПРЕДЕЛЕНИЕ И ОТЧЕТНОСТЬ
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
            rs.sale_date, rs.amount, rs.inn,
            pd.unified_name, pd.product_line,
            ph.pharmacy_type
        FROM raw_sales rs
        JOIN product_dictionary pd ON rs.product_id = pd.id
        JOIN pharmacies ph ON rs.inn = ph.inn
        WHERE rs.distributor_name IN ({dist_placeholders})
        """
        df_raw = pd.read_sql(query, conn, params=tuple(selected_dists))

        if not df_raw.empty:
            df_raw['period'] = pd.to_datetime(df_raw['sale_date']).dt.strftime('%Y-%m')
            df_raw = df_raw[df_raw['period'].isin(selected_periods)]

            if not df_raw.empty:
                df_wps = pd.read_sql("""
                    SELECT pw.inn, pw.workplace_id, e.full_name, e.rep_line 
                    FROM pharmacy_workplaces pw
                    LEFT JOIN employees e ON pw.workplace_id = e.workplace_id
                """, conn)

                pharm_wps_dict = {}
                for inn, group in df_wps.groupby('inn'):
                    pharm_wps_dict[inn] = group.to_dict('records')

                df_shares = pd.read_sql("SELECT * FROM type3_shares", conn)
                shares_dict = df_shares.set_index('unified_name').to_dict('index')

                distributed_data = []

                for _, row in df_raw.iterrows():
                    period = row['period']
                    uname = row['unified_name']
                    pline = row['product_line']
                    amt = row['amount']
                    ptype = row['pharmacy_type']
                    inn = row['inn']

                    wps = pharm_wps_dict.get(inn, [])


                    def add_record(wp_id, name, amount):
                        distributed_data.append([period, uname, pline, wp_id, name, amount])


                    if ptype == 1 or not wps:
                        add_record('Не покрыт', 'Не покрыт', amt)
                        continue

                    if ptype == 2:
                        wp = wps[0]
                        add_record(wp['workplace_id'], wp['full_name'], amt)

                    elif ptype == 3:
                        wp_l2 = next((w for w in wps if w['rep_line'] == 'Линия 2'), None)
                        wp_l3 = next((w for w in wps if w['rep_line'] == 'Линия 3'), None)

                        if pline == 'Линия 2' and wp_l2:
                            add_record(wp_l2['workplace_id'], wp_l2['full_name'], amt)
                        elif pline == 'Линия 3' and wp_l3:
                            add_record(wp_l3['workplace_id'], wp_l3['full_name'], amt)
                        else:
                            sh = shares_dict.get(uname, {'share_line2': 0.5, 'share_line3': 0.5})
                            if wp_l2: add_record(wp_l2['workplace_id'], wp_l2['full_name'],
                                                 amt * sh.get('share_line2', 0.5))
                            if wp_l3: add_record(wp_l3['workplace_id'], wp_l3['full_name'],
                                                 amt * sh.get('share_line3', 0.5))

                    elif ptype == 4:
                        direct_wp = next((w for w in wps if w['rep_line'] == pline), None)
                        if direct_wp:
                            add_record(direct_wp['workplace_id'], direct_wp['full_name'], amt)
                        else:
                            add_record('Не покрыт (Нет линии)', 'Не покрыт', amt)

                df_dist = pd.DataFrame(distributed_data,
                                       columns=['period', 'unified_name', 'product_line', 'workplace_id', 'rep_name',
                                                'distributed_amount'])

                pivot = df_dist.pivot_table(
                    index=['workplace_id', 'rep_name', 'product_line', 'unified_name'],
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
