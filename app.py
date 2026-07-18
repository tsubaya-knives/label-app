#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ラベルPDF作成ツール (Streamlit)

商品マスター(Google Sheets)から商品を選び、ラベルPDFを作ってGoogle Driveに保存する。
1つのSKUにつき1ファイル、1シート(44面)すべて同じラベルを印刷する。
"""
import hmac
import io
import re
import unicodedata

import streamlit as st
import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from label_gen import build_label_pdf, SHEET

# ==================================================================
# 設定
# ==================================================================
SPREADSHEET_ID = "1qS6mU5pnVN40KdF-6LcSve5axrrzEwvx2pJKn0jBC30"
DRIVE_FOLDER_ID = "1Se_ML_NoAKZgTBRxPpmAyAtZzFBEE9G4"
SHEET_NAME = "商品マスター"
MASTER_SHEET_NAME = "SKUコードマスター"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.file",
]

PER_SHEET = SHEET["cols"] * SHEET["rows"]   # 44

st.set_page_config(page_title="ラベル作成", page_icon="🏷️", layout="wide")

# 検索エンジンにインデックスさせない
st.markdown(
    '<meta name="robots" content="noindex, nofollow, noarchive">',
    unsafe_allow_html=True)


# ==================================================================
# パスワード認証
#   Streamlit Cloud の無料プランにはアクセス制限が無いため、
#   URLを知られた場合に備えて簡易的な認証をかける。
# ==================================================================
def check_password():
    """認証済みなら True。未認証ならログイン画面を出して False。"""
    if st.session_state.get("authed"):
        return True

    st.title("🏷️ ラベル作成")
    st.caption("社内用ツールです。パスワードを入力してください。")

    with st.form("login"):
        pw = st.text_input("パスワード", type="password")
        ok = st.form_submit_button("ログイン")

    if ok:
        correct = st.secrets.get("app", {}).get("password", "")
        if not correct:
            st.error("パスワードが設定されていません。管理者にご連絡ください。")
            return False
        if hmac.compare_digest(pw, correct):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("パスワードが違います。")
    return False


if not check_password():
    st.stop()


# ==================================================================
# Google API
# ==================================================================
@st.cache_resource
def get_services():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES)
    return (build("sheets", "v4", credentials=creds),
            build("drive", "v3", credentials=creds))


@st.cache_data(ttl=300)
def load_products():
    """商品マスターを読む。SKUと商品名が入っている行だけを対象にする。"""
    sheets, _ = get_services()
    res = sheets.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A2:AA5000").execute()
    values = res.get("values", [])
    if not values:
        return pd.DataFrame()

    header = values[0]
    rows = []
    for r in values[1:]:
        r = r + [""] * (len(header) - len(r))
        rows.append(r[:len(header)])
    df = pd.DataFrame(rows, columns=header)

    need = ["SKU", "商品名"]
    for c in need:
        if c not in df.columns:
            st.error(f"商品マスターに「{c}」列が見つかりません。")
            st.stop()

    df = df[(df["SKU"].str.strip() != "") & (df["商品名"].str.strip() != "")]
    df = df[~df["SKU"].str.contains(r"\?", na=False)]   # エラー行は除く
    return df.reset_index(drop=True)


def upload_pdf(pdf_bytes, filename):
    """Driveへ保存する。同名ファイルがあれば上書きする(最新が正のため)。"""
    _, drive = get_services()
    q = (f"name = '{filename}' and '{DRIVE_FOLDER_ID}' in parents "
         f"and trashed = false")
    found = drive.files().list(q=q, fields="files(id)",
                               supportsAllDrives=True,
                               includeItemsFromAllDrives=True).execute()
    media = MediaIoBaseUpload(io.BytesIO(pdf_bytes),
                              mimetype="application/pdf", resumable=False)
    files = found.get("files", [])
    if files:
        f = drive.files().update(fileId=files[0]["id"], media_body=media,
                                 fields="id, webViewLink",
                                 supportsAllDrives=True).execute()
        return f, True
    f = drive.files().create(
        body={"name": filename, "parents": [DRIVE_FOLDER_ID]},
        media_body=media, fields="id, webViewLink",
        supportsAllDrives=True).execute()
    return f, False


# ==================================================================
# ファイル名
#   [Brand](Supplier)[鋼材][意匠][構造] _ [種類][寸法] _ [和洋][柄材][形状] _ [補足]
# ==================================================================
STEEL_DISPLAY = {
    "白二": "白二鋼", "青二": "青二鋼", "白一": "白一鋼", "青一": "青一鋼",
    "青スーパー": "青紙スーパー", "MV鋼": "モリブデンバナジウム鋼",
    "銀三": "銀三鋼", "ハイス鋼": "粉末ハイス鋼", "コバルト": "コバルト鋼",
    "S440C": "モリブデン鋼", "非公開": "",
}
# 構造は慣習に合わせて出し分ける。
#   合わせ(霞)・三枚打(軟鉄)は和包丁として当たり前のため書かない。
#   ステン割込はハガネのときだけ書く(ステン包丁では言わない慣習)。
FN_STRUCTURE = {"積層(ダマ)": "積層", "全鋼": "全鋼"}
FN_STRUCTURE_IF_CARBON = {"ステン割込": "ステンレス割込"}

NONE = "該当なし"


def _clean(s):
    return re.sub(r"\(.*?\)", "", str(s)).strip()


def build_filename(v):
    b1 = ""
    if v.get("Brand", "") not in ("", NONE):
        b1 += _clean(v["Brand"])
    if v.get("Supplier", "") not in ("", NONE):
        b1 += f"({_clean(v['Supplier'])})"
    steel = v.get("Steel", "")
    if steel not in ("", NONE):
        b1 += STEEL_DISPLAY.get(steel, steel)
    if v.get("Design", "") not in ("", NONE):
        b1 += _clean(v["Design"])
    st_ = v.get("Structure", "")
    if st_ in FN_STRUCTURE:
        b1 += FN_STRUCTURE[st_]
    elif st_ in FN_STRUCTURE_IF_CARBON and v.get("Metal Type") == "ハガネ":
        b1 += FN_STRUCTURE_IF_CARBON[st_]

    cat = v.get("Category", "")
    b2 = (_clean(cat) if cat not in ("", NONE) else "") + str(v.get("Blade Size", ""))

    b3 = ""
    for a in ("Handle Type", "Handle Material", "Handle Shape"):
        if v.get(a, "") not in ("", NONE):
            b3 += _clean(v[a])

    name = "_".join([p for p in (b1, b2, b3) if p])
    if v.get("Supplement", "") not in ("", NONE):
        name += f"_{_clean(v['Supplement'])}"

    name = unicodedata.normalize("NFC", name)
    for ch in '/\\:*?"<>|':
        name = name.replace(ch, "")
    return (name or "label") + ".pdf"


# ==================================================================
# 画面
# ==================================================================
st.title("🏷️ ラベル作成")
st.caption("商品を選ぶと、1商品につき1ファイルのラベルPDFを作ります。"
           f"1枚のシート({PER_SHEET}面)すべてが同じラベルになります。")

try:
    df = load_products()
except Exception as e:
    st.error("商品マスターを読み込めませんでした。")
    st.exception(e)
    st.stop()

if df.empty:
    st.warning("商品マスターにデータがありません。")
    st.stop()

# --- 絞り込み ---
st.subheader("絞り込み")

c1, c2, c3, c4, c5 = st.columns(5)
filters = {}
for col, (label, key) in zip(
        (c1, c2, c3, c4, c5),
        [("仕入先", "Supplier"), ("鋼材", "Steel"), ("種類", "Category"),
         ("和洋", "Handle Type"), ("柄の素材", "Handle Material")]):
    if key in df.columns:
        opts = sorted([x for x in df[key].unique() if x and x != NONE])
        with col:
            filters[key] = st.multiselect(label, opts, key=f"f_{key}")

kw = st.text_input("検索", placeholder="商品名・SKUの一部を入力（例: 三徳、紫檀）")

view = df.copy()
for key, sel in filters.items():
    if sel:
        view = view[view[key].isin(sel)]
if kw:
    k = kw.strip()
    view = view[view["商品名"].str.contains(k, case=False, na=False)
                | view["SKU"].str.contains(k, case=False, na=False)]

st.divider()

# --- 一覧 ---
st.subheader(f"商品を選ぶ　（{len(view)} 件）")

if view.empty:
    st.info("条件に合う商品がありません。絞り込みを見直してください。")
    st.stop()

show_cols = ["商品名", "バリエーション", "Supplier", "SKU"]
show_cols = [c for c in show_cols if c in view.columns]

disp = view[show_cols].copy()
disp.insert(0, "選択", False)
disp = disp.rename(columns={"Supplier": "仕入先", "バリエーション": "刃渡り"})

edited = st.data_editor(
    disp,
    hide_index=True,
    use_container_width=True,
    height=420,
    column_config={
        "選択": st.column_config.CheckboxColumn(required=True, width="small"),
        "商品名": st.column_config.TextColumn(disabled=True, width="large"),
        "刃渡り": st.column_config.TextColumn(disabled=True, width="small"),
        "仕入先": st.column_config.TextColumn(disabled=True, width="small"),
        "SKU": st.column_config.TextColumn(disabled=True, width="medium"),
    },
    key="editor",
)

picked_idx = edited.index[edited["選択"]].tolist()
picked = view.loc[picked_idx]

st.divider()

n = len(picked)
if n == 0:
    st.info("商品にチェックを入れてください。")
else:
    st.success(f"{n} 商品を選択中　→　PDF {n} ファイル"
               f"（各ファイル {PER_SHEET} 面 = シート1枚分）")

if st.button("PDFを作成", type="primary", disabled=(n == 0),
             use_container_width=True):
    prog = st.progress(0.0, text="作成しています...")
    results, errors = [], []

    for i, (_, row) in enumerate(picked.iterrows(), 1):
        try:
            v = row.to_dict()
            fname = build_filename(v)
            item = {"sku": v["SKU"].strip(), "name": v["商品名"].strip()}
            pdf = build_label_pdf([item] * PER_SHEET)
            f, updated = upload_pdf(pdf, fname)
            results.append((fname, f.get("webViewLink", ""), updated))
        except Exception as e:
            errors.append((row.get("商品名", "?"), str(e)))
        prog.progress(i / n, text=f"作成しています... {i}/{n}")

    prog.empty()

    if results:
        st.success(f"{len(results)} ファイルを保存しました。")
        for fname, link, updated in results:
            tag = "（上書き）" if updated else ""
            st.markdown(f"- [{fname}]({link}) {tag}")
        st.markdown(
            f"[📁 保存先フォルダを開く]"
            f"(https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID})")
    if errors:
        st.error(f"{len(errors)} 件でエラーが起きました。")
        for name, msg in errors:
            st.write(f"- {name}: {msg}")

with st.sidebar:
    st.header("使い方")
    st.markdown(f"""
1. 絞り込みや検索で商品を探す
2. 一覧の「選択」にチェックを入れる（複数可）
3. **［PDFを作成］**を押す
4. 表示されたリンクからPDFを開いて印刷する

**印刷のときは**
- 倍率は **100%（等倍）**
- 「用紙サイズに合わせる」は **オフ**
- 手差しトレイ・厚紙モード
- 同じラベルが何枚も必要なときは、印刷画面で **部数** を増やす

**ラベル**
- エーワン 28388（A4 {PER_SHEET}面 / 48.3 × 25.4mm）
- 1ファイル = シート1枚分（{PER_SHEET}面すべて同じ商品）
- 余ったシートは保管して次回に使えます

**保存先**
- 同じ名前のファイルがあるときは上書きします
（作り直した最新のものが正しいため）
    """)
    if st.button("最新のデータを読み込む"):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    if st.button("ログアウト"):
        st.session_state["authed"] = False
        st.rerun()
