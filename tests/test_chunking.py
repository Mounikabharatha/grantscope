import fitz

from app.chunking import chunk_pdf


def make_pdf(path):
    """A tiny two-section grant notice: big headings, normal body text."""
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    def write(text, size, font="helv"):
        nonlocal y
        page.insert_text((72, y), text, fontsize=size, fontname=font)
        y += size + 8
    write("ELIGIBILITY", 16, "hebo")
    write("Eligible Applicants", 12, "hebo")
    for _ in range(3):
        write("State governments and federally recognized tribes may apply.", 11)
    write("FUNDING", 16, "hebo")
    for _ in range(3):
        write("The award ceiling is $675,000 per project for two years.", 11)
    doc.save(path)


def test_section_chunks_keep_heading_path(tmp_path):
    pdf = tmp_path / "grant.pdf"
    make_pdf(pdf)
    chunks = chunk_pdf(pdf, "section", chunk_words=300, overlap_words=0)
    sections = [c["section"] for c in chunks]
    assert sections == ["ELIGIBILITY > Eligible Applicants", "FUNDING"]
    assert "$675,000" in chunks[1]["text"]
    assert "675,000" not in chunks[0]["text"]  # sections never bleed together


def test_chunks_respect_size_and_overlap(tmp_path):
    pdf = tmp_path / "grant.pdf"
    make_pdf(pdf)
    chunks = chunk_pdf(pdf, "fixed", chunk_words=20, overlap_words=10)
    assert all(c["n_words"] <= 20 for c in chunks)
    assert len(chunks) > 3
    # Overlap: each chunk starts with the last sentence of the previous one.
    first_sentence_of_next = chunks[1]["text"].split(".")[0]
    assert first_sentence_of_next in chunks[0]["text"]
