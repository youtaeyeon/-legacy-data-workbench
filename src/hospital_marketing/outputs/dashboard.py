from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from ..domain import Hospital
from ..repository import Repository


def _safe_url(value: str) -> str | None:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or any(char in value for char in "\r\n\t"):
        return None
    return value.strip()


def _record(repository: Repository, hospital: Hospital) -> dict:
    deliveries = repository.list_deliveries(hospital.hospital_id)
    materials = repository.list_materials(hospital.hospital_id)
    channels = repository.list_channels(hospital.hospital_id)
    contents = repository.list_contents(hospital.hospital_id)
    return {
        "hospital_id": hospital.hospital_id,
        "hospital_name": hospital.hospital_name,
        "region": hospital.region or "",
        "contract_date": hospital.contract_date.isoformat() if hospital.contract_date else "",
        "products": sorted({item.product_name for item in deliveries}),
        "deliveries": [
            {"product_name": item.product_name, "delivery_date": item.delivery_date.isoformat() if item.delivery_date else "", "quantity": item.quantity}
            for item in deliveries
        ],
        "materials": [
            {"product_name": item.product_name, "material_name": item.material_name, "quantity": item.quantity, "status": item.status}
            for item in materials
        ],
        "channels": [
            {"platform": item.platform, "channel_name": item.channel_name, "url": _safe_url(item.url)}
            for item in channels if _safe_url(item.url)
        ],
        "contents": [
            {"platform": item.platform, "title": item.title, "url": _safe_url(item.url), "matched_product": item.matched_product or "", "published_at": item.published_at.isoformat() if item.published_at else "", "evidence": item.evidence or ""}
            for item in contents if item.relevance_status == "relevant" and _safe_url(item.url)
        ],
    }


def render_dashboard(repository: Repository, output_path: Path) -> Path:
    hospitals = [_record(repository, hospital) for hospital in repository.list_hospitals()]
    payload = json.dumps({"hospitals": hospitals}, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    html = f'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>병원 마케팅 위키 대시보드</title>
<style>
:root{{--cream:#f3eee2;--cream-strong:#faf7ee;--navy:#09223f;--gray:#3f4346;--muted:#5f666d;--blue:#245c9e;--khaki:#5d6c58;--line:rgba(9,34,63,.14)}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--cream);color:var(--navy);font-family:"Noto Serif KR",Georgia,serif}}
header{{padding:32px clamp(20px,5vw,72px);background:var(--navy);color:var(--cream)}}header p{{margin:0 0 8px;font:600 12px system-ui;letter-spacing:.16em}}h1{{font-size:clamp(28px,4vw,48px);margin:0}}main{{max-width:1400px;margin:auto;padding:32px clamp(16px,4vw,56px)}}
.filters{{display:grid;grid-template-columns:2fr 1fr 1fr;gap:12px;margin-bottom:24px}}input,select{{min-height:48px;padding:10px 12px;border:1px solid var(--line);background:var(--cream-strong);color:var(--navy);font:16px Georgia,serif;border-radius:4px}}input:focus,select:focus{{outline:2px solid #2b6cb8;outline-offset:2px}}
#result-count{{color:var(--muted);font:14px system-ui;margin:12px 0}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:16px}}article{{padding:22px;background:var(--cream-strong);border:1px solid var(--line);border-top:4px solid var(--khaki)}}article h2{{margin:0 0 8px;font-size:24px}}.meta{{color:var(--muted);font:14px/1.6 system-ui}}.tag{{display:inline-block;margin:10px 6px 4px 0;padding:4px 8px;background:#e9e3d3;color:var(--navy);font:13px system-ui}}ul{{padding-left:20px;line-height:1.6}}a{{color:var(--blue);text-underline-offset:3px}}.empty{{padding:36px;text-align:center;color:var(--muted);background:var(--cream-strong)}}
@media(max-width:720px){{.filters{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<header><p>MOCK DATA · MARKETING WIKI</p><h1>병원 마케팅 대시보드</h1></header>
<main>
<div class="filters" aria-label="병원 필터">
<input id="search-filter" type="search" placeholder="병원명·지역·콘텐츠 검색" aria-label="병원명, 지역 또는 콘텐츠 검색">
<select id="product-filter" aria-label="제품 필터"><option value="">전체 제품</option></select>
<select id="platform-filter" aria-label="채널 필터"><option value="">전체 채널</option></select>
</div>
<p id="result-count" aria-live="polite"></p>
<div id="results" class="grid"></div>
</main>
<script type="application/json" id="dashboard-data">{payload}</script>
<script>
(() => {{
  const data = JSON.parse(document.getElementById('dashboard-data').textContent).hospitals;
  const search = document.getElementById('search-filter');
  const product = document.getElementById('product-filter');
  const platform = document.getElementById('platform-filter');
  const results = document.getElementById('results');
  const count = document.getElementById('result-count');
  const products = [...new Set(data.flatMap(h => [...h.products, ...h.contents.map(c => c.matched_product)].filter(Boolean)))].sort();
  const platforms = [...new Set(data.flatMap(h => [...h.channels.map(c => c.platform), ...h.contents.map(c => c.platform)]))].sort();
  for (const value of products) {{ const option = document.createElement('option'); option.value = value; option.textContent = value; product.append(option); }}
  for (const value of platforms) {{ const option = document.createElement('option'); option.value = value; option.textContent = value; platform.append(option); }}
  function makeLink(label, url) {{
    const link = document.createElement('a'); link.textContent = label; link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; return link;
  }}
  function render() {{
    const query = search.value.trim().toLocaleLowerCase();
    const filtered = data.filter(h => {{
      const text = [h.hospital_name, h.region, ...h.products, ...h.contents.map(c => c.title)].join(' ').toLocaleLowerCase();
      const productMatch = !product.value || h.products.includes(product.value) || h.contents.some(c => c.matched_product === product.value);
      const platformMatch = !platform.value || h.channels.some(c => c.platform === platform.value) || h.contents.some(c => c.platform === platform.value);
      return (!query || text.includes(query)) && productMatch && platformMatch;
    }});
    results.replaceChildren(); count.textContent = `병원 ${{filtered.length}}곳`;
    if (!filtered.length) {{ const empty = document.createElement('p'); empty.className = 'empty'; empty.textContent = '조건에 맞는 병원이 없습니다.'; results.append(empty); return; }}
    for (const h of filtered) {{
      const card = document.createElement('article');
      const title = document.createElement('h2'); title.textContent = h.hospital_name; card.append(title);
      const meta = document.createElement('p'); meta.className = 'meta'; meta.textContent = `${{h.hospital_id}} · ${{h.region || '지역 정보 없음'}} · 계약일 ${{h.contract_date || '미입력'}}`; card.append(meta);
      for (const name of h.products) {{ const tag = document.createElement('span'); tag.className = 'tag'; tag.textContent = name; card.append(tag); }}
      if (h.channels.length) {{ const heading = document.createElement('h3'); heading.textContent = '온라인 채널'; card.append(heading); const list = document.createElement('ul'); for (const c of h.channels) {{ const item = document.createElement('li'); item.append(makeLink(`${{c.platform}} · ${{c.channel_name}}`, c.url)); list.append(item); }} card.append(list); }}
      if (h.contents.length) {{ const heading = document.createElement('h3'); heading.textContent = '제품 관련 콘텐츠'; card.append(heading); const list = document.createElement('ul'); for (const c of h.contents) {{ const item = document.createElement('li'); item.append(makeLink(c.title, c.url)); const note = document.createElement('span'); note.className = 'meta'; note.textContent = ` · ${{c.matched_product}}`; item.append(note); list.append(item); }} card.append(list); }}
      results.append(card);
    }}
  }}
  search.addEventListener('input', render);
  product.addEventListener('change', render);
  platform.addEventListener('change', render);
  render();
}})();
</script>
</body>
</html>
'''
    output_path.write_text(html, encoding="utf-8")
    return output_path
