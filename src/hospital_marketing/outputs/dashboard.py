from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

from ..domain import ContentScript, Hospital
from ..repository import Repository
from ..settings import DEFAULT_PRODUCTS


def _safe_url(value: str) -> str | None:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or any(char in value for char in "\r\n\t"):
        return None
    return value.strip()


def _record(repository: Repository, hospital: Hospital, scripts: dict[str, ContentScript]) -> dict:
    deliveries = repository.list_deliveries(hospital.hospital_id)
    materials = repository.list_materials(hospital.hospital_id)
    channels = repository.list_channels(hospital.hospital_id)
    candidates = repository.list_channel_candidates(hospital.hospital_id, "pending")
    contents = repository.list_contents(hospital.hospital_id)
    scripts_for_hospital = [scripts[item.url] for item in contents if item.url in scripts]
    return {
        "hospital_id": hospital.hospital_id,
        "hospital_name": hospital.hospital_name,
        "region": hospital.region or "",
        "contract_date": hospital.contract_date.isoformat() if hospital.contract_date else "",
        "contract_status": "거래 병원" if hospital.contract_date else "거래 정보 없음",
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
            {"platform": item.platform, "channel_name": item.channel_name, "url": _safe_url(item.url), "status": "자동 수집"}
            for item in channels if _safe_url(item.url)
        ],
        "pending_channels": [
            {"platform": item["platform"], "channel_name": item["channel_name"], "url": _safe_url(item["url"]), "status": "확인 필요"}
            for item in candidates if _safe_url(item["url"])
        ],
        "channel_candidates": [
            {"platform": item["platform"], "channel_name": item["channel_name"], "url": _safe_url(item["url"]), "confidence": item["confidence"]}
            for item in candidates if _safe_url(item["url"])
        ],
        "briefing": next((item.summary for item in scripts_for_hospital if item.summary), ""),
        "contents": [
            {"platform": item.platform, "title": item.title, "url": _safe_url(item.url), "matched_product": item.matched_product or "", "published_at": item.published_at.isoformat() if item.published_at else "", "evidence": item.evidence or "", "relevance_status": item.relevance_status, "script_text": scripts[item.url].script_text if item.url in scripts else "", "script_summary": scripts[item.url].summary if item.url in scripts else "", "usage_status": scripts[item.url].usage_status if item.url in scripts else "미활용", "has_script": bool(scripts.get(item.url) and scripts[item.url].script_text)}
            for item in contents if item.relevance_status == "relevant" and _safe_url(item.url)
        ],
    }


def _dashboard_html(payload: str) -> str:
    template = '''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>병원 마케팅 위키 MVP</title><style>
:root{--blue:#7899f5;--green:#78b96d;--orange:#e5a43d;--ink:#34354b;--muted:#77788b;--line:#e8e7ef;--glass:#ffffffc9}
*{box-sizing:border-box}body{margin:0;color:var(--ink);font:15px/1.55 "Noto Sans KR","Malgun Gothic",sans-serif;background:linear-gradient(135deg,#e9e7fb,#f4f0f8 55%,#e8eff7);min-height:100vh}
.side{position:fixed;inset:0 auto 0 0;width:218px;padding:24px 14px;background:#ffffff99;backdrop-filter:blur(18px);border-right:1px solid #fff;z-index:2}.brand{font-size:17px;font-weight:800;padding:8px 10px 24px}.side-link{display:block;width:100%;text-align:left;border:0;background:transparent;color:var(--ink);padding:11px 13px;border-radius:12px;margin:4px 0;font:inherit;cursor:pointer}.side-link:hover,.side-link.on{background:#7899f522;color:#466bd0}.shell{margin-left:218px;padding:25px;max-width:1600px}.crumb{color:var(--muted);font-size:13px;margin:0 0 14px}.layout{display:grid;grid-template-columns:minmax(0,1fr) 270px;gap:20px}.glass{background:var(--glass);backdrop-filter:blur(18px);border:1px solid #ffffffd9;border-radius:19px;box-shadow:0 10px 35px #4c4b6c12;padding:20px;margin-bottom:16px}h1{font-size:29px;margin:0}h2{font-size:19px;margin:0 0 14px}h3{font-size:16px;margin:18px 0 9px}.sub{color:var(--muted)}.topline{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:18px}.kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.kpi{background:#fff9;border-radius:15px;padding:15px}.kpi b{display:block;font-size:25px}.tag{display:inline-block;padding:3px 10px;border-radius:20px;background:#7899f522;color:#466bd0;font-size:12px;margin:2px}.tag.green{background:#78b96d24;color:#43873a}.tag.orange{background:#e5a43d25;color:#a66d13}.tools{display:flex;gap:9px;flex-wrap:wrap;margin:12px 0}.tools input,.tools select{border:1px solid var(--line);border-radius:10px;background:#fff;padding:10px;font:inherit}.tools input{flex:1;min-width:180px}.hospital-list{display:grid;gap:9px}.hospital-row{border:1px solid var(--line);border-radius:13px;padding:13px;background:#fff9;display:flex;justify-content:space-between;align-items:center;gap:12px;cursor:pointer}.hospital-row:hover{border-color:var(--blue)}.two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.info-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.info{background:#fff9;padding:12px;border-radius:12px;overflow-wrap:anywhere}.info small{display:block;color:var(--muted)}.tabs{display:flex;gap:6px;overflow:auto;border-bottom:1px solid var(--line);margin:14px 0}.tab{white-space:nowrap;border:0;background:none;padding:10px 12px;color:var(--muted);font:inherit;cursor:pointer}.tab.on{color:#466bd0;border-bottom:2px solid var(--blue)}.channel{padding:12px;border:1px solid var(--line);border-radius:13px;background:#fff9}.channel a,.item a{color:#466bd0;overflow-wrap:anywhere}.item{padding:12px 2px;border-bottom:1px solid var(--line)}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600}.rail-state{padding:10px 0;border-bottom:1px solid var(--line)}.empty{color:var(--muted);padding:18px;text-align:center}.gallery{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.gallery-item{border:1px solid var(--line);border-radius:14px;padding:14px;background:#fff9}.btn{border:0;background:var(--blue);color:white;border-radius:10px;padding:9px 14px;cursor:pointer}.script-modal{position:fixed;inset:0;background:#0007;display:grid;place-items:center;padding:20px;z-index:4}.script-dialog{background:white;border-radius:18px;padding:24px;max-width:700px;width:100%;max-height:85vh;overflow:auto}.script-dialog[hidden],.script-modal[hidden],[hidden]{display:none!important}.script-body{white-space:pre-wrap}.copyright{font-size:13px;color:var(--muted)}
@media(max-width:1100px){.layout{grid-template-columns:1fr}.rail{order:2}}@media(max-width:700px){.side{display:none}.shell{margin:0;padding:14px}.info-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.kpis{grid-template-columns:1fr}.two,.gallery{grid-template-columns:1fr}h1{font-size:23px}}
</style></head><body>
<nav class="side" aria-label="주요 메뉴"><div class="brand">🏥 병원 마케팅 위키 MVP</div>
<button class="side-link on" data-view="dashboard">▦ 대시보드</button><button class="side-link" data-view="hospitals">♧ 병원 관리</button><button class="side-link" data-view="channels">◎ SNS 채널</button><button class="side-link" data-view="collected">▤ 수집 콘텐츠</button><button class="side-link" data-view="analysis">✦ AI 분석</button><button class="side-link" data-view="creation">✍️ 콘텐츠 제작</button></nav>
<main class="shell"><p class="crumb" id="breadcrumb">홈　/　대시보드</p><p class="sub">MOCK DATA · MARKETING WIKI</p><section class="layout"><div>
<section class="glass" id="overview"><div class="topline"><div><h1>대시보드</h1><div class="sub">병원별 채널과 제품 관련 콘텐츠를 확인합니다.</div></div></div><div id="kpis" class="kpis"></div></section>
<section class="glass" id="hospital-list"><h2>병원 목록</h2><div class="tools"><input id="search-filter" type="search" placeholder="병원명·지역·제품·콘텐츠 검색" aria-label="병원 검색"><select id="product-filter" aria-label="제품 필터"><option value="">전체 제품</option></select><select id="platform-filter" aria-label="채널 필터"><option value="">전체 채널</option></select></div><div id="hospitals" class="hospital-list"></div></section>
<section class="glass" id="hospital-detail" hidden><div class="topline"><div><h1 id="detail-name"></h1><div id="detail-address" class="sub"></div></div><button class="btn" id="back-list" type="button">병원 목록</button></div><div id="detail-tags"></div><h2>병원 기본정보</h2><div id="basic-info" class="info-grid"></div><div id="hospital-tabs" class="tabs" role="tablist"><button class="tab on" data-tab="summary">전체 요약</button><button class="tab" data-tab="channels">SNS 채널</button><button class="tab" data-tab="collected">수집 콘텐츠</button><button class="tab" data-tab="analysis">AI 분석</button><button class="tab" data-tab="materials">제작 자료</button></div><div id="tab-panel"></div></section>
<section class="glass" id="global-panel" hidden></section></div>
<aside class="rail" id="right-rail"><section class="glass"><h2>확인 및 업무 상태</h2><div id="timeline"></div></section><section class="glass"><h2>AI 병원 브리핑</h2><p id="briefing" class="sub">병원에서 수집된 콘텐츠 요약이 없습니다.</p></section></aside></section>
<p class="copyright">병원 영상·글은 병원의 저작물이므로 SNS 활용 시 사전 허락과 출처 표기가 필요합니다. 스크립트는 소재 발굴·참고용입니다.</p></main>
<div class="script-modal" id="script-modal" hidden><section class="script-dialog" role="dialog" aria-modal="true" aria-labelledby="script-title"><button class="btn" id="script-close" type="button">닫기</button><h2 id="script-title"></h2><p id="script-meta" class="sub"></p><p id="script-status"></p><h3>스크립트</h3><div id="script-text" class="script-body"></div><h3>요약 · 콘텐츠 소재</h3><div id="script-summary" class="script-body"></div><button class="btn" id="script-copy" type="button">스크립트 복사</button><p><a id="script-source-link" target="_blank" rel="noopener noreferrer">원문에서 보기</a></p></section></div>
<script type="application/json" id="dashboard-data">__DASHBOARD_JSON_DATA__</script><script>
(()=>{const dashboardData=JSON.parse(document.getElementById('dashboard-data').textContent),data=dashboardData.hospitals,registeredProducts=dashboardData.product_keywords;let selected=null,tab='summary',view='dashboard';const $=id=>document.getElementById(id),el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n},allChannels=h=>[...h.channels,...h.channel_candidates.map(c=>({...c,status:'확인 필요'}))],safeLink=(label,url)=>{const a=el('a','',label);if(url){try{const u=new URL(url);if(['http:','https:'].includes(u.protocol)){a.href=u.href;a.target='_blank';a.rel='noopener noreferrer'}}catch{}}return a},showDetail=h=>{selected=h;view='detail';tab='summary';$('hospital-list').hidden=true;$('overview').hidden=true;$('hospital-detail').hidden=false;$('global-panel').hidden=true;$('right-rail').hidden=false;$('detail-name').textContent=h.hospital_name;$('detail-address').textContent=h.region||'주소 정보 없음';$('detail-tags').replaceChildren(el('span','tag green',h.contract_status),el('span','tag orange',h.pending_channels.length?`SNS 확인 필요 ${h.pending_channels.length}`:'SNS 확인 완료'),el('span','tag',h.hospital_id));const fields=[['병원명',h.hospital_name],['대표자','정보 없음'],['지역',h.region||'정보 없음'],['주소',h.region||'정보 없음'],['홈페이지','정보 없음'],['거래 상태',h.contract_status]];$('basic-info').replaceChildren(...fields.map(([k,v])=>{const n=el('div','info');n.append(el('small','',k),el('b','',v));return n}));renderTab();renderRail();$('breadcrumb').textContent=`홈　/　병원 관리　/　${h.hospital_name}`},renderChannels=h=>{const list=allChannels(h);if(!list.length)return el('div','empty','등록된 채널이 없습니다.');const grid=el('div','two');for(const c of list){const card=el('div','channel');card.append(el('b','',`${c.platform} · ${c.channel_name}`),el('div',''));card.lastChild.append(safeLink(c.url||'링크 확인',c.url));card.append(el('span',`tag ${c.status==='자동 수집'?'green':'orange'}`,c.status));grid.append(card)}return grid},renderContents=h=>{const wrap=el('div');if(!h.contents.length)return el('div','empty','수집된 관련 콘텐츠가 없습니다.');const table=el('table'),head=el('tr');for(const x of ['콘텐츠','플랫폼','게시일','제품 분류','상태'])head.append(el('th','',x));table.append(head);for(const c of h.contents){const row=el('tr'),title=el('td');title.append(safeLink(c.title,c.url));row.append(title,el('td','',c.platform),el('td','',c.published_at||'날짜 미입력'),el('td','',c.matched_product||'미분류'),el('td','',c.relevance_status==='relevant'?'관련':'검토'));table.append(row)}wrap.append(table);return wrap},renderTab=()=>{document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('on',b.dataset.tab===tab));const h=selected,p=$('tab-panel');p.replaceChildren();if(tab==='summary'){const k=el('div','kpis');[['SNS 채널 수',allChannels(h).length],['수집 콘텐츠 수',h.contents.length],['AI 분석 결과 수',h.contents.filter(c=>c.script_summary).length]].forEach(([a,b])=>{const n=el('div','kpi');n.append(el('span','sub',a),el('b','',b));k.append(n)});p.append(k,el('h3','', '채널'));const cards=el('div','two');for(const c of allChannels(h)){const n=el('div','channel');n.append(el('b','',`${c.platform} · ${c.channel_name}`),el('div',''));n.lastChild.append(safeLink(c.url||'링크 확인',c.url));n.append(el('span',`tag ${c.status==='자동 수집'?'green':'orange'}`,c.status));cards.append(n)}p.append(cards)}else if(tab==='channels')p.append(renderChannels(h));else if(tab==='collected')p.append(renderContents(h));else if(tab==='analysis'){const brief=el('div','glass',h.briefing||'분석 요약이 없습니다.');p.append(brief,renderContents(h))}else{const cards=el('div','two');for(const m of h.materials){const n=el('div','channel');n.append(el('b','',m.material_name),el('div','sub',`${m.product_name} · ${m.quantity}개 · ${m.status}`));cards.append(n)}for(const c of h.contents.filter(x=>x.has_script)){const b=el('button','channel',`${c.title} · 스크립트 보기`);b.type='button';b.addEventListener('click',()=>openScript(h,c));cards.append(b)}p.append(cards)}},renderRail=()=>{const h=selected;if(!h){$('timeline').replaceChildren(el('div','rail-state','병원을 선택하면 업무 상태를 확인할 수 있습니다.'));$('briefing').textContent='병원에서 수집된 콘텐츠 요약이 없습니다.';return}const needs=h.pending_channels.length;$('timeline').replaceChildren(el('div','rail-state',`채널 확인 필요 · ${needs}개`),el('div','rail-state',`콘텐츠 수집 상태 · ${h.contents.length?'수집 완료':'수집 대기'}`),el('div','rail-state',`AI 분석 상태 · ${h.briefing?'분석 완료':'분석 대기'}`));$('briefing').textContent=h.briefing||'수집된 콘텐츠를 바탕으로 한 AI 요약이 아직 없습니다.'},renderList=()=>{const q=$('search-filter').value.trim().toLocaleLowerCase(),plat=$('platform-filter').value,product=$('product-filter').value,items=data.filter(h=>(!q||[h.hospital_name,h.hospital_id,h.region,...h.products,...h.contents.map(c=>c.title)].join(' ').toLocaleLowerCase().includes(q))&&(!plat||allChannels(h).some(c=>c.platform===plat))&&(!product||h.products.includes(product)||h.contents.some(c=>c.matched_product===product)));$('hospitals').replaceChildren(...items.map(h=>{const row=el('div','hospital-row');row.append(el('div','',`${h.hospital_name} · ${h.region||'지역 미입력'}`),el('span','tag',`${allChannels(h).length} 채널 · ${h.contents.length} 콘텐츠`));row.addEventListener('click',()=>showDetail(h));return row}));$('kpis').replaceChildren(...[['전체 병원',items.length],['등록 제품',registeredProducts.length],['SNS 채널',items.reduce((n,h)=>n+allChannels(h).length,0)],['수집 콘텐츠',items.reduce((n,h)=>n+h.contents.length,0)]].map(([a,b])=>{const n=el('div','kpi');n.append(el('span','sub',a),el('b','',b));return n}))},openScript=(h,c)=>{$('script-title').textContent=c.title;$('script-meta').textContent=`${h.hospital_name} · ${c.platform} · ${c.published_at||'날짜 미입력'}`;$('script-status').textContent=c.usage_status;$('script-text').textContent=c.script_text||'스크립트 수집 전';$('script-summary').textContent=c.script_summary||'요약·콘텐츠 소재가 없습니다.';$('script-source-link').href=c.url;$('script-modal').hidden=false},setView=v=>{view=v;selected=null;$('hospital-detail').hidden=true;$('overview').hidden=v!=='dashboard'&&v!=='hospitals';$('hospital-list').hidden=v!=='dashboard'&&v!=='hospitals';$('global-panel').hidden=true;$('right-rail').hidden=false;const labels={dashboard:'대시보드',hospitals:'병원 관리',channels:'SNS 채널',collected:'수집 콘텐츠',analysis:'AI 분석',creation:'콘텐츠 제작'};$('breadcrumb').textContent=`홈　/　${labels[v]}`;document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('on',b.dataset.view===v));if(['channels','collected','analysis','creation'].includes(v)){const panel=$('global-panel');panel.hidden=false;panel.replaceChildren(el('h2','',labels[v]));const matches=data.filter(h=>v==='channels'?allChannels(h).length:v==='collected'?h.contents.length:v==='analysis'?h.briefing||h.contents.some(c=>c.script_summary):h.contents.some(c=>c.has_script));for(const h of matches){const row=el('div','item');row.append(el('b','',h.hospital_name),el('div','sub',v==='channels'?`${allChannels(h).length} 채널`:v==='collected'?`${h.contents.length} 콘텐츠`:v==='analysis'?(h.briefing||'분석 요약 없음'):'스크립트 자료'));row.addEventListener('click',()=>showDetail(h));panel.append(row)}}renderList();if(v==='collected'){const gallery=el('div','gallery');for(const h of data)for(const c of h.contents){const card=el('article','gallery-item'),link=safeLink(c.title,c.url);card.append(link,el('div','sub',`${h.hospital_name} · ${c.platform} · ${c.published_at||'날짜 미입력'}`),el('span','tag',c.matched_product||'미분류'));gallery.append(card)}$('global-panel').append(gallery)}renderRail()};
for(const value of registeredProducts){const o=el('option','',value);o.value=value;$('product-filter').append(o)}for(const c of [...new Set(data.flatMap(h=>allChannels(h).map(x=>x.platform)))].sort()){const o=el('option','',c);o.value=c;$('platform-filter').append(o)}document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.view)));document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>{tab=b.dataset.tab;renderTab()}));$('back-list').addEventListener('click',()=>setView('hospitals'));$('search-filter').addEventListener('input',renderList);$('product-filter').addEventListener('change',renderList);$('platform-filter').addEventListener('change',renderList);$('script-close').addEventListener('click',()=>$('script-modal').hidden=true);$('script-modal').addEventListener('click',e=>{if(e.target===$('script-modal'))$('script-modal').hidden=true});document.addEventListener('keydown',e=>{if(e.key==='Escape')$('script-modal').hidden=true});$('script-copy').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('script-text').textContent);$('script-status').textContent='복사했습니다.'}catch{$('script-status').textContent='복사할 수 없습니다. 스크립트를 직접 선택해 복사해 주세요.'}});renderList();renderRail()})();
</script></body></html>'''
    return template.replace("__DASHBOARD_JSON_DATA__", payload)


def render_dashboard(
    repository: Repository,
    output_path: Path,
    *,
    registered_products: Sequence[str] = DEFAULT_PRODUCTS,
) -> Path:
    scripts_by_url = {script.content_url: script for script in repository.list_scripts()}
    hospitals = [_record(repository, hospital, scripts_by_url) for hospital in repository.list_hospitals()]
    payload = json.dumps(
        {"hospitals": hospitals, "product_keywords": list(registered_products)},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    payload = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    html = _dashboard_html(payload)
    output_path.write_text(html, encoding="utf-8")
    return output_path
