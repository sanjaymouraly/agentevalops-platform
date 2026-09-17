"""Minimal dependency-free PDF writer for release reports.
Produces a valid, printable multi-page PDF (Type1 Helvetica, escaped text) —
deliberately small rather than a heavy reporting dependency."""

def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

def text_to_pdf(title: str, text: str, out_path) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.replace("\t", "    ")
        while len(line) > 105:
            lines.append(line[:105]); line = line[105:]
        lines.append(line)
    per_page = 52
    pages = [lines[i:i+per_page] for i in range(0, max(len(lines), 1), per_page)] or [[]]
    objects: list[bytes] = []
    def add(obj: bytes) -> int:
        objects.append(obj); return len(objects)  # object id = index
    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids = []
    content_ids = []
    for page_lines in pages:
        stream_lines = ["BT /F1 13 Tf 36 806 Td "]
        stream_lines.append(f"({_escape(title[:80])}) Tj")
        stream_lines.append(" /F1 8.5 Tf 0 -13 Td ")
        for line in page_lines:
            stream_lines.append(f"({_escape(line)}) Tj 0 -11.5 Td ")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode("latin-1", "replace")
        cid = add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        content_ids.append(cid)
        pid = add(f"<< /Type /Page /Parent {{pages_id}} /MediaBox [0 0 612 842] /Contents {cid} 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode())
        page_ids.append(pid)
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    pages_id = len(objects) + 1
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode())
    # fix page parent placeholders
    for i, pid in enumerate(page_ids):
        objects[pid-1] = objects[pid-1].replace(b"{pages_id}", str(pages_id).encode())
    catalog_id = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects)+1} /Root {catalog_id} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    from pathlib import Path
    Path(out_path).write_bytes(bytes(out))
    return str(out_path)
