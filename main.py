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

    # У рабочего места теперь есть своя Линия
    conn.execute('''CREATE TABLE IF NOT EXISTS workplaces (
                        workplace_id TEXT PRIMARY KEY,
                        rep_line TEXT)''')

    conn.execute('''CREATE TABLE IF NOT EXISTS pharmacies (
                        inn TEXT PRIMARY KEY,
                        pharmacy_name TEXT,
                        pharmacy_type INTEGER)''')

    conn.execute('''CREATE TABLE IF NOT EXISTS pharmacy_workplaces (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        inn TEXT,
                        workplace_id TEXT)''')

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
            st.error("Ошибка структуры файла! Проверьте названия колонок.")
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

                    with st.form("add_pharmacy"):
                        st.subheader("Регистрация аптеки")
                        sel_inn = st.selectbox("ИНН новой аптеки:", list(unknown_inns))

                        suggested_name = missing_df[missing_df['inn'] == sel_inn]['customer'].iloc[
                            0] if not missing_df.empty else ""
                        ph_name = st.text_input("Название аптеки:", value=suggested_name)

                        p_type = st.selectbox("Тип аптеки:", [1, 2, 3, 4])
                        workplaces = st.multiselect("Рабочие места:", avail_wps)

                        if st.form_submit_button("Зарегистрировать аптеку"):
                            has_error = False
                            p_type_val = int(p_type)

                            # Проверки теперь не требуют сотрудников, только количество рабочих мест
                            if p_type_val == 1 and len(workplaces) > 0:
                                st.error("ОШИБКА: Аптека Тип 1 не может быть привязана к рабочим местам!")
                                has_error = True
                            elif p_type_val == 2 and len(workplaces) != 1:
                                st.error("ОШИБКА: К аптеке Тип 2 должно быть привязано ровно 1 рабочее место!")
                                has_error = True

                            if not has_error:
                                conn.execute(
                                    "INSERT INTO pharmacies (inn, pharmacy_name, pharmacy_type) VALUES (?, ?, ?)",
                                    (sel_inn, ph_name, p_type_val))
                                for wp in workplaces:
                                    conn.execute("INSERT INTO pharmacy_workplaces (inn, workplace_id) VALUES (?, ?)",
                                                 (sel_inn, wp))
                                conn.commit()
                                st.success(f"Аптека {sel_inn} успешно сохранена!")
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
    col1, col2, col3 = st.columns(3)

    with col1:
        st.subheader("1. Справочник рабочих мест")
        with st.form("add_wp", clear_on_submit=True):
            wp_name = st.text_input("Название/Номер (например, RM-101)")
            wp_line = st.selectbox("Линия рабочего места", LINES)
            if st.form_submit_button("Добавить / Обновить"):
                conn.execute("INSERT OR REPLACE INTO workplaces (workplace_id, rep_line) VALUES (?, ?)",
                             (wp_name.strip(), wp_line))
                conn.commit()
                st.success("Рабочее место сохранено!")
        st.dataframe(pd.read_sql("SELECT * FROM workplaces", conn), use_container_width=True)

    with col2:
        st.subheader("2. Привязка Аптеки к Рабочему месту")
        avail_wps = pd.read_sql("SELECT workplace_id FROM workplaces", conn)['workplace_id'].tolist()
        pharms_df = pd.read_sql(
            "SELECT inn, IFNULL(pharmacy_name, 'Без названия') as name, pharmacy_type FROM pharmacies", conn)
        pharm_options = [f"{row['inn']} | {row['name']} (Тип {row['pharmacy_type']})" for _, row in
                         pharms_df.iterrows()]

        with st.form("bind_pharmacy", clear_on_submit=True):
            sel_pharm = st.selectbox("Выберите аптеку:",
                                     pharm_options if pharm_options else ["Нет зарегистрированных аптек"])
            sel_wps = st.multiselect("Привязать рабочие места:", avail_wps if avail_wps else [])

            if st.form_submit_button("Обновить привязку"):
                if pharm_options and avail_wps:
                    target_inn = sel_pharm.split(" | ")[0]
                    p_type = int(sel_pharm.split("(Тип ")[1].replace(")", ""))
                    has_error = False

                    if p_type == 1 and len(sel_wps) > 0:
                        st.error("ОШИБКА: Аптека Тип 1 не может быть привязана к рабочим местам!")
                        has_error = True
                    elif p_type == 2 and len(sel_wps) != 1:
                        st.error("ОШИБКА: К аптеке Тип 2 должно быть привязано ровно 1 рабочее место!")
                        has_error = True

                    if not has_error:
                        conn.execute("DELETE FROM pharmacy_workplaces WHERE inn = ?", (target_inn,))
                        for wp in sel_wps:
                            conn.execute("INSERT INTO pharmacy_workplaces (inn, workplace_id) VALUES (?, ?)",
                                         (target_inn, wp))
                        conn.commit()
                        st.success(f"Привязка для аптеки {target_inn} обновлена!")
                        st.rerun()

        st.dataframe(pd.read_sql("""
            SELECT pw.inn, p.pharmacy_name, pw.workplace_id 
            FROM pharmacy_workplaces pw
            JOIN pharmacies p ON pw.inn = p.inn
        """, conn), use_container_width=True)

    with col3:
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
    total_sales_count = conn.execute("SELECT COUNT(*) FROM raw_sales").fetchone()[0]

    if total_sales_count == 0:
        st.warning("⚠️ В базе продаж пока нет ни одной записи. Загрузите Excel-файл во вкладке 'Загрузка данных'.")
    else:
        all_dists = [row[0] for row in conn.execute("SELECT DISTINCT distributor_name FROM raw_sales").fetchall()]
        df_dates = pd.read_sql("SELECT sale_date FROM raw_sales", conn)
        all_periods = sorted(pd.to_datetime(df_dates['sale_date']).dt.strftime('%Y-%m').unique().tolist(), reverse=True)

        all_wps = [row[0] for row in conn.execute("SELECT workplace_id FROM workplaces").fetchall()] + ['Не покрыт',
                                                                                                        'Без линии']

        col1, col2, col3 = st.columns(3)
        with col1:
            selected_dists = st.multiselect("Фильтр по дистрибьюторам:", all_dists, default=all_dists)
        with col2:
            selected_periods = st.multiselect("Фильтр по месяцам:", all_periods, default=all_periods)
        with col3:
            selected_wps = st.multiselect("Фильтр по рабочим местам:", all_wps, default=all_wps)

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
                    # Присоединяем рабочие места напрямую к их линии
                    df_wps = pd.read_sql("""
                        SELECT pw.inn, pw.workplace_id, w.rep_line 
                        FROM pharmacy_workplaces pw
                        JOIN workplaces w ON pw.workplace_id = w.workplace_id
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


                        # Функция добавления больше не требует Имя сотрудника
                        def add_record(wp_id, amount):
                            distributed_data.append([period, uname, pline, wp_id, amount])


                        if ptype == 1 or not wps:
                            add_record('Не покрыт', amt)
                            continue

                        if ptype == 2:
                            direct_wp = next((w for w in wps if w['rep_line'] == pline), None)
                            if direct_wp:
                                add_record(direct_wp['workplace_id'], amt)
                            else:
                                add_record('Без линии', amt)

                        elif ptype == 3:
                            reps_l2 = [w for w in wps if w['rep_line'] == 'Линия 2']
                            reps_l3 = [w for w in wps if w['rep_line'] == 'Линия 3']

                            if pline == 'Линия 2' and reps_l2:
                                split_amt = amt / len(reps_l2)
                                for rep in reps_l2:
                                    add_record(rep['workplace_id'], split_amt)
                            elif pline == 'Линия 3' and reps_l3:
                                split_amt = amt / len(reps_l3)
                                for rep in reps_l3:
                                    add_record(rep['workplace_id'], split_amt)
                            elif pline == 'Линия 1':
                                add_record('Без линии', amt)
                            else:
                                sh = shares_dict.get(uname, {'share_line2': 0.5, 'share_line3': 0.5})
                                if reps_l2:
                                    split_l2 = (amt * sh.get('share_line2', 0.5)) / len(reps_l2)
                                    for rep in reps_l2:
                                        add_record(rep['workplace_id'], split_l2)
                                if reps_l3:
                                    split_l3 = (amt * sh.get('share_line3', 0.5)) / len(reps_l3)
                                    for rep in reps_l3:
                                        add_record(rep['workplace_id'], split_l3)

                        elif ptype == 4:
                            direct_wp = next((w for w in wps if w['rep_line'] == pline), None)
                            if direct_wp:
                                add_record(direct_wp['workplace_id'], amt)
                            else:
                                add_record('Без линии', amt)

                    df_dist = pd.DataFrame(distributed_data,
                                           columns=['period', 'unified_name', 'product_line', 'workplace_id',
                                                    'distributed_amount'])

                    df_dist = df_dist[df_dist['workplace_id'].isin(selected_wps)]

                    if not df_dist.empty:
                        pivot = df_dist.pivot_table(
                            index=['workplace_id', 'unified_name'],
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
                        st.warning("Нет продаж, соответствующих выбранным рабочим местам.")
                else:
                    st.warning("Нет продаж за выбранные периоды.")
            else:
                st.warning("Нет данных по выбранным дистрибьюторам.")