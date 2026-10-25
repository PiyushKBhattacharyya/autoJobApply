import sys
from pathlib import Path
import pdfplumber
import pypdf

pdf_path = Path("data/master_resume.pdf")

print("Checking pdfplumber hyperlinks...")
links_found = []
try:
    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages, 1):
            for link in getattr(page, "hyperlinks", []):
                uri = link.get("uri")
                if uri:
                    text = ""
                    try:
                        bbox = (link["x0"], link["top"], link["x1"], link["bottom"])
                        cropped = page.crop(bbox)
                        text = cropped.extract_text() or ""
                    except Exception as e:
                        text = f"err: {e}"
                    links_found.append({"source": "pdfplumber", "page": page_idx, "text": text.strip(), "uri": uri})
except Exception as e:
    print(f"pdfplumber error: {e}")

print(f"pdfplumber found {len(links_found)} links.")

print("Checking pypdf annotations...")
pypdf_links = []
try:
    reader = pypdf.PdfReader(str(pdf_path))
    for page_idx, page in enumerate(reader.pages, 1):
        if "/Annots" in page:
            for annot in page["/Annots"]:
                obj = annot.get_object()
                if obj.get("/Subtype") == "/Link":
                    action = obj.get("/A")
                    if action and "/URI" in action:
                        uri = str(action["/URI"])
                        rect = obj.get("/Rect", [])
                        pypdf_links.append({"source": "pypdf", "page": page_idx, "uri": uri, "rect": rect})
except Exception as e:
    print(f"pypdf error: {e}")

print(f"pypdf found {len(pypdf_links)} links.")

all_links = links_found if links_found else pypdf_links
for idx, l in enumerate(all_links, 1):
    print(f"{idx}. Text: '{l.get('text', '')}' -> URI: {l.get('uri')}")
