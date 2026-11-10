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
        "briefing": next((item.summary for item in scripts_for_hospital if item.summary), ""),
        "contents": [
            {"platform": item.platform, "title": item.title, "url": _safe_url(item.url), "matched_product": item.matched_product or "", "published_at": item.published_at.isoformat() if item.published_at else "", "evidence": item.evidence or "", "script_text": scripts[item.url].script_text if item.url in scripts else "", "script_summary": scripts[item.url].summary if item.url in scripts else "", "usage_status": scripts[item.url].usage_status if item.url in scripts else "미활용", "has_script": bool(scripts.get(item.url) and scripts[item.url].script_text)}
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
(()=>{const dashboardData=JSON.parse(document.getElementById('dashboard-data').textContent),data=dashboardData.hospitals,registeredProducts=dashboardData.product_keywords;let selected=null,tab='summary',view='dashboard';const $=id=>document.getElementById(id),el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n},allChannels=h=>[...h.channels,...h.pending_channels],safeLink=(label,url)=>{const a=el('a','',label);if(url){try{const u=new URL(url);if(['http:','https:'].includes(u.protocol)){a.href=u.href;a.target='_blank';a.rel='noopener noreferrer'}}catch{}}return a},showDetail=h=>{selected=h;view='detail';tab='summary';$('hospital-list').hidden=true;$('overview').hidden=true;$('hospital-detail').hidden=false;$('global-panel').hidden=true;$('right-rail').hidden=false;$('detail-name').textContent=h.hospital_name;$('detail-address').textContent=h.region||'주소 정보 없음';$('detail-tags').replaceChildren(el('span','tag green',h.contract_status),el('span','tag orange',h.pending_channels.length?`SNS 확인 필요 ${h.pending_channels.length}`:'SNS 확인 완료'),el('span','tag',h.hospital_id));const fields=[['병원명',h.hospital_name],['대표자','정보 없음'],['지역',h.region||'정보 없음'],['주소',h.region||'정보 없음'],['홈페이지','정보 없음'],['거래 상태',h.contract_status]];$('basic-info').replaceChildren(...fields.map(([k,v])=>{const n=el('div','info');n.append(el('small','',k),el('b','',v));return n}));renderTab();renderRail();$('breadcrumb').textContent=`홈　/　병원 관리　/　${h.hospital_name}`},renderChannels=h=>{const list=allChannels(h);if(!list.length)return el('div','empty','등록된 채널이 없습니다.');const grid=el('div','two');for(const c of list){const card=el('div','channel');card.append(el('b','',`${c.platform} · ${c.channel_name}`),el('div',''));card.lastChild.append(safeLink(c.url||'링크 확인',c.url));card.append(el('span',`tag ${c.status==='자동 수집'?'green':'orange'}`,c.status));grid.append(card)}return grid},renderContents=h=>{const wrap=el('div');if(!h.contents.length)return el('div','empty','수집된 관련 콘텐츠가 없습니다.');const table=el('table'),head=el('tr');for(const x of ['콘텐츠','플랫폼','게시일','제품 분류','상태'])head.append(el('th','',x));table.append(head);for(const c of h.contents){const row=el('tr'),title=el('td');title.append(safeLink(c.title,c.url));row.append(title,el('td','',c.platform),el('td','',c.published_at||'날짜 미입력'),el('td','',c.matched_product||'미분류'),el('td','',c.relevance_status==='relevant'?'관련':'검토'));table.append(row)}wrap.append(table);return wrap},renderTab=()=>{document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('on',b.dataset.tab===tab));const h=selected,p=$('tab-panel');p.replaceChildren();if(tab==='summary'){const k=el('div','kpis');[['SNS 채널 수',allChannels(h).length],['수집 콘텐츠 수',h.contents.length],['AI 분석 결과 수',h.contents.filter(c=>c.script_summary).length]].forEach(([a,b])=>{const n=el('div','kpi');n.append(el('span','sub',a),el('b','',b));k.append(n)});p.append(k,el('h3','', '채널'));const cards=el('div','two');for(const c of allChannels(h)){const n=el('div','channel');n.append(el('b','',`${c.platform} · ${c.channel_name}`),el('div',''));n.lastChild.append(safeLink(c.url||'링크 확인',c.url));n.append(el('span',`tag ${c.status==='자동 수집'?'green':'orange'}`,c.status));cards.append(n)}p.append(cards)}else if(tab==='channels')p.append(renderChannels(h));else if(tab==='collected')p.append(renderContents(h));else if(tab==='analysis'){const brief=el('div','glass',h.briefing||'분석 요약이 없습니다.');p.append(brief,renderContents(h))}else{const cards=el('div','two');for(const m of h.materials){const n=el('div','channel');n.append(el('b','',m.material_name),el('div','sub',`${m.product_name} · ${m.quantity}개 · ${m.status}`));cards.append(n)}for(const c of h.contents.filter(x=>x.has_script)){const b=el('button','channel',`${c.title} · 스크립트 보기`);b.type='button';b.addEventListener('click',()=>openScript(h,c));cards.append(b)}p.append(cards)}},renderRail=()=>{const h=selected;if(!h){$('timeline').replaceChildren(el('div','rail-state','병원을 선택하면 업무 상태를 확인할 수 있습니다.'));$('briefing').textContent='병원에서 수집된 콘텐츠 요약이 없습니다.';return}const needs=h.pending_channels.length;$('timeline').replaceChildren(el('div','rail-state',`채널 확인 필요 · ${needs}개`),el('div','rail-state',`콘텐츠 수집 상태 · ${h.contents.length?'수집 완료':'수집 대기'}`),el('div','rail-state',`AI 분석 상태 · ${h.briefing?'분석 완료':'분석 대기'}`));$('briefing').textContent=h.briefing||'수집된 콘텐츠를 바탕으로 한 AI 요약이 아직 없습니다.'},renderList=()=>{const q=$('search-filter').value.trim().toLocaleLowerCase(),plat=$('platform-filter').value,product=$('product-filter').value,items=data.filter(h=>(!q||[h.hospital_name,h.hospital_id,h.region,...h.products,...h.contents.map(c=>c.title)].join(' ').toLocaleLowerCase().includes(q))&&(!plat||allChannels(h).some(c=>c.platform===plat))&&(!product||h.products.includes(product)||h.contents.some(c=>c.matched_product===product)));$('hospitals').replaceChildren(...items.map(h=>{const row=el('div','hospital-row');row.append(el('div','',`${h.hospital_name} · ${h.region||'지역 미입력'}`),el('span','tag',`${allChannels(h).length} 채널 · ${h.contents.length} 콘텐츠`));row.addEventListener('click',()=>showDetail(h));return row}));$('kpis').replaceChildren(...[['전체 병원',items.length],['등록 제품',registeredProducts.length],['SNS 채널',items.reduce((n,h)=>n+allChannels(h).length,0)],['수집 콘텐츠',items.reduce((n,h)=>n+h.contents.length,0)]].map(([a,b])=>{const n=el('div','kpi');n.append(el('span','sub',a),el('b','',b));return n}))},openScript=(h,c)=>{$('script-title').textContent=c.title;$('script-meta').textContent=`${h.hospital_name} · ${c.platform} · ${c.published_at||'날짜 미입력'}`;$('script-status').textContent=c.usage_status;$('script-text').textContent=c.script_text||'스크립트 수집 전';$('script-summary').textContent=c.script_summary||'요약·콘텐츠 소재가 없습니다.';$('script-source-link').href=c.url;$('script-modal').hidden=false},setView=v=>{view=v;selected=null;$('hospital-detail').hidden=true;$('overview').hidden=v!=='dashboard'&&v!=='hospitals';$('hospital-list').hidden=v!=='dashboard'&&v!=='hospitals';$('global-panel').hidden=true;$('right-rail').hidden=false;const labels={dashboard:'대시보드',hospitals:'병원 관리',channels:'SNS 채널',collected:'수집 콘텐츠',analysis:'AI 분석',creation:'콘텐츠 제작'};$('breadcrumb').textContent=`홈　/　${labels[v]}`;document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('on',b.dataset.view===v));if(['channels','collected','analysis','creation'].includes(v)){const panel=$('global-panel');panel.hidden=false;panel.replaceChildren(el('h2','',labels[v]));const matches=data.filter(h=>v==='channels'?allChannels(h).length:v==='collected'?h.contents.length:v==='analysis'?h.briefing||h.contents.some(c=>c.script_summary):h.contents.some(c=>c.has_script));for(const h of matches){const row=el('div','item');row.append(el('b','',h.hospital_name),el('div','sub',v==='channels'?`${allChannels(h).length} 채널`:v==='collected'?`${h.contents.length} 콘텐츠`:v==='analysis'?(h.briefing||'분석 요약 없음'):'스크립트 자료'));row.addEventListener('click',()=>showDetail(h));panel.append(row)}}renderList();if(v==='collected'){const gallery=el('div','gallery');for(const h of data)for(const c of h.contents){const card=el('article','gallery-item'),link=safeLink(c.title,c.url);card.append(link,el('div','sub',`${h.hospital_name} · ${c.platform} · ${c.published_at||'날짜 미입력'}`),el('span','tag',c.matched_product||'미분류'));gallery.append(card)}$('global-panel').append(gallery)}renderRail()};
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
    html = r'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>병원 거래처 대시보드</title>
<style>
:root{--bg:#ffffff;--side:#f7f7f5;--text:#37352f;--sub:#787774;--line:#e9e9e7;--hover:#f1f1ef;--bar:#37352f;--bar-soft:#d9d9d6;--blue-bg:#e7f3f8;--blue-tx:#183347;--green-bg:#edf3ec;--green-tx:#1c3829;--gray-bg:#f1f1ef;--gray-tx:#787774;color-scheme:light}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#191919;--side:#202020;--text:#e6e6e4;--sub:#9b9a97;--line:#2f2f2f;--hover:#2a2a2a;--bar:#e6e6e4;--bar-soft:#3a3a38;--blue-bg:#1f3a4a;--blue-tx:#d3e5ef;--green-bg:#243b2d;--green-tx:#dbeddb;--gray-bg:#2a2a2a;--gray-tx:#9b9a97;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#191919;--side:#202020;--text:#e6e6e4;--sub:#9b9a97;--line:#2f2f2f;--hover:#2a2a2a;--bar:#e6e6e4;--bar-soft:#3a3a38;--blue-bg:#1f3a4a;--blue-tx:#d3e5ef;--green-bg:#243b2d;--green-tx:#dbeddb;--gray-bg:#2a2a2a;--gray-tx:#9b9a97;color-scheme:dark}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--text)}body{display:flex;min-height:100vh;font:15px/1.6 "Pretendard","Noto Sans KR",-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",sans-serif}
.side{width:240px;flex-shrink:0;position:sticky;top:0;height:100vh;overflow:auto;padding:16px 8px;background:var(--side);border-right:1px solid var(--line)}.ws{padding:6px 10px;font-weight:700;margin-bottom:12px}.side-link{display:flex;width:100%;gap:8px;align-items:center;padding:5px 10px;border:0;border-radius:4px;background:transparent;color:var(--text);text-align:left;font:inherit;font-size:14px;cursor:pointer}.side-link:hover,.side-link.on{background:var(--hover)}.side-link.on{font-weight:500}
main{flex:1;min-width:0;padding:48px 24px 80px}.wrap{max-width:900px;margin:0 auto}.title-row{display:flex;gap:16px;align-items:flex-start}.emoji{font-size:48px;line-height:1}h1{font-size:36px;font-weight:700;margin:0;letter-spacing:-.5px}.desc{color:var(--sub);margin:4px 0 20px}.tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin:12px 0 24px}.tab{background:none;border:0;border-bottom:2px solid transparent;color:var(--sub);font:inherit;font-size:14px;padding:6px 12px;cursor:pointer;margin-bottom:-1px}.tab:hover{background:var(--hover);border-radius:4px 4px 0 0}.tab.on{color:var(--text);border-bottom-color:var(--text);font-weight:500}
.dataset-label{margin:0 0 12px;color:var(--sub);font:600 12px system-ui,sans-serif;letter-spacing:.16em}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.card{min-width:0;border:1px solid var(--line);border-radius:6px;padding:14px 16px}.card-label{font-size:13px;color:var(--sub)}.card-value{font-size:26px;font-weight:700;margin:2px 0;letter-spacing:-.5px;overflow-wrap:anywhere}.tag{display:inline-block;margin:2px 4px 2px 0;padding:0 6px;border-radius:4px;font-size:12px;line-height:20px;font-weight:500;background:var(--blue-bg);color:var(--blue-tx)}.tag.green{background:var(--green-bg);color:var(--green-tx)}.tag.gray{background:var(--gray-bg);color:var(--gray-tx)}
h2{font-size:20px;font-weight:700;margin:36px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line)}.rows{display:flex;flex-direction:column;gap:4px}.rw{display:grid;grid-template-columns:112px 1fr 48px;align-items:center;gap:12px;padding:6px 8px;border-radius:4px}.rw.click{cursor:pointer}.rw:hover,.rw.on{background:var(--hover)}.rw-label{font-size:14px}.track{height:8px;background:var(--bar-soft);border-radius:2px;overflow:hidden}.fill{height:100%;background:var(--bar);border-radius:2px}.rw-count{text-align:right;color:var(--sub);font-size:13px}
.tools{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px}.tools input,.tools select{flex:1;min-width:150px;min-height:36px;border:1px solid var(--line);border-radius:4px;padding:5px 10px;background:var(--bg);color:var(--text);font:inherit;font-size:14px}.tools input:focus,.tools select:focus{outline:2px solid var(--sub);outline-offset:1px}.chip{border:1px solid var(--line);background:transparent;color:var(--text);border-radius:4px;padding:3px 10px;font:inherit;font-size:13px;cursor:pointer}.chip:hover{background:var(--hover)}.chip.on{background:var(--text);color:var(--bg);border-color:var(--text)}
.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;min-width:620px}th{text-align:left;font-weight:500;font-size:13px;color:var(--sub);padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}td{padding:10px;border-bottom:1px solid var(--line);vertical-align:top}tbody tr:hover{background:var(--hover)}.hospital-name{font-weight:500}.sub{display:block;color:var(--sub);font-size:12px}.stack{display:flex;flex-direction:column;gap:4px}.detail{font-size:13px}.dim{color:var(--sub)}td a{color:var(--text);text-decoration:underline;text-decoration-color:var(--bar-soft);text-underline-offset:3px}td a:hover{text-decoration-color:var(--text)}
.gal{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.gal[hidden]{display:none}.vc{display:block;color:inherit;text-decoration:none;border:1px solid var(--line);border-radius:6px;overflow:hidden}.vc:hover{background:var(--hover)}.thumb{aspect-ratio:16/9;background:var(--side);display:flex;align-items:center;justify-content:center;font-size:28px;color:var(--sub);border-bottom:1px solid var(--line)}.vb{padding:10px 12px}.vt{font-weight:500;font-size:14px;line-height:1.4;margin-bottom:6px}.vm{font-size:12px;color:var(--sub);display:flex;gap:6px;flex-wrap:wrap;align-items:center}.empty{padding:24px 10px;color:var(--sub);text-align:center}.section[hidden],.table-wrap[hidden]{display:none}.script-products{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.script-status{display:flex;flex-direction:column;gap:4px;margin:12px 0}.script-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.script-card{border:1px solid var(--line);border-radius:6px;padding:16px;cursor:pointer;background:var(--bg);color:var(--text);text-align:left;font:inherit}.script-card:hover{background:var(--hover)}.script-modal{position:fixed;inset:0;background:#0008;display:grid;place-items:center;padding:20px;z-index:10}.script-modal[hidden]{display:none}.script-dialog{position:relative;width:min(680px,100%);max-height:85vh;overflow:auto;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:24px}.script-close{position:absolute;right:12px;top:12px}.script-copy{margin:12px 8px 12px 0}.script-body{white-space:pre-wrap}.script-notice{color:var(--sub);font-size:13px}@media(max-width:760px){.script-cards{grid-template-columns:1fr}}
@media(max-width:1000px){.gal{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:760px){.side{display:none}main{padding:32px 16px 64px}.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.gal{grid-template-columns:1fr}h1{font-size:28px}.emoji{font-size:40px}}
</style>
</head>
<body>
<nav class="side" aria-label="주요 메뉴">
  <div class="ws">📁 병원 거래처</div>
  <button class="side-link on" type="button" data-view="sales">💼 영업부</button>
  <button class="side-link" type="button" data-view="marketing">📣 마케팅부</button>
  <button class="side-link" type="button" data-view="content">🎬 콘텐츠 피드</button>
  <button class="side-link" type="button" data-view="scripts">✍️ 콘텐츠 제작</button>
</nav>
<main><div class="wrap">
  <p class="dataset-label">MOCK DATA · MARKETING WIKI</p>
  <div class="title-row"><div class="emoji">🏥</div><div><h1>병원 거래처 대시보드</h1><p class="desc">병원·제품·온라인 마케팅 데이터를 한곳에서 확인합니다.</p></div></div>
  <div class="tabs" role="tablist" aria-label="대시보드 보기">
    <button class="tab on" type="button" role="tab" aria-selected="true" data-view="sales">💼 영업부</button>
    <button class="tab" type="button" role="tab" aria-selected="false" data-view="marketing">📣 마케팅부</button>
    <button class="tab" type="button" role="tab" aria-selected="false" data-view="content">🎬 콘텐츠</button>
    <button class="tab" type="button" role="tab" aria-selected="false" data-view="scripts">✍️ 콘텐츠 제작</button>
  </div>
  <div class="kpis" id="kpis"></div>
  <section class="section" id="aggregate-section"><h2 id="aggregate-heading"></h2><div class="rows" id="aggregate"></div></section>
  <section class="section"><h2 id="table-heading">🏥 병원 목록</h2>
    <div class="tools" aria-label="병원 필터">
      <input id="search-filter" type="search" placeholder="병원명·지역·제품·콘텐츠 검색" aria-label="병원명, 지역, 제품 또는 콘텐츠 검색">
      <select id="product-filter" aria-label="제품 필터"><option value="">전체 제품</option></select>
      <select id="platform-filter" aria-label="채널 필터"><option value="">전체 채널</option></select>
    </div>
    <div class="tools" id="region-chips" aria-label="지역 필터"></div>
    <div class="table-wrap" id="table-wrap"><table><thead id="table-head"></thead><tbody id="table-body"></tbody></table><div class="empty" id="table-empty" hidden>검색 결과가 없어요.</div></div>
    <div class="gal" id="content-feed" hidden></div>
    <div id="script-view" hidden>
      <p class="script-notice">병원 영상·글은 병원의 저작물이므로 SNS 활용 시 사전 허락과 출처 표기가 필요합니다. 스크립트는 소재 발굴·참고용입니다.</p>
      <div class="script-status" id="script-status"></div><div class="script-products" id="script-products"></div><div class="script-cards" id="script-cards"></div>
    </div>
  </section>
</div></main>
<div class="script-modal" id="script-modal" hidden><section class="script-dialog" role="dialog" aria-modal="true" aria-labelledby="script-modal-title"><button class="chip script-close" id="script-close" type="button" aria-label="닫기">✕</button><h2 id="script-modal-title"></h2><div id="script-modal-meta" class="script-notice"></div><p id="script-modal-status"></p><h3>스크립트</h3><div id="script-modal-body" class="script-body"></div><h3>요약 · 콘텐츠 소재</h3><div id="script-modal-summary" class="script-body"></div><button class="chip script-copy" id="script-copy" type="button">스크립트 복사</button><a id="script-source-link" target="_blank" rel="noopener noreferrer">원문에서 보기</a><p class="script-notice">병원 영상·글은 병원의 저작물이므로 SNS 활용 시 사전 허락과 출처 표기가 필요합니다. 스크립트는 소재 발굴·참고용입니다.</p></section></div>
<script type="application/json" id="dashboard-data">__DASHBOARD_JSON_DATA__</script>
<script>
(() => {
  const dashboardData = JSON.parse(document.getElementById('dashboard-data').textContent);
  const data = dashboardData.hospitals;
  const registeredProducts = dashboardData.product_keywords;
  const search = document.getElementById('search-filter');
  const product = document.getElementById('product-filter');
  const platform = document.getElementById('platform-filter');
  const kpis = document.getElementById('kpis');
  const aggregate = document.getElementById('aggregate');
  const aggregateHeading = document.getElementById('aggregate-heading');
  const tableHead = document.getElementById('table-head');
  const tableBody = document.getElementById('table-body');
  const tableWrap = document.getElementById('table-wrap');
  const tableEmpty = document.getElementById('table-empty');
  const feed = document.getElementById('content-feed');
  const scriptView = document.getElementById('script-view');
  const scriptCards = document.getElementById('script-cards');
  const scriptProducts = document.getElementById('script-products');
  const scriptStatus = document.getElementById('script-status');
  const scriptModal = document.getElementById('script-modal');
  const tableHeading = document.getElementById('table-heading');
  let view = 'sales';
  let selectedRegion = '';
  let selectedScriptProduct = '';

  function formatDate(value, emptyLabel) {
    return value ? value.slice(0, 10).replace(/-/g, '.') : (emptyLabel || '–');
  }
  const el = (tag, className, value) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = value;
    return node;
  };
  const unique = values => [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b, 'ko'));
  const regionGroup = value => value ? value.split('/')[0] : '';
  const productsFor = h => [...h.products, ...h.deliveries.map(x => x.product_name), ...h.materials.map(x => x.product_name), ...h.contents.map(x => x.matched_product)].filter(Boolean);
  const platformsFor = h => [...h.channels.map(x => x.platform), ...h.contents.map(x => x.platform)].filter(Boolean);
  const allPlatforms = unique(data.flatMap(platformsFor));
  for (const value of registeredProducts) { const option = el('option', '', value); option.value = value; product.append(option); }
  for (const value of allPlatforms) { const option = el('option', '', value); option.value = value; platform.append(option); }

  function addOptions(row, labels) {
    const tr = el('tr');
    for (const label of labels) tr.append(el('th', '', label));
    row.replaceChildren(tr);
  }
  function cell(row, value, className) {
    const td = el('td', className || '', value || '–');
    row.append(td);
    return td;
  }
  function tags(row, values) {
    const td = el('td');
    if (!values.length) td.textContent = '–';
    for (const value of values) td.append(el('span', 'tag', value));
    row.append(td);
  }
  function link(label, url) {
    const node = el('a', '', label);
    if (url) { node.href = url; node.target = '_blank'; node.rel = 'noopener noreferrer'; }
    return node;
  }
  function listCell(row, values, formatter) {
    const td = el('td');
    if (!values.length) td.textContent = '–';
    else {
      const stack = el('div', 'stack');
      for (const value of values) { const item = el('div', 'detail'); formatter(item, value); stack.append(item); }
      td.append(stack);
    }
    row.append(td);
  }
  function card(label, value, note, tone) {
    const node = el('div', 'card');
    node.append(el('div', 'card-label', label), el('div', 'card-value', String(value)));
    if (note) node.append(el('span', `tag ${tone || ''}`, note));
    return node;
  }
  function showCards(items) { kpis.replaceChildren(...items); }
  function bars(title, counts, clickable, unit) {
    aggregateHeading.textContent = title;
    aggregate.replaceChildren();
    const max = Math.max(1, ...Object.values(counts));
    const countUnit = unit || '곳';
    for (const [label, count] of Object.entries(counts)) {
      const row = el('div', `rw${clickable ? ' click' : ''}${selectedRegion === label ? ' on' : ''}`);
      row.append(el('div', 'rw-label', label));
      const track = el('div', 'track');
      const fill = el('div', 'fill'); fill.style.width = `${count / max * 100}%`; track.append(fill);
      row.append(track, el('div', 'rw-count', `${count}${countUnit}`));
      if (clickable) row.addEventListener('click', () => { selectedRegion = selectedRegion === label ? '' : label; render(); });
      aggregate.append(row);
    }
    if (!Object.keys(counts).length) aggregate.append(el('div', 'empty', '표시할 현황이 없습니다.'));
  }
  function filteredHospitals() {
    const query = search.value.trim().toLocaleLowerCase();
    return data.filter(h => {
      const regionMatch = !selectedRegion || regionGroup(h.region) === selectedRegion;
      if (view === 'content' || view === 'scripts') return regionMatch;
      const searchable = [h.hospital_id, h.hospital_name, h.region, ...productsFor(h), ...h.deliveries.map(x => `${x.product_name} ${x.delivery_date} ${x.quantity}`), ...h.materials.map(x => `${x.product_name} ${x.material_name} ${x.quantity} ${x.status}`), ...h.channels.map(x => `${x.platform} ${x.channel_name}`), ...h.contents.map(x => `${x.platform} ${x.title} ${x.matched_product} ${x.evidence}`)].join(' ').toLocaleLowerCase();
      const productMatch = !product.value || productsFor(h).includes(product.value);
      const platformMatch = !platform.value || platformsFor(h).includes(platform.value);
      return (!query || searchable.includes(query)) && productMatch && platformMatch && regionMatch;
    });
  }
  function renderChips() {
    const chips = document.getElementById('region-chips');
    chips.replaceChildren();
    const regions = unique(data.map(h => regionGroup(h.region)));
    for (const value of ['', ...regions]) {
      const label = value || '전체 지역';
      const button = el('button', `chip${selectedRegion === value ? ' on' : ''}`, label);
      button.type = 'button';
      button.addEventListener('click', () => { selectedRegion = value; render(); });
      chips.append(button);
    }
  }
  function hospitalCell(row, hospital) {
    const td = el('td');
    td.append(el('div', 'hospital-name', hospital.hospital_name), el('span', 'sub', hospital.hospital_id));
    row.append(td);
  }
  function renderSales(hospitals) {
    const regions = {};
    for (const h of hospitals) { const group = regionGroup(h.region); if (group) regions[group] = (regions[group] || 0) + 1; }
    const deliveries = hospitals.reduce((count, h) => count + h.deliveries.length, 0);
    showCards([card('전체 병원', hospitals.length, '곳'), card('지역 그룹', Object.keys(regions).length, '개 권역', 'gray'), card('등록 제품', registeredProducts.length, '종', 'green'), card('납품 기록', deliveries, '건', 'gray')]);
    bars('📍 지역별 현황', regions, true);
    tableHeading.textContent = '🏥 병원 목록';
    addOptions(tableHead, ['병원명', '지역', '계약일', '제품', '납품 내역']);
    tableBody.replaceChildren();
    for (const h of hospitals) {
      const row = el('tr'); hospitalCell(row, h); cell(row, h.region); cell(row, formatDate(h.contract_date)); tags(row, h.products);
      listCell(row, h.deliveries, (node, item) => { node.textContent = `${item.product_name} · 수량 ${item.quantity}`; });
      tableBody.append(row);
    }
    tableEmpty.hidden = hospitals.length > 0;
  }
  function renderMarketing(hospitals) {
    const channelCount = hospitals.reduce((count, h) => count + h.channels.length, 0);
    const materialCount = hospitals.reduce((count, h) => count + h.materials.length, 0);
    const contentCount = hospitals.reduce((count, h) => count + h.contents.length, 0);
    const channelHospitals = hospitals.filter(h => h.channels.length).length;
    const platforms = {};
    for (const h of hospitals) for (const value of platformsFor(h)) platforms[value] = (platforms[value] || 0) + 1;
    showCards([card('채널 등록 병원', channelHospitals, '곳'), card('온라인 채널', channelCount, '개', 'green'), card('홍보물 기록', materialCount, '건', 'gray'), card('관련 콘텐츠', contentCount, '건')]);
    bars('📣 플랫폼별 등록 현황', platforms, false, '건');
    tableHeading.textContent = '📣 병원별 마케팅 정보';
    addOptions(tableHead, ['병원명', '홍보 물품', '온라인 채널', '제품 관련 콘텐츠']);
    tableBody.replaceChildren();
    for (const h of hospitals) {
      const row = el('tr'); hospitalCell(row, h);
      listCell(row, h.materials, (node, item) => { node.textContent = `${item.product_name} · ${item.material_name} · 수량 ${item.quantity} · ${item.status}`; });
      listCell(row, h.channels, (node, item) => node.append(link(`${item.platform} · ${item.channel_name}`, item.url)));
      listCell(row, h.contents, (node, item) => node.append(link(`${item.platform} · ${item.title}`, item.url)));
      tableBody.append(row);
    }
    tableEmpty.hidden = hospitals.length > 0;
  }
  function renderContent(hospitals) {
    const query = search.value.trim().toLocaleLowerCase();
    const items = hospitals.flatMap(h => h.contents.map(content => ({hospital: h, content})))
      .filter(({hospital, content}) => {
        const text = [hospital.hospital_name, hospital.region, content.platform, content.title, content.matched_product, content.evidence].join(' ').toLocaleLowerCase();
        const productMatch = !product.value || content.matched_product === product.value;
        return (!query || text.includes(query)) && (!platform.value || content.platform === platform.value) && productMatch;
      })
      .sort((a, b) => (b.content.published_at || '').localeCompare(a.content.published_at || ''));
    const publishers = unique(items.map(item => item.hospital.hospital_id)).length;
    const latest = items.length ? formatDate(items[0].content.published_at, '날짜 미입력') : '–';
    showCards([card('관련 콘텐츠', items.length, '건'), card('콘텐츠 등록 병원', publishers, '곳', 'green'), card('플랫폼', unique(items.map(item => item.content.platform)).length, '개', 'gray'), card('최근 게시', latest, '최신')]);
    bars('🎬 업로드 플랫폼', items.reduce((counts, item) => { const name = item.content.platform || '플랫폼 미입력'; counts[name] = (counts[name] || 0) + 1; return counts; }, {}), false, '건');
    tableHeading.textContent = '🎬 콘텐츠 피드 (최신순)';
    feed.replaceChildren();
    for (const {hospital, content} of items) {
      const article = link('', content.url); article.className = 'vc';
      const thumb = el('div', 'thumb', '▶');
      const body = el('div', 'vb');
      body.append(el('div', 'vt', content.title), el('div', 'vm', `${hospital.hospital_name} · ${content.platform} · ${formatDate(content.published_at, '날짜 미입력')}`));
      if (content.matched_product) body.append(el('span', 'tag', content.matched_product));
      article.append(thumb, body); feed.append(article);
    }
    if (!items.length) { const empty = el('div', 'empty', '조건에 맞는 콘텐츠가 없습니다.'); empty.style.gridColumn = '1 / -1'; feed.append(empty); }
  }
  function renderScripts(hospitals) {
    const items = hospitals.flatMap(h => h.contents.map(content => ({hospital: h, content})))
      .filter(({hospital, content}) => {
        const searchText = [hospital.hospital_name, content.title, content.matched_product, content.platform].join(' ').toLocaleLowerCase();
        return (!search.value.trim() || searchText.includes(search.value.trim().toLocaleLowerCase())) && (!product.value || content.matched_product === product.value) && (!selectedScriptProduct || (selectedScriptProduct === '기타' ? !registeredProducts.includes(content.matched_product) : content.matched_product === selectedScriptProduct)) && (!platform.value || content.platform === platform.value);
      }).sort((a, b) => (b.content.published_at || '').localeCompare(a.content.published_at || ''));
    const counts = {'미활용': 0, '제작 중': 0, '게시 완료': 0};
    for (const {content} of items) counts[content.usage_status] = (counts[content.usage_status] || 0) + 1;
    const collected = items.filter(item => item.content.has_script).length;
    showCards([card('스크립트 수집', `${collected}/${items.length}`, '건'), card('미활용', counts['미활용'], '건', 'gray'), card('제작 중', counts['제작 중'], '건'), card('게시 완료', counts['게시 완료'], '건', 'green')]);
    const productCounts = {};
    for (const {content} of items) { const name = registeredProducts.includes(content.matched_product) ? content.matched_product : '기타'; productCounts[name] = (productCounts[name] || 0) + 1; }
    scriptProducts.replaceChildren();
    for (const name of ['전체', ...Object.keys(productCounts).sort((a,b) => a.localeCompare(b, 'ko'))]) {
      const button = el('button', `chip${(name === '전체' && !selectedScriptProduct) || selectedScriptProduct === name ? ' on' : ''}`, `${name} ${name === '전체' ? items.length : productCounts[name]}`);
      button.type = 'button'; button.addEventListener('click', () => { selectedScriptProduct = name === '전체' ? '' : name; render(); }); scriptProducts.append(button);
    }
    scriptStatus.replaceChildren();
    const maxStatus = Math.max(1, ...Object.values(counts));
    for (const [name, count] of Object.entries(counts)) {
      const row = el('div', `rw click${search.dataset.usageStatus === name ? ' on' : ''}`);
      row.setAttribute('role', 'button'); row.tabIndex = 0;
      const track = el('div', 'track'); const fill = el('div', 'fill'); fill.style.width = `${count / maxStatus * 100}%`; track.append(fill);
      row.append(el('div', 'rw-label', name), track, el('div', 'rw-count', `${count}건`));
      const toggleStatus = () => { search.dataset.usageStatus = search.dataset.usageStatus === name ? '' : name; render(); };
      row.addEventListener('click', toggleStatus); row.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggleStatus(); } }); scriptStatus.append(row);
    }
    const shown = search.dataset.usageStatus ? items.filter(({content}) => content.usage_status === search.dataset.usageStatus) : items;
    scriptCards.replaceChildren();
    for (const {hospital, content} of shown) {
      const button = el('button', 'script-card'); button.type = 'button';
      button.append(el('div', 'vt', content.title), el('div', 'vm', `${hospital.hospital_name} · ${formatDate(content.published_at, '날짜 미입력')}`), el('span', `tag ${content.usage_status === '게시 완료' ? 'green' : content.usage_status === '미활용' ? 'gray' : ''}`, content.usage_status), el('div', 'sub', content.has_script ? '스크립트 보기 ›' : '스크립트 수집 전'));
      button.addEventListener('click', () => openScriptModal(hospital, content)); scriptCards.append(button);
    }
    if (!shown.length) scriptCards.append(el('div', 'empty', '조건에 맞는 콘텐츠가 없습니다.'));
    tableHeading.textContent = '✍️ 콘텐츠 제작 현황';
  }
  function openScriptModal(hospital, content) {
    document.getElementById('script-modal-title').textContent = content.title;
    document.getElementById('script-modal-meta').textContent = `${hospital.hospital_name} · ${content.platform} · ${formatDate(content.published_at, '날짜 미입력')}`;
    document.getElementById('script-modal-status').textContent = content.usage_status;
    document.getElementById('script-modal-body').textContent = content.script_text || '스크립트 수집 전';
    document.getElementById('script-modal-summary').textContent = content.script_summary || '요약·콘텐츠 소재가 없습니다.';
    const source = document.getElementById('script-source-link');
    const safe = new URL(content.url, window.location.href);
    if (['http:', 'https:'].includes(safe.protocol)) { source.href = safe.href; source.hidden = false; } else source.hidden = true;
    scriptModal.hidden = false; document.getElementById('script-close').focus();
  }
  function closeScriptModal() { scriptModal.hidden = true; }
  document.getElementById('script-close').addEventListener('click', closeScriptModal);
  scriptModal.addEventListener('click', event => { if (event.target === scriptModal) closeScriptModal(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !scriptModal.hidden) closeScriptModal(); });
  document.getElementById('script-copy').addEventListener('click', async () => {
    const body = document.getElementById('script-modal-body');
    try { if (!navigator.clipboard) throw new Error('clipboard unavailable'); await navigator.clipboard.writeText(body.textContent); document.getElementById('script-modal-status').textContent = '복사했습니다.'; }
    catch { const selection = window.getSelection(); const range = document.createRange(); range.selectNodeContents(body); selection.removeAllRanges(); selection.addRange(range); document.getElementById('script-modal-status').textContent = '복사 실패 — 스크립트가 선택되었습니다. 직접 복사해 주세요.'; }
  });
  function render() {
    document.querySelectorAll('[data-view]').forEach(button => {
      const active = button.dataset.view === view;
      button.classList.toggle('on', active);
      if (button.getAttribute('role') === 'tab') button.setAttribute('aria-selected', String(active));
    });
    renderChips();
    const hospitals = filteredHospitals();
    const contentView = view === 'content';
    const scriptsView = view === 'scripts';
    document.getElementById('aggregate-section').hidden = contentView || scriptsView;
    tableWrap.hidden = contentView || scriptsView;
    feed.hidden = !contentView;
    scriptView.hidden = !scriptsView;
    if (contentView) { tableEmpty.hidden = true; renderContent(hospitals); }
    else if (scriptsView) renderScripts(hospitals);
    else if (view === 'marketing') renderMarketing(hospitals);
    else renderSales(hospitals);
  }
  document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => { view = button.dataset.view; render(); }));
  search.addEventListener('input', render);
  product.addEventListener('change', render);
  platform.addEventListener('change', render);
  render();
})();
</script>
</body>
</html>
'''.replace('__DASHBOARD_JSON_DATA__', payload)
    html = _dashboard_html(payload)
    output_path.write_text(html, encoding="utf-8")
    return output_path
