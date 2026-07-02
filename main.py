import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime

# Настройка БД
conn = sqlite3.connect('sales_data.db', check_same_thread=False)


def get_known_products():
    df = pd.read_sql("SELECT original_name FROM product_dictionary", conn)
    return set(df['original_name'].tolist())


# Список дистрибьюторов (можно дополнять)
DISTRIBUTORS = ["Grand", "Optima", "MegaPharm", "GlobalMed"]

st.title("Загрузка данных продаж")

# 1. Выпадающий список дистрибьютора
distributor = st.selectbox("Выберите дистрибьютора:", DISTRIBUTORS)
uploaded_file = st.file_uploader("Выберите Excel-файл", type="xlsx")

if uploaded_file and distributor:
    df = pd.read_excel(uploaded_file)

    if 'Наименование' not in df.columns:
        st.error("Ошибка: в файле нет колонки 'Наименование'!")
    else:
        file_products = set(df['Наименование'].dropna().unique())
        known_products = get_known_products()
        unknown_products = file_products - known_products

        if unknown_products:
            st.warning(f"Найдено новых препаратов: {len(unknown_products)}")
            # Форма добавления нового препарата прямо здесь
            with st.form("add_product_form"):
                selected_new = st.selectbox("Препарат из файла:", list(unknown_products))
                unified_name = st.text_input("Унифицированное название:")
                submit_new = st.form_submit_button("Добавить в справочник")

                if submit_new and unified_name:
                    conn.execute("INSERT INTO product_dictionary VALUES (?, ?)", (selected_new, unified_name))
                    conn.commit()
                    st.success(f"Препарат {selected_new} добавлен! Обновите страницу для продолжения.")
                    st.rerun()
        else:
            if st.button("Загрузить все данные в базу"):
                df['distributor_name'] = distributor
                df['load_date'] = datetime.now()
                df.to_sql('raw_sales', conn, if_exists='append', index=False)
                st.success(f"Файл для {distributor} успешно загружен!")