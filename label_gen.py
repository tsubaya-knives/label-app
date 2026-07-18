#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
label_gen.py -- A-one 44面ラベル(48.3x25.4mm / 4列x11段) 用 QRラベルPDF生成

用途:
  1) キャリブレーション: 実シートに枠線を試し刷りしてズレ量を測定
  2) 本番: SKU+商品名のQRラベルを生成

使い方:
  # ステップ1: 位置合わせ用の枠線シートを印刷
  #   ※ ラベルシート付属の「テストプリント用紙」に直接刷るのが早い
  python3 label_gen.py --calibrate -o calib.pdf

  # ステップ2: 測ったズレを補正して本番印刷(右に0.8mm/下に1.2mmズレていた場合)
  python3 label_gen.py -i items.csv -o labels.pdf --offset-x -0.8 --offset-y -1.2

  # 途中のラベルから印刷開始(使いかけシートの再利用)
  python3 label_gen.py -i items.csv -o labels.pdf --start 5

印刷設定(必須):
  - 倍率 100% / 等倍 (「用紙サイズに合わせる」は必ずOFF)
  - 手差しトレイ + 厚紙モード
"""
import argparse
import csv
import sys

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# ==================================================================
# シート定義: エーワン 28388 (A4 44面 48.3x25.4mm 4列x11段 四辺余白付・レーザー用/20シート入)
#             ※28368(100シート入)と寸法同一のため共用可
# 寸法根拠: メーカー公式図(Amazon商品画像)より確定
#   横 8.4 + 4x48.3 + 8.4 = 210mm / 縦 8.8 + 11x25.4 + 8.8 = 297mm (ともにピッタリ)
#   → ラベル間の隙間(gap)は縦横とも 0mm
# ※ margin/gap はメーカー公式図で確定済み。残る誤差はプリンター固有の
#   用紙送りズレのみ → --offset-x/y で補正する
# ==================================================================
SHEET = {
    "name": "A-one 28388 (44men 48.3x25.4mm)",
    "cols": 4,
    "rows": 11,
    "label_w": 48.3,
    "label_h": 25.4,
    "margin_left": 8.4,   # 公式値
    "margin_top": 8.8,    # 公式値
    "gap_x": 0.0,         # 公式値(密着面付け)
    "gap_y": 0.0,         # 公式値(密着面付け)
}

# 日本語フォント(環境に合わせて変更可)
FONT_CANDIDATES = [
    ("IPAGothic", "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf"),
    ("NotoJP", "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf"),
]


def register_font():
    for name, path in FONT_CANDIDATES:
        try:
            pdfmetrics.registerFont(TTFont(name, path))
            return name
        except Exception:
            continue
    print("警告: 日本語フォントが見つかりません。Helveticaで代替します。", file=sys.stderr)
    return "Helvetica"


def label_origin(idx, ox, oy):
    """idx(0始まり)のラベル左上座標(mm, 用紙左上原点)を返す"""
    col = idx % SHEET["cols"]
    row = idx // SHEET["cols"]
    x = SHEET["margin_left"] + col * (SHEET["label_w"] + SHEET["gap_x"]) + ox
    y = SHEET["margin_top"] + row * (SHEET["label_h"] + SHEET["gap_y"]) + oy
    return x, y


def qr_image(data):
    """SKU文字列のQRコード画像を生成(誤り訂正レベルM)"""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_Q,
        box_size=10,
        border=0,  # クワイエットゾーンはPDF側の余白で確保
    )
    qr.add_data(data)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def draw_label(c, idx, item, font, ox, oy):
    """1枚分のラベルを描画。用紙左上原点(mm)→reportlab座標に変換

    レイアウト:
      左に QR(15mm角)、右に 商品名(最大3行) + SKU全文(2行)
      商品名は長さに応じて自動で文字を縮める(6.5pt → 5.5pt)
      価格は載せない(変更のたびに貼り替えが必要になるため)
      枠線も引かない(印刷位置がずれたときに目立つため)
    """
    x_mm, y_mm = label_origin(idx, ox, oy)
    lw, lh = SHEET["label_w"], SHEET["label_h"]
    x = x_mm * mm
    y = (A4[1] / mm - y_mm - lh) * mm

    # 印刷位置は手差し給紙で1mm前後ずれる。縁に寄せると切れるため余白を広く取る。
    pad = 2.5          # ラベル内側の余白(mm) 1mmずれても縁まで1.5mm残る
    qr_size = 15.0     # QRの一辺(mm)。SKU39文字で1モジュール0.52mm(スキャナ要件の1.5倍)
    gap = 1.2          # QRとテキストの間隔(mm)

    # --- QRコード(垂直方向は中央寄せ) ---
    img = qr_image(item["sku"])
    qr_y = y + (lh - qr_size) / 2 * mm
    c.drawImage(ImageReader(img), x + pad * mm, qr_y,
                width=qr_size * mm, height=qr_size * mm,
                preserveAspectRatio=True)

    # --- テキスト領域 ---
    tx = x + (pad + qr_size + gap) * mm
    tw = (lw - pad * 2 - qr_size - gap) * mm

    # 商品名: 3行に収まるよう文字サイズを自動調整
    name_size, name_lines = fit_text(item["name"], font, tw,
                                     sizes=(6.5, 6.0, 5.5), max_lines=3)
    name_leading = name_size + 1.2

    # SKU: 全文をハイフンで折り返して表示(照合用)
    sku_size, sku_lines = fit_sku(item["sku"], font, tw)
    sku_leading = sku_size + 0.8

    # 全体を垂直方向の中央に配置する
    total_h = len(name_lines) * name_leading + 1.2 + len(sku_lines) * sku_leading
    ty = y + lh * mm / 2 + total_h / 2 - name_size

    c.setFillColorRGB(0, 0, 0)
    c.setFont(font, name_size)
    for line in name_lines:
        c.drawString(tx, ty, line)
        ty -= name_leading

    ty -= 1.2
    c.setFillColorRGB(0.35, 0.35, 0.35)
    c.setFont(font, sku_size)
    for line in sku_lines:
        c.drawString(tx, ty, line)
        ty -= sku_leading


def fit_sku(sku, font, max_width):
    """SKU全文が入る文字サイズと行を返す。
    ハイフンの位置で折り返し、SKUの区切りが読み取りやすいようにする。
    """
    blocks = sku.split("-")
    for size in (5.5, 5.0, 4.5, 4.0):
        # ブロック単位で詰められるだけ詰める
        lines, cur = [], ""
        for i, b in enumerate(blocks):
            piece = b if i == len(blocks) - 1 else b + "-"
            if not cur:
                cand = piece
            else:
                cand = cur + piece
            if pdfmetrics.stringWidth(cand, font, size) <= max_width:
                cur = cand
            else:
                if cur:
                    lines.append(cur)
                cur = piece
        if cur:
            lines.append(cur)
        if len(lines) <= 2 and all(
                pdfmetrics.stringWidth(l, font, size) <= max_width for l in lines):
            return size, lines
    # ここには通常到達しない
    return 4.0, [sku]


def fit_text(text, font, max_width, sizes=(6.5, 6.0, 5.5), max_lines=3):
    """指定行数に収まる最大の文字サイズを選び、折り返した行を返す。
    どのサイズでも収まらない場合は最小サイズで末尾を省略する。
    """
    for size in sizes:
        lines = wrap_text(text, font, size, max_width, max_lines=max_lines,
                          ellipsis=False)
        if lines is not None:
            return size, lines
    # 全て入りきらなければ最小サイズで省略
    return sizes[-1], wrap_text(text, font, sizes[-1], max_width,
                                max_lines=max_lines, ellipsis=True)


def wrap_text(text, font, size, max_width, max_lines=3, ellipsis=True):
    """指定幅で日本語テキストを折り返す。
    ellipsis=False のとき、max_lines に収まらなければ None を返す。
    """
    lines, cur = [], ""
    for ch in text:
        if pdfmetrics.stringWidth(cur + ch, font, size) <= max_width:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
            if len(lines) >= max_lines:
                if not ellipsis:
                    return None          # 収まらない
                # 末尾を省略記号に置き換える
                last = lines[-1]
                while last and pdfmetrics.stringWidth(last + "…", font, size) > max_width:
                    last = last[:-1]
                lines[-1] = last + "…"
                return lines
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        if not ellipsis:
            return None
        lines = lines[:max_lines]
    return lines


def calibration_page(c, font, ox, oy):
    """位置合わせ用: 全44枠に枠線と十字マーカー、通し番号を描画"""
    per = SHEET["cols"] * SHEET["rows"]
    for i in range(per):
        x_mm, y_mm = label_origin(i, ox, oy)
        lw, lh = SHEET["label_w"], SHEET["label_h"]
        x = x_mm * mm
        y = (A4[1] / mm - y_mm - lh) * mm
        c.setStrokeColorRGB(0, 0, 0)
        c.setLineWidth(0.4)
        c.rect(x, y, lw * mm, lh * mm)
        # 中心十字
        cx, cy = x + lw * mm / 2, y + lh * mm / 2
        c.setLineWidth(0.3)
        c.line(cx - 3 * mm, cy, cx + 3 * mm, cy)
        c.line(cx, cy - 3 * mm, cx, cy + 3 * mm)
        c.setFont(font, 6)
        c.drawString(x + 1.5 * mm, y + 1.5 * mm, str(i + 1))
    c.setFont(font, 8)
    c.drawString(
        10 * mm, 6 * mm,
        f"CALIBRATION / {SHEET['name']} / offset x={ox}mm y={oy}mm / 必ず倍率100%(等倍)で印刷"
    )


def build_label_pdf(items, offset_x=0.0, offset_y=0.0):
    """ラベルPDFをバイト列で返す。Webアプリから呼ぶための入口。

    items: [{"sku": ..., "name": ...}, ...]
           44件を超える場合は自動で改ページする。
    """
    import io
    font = register_font()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle("Barcode Labels")
    per = SHEET["cols"] * SHEET["rows"]
    idx = 0
    for item in items:
        if idx >= per:
            c.showPage()
            idx = 0
        draw_label(c, idx, item, font, offset_x, offset_y)
        idx += 1
    c.save()
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", help="CSV(sku,name,price) ※先頭行はヘッダー")
    ap.add_argument("-o", "--output", default="labels.pdf")
    ap.add_argument("--calibrate", action="store_true", help="位置合わせ用の枠線シートを生成")
    ap.add_argument("--offset-x", type=float, default=0.0, help="X補正(mm) 右にズレたら負の値")
    ap.add_argument("--offset-y", type=float, default=0.0, help="Y補正(mm) 下にズレたら負の値")
    ap.add_argument("--start", type=int, default=1, help="開始位置(1-44) 使いかけシート用")
    args = ap.parse_args()

    font = register_font()
    c = canvas.Canvas(args.output, pagesize=A4)
    c.setTitle("Barcode Labels")

    if args.calibrate:
        calibration_page(c, font, args.offset_x, args.offset_y)
        c.save()
        print(f"生成: {args.output} (キャリブレーション用)")
        return

    if not args.input:
        ap.error("--input または --calibrate が必要")

    with open(args.input, encoding="utf-8-sig") as f:
        items = [r for r in csv.DictReader(f) if r.get("sku")]
    for it in items:
        if not it.get("name"):
            it["name"] = ""

    per = SHEET["cols"] * SHEET["rows"]
    idx = args.start - 1
    for item in items:
        if idx >= per:
            c.showPage()
            idx = 0
        draw_label(c, idx, item, font, args.offset_x, args.offset_y)
        idx += 1
    c.save()
    print(f"生成: {args.output} / {len(items)}枚 / {SHEET['name']}")
    print("印刷設定: 倍率100%(等倍) / 手差し・厚紙モード")


if __name__ == "__main__":
    main()
