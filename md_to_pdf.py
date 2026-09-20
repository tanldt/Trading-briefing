"""
md_to_pdf.py — chuyển báo cáo Markdown (tiếng Việt, có bảng/emoji) sang PDF.

Engine: Edge hoặc Chrome headless có sẵn trên Windows (--print-to-pdf), không cần thư viện PDF.
Chỉ cần: pip install markdown

Chạy:
  python md_to_pdf.py reports/2026-09-20.md                 -> reports/2026-09-20.pdf
  python md_to_pdf.py reports/method/advice-*.md            -> mỗi file một PDF
  python md_to_pdf.py a.md b.md --merge --out reports/tong-hop.pdf   -> gộp thành 1 PDF
  python md_to_pdf.py reports/2026-09-20.md --title "SOXL 20/09/2026"
Dùng trong code:  from md_to_pdf import md_file_to_pdf
"""
import sys, os, glob, argparse, subprocess, tempfile, shutil
from pathlib import Path
import markdown

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

CSS = """
@page { size: A4; margin: 16mm 14mm 18mm 14mm; }
body { font-family: "Segoe UI", "Segoe UI Emoji", Arial, sans-serif; font-size: 10.5pt;
       line-height: 1.45; color: #1a1a1a; }
h1 { font-size: 17pt; margin: 0 0 6pt; border-bottom: 2px solid #2b4c7e; padding-bottom: 4pt; color: #2b4c7e; }
h2 { font-size: 13.5pt; margin: 14pt 0 4pt; color: #2b4c7e; }
h3 { font-size: 11.5pt; margin: 10pt 0 3pt; }
p  { margin: 4pt 0; }
ul, ol { margin: 3pt 0 6pt 18pt; padding: 0; }
li { margin: 2pt 0; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 8pt; font-size: 9.5pt; page-break-inside: avoid; }
th, td { border: 1px solid #c9c9c9; padding: 3pt 6pt; text-align: left; vertical-align: top; }
th { background: #eef2f8; }
tr:nth-child(even) td { background: #fafafa; }
code { font-family: Consolas, monospace; font-size: 9.5pt; background: #f3f3f3; padding: 0 3pt; }
pre { background: #f3f3f3; padding: 6pt; font-size: 9pt; white-space: pre-wrap; }
hr { border: 0; border-top: 1px solid #ccc; margin: 10pt 0; }
em { color: #555; }
.meta { color: #777; font-size: 9pt; margin-bottom: 8pt; }
.section { page-break-after: always; }
.section:last-child { page-break-after: auto; }
"""


def find_browser():
    env = os.environ.get("MD_PDF_BROWSER")
    if env and Path(env).exists():
        return env
    for p in BROWSERS:
        if Path(p).exists():
            return p
    for name in ("msedge", "chrome"):
        w = shutil.which(name)
        if w:
            return w
    return None


def md_to_html(md_text, title=None, source=None):
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists", "nl2br"])
    head = f"<h1>{title}</h1>" if title else ""
    meta = f'<div class="meta">Nguồn: {source}</div>' if source else ""
    return f"<!doctype html><html lang='vi'><head><meta charset='utf-8'><title>{title or ''}</title>" \
           f"<style>{CSS}</style></head><body>{head}{meta}{body}</body></html>"


def html_to_pdf(html, out_pdf, browser=None, timeout=90):
    browser = browser or find_browser()
    if not browser:
        raise RuntimeError("Không tìm thấy Edge/Chrome. Đặt biến MD_PDF_BROWSER=<đường dẫn msedge.exe>.")
    out_pdf = Path(out_pdf).resolve()
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        html_path = Path(td) / "report.html"
        html_path.write_text(html, encoding="utf-8")
        cmd = [browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
               f"--user-data-dir={Path(td) / 'profile'}",
               f"--print-to-pdf={out_pdf}", html_path.as_uri()]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if not out_pdf.exists():
            raise RuntimeError(f"Trình duyệt không tạo được PDF (exit {r.returncode}): {r.stderr[-400:]}")
    return str(out_pdf)


def md_file_to_pdf(md_path, out_pdf=None, title=None):
    md_path = Path(md_path)
    text = md_path.read_text(encoding="utf-8")
    out_pdf = out_pdf or md_path.with_suffix(".pdf")
    return html_to_pdf(md_to_html(text, title=title, source=md_path.name), out_pdf)


def merge_md_to_pdf(md_paths, out_pdf, title=None):
    parts = []
    for p in md_paths:
        p = Path(p)
        body = markdown.markdown(p.read_text(encoding="utf-8"),
                                 extensions=["tables", "fenced_code", "sane_lists", "nl2br"])
        parts.append(f'<div class="section"><div class="meta">Nguồn: {p.name}</div>{body}</div>')
    head = f"<h1>{title}</h1>" if title else ""
    html = f"<!doctype html><html lang='vi'><head><meta charset='utf-8'><style>{CSS}</style></head>" \
           f"<body>{head}{''.join(parts)}</body></html>"
    return html_to_pdf(html, out_pdf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="file .md hoặc glob")
    ap.add_argument("--out", help="đường dẫn PDF (khi 1 file hoặc --merge)")
    ap.add_argument("--merge", action="store_true", help="gộp tất cả vào một PDF")
    ap.add_argument("--title", help="tiêu đề in đầu PDF")
    a = ap.parse_args()

    files = []
    for f in a.files:
        files += sorted(glob.glob(f)) or ([f] if Path(f).exists() else [])
    files = [f for f in files if f.lower().endswith(".md")]
    if not files:
        print("Không có file .md nào khớp.")
        return 1

    if a.merge:
        out = a.out or str(Path(files[0]).with_suffix(".pdf"))
        print("Đã tạo", merge_md_to_pdf(files, out, a.title))
        return 0
    for f in files:
        out = a.out if (a.out and len(files) == 1) else None
        print("Đã tạo", md_file_to_pdf(f, out, a.title))
    return 0


if __name__ == "__main__":
    sys.exit(main())
