#!/usr/bin/env python3
from gold_macro import _extract_rows

sample=b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
      xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">
  <entry><content type="application/xml"><m:properties>
    <d:NEW_DATE m:type="Edm.DateTime">2026-10-08T00:00:00</d:NEW_DATE>
    <d:BC_2YEAR m:type="Edm.Double">4.01</d:BC_2YEAR>
    <d:BC_10YEAR m:type="Edm.Double">4.23</d:BC_10YEAR>
    <d:BC_30YEAR m:type="Edm.Double">4.71</d:BC_30YEAR>
  </m:properties></content></entry>
  <entry><content type="application/xml"><m:properties>
    <d:NEW_DATE m:type="Edm.DateTime">2026-10-09T00:00:00</d:NEW_DATE>
    <d:BC_2YEAR m:type="Edm.Double">4.03</d:BC_2YEAR>
    <d:BC_10YEAR m:type="Edm.Double">4.27</d:BC_10YEAR>
    <d:BC_30YEAR m:type="Edm.Double">4.75</d:BC_30YEAR>
  </m:properties></content></entry>
</feed>"""
rows=_extract_rows(sample)
assert len(rows)==2, rows
assert rows[-1]["2y"]==4.03, rows
assert rows[-1]["10y"]==4.27, rows
print("TREASURY_PARSER_OK")
