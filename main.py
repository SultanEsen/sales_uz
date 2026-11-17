import streamlit as st
import pandas as pd
import sqlite3
import io
import hashlib
import secrets
from datetime import datetime

# ==========================================
# 0. НАСТРОЙКИ СТРАНИЦЫ И ФУНКЦИИ
# ==========================================
st.set_page_config(layout="wide", page_title="Аналитика продаж")
st.markdown(
    """<style>[data-testid="stToolbar"] {visibility: hidden !important;} header {visibility: hidden !important;}</style>""",
    unsafe_allow_html=True)


# Функция безопасного шифрования паролей
def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


# ==========================================
# 1. ПОДКЛЮЧЕНИЕ К БД И ИНИЦИАЛИЗАЦИЯ
# ==========================================
conn = sqlite3.connect('sales_data.db', check_same_thread=False)


def init_db():
    conn.execute('''CREATE TABLE IF NOT EXISTS pharmacies (inn TEXT PRIMARY KEY, pharmacy_name TEXT)''')

    # ДОБАВЛЕНО: Безопасное добавление колонки с районом для старых баз
    try:
        conn.execute("ALTER TABLE pharmacies ADD COLUMN district TEXT")
    except sqlite3.OperationalError:
        pass  # Колонка уже существует

    conn.execute(
        '''CREATE TABLE IF NOT EXISTS product_dictionary (id INTEGER PRIMARY KEY AUTOINCREMENT, original_name TEXT, unified_name TEXT, product_line TEXT)''')
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS district_dictionary (original_name TEXT PRIMARY KEY, unified_name TEXT)''')
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS raw_sales (id INTEGER PRIMARY KEY AUTOINCREMENT, period TEXT, distributor_name TEXT, inn TEXT, customer TEXT, address TEXT, district TEXT, region TEXT, product_id INTEGER, amount REAL, source TEXT, load_date TIMESTAMP)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS workplaces (workplace_id TEXT PRIMARY KEY, rep_line TEXT)''')
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS monthly_pharmacy_type (inn TEXT, period TEXT, pharmacy_type INTEGER, PRIMARY KEY (inn, period))''')
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS monthly_pharmacy_workplaces (inn TEXT, period TEXT, workplace_id TEXT, PRIMARY KEY (inn, period, workplace_id))''')

    conn.execute('''CREATE TABLE IF NOT EXISTS distributors (name TEXT PRIMARY KEY)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS sys_settings (key TEXT PRIMARY KEY, value TEXT)''')
    is_init = conn.execute("SELECT COUNT(*) FROM sys_settings WHERE key='first_run'").fetchone()[0]

    if is_init == 0:
        for d in ["Grand", "Optima", "MegaPharm"]:
            conn.execute("INSERT OR IGNORE INTO distributors (name) VALUES (?)", (d,))
        conn.execute("INSERT INTO sys_settings (key, value) VALUES ('first_run', 'done')")

    conn.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password_hash TEXT, token TEXT)''')
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.execute("INSERT INTO users (username, password_hash, token) VALUES (?, ?, ?)",
                     ("admin", hash_password("12345"), secrets.token_hex(16)))

    conn.commit()

init_db()

LINES = ["Линия 1", "Линия 2", "Линия 3", "Другая"]

# ==========================================
# 2. СИСТЕМА АВТОРИЗАЦИИ
# ==========================================
if "token" in st.query_params:
    url_token = st.query_params["token"]
    user_row = conn.execute("SELECT username FROM users WHERE token=?", (url_token,)).fetchone()
    if user_row:
        st.session_state.authenticated = True
        st.session_state.user = user_row[0]

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.title("🔐 Авторизация")
        with st.form("login_form"):
            username = st.text_input("Логин")
            password = st.text_input("Пароль", type="password")
            if st.form_submit_button("Войти"):
                # Ищем пользователя и сверяем зашифрованный пароль
                user_data = conn.execute("SELECT password_hash, token FROM users WHERE username=?",
                                         (username,)).fetchone()
                if user_data and user_data[0] == hash_password(password):
                    st.session_state.authenticated = True
                    st.session_state.user = username
                    st.query_params["token"] = user_data[1]
                    st.rerun()
                else:
                    st.error("Неверный логин или пароль!")

# ==========================================
# 3. ОСНОВНОЕ ПРИЛОЖЕНИЕ
# ==========================================
else:
    col_title, col_logout = st.columns([5, 1])
    with col_title:
        st.title("Система управления продажами_V1.0")
    with col_logout:
        st.write(f"👤 Пользователь: **{st.session_state.user}**")
        if st.button("🚪 Выйти", use_container_width=True):
            st.session_state.authenticated = False
            st.query_params.clear()
            st.rerun()

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["Загрузка данных", "Отчетность", "Базовые настройки", "Привязки по месяцам", "Дашборд"])

    # === ВКЛАДКА 1: ЗАГРУЗКА И РЕГИСТРАЦИЯ ===
    with tab1:
        distributors_list = [row[0] for row in conn.execute("SELECT name FROM distributors ORDER BY name").fetchall()]

        # ДОБАВЛЕНО: Заглушка, чтобы заставить пользователя сделать осознанный выбор
        dist_options = ["➖ Выберите дистрибьютора ➖"] + distributors_list if distributors_list else [
            "Нет дистрибьюторов"]
        distributor = st.selectbox("Дистрибьютор:", dist_options)

        uploaded_file = st.file_uploader("Выберите Excel-файл продаж", type="xlsx")

        if uploaded_file:
            # ДОБАВЛЕНО: Блокировка загрузки, если дистрибьютор не выбран
            if distributor in ["➖ Выберите дистрибьютора ➖", "Нет дистрибьюторов"]:
                st.warning(
                    "⚠️ Пожалуйста, сначала выберите дистрибьютора из списка выше, чтобы система знала, к кому привязать продажи.")
            else:
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
                    df['inn'] = df['inn'].fillna('').astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

                    empty_mask = df['product_name'].isna() | df['sale_date'].isna() | df['amount'].isna() | (
                                df['inn'] == '')

                    if empty_mask.any():
                        empty_rows = (df.index[empty_mask] + 2).tolist()
                        rows_str = ", ".join(map(str, empty_rows[:10])) + (
                            f" ... и еще {len(empty_rows) - 10}" if len(empty_rows) > 10 else "")

                        st.error("❌ **Критическая ошибка: Найдены пустые ячейки**")
                        st.error(
                            f"В колонках 'Препарат', 'Дата', 'Кол-во' или 'ИНН' отсутствуют данные. Проверьте строки в Excel: **{rows_str}**")
                        st.warning("Загрузка остановлена. Заполните пустые ячейки и загрузите файл заново.")

                    else:
                        invalid_mask = ~df['inn'].str.fullmatch(r'^\d{9}$')

                        if invalid_mask.any():
                            invalid_rows = (df.index[invalid_mask] + 2).tolist()
                            rows_str = ", ".join(map(str, invalid_rows[:10])) + (
                                f" ... и еще {len(invalid_rows) - 10}" if len(invalid_rows) > 10 else "")
                            st.error("❌ **Критическая ошибка файла: некорректный ИНН**")
                            st.error(f"ИНН должен состоять ровно из 9 цифр. Проверьте строки в Excel: **{rows_str}**")

                        else:
                            df['period'] = pd.to_datetime(df['sale_date']).dt.strftime('%Y-%m')
                            file_periods = df['period'].unique().tolist()

                            prod_dict = pd.read_sql("SELECT original_name FROM product_dictionary", conn)[
                                'original_name'].tolist()
                            unknown_prods = set(df['product_name'].dropna().unique()) - set(prod_dict)

                            dist_dict = pd.read_sql("SELECT original_name FROM district_dictionary", conn)[
                                'original_name'].tolist()
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
                                existing_unified_dists = pd.read_sql(
                                    "SELECT DISTINCT unified_name FROM district_dictionary WHERE unified_name IS NOT NULL",
                                    conn)['unified_name'].tolist()
                                dist_options = ["➕ Создать новый..."] + sorted(existing_unified_dists)

                                with st.form("add_dist", clear_on_submit=True):
                                    selected_dist = st.selectbox("Город/Район из файла:", list(unknown_dists))
                                    chosen_unified = st.selectbox("Выберите существующий район:", dist_options)
                                    new_unified = st.text_input(
                                        "Или введите новое название (если выбрали 'Создать новый...'):")

                                    if st.form_submit_button("Добавить в справочник"):
                                        final_unified = new_unified.strip() if chosen_unified == "➕ Создать новый..." else chosen_unified
                                        if not final_unified:
                                            st.error("Ошибка: Выберите район из списка или введите новое название!")
                                        else:
                                            conn.execute(
                                                "INSERT INTO district_dictionary (original_name, unified_name) VALUES (?, ?)",
                                                (selected_dist, final_unified))
                                            conn.commit()
                                            st.rerun()

                            elif unknown_inns:
                                st.error(f"БЛОКИРОВКА: Найдено {len(unknown_inns)} новых аптек.")
                                missing_df = df[df['inn'].isin(unknown_inns)][
                                    ['inn', 'customer', 'address', 'district']].drop_duplicates('inn')
                                st.dataframe(missing_df.head(5), use_container_width=True)

                                avail_wps = pd.read_sql("SELECT workplace_id FROM workplaces", conn)[
                                    'workplace_id'].tolist()
                                valid_dists = pd.read_sql(
                                    "SELECT DISTINCT unified_name FROM district_dictionary WHERE unified_name IS NOT NULL",
                                    conn)['unified_name'].dropna().unique().tolist()
                                valid_dists = sorted(valid_dists)

                                with st.form("add_pharmacy"):
                                    st.write(
                                        f"Регистрация (Привязка сработает на месяцы из файла: {', '.join(file_periods)})")
                                    sel_inn = st.selectbox("ИНН новой аптеки:", list(unknown_inns))

                                    row_data = missing_df[missing_df['inn'] == sel_inn].iloc[
                                        0] if not missing_df.empty else None
                                    def_name = row_data['customer'] if row_data is not None else ""
                                    raw_dist = row_data['district'] if row_data is not None else ""

                                    def_unified_dist = conn.execute(
                                        "SELECT unified_name FROM district_dictionary WHERE original_name=?",
                                        (raw_dist,)).fetchone()
                                    def_unified_dist = def_unified_dist[0] if def_unified_dist else ""
                                    dist_idx = valid_dists.index(
                                        def_unified_dist) if def_unified_dist in valid_dists else 0

                                    ph_name = st.text_input("Название аптеки:", value=def_name)
                                    ph_district = st.selectbox("Район аптеки:",
                                                               valid_dists if valid_dists else ["Нет районов"],
                                                               index=dist_idx if valid_dists else 0)
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
                                                st.error(
                                                    "Аптека Тип 2 обязана иметь ровно 1 привязанное рабочее место!")
                                                has_error = True
                                            else:
                                                wp_line = \
                                                conn.execute("SELECT rep_line FROM workplaces WHERE workplace_id = ?",
                                                             (workplaces[0],)).fetchone()[0]
                                                if wp_line != 'Линия 1':
                                                    st.error(
                                                        f"Ошибка: Аптека Тип 2 привязывается только к РМ из 'Линия 1' (выбрано: {wp_line})!")
                                                    has_error = True

                                        if not has_error:
                                            conn.execute(
                                                "INSERT INTO pharmacies (inn, pharmacy_name, district) VALUES (?, ?, ?)",
                                                (sel_inn, ph_name, ph_district))
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
                                overlaps = []
                                for p in file_periods:
                                    count = \
                                    conn.execute("SELECT COUNT(*) FROM raw_sales WHERE distributor_name=? AND period=?",
                                                 (distributor, p)).fetchone()[0]
                                    if count > 0:
                                        overlaps.append(p)

                                if overlaps:
                                    st.warning("⚠️ **Внимание: Данные уже существуют!**")
                                    st.write(
                                        f"В базе уже есть загруженные продажи от **{distributor}** за периоды: **{', '.join(overlaps)}**.")
                                    st.info(
                                        "Если вы нажмете кнопку ниже, старые продажи этого дистрибьютора за эти месяцы будут удалены, а новые записаны.")

                                    if st.button("🔄 Перезаписать данные", type="primary", use_container_width=True):
                                        for p in overlaps:
                                            conn.execute("DELETE FROM raw_sales WHERE distributor_name=? AND period=?",
                                                         (distributor, p))
                                        conn.commit()

                                        df_to_db = df[required + ['period']].copy()
                                        prod_map = dict(
                                            zip(pd.read_sql("SELECT original_name, id FROM product_dictionary",
                                                            conn).values[:, 0],
                                                pd.read_sql("SELECT original_name, id FROM product_dictionary",
                                                            conn).values[:, 1]))
                                        df_to_db['product_id'] = df_to_db['product_name'].map(prod_map)
                                        df_to_db = df_to_db.drop(columns=['product_name'])
                                        df_to_db['distributor_name'] = distributor
                                        df_to_db['load_date'] = datetime.now()
                                        df_to_db.to_sql('raw_sales', conn, if_exists='append', index=False)

                                        st.success("Старые данные удалены, новые успешно загружены!")
                                        st.rerun()
                                else:
                                    st.success("Проверки пройдены! Дубликатов не найдено.")
                                    if st.button("📥 Загрузить новые данные", use_container_width=True):
                                        df_to_db = df[required + ['period']].copy()
                                        prod_map = dict(
                                            zip(pd.read_sql("SELECT original_name, id FROM product_dictionary",
                                                            conn).values[:, 0],
                                                pd.read_sql("SELECT original_name, id FROM product_dictionary",
                                                            conn).values[:, 1]))
                                        df_to_db['product_id'] = df_to_db['product_name'].map(prod_map)
                                        df_to_db = df_to_db.drop(columns=['product_name'])
                                        df_to_db['distributor_name'] = distributor
                                        df_to_db['load_date'] = datetime.now()
                                        df_to_db.to_sql('raw_sales', conn, if_exists='append', index=False)

                                        st.success("Загружено успешно!")
                                        st.rerun()
    # === ВКЛАДКА 2: РАСПРЕДЕЛЕНИЕ И ОТЧЕТНОСТЬ ===
    with tab2:
        if conn.execute("SELECT COUNT(*) FROM raw_sales").fetchone()[0] == 0:
            st.warning("В базе продаж пока нет данных.")
        else:
            df_dates = pd.read_sql("SELECT period FROM raw_sales", conn)
            all_periods = sorted(df_dates['period'].unique().tolist(), reverse=True)
            all_wps = [row[0] for row in
                       conn.execute("SELECT workplace_id FROM workplaces").fetchall()] + ['Не покрыт',
                                                                                          'Без линии',
                                                                                          'empty WP']

            # ДОБАВЛЕНО: Выгружаем список дистрибьюторов, по которым есть продажи
            all_dists_tab2 = sorted([row[0] for row in conn.execute(
                "SELECT DISTINCT distributor_name FROM raw_sales WHERE distributor_name IS NOT NULL").fetchall()])

            # ДОБАВЛЕНО: Разбиваем фильтры на 3 колонки
            c1, c2, c3 = st.columns(3)
            selected_periods = c1.multiselect("Фильтр по месяцам:", all_periods, default=all_periods)
            selected_dists_tab2 = c2.multiselect("Фильтр по дистрибьюторам:", all_dists_tab2,
                                                 default=all_dists_tab2)
            selected_wps = c3.multiselect("Фильтр по рабочим местам:", all_wps, default=all_wps)

            # Проверяем, что выбраны и месяцы, и дистрибьюторы
            if selected_periods and selected_dists_tab2:
                p_placeholders = ', '.join(['?'] * len(selected_periods))
                d_placeholders = ', '.join(['?'] * len(selected_dists_tab2))

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
                  AND rs.distributor_name IN ({d_placeholders}) 
                """
                # Передаем параметры обоих фильтров в запрос
                params = tuple(selected_periods) + tuple(selected_dists_tab2)
                df_raw = pd.read_sql(query, conn, params=params)

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

        # --- Справочник препаратов ---
        st.write("---")
        st.subheader("💊 Справочник препаратов")

        prod_df = pd.read_sql(
            "SELECT original_name as 'Оригинальное название (из Excel)', unified_name as 'Единое название (в отчетах)', product_line as 'Линия' FROM product_dictionary",
            conn)

        col_p1, col_p2 = st.columns([1, 2])

        with col_p1:
            st.write("**Редактирование препарата**")
            if not prod_df.empty:
                sel_prod = st.selectbox("Выберите препарат для исправления:",
                                        prod_df['Оригинальное название (из Excel)'].tolist())

                current_unified = prod_df.loc[
                    prod_df['Оригинальное название (из Excel)'] == sel_prod, 'Единое название (в отчетах)'].values[
                    0]
                current_line = prod_df.loc[prod_df['Оригинальное название (из Excel)'] == sel_prod, 'Линия'].values[
                    0]

                with st.form("edit_product_form"):
                    new_unified = st.text_input("Унифицированное название:", value=current_unified)
                    line_idx = LINES.index(current_line) if current_line in LINES else 0
                    new_line = st.selectbox("Линия препарата:", LINES, index=line_idx)

                    if st.form_submit_button("💾 Сохранить изменения"):
                        if new_unified.strip():
                            conn.execute(
                                "UPDATE product_dictionary SET unified_name = ?, product_line = ? WHERE original_name = ?",
                                (new_unified.strip(), new_line, sel_prod))
                            if current_unified != new_unified.strip():
                                conn.execute("UPDATE type3_shares SET unified_name = ? WHERE unified_name = ?",
                                             (new_unified.strip(), current_unified))
                            conn.commit()
                            st.success("Изменения сохранены!")
                            st.rerun()
                        else:
                            st.warning("Название не может быть пустым.")
            else:
                st.info("Справочник пока пуст.")

        with col_p2:
            st.dataframe(prod_df, use_container_width=True, hide_index=True, height=250)

        # --- ДОБАВЛЕНО: Справочник городов/районов ---
        st.write("---")
        st.subheader("🗺️ Справочник городов/районов")

        dist_df = pd.read_sql(
            "SELECT original_name as 'Оригинальное название (из Excel)', unified_name as 'Единое название (в отчетах)' FROM district_dictionary",
            conn)

        col_d1, col_d2 = st.columns([1, 2])

        with col_d1:
            st.write("**Редактирование района**")
            if not dist_df.empty:
                sel_dist = st.selectbox("Выберите район для исправления:",
                                        dist_df['Оригинальное название (из Excel)'].tolist())

                current_dist_unified = dist_df.loc[
                    dist_df['Оригинальное название (из Excel)'] == sel_dist, 'Единое название (в отчетах)'].values[
                    0]

                with st.form("edit_district_form"):
                    new_dist_unified = st.text_input("Унифицированное название:", value=current_dist_unified)

                    if st.form_submit_button("💾 Сохранить изменения"):
                        if new_dist_unified.strip():
                            conn.execute("UPDATE district_dictionary SET unified_name = ? WHERE original_name = ?",
                                         (new_dist_unified.strip(), sel_dist))
                            conn.commit()
                            st.success("Изменения сохранены!")
                            st.rerun()
                        else:
                            st.warning("Название не может быть пустым.")
            else:
                st.info("Справочник пока пуст.")

        with col_d2:
            st.dataframe(dist_df, use_container_width=True, hide_index=True, height=250)

        # --- Управление дистрибьюторами ---
        st.write("---")
        st.subheader("🏢 Управление дистрибьюторами")

        curr_dists = [row[0] for row in conn.execute("SELECT name FROM distributors ORDER BY name").fetchall()]
        st.write(f"**Текущие дистрибьюторы:** {', '.join(curr_dists) if curr_dists else 'Нет данных'}")

        col_dist1, col_dist2 = st.columns(2)
        with col_dist1:
            with st.form("add_distributor_form", clear_on_submit=True):
                new_dist = st.text_input("Добавить нового дистрибьютора:")
                if st.form_submit_button("➕ Добавить"):
                    if new_dist.strip():
                        try:
                            conn.execute("INSERT INTO distributors (name) VALUES (?)", (new_dist.strip(),))
                            conn.commit()
                            st.success(f"Дистрибьютор '{new_dist}' добавлен!")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("Ошибка: Такой дистрибьютор уже существует.")
                    else:
                        st.warning("Введите название дистрибьютора.")

        with col_dist2:
            with st.form("del_distributor_form"):
                del_dist = st.selectbox("Удалить дистрибьютора:",
                                        curr_dists if curr_dists else ["Нет дистрибьюторов"])
                if st.form_submit_button("🗑️ Удалить"):
                    if curr_dists:
                        sales_count = conn.execute("SELECT COUNT(*) FROM raw_sales WHERE distributor_name=?",
                                                   (del_dist,)).fetchone()[0]
                        if sales_count > 0:
                            st.error(
                                f"Нельзя удалить '{del_dist}', так как в базе загружено {sales_count} строк продаж от него!")
                        else:
                            conn.execute("DELETE FROM distributors WHERE name=?", (del_dist,))
                            conn.commit()
                            st.success(f"Дистрибьютор '{del_dist}' удален!")
                            st.rerun()

        # --- Управление пользователями (ТОЛЬКО ДЛЯ ADMIN) ---
        if st.session_state.user == "admin":
            st.write("---")
            st.subheader("👥 Управление пользователями (Только для Администратора)")

            curr_users = [row[0] for row in conn.execute("SELECT username FROM users ORDER BY username").fetchall()]
            st.write(f"**Зарегистрированные аккаунты:** {', '.join(curr_users)}")

            col_u1, col_u2 = st.columns(2)
            with col_u1:
                with st.form("add_user_form", clear_on_submit=True):
                    st.write("**Добавить пользователя / Изменить пароль**")
                    new_username = st.text_input("Логин (существующий или новый):")
                    new_password = st.text_input("Пароль:", type="password")
                    if st.form_submit_button("💾 Сохранить"):
                        if new_username.strip() and len(new_password.strip()) >= 5:
                            new_token = secrets.token_hex(16)
                            hashed_pw = hash_password(new_password)
                            conn.execute(
                                "INSERT OR REPLACE INTO users (username, password_hash, token) VALUES (?, ?, ?)",
                                (new_username.strip(), hashed_pw, new_token))
                            conn.commit()
                            st.success(f"Аккаунт '{new_username}' успешно сохранен!")
                            st.rerun()
                        else:
                            st.warning("Введите логин и пароль (минимум 5 символов).")

            with col_u2:
                with st.form("del_user_form"):
                    st.write("**Удалить пользователя**")
                    del_user = st.selectbox("Выберите аккаунт:", curr_users)
                    if st.form_submit_button("🗑️ Удалить"):
                        if len(curr_users) <= 1:
                            st.error(
                                "Запрещено! Нельзя удалить последнего пользователя (система будет заблокирована).")
                        elif del_user == st.session_state.user:
                            st.error("Запрещено! Вы не можете удалить самого себя во время работы.")
                        else:
                            conn.execute("DELETE FROM users WHERE username=?", (del_user,))
                            conn.commit()
                            st.success(f"Аккаунт '{del_user}' удален!")
                            st.rerun()

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
            with st.container(height=450, border=True):
                target_period = st.selectbox("Выберите период (ГГГГ-ММ):", all_target_periods, index=default_idx)

                st.markdown("**Управление матрицей месяца:**")

                try:
                    prev_period = (pd.to_datetime(target_period + '-01') - pd.DateOffset(months=1)).strftime('%Y-%m')
                    if st.button(f"📋 Скопировать привязки из {prev_period}", use_container_width=True):
                        curr_count = conn.execute("SELECT COUNT(*) FROM monthly_pharmacy_type WHERE period=?",
                                                  (target_period,)).fetchone()[0]
                        if curr_count > 0:
                            st.warning("В текущем месяце уже есть данные. Очистите их перед копированием.")
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

                if st.button(f"🗑️ Очистить все привязки за {target_period}", use_container_width=True):
                    curr_count = conn.execute("SELECT COUNT(*) FROM monthly_pharmacy_type WHERE period=?",
                                              (target_period,)).fetchone()[0]
                    if curr_count == 0:
                        st.info("В этом месяце матрица уже пуста.")
                    else:
                        conn.execute("DELETE FROM monthly_pharmacy_type WHERE period=?", (target_period,))
                        conn.execute("DELETE FROM monthly_pharmacy_workplaces WHERE period=?", (target_period,))
                        conn.commit()
                        st.success(f"Матрица за {target_period} полностью очищена!")
                        st.rerun()

                with st.expander("📥 Массовая загрузка из Excel"):
                    st.info(
                        f"Загрузка привязок на **{target_period}**. Вы можете скачать текущую матрицу справа, отредактировать и загрузить сюда. Обязательные колонки: **ИНН**, **Тип**, **Рабочие места** (через запятую).")
                    matrix_file = st.file_uploader("Выберите файл матрицы", type="xlsx", key="matrix_upload")

                    if matrix_file and st.button("Обработать и загрузить", use_container_width=True):
                        df_m = pd.read_excel(matrix_file)
                        req_cols = ['ИНН', 'Тип', 'Рабочие места']

                        if not all(c in df_m.columns for c in req_cols):
                            st.error(f"Ошибка файла! Не найдены колонки: {', '.join(req_cols)}")
                        else:
                            df_m['ИНН'] = df_m['ИНН'].fillna('').astype(str).str.replace(r'\.0$', '',
                                                                                         regex=True).str.strip()
                            df_m = df_m[df_m['ИНН'] != '']

                            known_inns = pd.read_sql("SELECT inn FROM pharmacies", conn)['inn'].tolist()
                            avail_wps = pd.read_sql("SELECT workplace_id FROM workplaces", conn)[
                                'workplace_id'].tolist()

                            errors = []
                            missing_inns = set()
                            success_count = 0

                            for _, row in df_m.iterrows():
                                inn = row['ИНН']
                                p_type = row['Тип']
                                wps_raw = str(row['Рабочие места']) if pd.notna(row['Рабочие места']) and str(
                                    row['Рабочие места']).strip() != 'Не покрыт' else ""

                                if inn not in known_inns:
                                    missing_inns.add(inn)
                                    continue

                                try:
                                    p_type_val = int(float(p_type))
                                    if p_type_val not in [1, 2, 3, 4]: raise ValueError
                                except:
                                    errors.append(f"ИНН {inn}: Неверный тип аптеки ({p_type}).")
                                    continue

                                wps = [w.strip() for w in wps_raw.split(',')] if wps_raw.strip() else []
                                wps = [w for w in wps if w]

                                invalid_wps = [w for w in wps if w not in avail_wps]
                                if invalid_wps:
                                    errors.append(f"ИНН {inn}: Неизвестные рабочие места ({', '.join(invalid_wps)}).")
                                    continue

                                if p_type_val == 1 and len(wps) > 0:
                                    errors.append(f"ИНН {inn}: Аптека Тип 1 не может иметь рабочих мест.")
                                    continue
                                if p_type_val == 2:
                                    if len(wps) != 1:
                                        errors.append(f"ИНН {inn}: Аптека Тип 2 должна иметь ровно 1 рабочее место.")
                                        continue
                                    else:
                                        wp_line = conn.execute("SELECT rep_line FROM workplaces WHERE workplace_id = ?",
                                                               (wps[0],)).fetchone()[0]
                                        if wp_line != 'Линия 1':
                                            errors.append(f"ИНН {inn}: Рабочее место Типа 2 должно быть из 'Линия 1'.")
                                            continue

                                conn.execute("DELETE FROM monthly_pharmacy_type WHERE inn = ? AND period = ?",
                                             (inn, target_period))
                                conn.execute("DELETE FROM monthly_pharmacy_workplaces WHERE inn = ? AND period = ?",
                                             (inn, target_period))

                                conn.execute(
                                    "INSERT INTO monthly_pharmacy_type (inn, period, pharmacy_type) VALUES (?, ?, ?)",
                                    (inn, target_period, p_type_val))
                                for wp in wps:
                                    conn.execute(
                                        "INSERT INTO monthly_pharmacy_workplaces (inn, period, workplace_id) VALUES (?, ?, ?)",
                                        (inn, target_period, wp))

                                success_count += 1

                            conn.commit()

                            if success_count > 0:
                                st.success(f"✅ Успешно обновлено аптек: {success_count}")

                            if missing_inns:
                                st.error(f"⚠️ Внимание: {len(missing_inns)} ИНН не найдены в базе. Они пропущены.")
                                df_missing = pd.DataFrame({"Незарегистрированные ИНН": list(missing_inns)})
                                st.dataframe(df_missing, use_container_width=True, hide_index=True)

                            if errors:
                                st.warning(f"⚠️ Прочие ошибки валидации: {len(errors)} (строки пропущены)")
                                with st.expander("Посмотреть список ошибок"):
                                    for e in errors:
                                        st.write(e)

                            if success_count > 0:
                                if missing_inns or errors:
                                    if st.button("🔄 Обновить матрицу на экране"):
                                        st.rerun()
                                else:
                                    st.rerun()

                st.write("---")
                st.write(f"**Настроить аптеку на {target_period} (Вручную)**")

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
            st.write(f"**Текущая матрица за {target_period}:**")
            matrix_search = st.text_input("🔎 Фильтр матрицы (введите ИНН или Название для быстрого поиска):")

            df_matrix = pd.read_sql(f"""
                SELECT t.inn as 'ИНН', p.pharmacy_name as 'Название', t.pharmacy_type as 'Тип', IFNULL(GROUP_CONCAT(w.workplace_id, ', '), 'Не покрыт') as 'Рабочие места'
                FROM monthly_pharmacy_type t
                LEFT JOIN pharmacies p ON t.inn = p.inn
                LEFT JOIN monthly_pharmacy_workplaces w ON t.inn = w.inn AND t.period = w.period
                WHERE t.period = '{target_period}'
                GROUP BY t.inn
            """, conn)

            if matrix_search:
                mask = df_matrix['ИНН'].astype(str).str.contains(matrix_search, case=False, na=False) | \
                       df_matrix['Название'].astype(str).str.contains(matrix_search, case=False, na=False)
                df_matrix = df_matrix[mask]

            st.caption(f"Показано аптек: {len(df_matrix)}")
            st.dataframe(df_matrix, use_container_width=True, hide_index=True, height=450)

            if not df_matrix.empty:
                buf_matrix = io.BytesIO()
                with pd.ExcelWriter(buf_matrix, engine='xlsxwriter') as w:
                    df_matrix.to_excel(w, index=False, sheet_name='Матрица')
                st.download_button(
                    label="📥 Скачать текущую матрицу (Excel)",
                    data=buf_matrix.getvalue(),
                    file_name=f"Pharmacy_Matrix_{target_period}.xlsx",
                    use_container_width=True
                )

    # === ВКЛАДКА 5: ДАШБОРД ===
    with tab5:
        st.subheader("📊 Аналитический дашборд")

        if conn.execute("SELECT COUNT(*) FROM raw_sales").fetchone()[0] == 0:
            st.warning("Нет данных для отображения дашборда. Загрузите файлы продаж во Вкладке 1.")
        else:
            df_dash = pd.read_sql("""
                SELECT 
                    rs.period, rs.amount, rs.distributor_name,
                    IFNULL(pd.original_name, 'Неизвестный препарат') as product_name,
                    IFNULL(pd.product_line, 'Без линии') as product_line,
                    IFNULL(ph.pharmacy_name, 'Без названия') as pharmacy_name
                FROM raw_sales rs
                LEFT JOIN product_dictionary pd ON rs.product_id = pd.id
                LEFT JOIN pharmacies ph ON rs.inn = ph.inn
            """, conn)

            all_dash_periods = sorted(df_dash['period'].unique().tolist(), reverse=True)
            default_periods = all_dash_periods[:6] if len(all_dash_periods) > 6 else all_dash_periods

            all_dists = sorted(df_dash['distributor_name'].dropna().unique().tolist())
            all_prods = sorted(df_dash['product_name'].dropna().unique().tolist())

            f1, f2, f3 = st.columns(3)
            with f1:
                selected_dash_periods = st.multiselect("🗓️ Месяцы:", all_dash_periods, default=default_periods)
            with f2:
                selected_dists = st.multiselect("🏢 Дистрибьюторы:", all_dists, default=all_dists)
            with f3:
                selected_products = st.multiselect("💊 Препараты:", all_prods, default=all_prods)

            if selected_dash_periods and selected_dists and selected_products:
                df_filtered = df_dash[
                    (df_dash['period'].isin(selected_dash_periods)) &
                    (df_dash['distributor_name'].isin(selected_dists)) &
                    (df_dash['product_name'].isin(selected_products))
                    ]

                total_sales = df_filtered['amount'].sum()
                total_pharms = df_filtered['pharmacy_name'].nunique()

                m1, m2, m3 = st.columns(3)
                m1.metric("📦 Объем продаж (с учетом фильтров)", f"{total_sales:,.0f}".replace(',', ' '))
                m2.metric("🏥 Активных аптек", total_pharms)
                m3.metric("📅 Выбрано месяцев", len(selected_dash_periods))

                st.write("---")

                c1, c2 = st.columns(2)
                with c1:
                    st.write("**📈 Динамика продаж по месяцам**")
                    if not df_filtered.empty:
                        dyn_df = df_filtered.groupby('period')['amount'].sum().reset_index()

                        # ДОБАВЛЕНО: Плавный график через встроенную библиотеку Altair
                        import altair as alt

                        chart = alt.Chart(dyn_df).mark_line(
                            interpolate='monotone',  # Делает линии плавными (сглаженными)
                            point=True,  # Оставляет точки для точных значений
                            strokeWidth=3  # Делает линию чуть толще и красивее
                        ).encode(
                            x=alt.X('period', title=''),
                            y=alt.Y('amount', title='')
                        )
                        st.altair_chart(chart, use_container_width=True)
                    else:
                        st.info("Нет данных")

                with c2:
                    st.write("**📊 Продажи по линиям препаратов**")
                    if not df_filtered.empty:
                        line_df = df_filtered.groupby('product_line')['amount'].sum().reset_index().set_index(
                            'product_line')
                        st.bar_chart(line_df, use_container_width=True)
                    else:
                        st.info("Нет данных")

                st.write("---")

                c3, c4 = st.columns(2)
                with c3:
                    st.write("**🏆 Топ-10 аптек по объему продаж**")
                    if not df_filtered.empty:
                        top_pharms = df_filtered.groupby('pharmacy_name')['amount'].sum().sort_values(
                            ascending=False).head(10).reset_index().set_index('pharmacy_name')
                        st.bar_chart(top_pharms, use_container_width=True)
                    else:
                        st.info("Нет данных")

                with c4:
                    st.write("**🏅 Топ-10 рабочих мест (с учетом долей)**")
                    periods_str = "','".join(selected_dash_periods)
                    dists_str = "','".join(selected_dists)
                    safe_products = [p.replace("'", "''") for p in selected_products]
                    prods_str = "','".join(safe_products)

                    df_wp = pd.read_sql(f"""
                        SELECT 
                            w.workplace_id as 'Рабочее место',
                            SUM(rs.amount * 1.0 / c.wp_count) as 'Объем продаж'
                        FROM raw_sales rs
                        JOIN monthly_pharmacy_workplaces w 
                            ON rs.inn = w.inn AND rs.period = w.period
                        JOIN (
                            SELECT inn, period, COUNT(workplace_id) as wp_count
                            FROM monthly_pharmacy_workplaces
                            GROUP BY inn, period
                        ) c ON w.inn = c.inn AND w.period = c.period
                        LEFT JOIN product_dictionary pd ON rs.product_id = pd.id
                        WHERE rs.period IN ('{periods_str}')
                          AND rs.distributor_name IN ('{dists_str}')
                          AND IFNULL(pd.original_name, 'Неизвестный препарат') IN ('{prods_str}')
                        GROUP BY w.workplace_id
                        ORDER BY 'Объем продаж' DESC
                        LIMIT 10
                    """, conn)

                    if not df_wp.empty:
                        df_wp = df_wp.set_index('Рабочее место')
                        st.bar_chart(df_wp, use_container_width=True)
                    else:
                        st.info("Нет данных о привязках к рабочим местам по этим критериям.")
