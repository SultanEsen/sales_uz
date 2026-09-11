import streamlit as st
import pandas as pd
import sqlite3
import io
from datetime import datetime

# ==========================================
# 0. НАСТРОЙКИ ДОСТУПА (ЗАДАЙТЕ ЛОГИНЫ И ПАРОЛИ)
# ==========================================
# Формат: "Логин": "Пароль"
USERS = {
    "admin": "12345",
    "manager": "qwerty"
}

# Базовые настройки страницы должны идти первыми
st.set_page_config(layout="wide", page_title="Аналитика продаж")
st.markdown(
    """<style>[data-testid="stToolbar"] {visibility: hidden !important;} header {visibility: hidden !important;}</style>""",
    unsafe_allow_html=True)

# Инициализация состояния авторизации
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

# ==========================================
# ЭКРАН ВХОДА (Если не авторизован)
# ==========================================
if not st.session_state.authenticated:
    # Делаем форму входа по центру
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.title("🔐 Авторизация")
        with st.form("login_form"):
            username = st.text_input("Логин")
            password = st.text_input("Пароль", type="password")
            if st.form_submit_button("Войти"):
                if username in USERS and USERS[username] == password:
                    st.session_state.authenticated = True
                    st.session_state.user = username
                    st.rerun()
                else:
                    st.error("Неверный логин или пароль!")

# ==========================================
# ОСНОВНОЕ ПРИЛОЖЕНИЕ (Если авторизован)
# ==========================================
else:
    # Шапка с заголовком и кнопкой выхода в правом верхнем углу
    col_title, col_logout = st.columns([5, 1])
    with col_title:
        st.title("Система управления продажами")
    with col_logout:
        st.write(f"👤 Пользователь: **{st.session_state.user}**")
        if st.button("🚪 Выйти из системы", use_container_width=True):
            st.session_state.authenticated = False
            st.rerun()

    # --- 1. БАЗА ДАННЫХ ---
    conn = sqlite3.connect('sales_data.db', check_same_thread=False)


    def init_db():
        conn.execute('''CREATE TABLE IF NOT EXISTS product_dictionary (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            original_name TEXT UNIQUE,
                            unified_name TEXT,
                            product_line TEXT)''')

        conn.execute('''CREATE TABLE IF NOT EXISTS district_dictionary (
                            original_name TEXT PRIMARY KEY,
                            unified_name TEXT)''')

        conn.execute('''CREATE TABLE IF NOT EXISTS raw_sales (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            product_id INTEGER, manufacturer TEXT, customer TEXT, 
                            number TEXT, sale_date DATE, period TEXT, amount REAL, 
                            source TEXT, inn TEXT, region TEXT, district TEXT, address TEXT, 
                            distributor_name TEXT, load_date TIMESTAMP)''')

        conn.execute('''CREATE TABLE IF NOT EXISTS workplaces (
                            workplace_id TEXT PRIMARY KEY,
                            rep_line TEXT)''')

        conn.execute('''CREATE TABLE IF NOT EXISTS pharmacies (
                            inn TEXT PRIMARY KEY,
                            pharmacy_name TEXT)''')

        conn.execute('''CREATE TABLE IF NOT EXISTS monthly_pharmacy_type (
                            inn TEXT, period TEXT, pharmacy_type INTEGER,
                            PRIMARY KEY (inn, period))''')

        conn.execute('''CREATE TABLE IF NOT EXISTS monthly_pharmacy_workplaces (
                            inn TEXT, period TEXT, workplace_id TEXT)''')

        conn.execute('''CREATE TABLE IF NOT EXISTS type3_shares (
                            unified_name TEXT PRIMARY KEY, share_line2 REAL, share_line3 REAL)''')
        conn.commit()


    init_db()

    LINES = ["Линия 1", "Линия 2", "Линия 3", "Другая"]

    tab1, tab2, tab3, tab4 = st.tabs(["Загрузка данных", "Отчетность", "Базовые настройки", "Привязки по месяцам"])

    # === ВКЛАДКА 1: ЗАГРУЗКА И РЕГИСТРАЦИЯ ===
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
                df['period'] = pd.to_datetime(df['sale_date']).dt.strftime('%Y-%m')
                file_periods = df['period'].unique().tolist()

                prod_dict = pd.read_sql("SELECT original_name FROM product_dictionary", conn)['original_name'].tolist()
                unknown_prods = set(df['product_name'].dropna().unique()) - set(prod_dict)

                dist_dict = pd.read_sql("SELECT original_name FROM district_dictionary", conn)['original_name'].tolist()
                unknown_dists = set(df['district'].dropna().unique()) - set(dist_dict)

                known_inns = pd.read_sql("SELECT inn FROM pharmacies", conn)['inn'].tolist()
                unknown_inns = set(df['inn'].dropna().unique()) - set(known_inns)

                if unknown_prods:
                    st.warning(f"Найдено {len(unknown_prods)} новых препаратов.")
                    with st.form("add_prod", clear_on_submit=True):
                        selected = st.selectbox("Препарат:", list(unknown_prods))
                        unified = st.text_input("Унифицированное название:")
                        prod_line = st.selectbox("Линия препарата:", LINES)
                        if st.form_submit_button("Добавить"):
                            conn.execute(
                                "INSERT INTO product_dictionary (original_name, unified_name, product_line) VALUES (?, ?, ?)",
                                (selected, unified, prod_line))
                            conn.commit()
                            st.rerun()

                elif unknown_dists:
                    st.warning(f"Найдено {len(unknown_dists)} новых городов/районов.")
                    with st.form("add_dist", clear_on_submit=True):
                        selected_dist = st.selectbox("Город/Район из файла:", list(unknown_dists))
                        unified_dist = st.text_input("Унифицированное название района:")
                        if st.form_submit_button("Добавить в справочник"):
                            conn.execute("INSERT INTO district_dictionary (original_name, unified_name) VALUES (?, ?)",
                                         (selected_dist, unified_dist))
                            conn.commit()
                            st.rerun()

                elif unknown_inns:
                    st.error(f"БЛОКИРОВКА: Найдено {len(unknown_inns)} новых аптек.")
                    missing_df = df[df['inn'].isin(unknown_inns)][['inn', 'customer', 'address']].drop_duplicates('inn')
                    st.dataframe(missing_df.head(5), use_container_width=True)

                    avail_wps = pd.read_sql("SELECT workplace_id FROM workplaces", conn)['workplace_id'].tolist()

                    with st.form("add_pharmacy"):
                        st.write(f"Регистрация (Привязка сработает на месяцы из файла: {', '.join(file_periods)})")
                        sel_inn = st.selectbox("ИНН новой аптеки:", list(unknown_inns))
                        ph_name = st.text_input("Название аптеки:",
                                                value=missing_df[missing_df['inn'] == sel_inn]['customer'].iloc[
                                                    0] if not missing_df.empty else "")
                        p_type = st.selectbox("Тип аптеки:", [1, 2, 3, 4])
                        workplaces = st.multiselect("Рабочие места:", avail_wps)

                        if st.form_submit_button("Зарегистрировать аптеку"):
                            p_type_val = int(p_type)
                            has_error = False

                            if p_type_val == 1 and len(workplaces) > 0:
                                st.error("Аптека Тип 1 не может быть привязана к рабочему месту!")
                                has_error = True
                            elif p_type_val == 2:
                                if len(workplaces) != 1:
                                    st.error("Аптека Тип 2 обязана иметь ровно 1 привязанное рабочее место!")
                                    has_error = True
                                else:
                                    wp_line = conn.execute("SELECT rep_line FROM workplaces WHERE workplace_id = ?",
                                                           (workplaces[0],)).fetchone()[0]
                                    if wp_line != 'Линия 1':
                                        st.error(
                                            f"Ошибка: Аптека Тип 2 привязывается только к РМ из 'Линия 1' (выбрано: {wp_line})!")
                                        has_error = True

                            if not has_error:
                                conn.execute("INSERT INTO pharmacies (inn, pharmacy_name) VALUES (?, ?)",
                                             (sel_inn, ph_name))
                                for p in file_periods:
                                    conn.execute(
                                        "INSERT INTO monthly_pharmacy_type (inn, period, pharmacy_type) VALUES (?, ?, ?)",
                                        (sel_inn, p, p_type_val))
                                    for wp in workplaces:
                                        conn.execute(
                                            "INSERT INTO monthly_pharmacy_workplaces (inn, period, workplace_id) VALUES (?, ?, ?)",
                                            (sel_inn, p, wp))
                                conn.commit()
                                st.success("Успешно!")
                                st.rerun()
                else:
                    st.success("Проверки пройдены!")
                    if st.button("Загрузить данные"):
                        df_to_db = df[required + ['period']].copy()
                        prod_map = dict(
                            zip(pd.read_sql("SELECT original_name, id FROM product_dictionary", conn).values[:, 0],
                                pd.read_sql("SELECT original_name, id FROM product_dictionary", conn).values[:, 1]))
                        df_to_db['product_id'] = df_to_db['product_name'].map(prod_map)
                        df_to_db = df_to_db.drop(columns=['product_name'])
                        df_to_db['distributor_name'] = distributor
                        df_to_db['load_date'] = datetime.now()
                        df_to_db.to_sql('raw_sales', conn, if_exists='append', index=False)
                        st.success("Загружено успешно!")

    # === ВКЛАДКА 3: БАЗОВЫЕ НАСТРОЙКИ ===
    with tab3:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Справочник рабочих мест")
            with st.form("add_wp", clear_on_submit=True):
                wp_name = st.text_input("Номер (например, RM-101)")
                wp_line = st.selectbox("Линия рабочего места", LINES)
                if st.form_submit_button("Создать"):
                    conn.execute("INSERT OR REPLACE INTO workplaces (workplace_id, rep_line) VALUES (?, ?)",
                                 (wp_name.strip(), wp_line))
                    conn.commit()
                    st.rerun()
            st.dataframe(pd.read_sql("SELECT * FROM workplaces", conn), use_container_width=True)

        with c2:
            st.subheader("Пропорции Тип 3")
            with st.form("add_share", clear_on_submit=True):
                unified_names = pd.read_sql("SELECT DISTINCT unified_name FROM product_dictionary", conn)[
                    'unified_name'].tolist()
                s_name = st.selectbox("Препарат", unified_names if unified_names else ["Пусто"])
                s_l2 = st.number_input("Доля Линии 2", value=0.5, step=0.1)
                s_l3 = st.number_input("Доля Линии 3", value=0.5, step=0.1)
                if st.form_submit_button("Сохранить"):
                    conn.execute(
                        "INSERT OR REPLACE INTO type3_shares (unified_name, share_line2, share_line3) VALUES (?, ?, ?)",
                        (s_name, s_l2, s_l3))
                    conn.commit()
                    st.rerun()
            st.dataframe(pd.read_sql("SELECT * FROM type3_shares", conn), use_container_width=True)

    # === ВКЛАДКА 4: ПРИВЯЗКИ ПО МЕСЯЦАМ ===
    with tab4:
        st.subheader("Управление территориями по месяцам (Прямая правка)")

        existing_periods = [row[0] for row in
                            conn.execute("SELECT DISTINCT period FROM monthly_pharmacy_type").fetchall()]
        sales_periods = [row[0] for row in conn.execute("SELECT DISTINCT period FROM raw_sales").fetchall()]
        base_dates = pd.date_range(start=datetime.now() - pd.DateOffset(months=12), periods=24, freq='MS').strftime(
            '%Y-%m').tolist()

        all_target_periods = sorted(list(set(existing_periods + sales_periods + base_dates)), reverse=True)
        curr_month = datetime.now().strftime('%Y-%m')
        default_idx = all_target_periods.index(curr_month) if curr_month in all_target_periods else 0

        col_left, col_right = st.columns([1, 2])

        with col_left:
            # Уменьшили высоту до 550, чтобы панель точно влезла на экран любого ноутбука
            with st.container(height=550, border=True):
                target_period = st.selectbox("Выберите период (ГГГГ-ММ):", all_target_periods, index=default_idx)

                st.markdown("**(Опционально) Быстрый старт:**")
                try:
                    prev_period = (pd.to_datetime(target_period + '-01') - pd.DateOffset(months=1)).strftime('%Y-%m')
                    if st.button(f"Скопировать привязки из {prev_period} в {target_period}"):
                        curr_count = conn.execute("SELECT COUNT(*) FROM monthly_pharmacy_type WHERE period=?",
                                                  (target_period,)).fetchone()[0]
                        if curr_count > 0:
                            st.warning("В текущем месяце уже есть данные. Очистите их или редактируйте вручную.")
                        else:
                            conn.execute(
                                "INSERT INTO monthly_pharmacy_type (inn, period, pharmacy_type) SELECT inn, ?, pharmacy_type FROM monthly_pharmacy_type WHERE period=?",
                                (target_period, prev_period))
                            conn.execute(
                                "INSERT INTO monthly_pharmacy_workplaces (inn, period, workplace_id) SELECT inn, ?, workplace_id FROM monthly_pharmacy_workplaces WHERE period=?",
                                (target_period, prev_period))
                            conn.commit()
                            st.success(f"Данные из {prev_period} успешно перенесены!")
                            st.rerun()
                except Exception:
                    st.warning("Ошибка обработки периода.")

                st.write("---")
                st.write(f"**Настроить аптеку на {target_period}**")

                search_query = st.text_input("🔍 Поиск аптеки (введите ИНН или название):",
                                             help="Начните вводить текст для фильтрации списка")
                pharms_df = pd.read_sql("SELECT inn, IFNULL(pharmacy_name, 'Без названия') as name FROM pharmacies",
                                        conn)
                all_pharm_options = [f"{row['inn']} | {row['name']}" for _, row in pharms_df.iterrows()]

                if search_query:
                    pharm_options = [p for p in all_pharm_options if search_query.lower() in p.lower()]
                else:
                    pharm_options = all_pharm_options

                avail_wps = pd.read_sql("SELECT workplace_id FROM workplaces", conn)['workplace_id'].tolist()

                with st.form("edit_monthly_bind", clear_on_submit=True):
                    sel_pharm = st.selectbox("Выберите аптеку:",
                                             pharm_options if pharm_options else ["Ничего не найдено"])
                    p_type = st.selectbox("Тип аптеки:", [1, 2, 3, 4])
                    workplaces = st.multiselect("Рабочие места:", avail_wps)

                    if st.form_submit_button("Сохранить привязку"):
                        if pharm_options and sel_pharm != "Ничего не найдено":
                            inn = sel_pharm.split(" | ")[0]
                            p_type_val = int(p_type)
                            has_error = False

                            if p_type_val == 1 and len(workplaces) > 0:
                                st.error("Ошибка: Аптека Тип 1 не может быть привязана к рабочим местам!")
                                has_error = True
                            elif p_type_val == 2:
                                if len(workplaces) != 1:
                                    st.error("Ошибка: К аптеке Тип 2 должно быть привязано ровно 1 рабочее место!")
                                    has_error = True
                                else:
                                    wp_line = conn.execute("SELECT rep_line FROM workplaces WHERE workplace_id = ?",
                                                           (workplaces[0],)).fetchone()[0]
                                    if wp_line != 'Линия 1':
                                        st.error(
                                            f"Ошибка: Аптека Тип 2 привязывается только к РМ из 'Линия 1' (выбрано: {wp_line})!")
                                        has_error = True

                            if not has_error:
                                conn.execute("DELETE FROM monthly_pharmacy_type WHERE inn = ? AND period = ?",
                                             (inn, target_period))
                                conn.execute("DELETE FROM monthly_pharmacy_workplaces WHERE inn = ? AND period = ?",
                                             (inn, target_period))

                                conn.execute(
                                    "INSERT INTO monthly_pharmacy_type (inn, period, pharmacy_type) VALUES (?, ?, ?)",
                                    (inn, target_period, p_type_val))
                                for wp in workplaces:
                                    conn.execute(
                                        "INSERT INTO monthly_pharmacy_workplaces (inn, period, workplace_id) VALUES (?, ?, ?)",
                                        (inn, target_period, wp))
                                conn.commit()
                                st.success("Привязка для аптеки обновлена!")
                                st.rerun()

        with col_right:
            # ПРАВАЯ ЧАСТЬ: помещаем таблицу в точно такой же жесткий контейнер высотой 550.
            with st.container(height=550, border=True):
                st.write(f"**Текущая матрица за {target_period}:**")
                df_matrix = pd.read_sql(f"""
                    SELECT t.inn as 'ИНН', p.pharmacy_name as 'Название', t.pharmacy_type as 'Тип', IFNULL(GROUP_CONCAT(w.workplace_id, ', '), 'Не покрыт') as 'Рабочие места'
                    FROM monthly_pharmacy_type t
                    LEFT JOIN pharmacies p ON t.inn = p.inn
                    LEFT JOIN monthly_pharmacy_workplaces w ON t.inn = w.inn AND t.period = w.period
                    WHERE t.period = '{target_period}'
                    GROUP BY t.inn
                """, conn)

                # ВАЖНО: Мы убрали параметр height отсюда. Теперь прокруткой управляет st.container
                st.dataframe(df_matrix, use_container_width=True, hide_index=True)
    # with tab4:
    #     st.subheader("Управление территориями по месяцам (Прямая правка)")
    #
    #     existing_periods = [row[0] for row in
    #                         conn.execute("SELECT DISTINCT period FROM monthly_pharmacy_type").fetchall()]
    #     sales_periods = [row[0] for row in conn.execute("SELECT DISTINCT period FROM raw_sales").fetchall()]
    #     base_dates = pd.date_range(start=datetime.now() - pd.DateOffset(months=12), periods=24, freq='MS').strftime(
    #         '%Y-%m').tolist()
    #
    #     all_target_periods = sorted(list(set(existing_periods + sales_periods + base_dates)), reverse=True)
    #     curr_month = datetime.now().strftime('%Y-%m')
    #     default_idx = all_target_periods.index(curr_month) if curr_month in all_target_periods else 0
    #
    #     col_left, col_right = st.columns([1, 2])
    #
    #     with col_left:
    #         with st.container(height=650, border=False):
    #             target_period = st.selectbox("Выберите период (ГГГГ-ММ):", all_target_periods, index=default_idx)
    #
    #             st.markdown("**(Опционально) Быстрый старт:**")
    #             try:
    #                 prev_period = (pd.to_datetime(target_period + '-01') - pd.DateOffset(months=1)).strftime('%Y-%m')
    #                 if st.button(f"Скопировать привязки из {prev_period} в {target_period}"):
    #                     curr_count = conn.execute("SELECT COUNT(*) FROM monthly_pharmacy_type WHERE period=?",
    #                                               (target_period,)).fetchone()[0]
    #                     if curr_count > 0:
    #                         st.warning("В текущем месяце уже есть данные. Очистите их или редактируйте вручную.")
    #                     else:
    #                         conn.execute(
    #                             "INSERT INTO monthly_pharmacy_type (inn, period, pharmacy_type) SELECT inn, ?, pharmacy_type FROM monthly_pharmacy_type WHERE period=?",
    #                             (target_period, prev_period))
    #                         conn.execute(
    #                             "INSERT INTO monthly_pharmacy_workplaces (inn, period, workplace_id) SELECT inn, ?, workplace_id FROM monthly_pharmacy_workplaces WHERE period=?",
    #                             (target_period, prev_period))
    #                         conn.commit()
    #                         st.success(f"Данные из {prev_period} успешно перенесены!")
    #                         st.rerun()
    #             except Exception:
    #                 st.warning("Ошибка обработки периода.")
    #
    #             st.write("---")
    #             st.write(f"**Настроить аптеку на {target_period}**")
    #
    #             search_query = st.text_input("🔍 Поиск аптеки (введите ИНН или название):",
    #                                          help="Начните вводить текст для фильтрации списка")
    #             pharms_df = pd.read_sql("SELECT inn, IFNULL(pharmacy_name, 'Без названия') as name FROM pharmacies",
    #                                     conn)
    #             all_pharm_options = [f"{row['inn']} | {row['name']}" for _, row in pharms_df.iterrows()]
    #
    #             if search_query:
    #                 pharm_options = [p for p in all_pharm_options if search_query.lower() in p.lower()]
    #             else:
    #                 pharm_options = all_pharm_options
    #
    #             avail_wps = pd.read_sql("SELECT workplace_id FROM workplaces", conn)['workplace_id'].tolist()
    #
    #             with st.form("edit_monthly_bind", clear_on_submit=True):
    #                 sel_pharm = st.selectbox("Выберите аптеку:",
    #                                          pharm_options if pharm_options else ["Ничего не найдено"])
    #                 p_type = st.selectbox("Тип аптеки:", [1, 2, 3, 4])
    #                 workplaces = st.multiselect("Рабочие места:", avail_wps)
    #
    #                 if st.form_submit_button("Сохранить привязку"):
    #                     if pharm_options and sel_pharm != "Ничего не найдено":
    #                         inn = sel_pharm.split(" | ")[0]
    #                         p_type_val = int(p_type)
    #                         has_error = False
    #
    #                         if p_type_val == 1 and len(workplaces) > 0:
    #                             st.error("Ошибка: Аптека Тип 1 не может быть привязана к рабочим местам!")
    #                             has_error = True
    #                         elif p_type_val == 2:
    #                             if len(workplaces) != 1:
    #                                 st.error("Ошибка: К аптеке Тип 2 должно быть привязано ровно 1 рабочее место!")
    #                                 has_error = True
    #                             else:
    #                                 wp_line = conn.execute("SELECT rep_line FROM workplaces WHERE workplace_id = ?",
    #                                                        (workplaces[0],)).fetchone()[0]
    #                                 if wp_line != 'Линия 1':
    #                                     st.error(
    #                                         f"Ошибка: Аптека Тип 2 привязывается только к РМ из 'Линия 1' (выбрано: {wp_line})!")
    #                                     has_error = True
    #
    #                         if not has_error:
    #                             conn.execute("DELETE FROM monthly_pharmacy_type WHERE inn = ? AND period = ?",
    #                                          (inn, target_period))
    #                             conn.execute("DELETE FROM monthly_pharmacy_workplaces WHERE inn = ? AND period = ?",
    #                                          (inn, target_period))
    #
    #                             conn.execute(
    #                                 "INSERT INTO monthly_pharmacy_type (inn, period, pharmacy_type) VALUES (?, ?, ?)",
    #                                 (inn, target_period, p_type_val))
    #                             for wp in workplaces:
    #                                 conn.execute(
    #                                     "INSERT INTO monthly_pharmacy_workplaces (inn, period, workplace_id) VALUES (?, ?, ?)",
    #                                     (inn, target_period, wp))
    #                             conn.commit()
    #                             st.success("Привязка для аптеки обновлена!")
    #                             st.rerun()
    #
    #     with col_right:
    #         st.write(f"**Текущая матрица за {target_period}:**")
    #         df_matrix = pd.read_sql(f"""
    #             SELECT t.inn as 'ИНН', p.pharmacy_name as 'Название', t.pharmacy_type as 'Тип', IFNULL(GROUP_CONCAT(w.workplace_id, ', '), 'Не покрыт') as 'Рабочие места'
    #             FROM monthly_pharmacy_type t
    #             LEFT JOIN pharmacies p ON t.inn = p.inn
    #             LEFT JOIN monthly_pharmacy_workplaces w ON t.inn = w.inn AND t.period = w.period
    #             WHERE t.period = '{target_period}'
    #             GROUP BY t.inn
    #         """, conn)
    #         st.dataframe(df_matrix, use_container_width=True, hide_index=True, height=650)


    # === ВКЛАДКА 2: РАСПРЕДЕЛЕНИЕ И ОТЧЕТНОСТЬ ===
    with tab2:
        if conn.execute("SELECT COUNT(*) FROM raw_sales").fetchone()[0] == 0:
            st.warning("В базе продаж пока нет данных.")
        else:
            df_dates = pd.read_sql("SELECT period FROM raw_sales", conn)
            all_periods = sorted(df_dates['period'].unique().tolist(), reverse=True)
            all_wps = [row[0] for row in conn.execute("SELECT workplace_id FROM workplaces").fetchall()] + ['Не покрыт',
                                                                                                            'Без линии',
                                                                                                            'empty WP']

            c1, c2 = st.columns(2)
            selected_periods = c1.multiselect("Фильтр по месяцам:", all_periods, default=all_periods)
            selected_wps = c2.multiselect("Фильтр по рабочим местам:", all_wps, default=all_wps)

            if selected_periods:
                p_placeholders = ', '.join(['?'] * len(selected_periods))
                query = f"""
                SELECT 
                    rs.period, rs.amount, rs.inn,
                    dd.unified_name as district,
                    pd.unified_name as product, pd.product_line,
                    IFNULL(mpt.pharmacy_type, 1) as ptype,
                    IFNULL(ph.pharmacy_name, 'Без названия') as pharm_name
                FROM raw_sales rs
                LEFT JOIN product_dictionary pd ON rs.product_id = pd.id
                LEFT JOIN district_dictionary dd ON rs.district = dd.original_name
                LEFT JOIN monthly_pharmacy_type mpt ON rs.inn = mpt.inn AND rs.period = mpt.period
                LEFT JOIN pharmacies ph ON rs.inn = ph.inn
                WHERE rs.period IN ({p_placeholders})
                """
                df_raw = pd.read_sql(query, conn, params=tuple(selected_periods))

                if not df_raw.empty:
                    df_wps = pd.read_sql(f"""
                        SELECT mpw.inn, mpw.period, mpw.workplace_id, w.rep_line 
                        FROM monthly_pharmacy_workplaces mpw
                        JOIN workplaces w ON mpw.workplace_id = w.workplace_id
                        WHERE mpw.period IN ({p_placeholders})
                    """, conn, params=tuple(selected_periods))

                    pharm_wps_dict = {}
                    for (inn, period), group in df_wps.groupby(['inn', 'period']):
                        pharm_wps_dict[(inn, period)] = group.to_dict('records')

                    shares_dict = pd.read_sql("SELECT * FROM type3_shares", conn).set_index('unified_name').to_dict(
                        'index')
                    dist_data = []

                    for _, row in df_raw.iterrows():
                        period, amt, inn = row['period'], row['amount'], row['inn']
                        dist, prod, pline, ptype = row['district'], row['product'], row['product_line'], row['ptype']
                        ph_name = row['pharm_name']

                        wps = pharm_wps_dict.get((inn, period), [])


                        def add_row(wp, force_line=pline):
                            dist_data.append([period, dist, inn, ph_name, prod, force_line, wp, amt])


                        def split_row(wp, fraction, force_line=pline):
                            dist_data.append([period, dist, inn, ph_name, prod, force_line, wp, amt * fraction])


                        if ptype == 1 or not wps:
                            add_row('Не покрыт')
                            continue

                        if ptype == 2:
                            if wps:
                                add_row(wps[0]['workplace_id'], force_line='Линия 1')
                            else:
                                add_row('Без линии', force_line='Линия 1')

                        elif ptype == 3:
                            r_l2 = [w for w in wps if w['rep_line'] == 'Линия 2']
                            r_l3 = [w for w in wps if w['rep_line'] == 'Линия 3']

                            if pline == 'Линия 2':
                                if r_l2:
                                    for w in r_l2: split_row(w['workplace_id'], 1 / len(r_l2))
                                else:
                                    add_row('empty WP')

                            elif pline == 'Линия 3':
                                if r_l3:
                                    for w in r_l3: split_row(w['workplace_id'], 1 / len(r_l3))
                                else:
                                    add_row('empty WP')

                            elif pline == 'Линия 1':
                                add_row('Без линии')

                            else:
                                sh = shares_dict.get(prod, {'share_line2': 0.5, 'share_line3': 0.5})
                                if r_l2:
                                    for w in r_l2: split_row(w['workplace_id'], sh.get('share_line2', 0.5) / len(r_l2))
                                else:
                                    split_row('empty WP', sh.get('share_line2', 0.5))

                                if r_l3:
                                    for w in r_l3: split_row(w['workplace_id'], sh.get('share_line3', 0.5) / len(r_l3))
                                else:
                                    split_row('empty WP', sh.get('share_line3', 0.5))

                        elif ptype == 4:
                            direct_wp = next((w for w in wps if w['rep_line'] == pline), None)
                            add_row(direct_wp['workplace_id'] if direct_wp else 'Без линии')

                    df_flat = pd.DataFrame(dist_data, columns=['Период', 'Город/Район', 'ИНН Аптеки', 'Название Аптеки',
                                                               'Препарат', 'Линия', 'Рабочее место', 'Сумма'])
                    df_flat = df_flat[df_flat['Рабочее место'].isin(selected_wps)]

                    st.dataframe(df_flat, use_container_width=True)

                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine='xlsxwriter') as w:
                        df_flat.to_excel(w, index=False, sheet_name='Отчет')
                    st.download_button("📥 Скачать плоский отчет (Excel)", buf.getvalue(), "Flat_Sales_Report.xlsx")
