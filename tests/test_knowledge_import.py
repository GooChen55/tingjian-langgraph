import io
import pytest
from pypdf import PdfWriter
from app.listening.ingestion import parse_document
from app.listening.index import split_documents
from knowledge_catalog import artifact_path


def test_utf8_and_stable_source_identifiers(tmp_path):
    path=tmp_path/'document.md'
    path.write_text('# 第一节\n带有书名的原始资料\n## 第二节\n另一段有依据的文字',encoding='utf-8')
    chunks=split_documents('',entries=[{'path':str(path),'title':'资料书名','source':'uploaded:1:revision-a'}])
    assert {c['title'] for c in chunks}=={'资料书名'}
    assert {c['source'] for c in chunks}=={'uploaded:1:revision-a'}
    other=split_documents('',entries=[{'path':str(path),'title':'资料书名','source':'uploaded:1:revision-b'}])
    assert {c['chunk_id'] for c in chunks}.isdisjoint(c['chunk_id'] for c in other)
    assert parse_document(b'\xef\xbb\xbf# title\r\ntext','.md')=='# title\ntext'


def test_scanned_pdf_and_unsafe_paths_are_explicitly_rejected():
    writer=PdfWriter();writer.add_blank_page(width=100,height=100);stream=io.BytesIO();writer.write(stream)
    with pytest.raises(ValueError,match='NeedsOcr'):parse_document(stream.getvalue(),'.pdf')
    with pytest.raises(ValueError,match='Foreign'):artifact_path('../../../../outside.md')
    with pytest.raises(ValueError,match='60000'):parse_document(('字'*60001).encode(),'.txt')
