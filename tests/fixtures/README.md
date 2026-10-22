# Independent stamp rotation reference

`native-draft-stamp-30.pdf` is a synthetic blank A4 page with a 190 × 50 pt
Draft stamp rotated 30 degrees. No application annotation functions or customer
data were used. It was generated with the supported PyMuPDF 1.26.6 API:

```python
import pymupdf
with pymupdf.open() as doc:
    page = doc.new_page(width=595, height=842)
    stamp = page.add_stamp_annot(pymupdf.Rect(100, 100, 290, 150), stamp=pymupdf.STAMP_Draft)
    stamp.set_rotation(30)
    stamp.update()
    doc.save("native-draft-stamp-30.pdf")
```

The fixture preserves the existing test's independent 1.26.6 rendering oracle.
PyMuPDF 2.0's same API call produces an unrotated appearance, while application
output remains identical to the 1.26.6 reference. Both engines render this fixed
reference during tests; the original pixel-error tolerance remains unchanged.
Do not regenerate it with a new SDK simply to make a regression pass.

The local `.gitattributes` keeps PDF fixtures binary, preventing Git newline
conversion from changing their byte offsets or reference checksums on Windows.

SHA-256: `3d20a8990e5eb1a522f42e0760affae63bca3e70c16ba67d842380cb27f4703a`.
