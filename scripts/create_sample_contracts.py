"""data/source/<날짜>/ 아래에 importer 형식(Hospitals + 마케팅 보강 시트)의 날짜별 누적 테스트 원본 생성."""
from datetime import date, datetime
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font

ROOT = Path(__file__).resolve().parents[1] / 'data' / 'source'
PRODUCTS = ('울트라클리어', '리뉴비온', '피아모')
PLATFORMS = ('Instagram', 'YouTube', 'Blog')

# 실제 병원 공개 정보를 조사해 병원명·대표명을 한 글자씩 바꾼 목업 (연락처는 가상)
H = [
    ['피어봉의원', '서울/강남', '장효성'], ['루미피부과의원', '서울/신사', '김재운'],
    ['더퍼스터피부과의원', '부산', '황성한'], ['청담글래스피부과의원', '서울/청담', '주홍민'],
    ['아트니의원', '대구', '강민제'], ['라인피부과의원', '서울/강남', '권혁민'],
    ['갤럭사성형외과의원', '부산', '신정운'], ['삼성밝은피부과의원', '경기/분당', '박세윤'],
    ['나윤의원', '서울/마포', '이고운'], ['팜의원', '대전', '강경환'],
    # 20261102 신규
    ['셀빈의원', '서울/강남', '김유승'], ['서운피부과의원', '경상/김해', '서치원'],
    ['리저부성형외과의원', '부산', '강경도'], ['서울리저피부과의원', '서울/강남', '김성옥'],
    # 20261103 신규
    ['창주피부과의원', '경상/울산', '곽태은'], ['유앤비의원', '서울/마포', '고성규'],
    ['메디아투의원', '부산', '송경호'],
    # 20261106 신규
    ['강남온샤인의원', '서울/강남', '김선창'], ['황피부과의원', '서울/송파', '홍민수'],
    ['강남셀리핑의원', '서울/강남', '이영지'], ['유엔아이의원', '서울/목동', '박지운'],
]
CUTS = [('20261102', 0, 14), ('20261103', 14, 17), ('20261106', 17, 21)]
BOLD = Font(name='맑은 고딕', size=11, bold=True)


def contract_day(i):
    for d, start, end in CUTS:
        if start <= i < end and i >= 10:
            return date(int(d[:4]), int(d[4:6]), int(d[6:]))
    return date(2026, 10, 1 + i * 2)  # 기존 10곳: 10월 계약


def rows_for(n, file_date):
    hosp, dlv, mat, ch, cont, scripts = [], [], [], [], [], []
    for i in range(n):
        name, region, rep = H[i]
        hid = f'HM-{i + 1:03d}'
        cd = contract_day(i)
        p = PRODUCTS[i % 3]
        plat = PLATFORMS[i % 3]
        slug = f'https://example.test/{hid.lower()}'
        hosp.append([hid, name, region, rep, f'010-3456-{7801 + i}', cd, datetime(cd.year, cd.month, cd.day, 9, 0)])
        dlv.append([hid, p, cd, 1 + i % 2])
        mat.append([hid, p, '제품 소개 리플릿', 10, '준비 완료' if i % 2 == 0 else '준비 중'])
        ch.append([hid, plat, f'{name} 공식 {plat}', f'{slug}/{plat.lower()}'])
        cont.append([hid, plat, f'{p} 시술 후기', f'{slug}/content/1', f'{name}의 {p} 관련 목업 게시물', cd, p, 'relevant'])
        if i in (0, 1, 2, 3):
            status = ('제작 중' if file_date != '20261102' else '미활용') if i == 0 else ('제작 중' if i == 1 else '게시 완료' if i == 2 else '미활용')
            scripts.append([f'{slug}/content/1', f'(샘플) {p}에 관한 가상 콘텐츠 안내 문장입니다.', '' if i == 1 else f'{p}의 가상 콘텐츠 소재', status, date(2026, 11, 2)])
        if i % 4 == 3:  # 분류 테스트용 무관 콘텐츠
            cont.append([hid, plat, '연말 이벤트 안내', f'{slug}/content/2', '제품과 무관한 병원 공지 목업', cd, None, 'irrelevant'])
    return {
        'Hospitals': (['hospital_id', 'hospital_name', 'region', 'representative', 'phone', 'contract_date', 'source_updated_at'], hosp),
        'Deliveries': (['hospital_id', 'product_name', 'delivery_date', 'quantity'], dlv),
        'Materials': (['hospital_id', 'product_name', 'material_name', 'quantity', 'status'], mat),
        'Channels': (['hospital_id', 'platform', 'channel_name', 'url'], ch),
        'ContentCandidates': (['hospital_id', 'platform', 'title', 'url', 'description', 'published_at', 'matched_product', 'expected_relevance'], cont),
        'Scripts': (['content_url', 'script_text', 'summary', 'usage_status', 'collected_at'], scripts),
    }


def main() -> None:
    for d, _, end in CUTS:
        wb = Workbook(); wb.remove(wb.active)
        for sheet, (header, rows) in rows_for(end, d).items():
            ws = wb.create_sheet(sheet); ws.append(header)
            for c in ws[1]: c.font = BOLD
            for r in rows: ws.append(r)
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = max(len(str(c.value or '')) for c in col) * 1.6 + 2
                for c in col:
                    if isinstance(c.value, datetime): c.number_format = 'yyyy-mm-dd hh:mm' if c.value.hour else 'yyyy-mm-dd'
                    elif isinstance(c.value, date): c.number_format = 'yyyy-mm-dd'
        out = ROOT / d / f'{d}_계약병원.xlsx'
        out.parent.mkdir(parents=True, exist_ok=True)
        wb.save(out); print(out.relative_to(ROOT.parent), end, 'hospitals')


if __name__ == '__main__':
    main()
