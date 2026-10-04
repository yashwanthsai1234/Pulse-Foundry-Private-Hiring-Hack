"""Generates the NON-reportlab schedule PDFs (Chrome, PyMuPDF Story/draw, LibreOffice, raster scan) + ground truth JSON.
Run once (needs Chrome + soffice); the tests only read the saved files."""
import json, subprocess, random, shutil, tempfile
from pathlib import Path
import pymupdf, openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from PIL import Image, ImageFilter
import numpy as np

OUT = Path(__file__).parent.parent / "fixtures" / "realworld" / "pdf"
HDR = ["Staff", "Role", "Mon 09/14", "Tue 09/15", "Wed 09/16", "Thu 09/17", "Fri 09/18", "Sat 09/19", "Sun 09/20"]
FOOT = "Shifts: 7a-3p, 3p-11p, 11p-7a are 8 hours. 7a-7p is 12 hours."
TOK = ["7a-3p", "3p-11p", "11p-7a", "7a-7p", "OFF", "OFF"]
BAY = ["Sofia Reyes", "Marc Bell", "Dorothy Washington-Greene", "Li Wei", "Anthony Fitzgerald", "Priya Natarajan", "Tom Ng", "Maria Del Carmen Gonzalez"]
RIV = ["Jamal Carter", "Olivia Brennan", "Esteban Ruiz", "Hannah Kowalski", "Bo Chen", "Ifeoma Okafor"]
ROLES = ["RN", "CNA", "LPN", "CNA", "RN", "LPN", "CNA", "RN"]


def make_spec(seed=7):
    rnd = random.Random(seed)
    pages = []
    for title, names in (("Harborview Bayside", BAY), ("Harborview Riverdale", RIV)):
        rows = [[n, ROLES[i % len(ROLES)]] + [rnd.choice(TOK) for _ in range(7)] for i, n in enumerate(names)]
        pages.append({"title": title, "subtitle": "Weekly Staff Schedule - Week of 09/14", "rows": rows})
    return {"header": HDR, "footnote": FOOT, "pages": pages}


def split_hdr(h):  # "Mon 09/14" -> two lines
    return h.replace(" ", "<br>") if h[:3] in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun") else h

COL = {"7a-3p": "#fff2cc", "3p-11p": "#d9ead3", "11p-7a": "#cfe2f3", "7a-7p": "#f4cccc", "OFF": "#eeeeee"}


def html_doc(spec, border=True, color_cells=True, zebra=True, two_line=True):
    css = f"""@page {{ size: Letter; margin: 0.6in; }} body {{ font-family: Helvetica, Arial, sans-serif; font-size: 10pt }}
    h1 {{ font-size: 18pt; margin:0 }} h2 {{ font-size: 11pt; font-weight: normal; color:#555; margin:2pt 0 10pt }}
    table {{ border-collapse: collapse; width: 100% }} th {{ background:#1f4e79; color:#fff; padding:5px 3px; font-size:9pt }}
    td {{ padding:5px 4px; text-align:center; {'border:1px solid #999;' if border else ''} }} td:first-child {{ text-align:left; font-weight:bold }}
    {'tr:nth-child(even) td { background:#f2f2f2 }' if zebra else ''} .pb {{ page-break-after: always }} .foot {{ margin-top:12pt; font-size:9pt; font-style:italic }}"""
    out = [f"<html><head><meta charset=utf-8><style>{css}</style></head><body>"]
    for i, p in enumerate(spec["pages"]):
        out.append(f"<div class={'pb' if i < len(spec['pages']) - 1 else ''}><h1>{p['title']}</h1><h2>{p['subtitle']}</h2><table><tr>")
        out += [f"<th>{split_hdr(h) if two_line else h}</th>" for h in spec["header"]]
        out.append("</tr>")
        for r in p["rows"]:
            out.append("<tr>" + "".join(
                f"<td style='background:{COL[c]}'>{c}</td>" if color_cells and c in COL and j >= 2 else f"<td>{c}</td>"
                for j, c in enumerate(r)) + "</tr>")
        out.append(f"</table><div class=foot>{spec['footnote']}</div></div>")
    out.append("</body></html>")
    return "\n".join(out)


def chrome_pdf(html, dest):
    tmp = Path(tempfile.mkdtemp()) / "s.html"
    tmp.write_text(html)
    subprocess.run(["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--headless=new", "--disable-gpu",
                    "--no-pdf-header-footer", f"--print-to-pdf={dest}", f"file://{tmp}"], check=True, capture_output=True, timeout=90)


def story_pdf(spec, dest, border=True):
    html = html_doc(spec, border=border, color_cells=True, zebra=False, two_line=True).replace("page-break-after: always", "")
    story = pymupdf.Story(html=html)
    w = pymupdf.DocumentWriter(str(dest))
    mediabox = pymupdf.paper_rect("letter")
    where = mediabox + (40, 40, -40, -40)
    more = 1
    while more:
        dev = w.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        w.end_page()
    w.close()


def draw_pdf(spec, dest, rotate_header=True):
    doc = pymupdf.open()
    widths = [120, 40] + [52] * 7
    for p in spec["pages"]:
        pg = doc.new_page(width=612, height=792)
        pg.insert_text((40, 60), p["title"], fontsize=18, fontname="hebo")
        pg.insert_text((40, 78), p["subtitle"], fontsize=10)
        x0, y = 40, 140 if rotate_header else 100
        hh = 60 if rotate_header else 24
        x = x0
        for h, w in zip(spec["header"], widths):
            r = pymupdf.Rect(x, y - hh, x + w, y)
            pg.draw_rect(r, color=(0, 0, 0), fill=(0.12, 0.3, 0.47), width=0.5)
            if rotate_header and h[:3] in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
                pg.insert_textbox(pymupdf.Rect(x, y - hh, x + w, y), "", rotate=0)
                # rotated 90 degrees text anchored at the lower-left of the cell
                pg.insert_text((x + w / 2 + 4, y - 4), h, fontsize=9, color=(1, 1, 1), rotate=90)
            else:
                pg.insert_text((x + 4, y - hh / 2 + 3), h, fontsize=9, color=(1, 1, 1))
            x += w
        for row in p["rows"]:
            x = x0
            for c, w in zip(row, widths):
                r = pymupdf.Rect(x, y, x + w, y + 22)
                pg.draw_rect(r, color=(0.5, 0.5, 0.5), width=0.5)
                pg.insert_text((x + 4, y + 15), c, fontsize=8 if len(c) > 14 else 9)
                x += w
            y += 22
        pg.insert_text((40, y + 20), spec["footnote"], fontsize=9, fontname="heit")
    doc.save(dest)


def xlsx_pdf(spec, dest, merged_title=True):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    thin = Side(style="thin", color="888888")
    for p in spec["pages"]:
        ws = wb.create_sheet(p["title"].split()[-1])
        ws["A1"] = p["title"]; ws["A1"].font = Font(size=16, bold=True)
        ws["A2"] = p["subtitle"]
        if merged_title:
            ws.merge_cells("A1:I1")
            ws["A1"].alignment = Alignment(horizontal="center")
        for j, h in enumerate(spec["header"], 1):
            c = ws.cell(row=4, column=j, value=h.replace(" ", "\n") if h[:3] in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun") else h)
            c.fill = PatternFill("solid", fgColor="1F4E79"); c.font = Font(color="FFFFFF", bold=True)
            c.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center"); c.border = Border(left=thin, right=thin, top=thin, bottom=thin)
        ws.row_dimensions[4].height = 32
        for i, r in enumerate(p["rows"], 5):
            for j, v in enumerate(r, 1):
                c = ws.cell(row=i, column=j, value=v)
                c.border = Border(left=thin, right=thin, top=thin, bottom=thin)
                if j >= 3: c.fill = PatternFill("solid", fgColor=COL[v][1:]); c.alignment = Alignment(horizontal="center")
        ws.cell(row=5 + len(p["rows"]) + 1, column=1, value=spec["footnote"]).font = Font(italic=True)
        ws.column_dimensions["A"].width = 28
        for col in "BCDEFGHI": ws.column_dimensions[col].width = 11
        ws.page_setup.orientation = "landscape"; ws.page_setup.fitToWidth = 1; ws.sheet_properties.pageSetUpPr = openpyxl.worksheet.properties.PageSetupProperties(fitToPage=True)
    tmp = Path(tempfile.mkdtemp()); x = tmp / "s.xlsx"; wb.save(x)
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(tmp), str(x)], check=True, capture_output=True, timeout=180)
    shutil.copy(tmp / "s.pdf", dest)


def docx_pdf(spec, dest):
    tmp = Path(tempfile.mkdtemp())
    (tmp / "s.html").write_text(html_doc(spec, border=True, color_cells=True, zebra=False, two_line=True))
    subprocess.run(["pandoc", str(tmp / "s.html"), "-o", str(tmp / "s.docx")], check=True, capture_output=True)
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(tmp), str(tmp / "s.docx")], check=True, capture_output=True, timeout=180)
    shutil.copy(tmp / "s.pdf", dest)


def scan_pdf(src, dest, dpi=130, angle=1.5, noise=18, seed=3):
    rng = np.random.default_rng(seed)
    out = pymupdf.open()
    with pymupdf.open(src) as d:
        for pg in d:
            pix = pg.get_pixmap(dpi=dpi)
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
            im = im.rotate(angle, expand=True, fillcolor=255).filter(ImageFilter.GaussianBlur(0.6))
            a = np.asarray(im).astype(np.float32) + rng.normal(0, noise, (im.height, im.width))
            a = np.clip(a, 0, 255).astype(np.uint8)
            tmp = Path(tempfile.mkdtemp()) / "p.jpg"; Image.fromarray(a).save(tmp, quality=60)
            page = out.new_page(width=pix.width * 72 / dpi, height=pix.height * 72 / dpi)
            page.insert_image(page.rect, filename=str(tmp))
    out.save(dest)


if __name__ == "__main__":
    spec = make_spec()
    (OUT / "truth.json").write_text(json.dumps(spec, indent=1))
    chrome_pdf(html_doc(spec), OUT / "chrome_bordered_twoline.pdf")
    chrome_pdf(html_doc(spec, border=False, color_cells=False, zebra=True, two_line=True), OUT / "chrome_borderless_zebra.pdf")
    chrome_pdf(html_doc(spec, two_line=False), OUT / "chrome_bordered_oneline.pdf")
    story_pdf(spec, OUT / "pymupdf_story.pdf")
    draw_pdf(spec, OUT / "pymupdf_draw_rotated_header.pdf", True)
    draw_pdf(spec, OUT / "pymupdf_draw_plain.pdf", False)
    xlsx_pdf(spec, OUT / "libreoffice_xlsx.pdf")
    docx_pdf(spec, OUT / "libreoffice_docx_pandoc.pdf")
    scan_pdf(OUT / "chrome_bordered_oneline.pdf", OUT / "scan_130dpi_rot1.5.pdf")
    scan_pdf(OUT / "chrome_bordered_oneline.pdf", OUT / "scan_100dpi_rot2.pdf", dpi=100, angle=-2, noise=25)
