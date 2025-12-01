import pandas as pd
import gspread
import numpy as np
from google.oauth2.credentials import Credentials
import timeit
import datetime
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from tenacity import retry, stop_after_attempt, wait_fixed

# ===============================
# SET DATE
# ===============================
today = datetime.today() - timedelta(days=1)
today = today.strftime('%Y%m%d')

# ===============================
# READ CSV FILES
# ===============================
# Notes:
# df1 = pd.read_csv(rf'S:\Forecast\Forecast_{today}.csv', sep=';', on_bad_lines='skip', engine='python', encoding='utf-16')
# df2 = pd.read_csv(rf'S:\CatalogueUpdate\CatalogueUpdate_{today}.csv', sep=';', on_bad_lines='skip', engine='python', encoding='latin-1')
# df3 = pd.read_csv(rf'S:\ContainerUpdate\Container{today}.csv', sep=';', on_bad_lines='skip', engine='python', encoding='utf-16')

df1 = pd.read_csv(rf'Forecast_20251130.csv', sep=';', on_bad_lines='skip', engine='python', encoding='utf-16')
df2 = pd.read_csv(rf'CatalogueUpdate_20251130.csv', sep=';', on_bad_lines='skip', engine='python', encoding='latin-1')
df3 = pd.read_csv(rf'Container20251130.csv', sep=';', on_bad_lines='skip', engine='python', encoding='utf-16')

# ===============================
# BUILD DATABASE
# ===============================
df_database = df1[['ItemCode', 'ItemName', 'Kategori', 'SubItemName', 'ItemStatus', 'InventoryUoM', 'IsiCtn', 'LastPurchasePrice', 'PriceFC', 'HargaJualLusin', 'HargaJualKoli', 'HargaJualSpecial']]

# Merge Catalogue Update info
df_database = pd.merge(df_database, df2[['ItemCode', 'U_KonversiBeli']], how='left', on='ItemCode')

# ===============================
# GOOGLE SHEET (IMAGE DATABASE)
# ===============================
SERVICE_ACCOUNT_FILE = r'projectcataloguedashboard.json'
SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)

client = gspread.authorize(credentials)
sheet = client.open_by_key("1-mAmI6-XiWEM5vBlT6TLbeCmqus0ZvvSD_UHvN7zLnM")
worksheet = sheet.sheet1

database = worksheet.get_all_records()
df_foto = pd.DataFrame(database)

df_foto['Upload Date'] = pd.to_datetime(df_foto['Upload Date'])
df_foto = df_foto.groupby(['ItemCode', 'Link'])['Upload Date'].agg(max).reset_index()

df_database = pd.merge(df_database, df_foto[['ItemCode', 'Link']], on='ItemCode', how='left')
df_database.insert(1, 'Link', df_database.pop('Link'))

# Merge more Catalogue Update details
df_database = pd.merge(df_database, df2[['ItemCode', 'Gudang', 'Asemka', 'Tengsek', 'Nami', 'Harga Under']], on='ItemCode', how='left')

df_database.insert(10, 'Harga Under', df_database.pop('Harga Under'))

# Convert types
df_database['PriceFC'] = pd.to_numeric(df_database['PriceFC'], errors='coerce')
df_database['U_KonversiBeli'] = pd.to_numeric(df_database['U_KonversiBeli'], errors='coerce')
df_database['Harga Under'] = pd.to_numeric(df_database['Harga Under'], errors='coerce')

df_database[['Gudang', 'Asemka', 'Tengsek', 'Nami', 'IsiCtn']] = \
    df_database[['Gudang', 'Asemka', 'Tengsek', 'Nami', 'IsiCtn']].apply(pd.to_numeric, errors='coerce')

# Calculations
df_database['RMB per PCS'] = round(df_database['PriceFC'] / df_database['U_KonversiBeli'], 2)
df_database['Harga Pcs'] = df_database['Harga Under'] / df_database['U_KonversiBeli']

df_database = pd.merge(df_database, df1[['ItemCode', 'OnOrder']], on='ItemCode', how='left')
df_database.rename(columns={'PriceFC': 'RMB'}, inplace=True)

today = datetime.today().strftime('%Y%m%d')
df_database['UpdatedDate'] = today

df_database['StockKeseluruhan'] = df_database[['Gudang', 'Asemka', 'Tengsek', 'Nami']].sum(axis=1)
df_database['StockKoli'] = df_database['StockKeseluruhan'] / df_database['IsiCtn']
df_database['FilterKoli'] = df_database['StockKeseluruhan'] >= df_database['IsiCtn']

# Merge transaction info
df_database = pd.merge(
    df_database,
    df1[['ItemCode', 'VendorName', 'Tanggal Last SO', 'Tanggal Last GRPO', 'QtyLastGR', 'Tanggal Due Date GRPO', 'Disc_LastGRPO', 'Price_LastGRPO']],
    on='ItemCode', how='left'
)

df_database['Tanggal Last GRPO'] = pd.to_datetime(df_database['Tanggal Last GRPO'], errors='coerce')
df_database['Tanggal Last SO'] = pd.to_datetime(df_database['Tanggal Last SO'], errors='coerce')

df_database['Tanggal Last SO'] = df_database['Tanggal Last SO'].dt.strftime('%m/%d/%Y')
df_database['Tanggal Last GRPO'] = df_database['Tanggal Last GRPO'].dt.strftime('%m/%d/%Y')

df_database['Tanggal Due Date GRPO'] = pd.to_datetime(df_database['Tanggal Due Date GRPO'], errors='coerce')
df_database['Tanggal Due Date GRPO'] = df_database['Tanggal Due Date GRPO'].dt.strftime('%m/%d/%Y')

df_database.rename(columns={'Tanggal Last GRPO': 'Tanggal Kontainer Datang'}, inplace=True)
df_database.rename(columns={'Tanggal Due Date GRPO': 'Tanggal Last GRPO'}, inplace=True)

df_database.fillna('', inplace=True)
df_database = df_database.drop_duplicates(subset=['ItemCode'])

df_final = df_database[df_database['ItemStatus'] == 'Active']
df_final = df_final.replace([np.nan, np.inf, -np.inf], '')

# ===============================
# BUILD "byContainer" SHEET
# ===============================
df3 = df3.fillna("")
df3['DocDate'] = pd.to_datetime(df3['DocDate'], errors='coerce')
df3['DocDueDate'] = pd.to_datetime(df3['DocDueDate'], errors='coerce')

percontainer = df3.groupby(
    ['ItemCode', 'Quantity', 'Price', 'CardName', 'U_TglLoading', 'U_Container']
).agg({'DocDate': 'min', 'DocDueDate': 'min'}).reset_index()

percontainer = percontainer.sort_values(by='DocDueDate', ascending=False)

percontainer = pd.merge(
    percontainer,
    df_database[['ItemCode', 'VendorName', 'ItemName', 'Link', 'Gudang', 'Asemka', 'Tengsek', 'Nami', 'OnOrder', 'IsiCtn', 'LastPurchasePrice', 'HargaJualLusin', 'InventoryUoM', 'U_KonversiBeli', 'RMB', 'RMB per PCS', 'Tanggal Last SO', 'QtyLastGR', 'Tanggal Last GRPO']],
    on='ItemCode', how='left'
)

percontainer['Selisih Hari'] = (pd.to_datetime('today') - percontainer['DocDueDate']).dt.days

percontainer['DocDate'] = percontainer['DocDate'].dt.strftime('%m/%d/%Y')
percontainer['DocDueDate'] = percontainer['DocDueDate'].dt.strftime('%m/%d/%Y')

percontainer.fillna("", inplace=True)
percontainer = percontainer.replace([float('inf'), float('-inf')], 0)

data = percontainer.values.tolist()
data.insert(0, percontainer.columns.to_list())

# ===============================
# UPDATE GOOGLE SHEETS
# ===============================
@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def update_sheet(spreadsheet_id, range_name, data):
    try:
        service = build('sheets', 'v4', credentials=credentials)

        print(f"Membersihkan data di {spreadsheet_id} - {range_name}...")
        service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()

        print(f"Memperbarui data di {spreadsheet_id} - {range_name}...")
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_name + "!A1",
            valueInputOption='USER_ENTERED',
            body={"values": data}
        ).execute()

        print("Update berhasil!")

    except Exception as e:
        print(f"Terjadi error saat update ke {spreadsheet_id} - {range_name}: {e}")
        raise

SPREADSHEET_ID_1 = "19rbqNUaonJfDDtEWnofU3t4szkvHhNllKzjaETi7qnI"
SPREADSHEET_ID_2 = "1-mAmI6-XiWEM5vBlT6TLbeCmqus0ZvvSD_UHvN7zLnM"

# Update sheets
update_sheet(SPREADSHEET_ID_1, "byContainer", data)

data1 = df_final.values.tolist()
data1.insert(0, df_final.columns.to_list())
update_sheet(SPREADSHEET_ID_1, "Database", data1)

cleandf2 = df2.fillna(" ")
data2 = cleandf2.values.tolist()
data2.insert(0, cleandf2.columns.to_list())
update_sheet(SPREADSHEET_ID_2, "CatalogueUpdate", data2)

print("Proses selesai!")